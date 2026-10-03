"""Questions, physical world models, editable L3 files and privacy retention."""
import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from .contexts import dt, context, hierarchy, boundary, attributes, number, latest
from .memory_store import initialize, canonical, identity, objects, put, change
from .statistics import quantile, fit_thermal, heating_duration, optimal_absence, beta_tail


def update_questions(store,config,asof):
    from .memory import human_actions,event_context
    known={q['id']:q for q in objects(store,'memory_questions')}
    groups=defaultdict(list)
    for r in human_actions(store,asof):
        if dt(r['occurred_at']) < asof-timedelta(days=14): continue
        value=event_context(store,r); c=value['features']
        groups[(r['entity_id'],value['property'],value['target'],c['day_type'],c['slot'])].append(c)
    for key,values in groups.items():
        if len(values)<4: continue
        qid=identity(['question',key])
        q=known.get(qid,dict(id=qid,created_at=asof.isoformat(),status='open'))
        q.update(entity_id=key[0],occurrences=len(values),evidence_features=values,
                 text=f'{key[0]} → {key[2]} recurs in slot {key[4]}; does weekday or weather explain it?')
        for feature in ('weekday','outdoor'):
            usable=[v for v in values if v[feature]!='unknown']
            if len(usable)<6: continue
            train,test=usable[:-2],usable[-2:]
            counts=defaultdict(int)
            for v in train: counts[canonical(v[feature])]+=1
            best=max(counts,key=counts.get)
            if counts[best]>=4 and all(canonical(v[feature])==best for v in test):
                q.update(status='archived',resolved_at=asof.isoformat(),explanation=dict(feature=feature,
                    value=json.loads(best),training=counts[best],holdout=2,qualification='association, not a causal explanation'))
                break
        put(store,'memory_questions',q)
    events=store.events()
    for entity,spec in config['entities'].items():
        if spec['role']!='actuator': continue
        qid=identity(['attribution',entity])
        uncertain=[r for r in events if r['entity_id']==entity and r['attributed_source']=='unknown' and
                   r['kind'] in {'transition','attributes'} and dt(r['occurred_at'])<asof]
        if uncertain:
            put(store,'memory_questions',dict(id=qid,status='open',entity_id=entity,occurrences=len(uncertain),
                created_at=known.get(qid,{}).get('created_at',asof.isoformat()),
                text='Verify physical controls and existing automations before learning these changes.'))
        elif qid in known:
            put(store,'memory_questions',dict(known[qid],status='archived',resolved_at=asof.isoformat(),
                                             explanation='Observed changes now have explicit attribution evidence.'))


def world_models(store,config,asof):
    from .memory import coverage,covered,human_actions,event_context
    events=[r for r in store.events() if dt(r['occurred_at'])<asof]
    intervals=coverage(store)
    for room,spec in config.get('thermal_rooms',{}).items():
        if not all(spec.get(k) in config['entities'] for k in ('indoor','outdoor','hvac')):
            put(store,'memory_models',dict(id='thermal:'+room,room=room,status='missing_configuration')); continue
        samples=[r for r in events if r['entity_id']==spec['indoor'] and
                 dt(r['occurred_at'])>=asof-timedelta(days=30) and number(r['new_state']) is not None]
        rows=[]
        for first,second in zip(samples,samples[1:]):
            t1,t2=dt(first['occurred_at']),dt(second['occurred_at']); hours=(t2-t1).total_seconds()/3600
            outside,hvac=latest(events,spec['outdoor'],t1),latest(events,spec['hvac'],t1)
            if not .01<=hours<=1 or not covered(intervals,t1,t2) or not outside or not hvac: continue
            unit=attributes(first).get('unit_of_measurement') or config['entities'][spec['indoor']].get('unit')
            outunit=attributes(outside).get('unit_of_measurement') or config['entities'][spec['outdoor']].get('unit')
            if unit not in {'°C','C'} or outunit not in {'°C','C'} or number(outside['new_state']) is None: continue
            if t1-dt(outside['occurred_at'])>timedelta(minutes=30): continue
            if any(r['entity_id']==spec['hvac'] and t1<dt(r['occurred_at'])<t2 for r in events): continue
            s=hvac['new_state']
            input_mode=spec.get('input_mode','hvac_action')
            if input_mode=='hvac_action':
                operating=attributes(hvac).get('hvac_action')
                u=1 if operating=='heating' else -1 if operating=='cooling' else 0 if operating in {'off','idle'} else None
            elif input_mode=='verified_state':
                u=1 if s in spec.get('heat_states',[]) else -1 if s in spec.get('cool_states',[]) else 0 if s in spec.get('idle_states',['off','idle']) else None
            elif input_mode=='power':
                watts=number(s); rated=number(spec.get('rated_power_watts'))
                punit=attributes(hvac).get('unit_of_measurement') or config['entities'][spec['hvac']].get('unit')
                u=(watts/rated)*(1 if spec.get('mode')=='heat' else -1) if watts is not None and watts>=0 and rated and rated>0 and punit=='W' and spec.get('mode') in {'heat','cool'} else None
            else: u=None
            if u is None: continue
            temp=number(first['new_state'])
            rows.append((number(outside['new_state'])-temp,u,(number(second['new_state'])-temp)/hours))
        put(store,'memory_models',dict(fit_thermal(rows),id='thermal:'+room,room=room,fitted_at=asof.isoformat()))
    arrivals=defaultdict(list); durations=[]; departure=None
    zone=ZoneInfo(config.get('timezone','Asia/Shanghai'))
    for r in events:
        b=boundary(r,config)
        if b=='departure': departure=dt(r['occurred_at'])
        elif b=='arrival':
            at=dt(r['occurred_at']); local=at.astimezone(zone)
            arrivals[str(local.weekday())].append(local.hour*60+local.minute)
            if departure:
                if covered(intervals,departure,at): durations.append((at-departure).total_seconds()/60)
                departure=None
    for weekday,values in arrivals.items():
        put(store,'memory_models',dict(id='arrival:'+weekday,weekday=int(weekday),samples=len(values),values=values,
            quantile20_minutes=quantile(values,.2),status='fitted' if len(values)>=4 else 'insufficient_data'))
    costs=config.get('absence_costs',{})
    absence=optimal_absence(durations,float(costs.get('regret',0)),float(costs.get('waste_per_minute',0)))
    put(store,'memory_models',dict(absence or {},id='absence',status='fitted' if absence and len(durations)>=4 else 'needs_observations_and_costs'))
    preferences=defaultdict(list)
    for r in human_actions(store,asof):
        value=event_context(store,r)
        if value['property']=='temperature' and number(value['target']) is not None and r['new_state'] in {'heat','cool'}:
            key=(r['entity_id'],r['new_state'],canonical(hierarchy(value['features'])[2]))
            preferences[key].append(number(value['target']))
    for (entity,mode,ctx),values in preferences.items():
        q=.35 if mode=='heat' else .65
        put(store,'memory_models',dict(id='preference:'+identity([entity,mode,ctx]),entity_id=entity,mode=mode,
            context=json.loads(ctx),samples=len(values),values=values,accepted_range=[min(values),max(values)],
            quantile=q,energy_target=quantile(values,q),status='fitted'))


def preheat(store,config,room,at,indoor,outdoor,target):
    models={m['id']:m for m in objects(store,'memory_models')}
    weekday=at.astimezone(ZoneInfo(config.get('timezone','Asia/Shanghai'))).weekday()
    arrival=models.get('arrival:'+str(weekday),{})
    if arrival.get('status')!='fitted': return dict(status='insufficient_arrival_data')
    duration=heating_duration(models.get('thermal:'+room,{}),indoor,outdoor,target)
    if duration is None: return dict(status='insufficient_thermal_data_or_unreachable_target')
    return dict(status='shadow',room=room,target=target,arrival_minutes=arrival['quantile20_minutes'],
                heating_minutes=duration,start_minutes=arrival['quantile20_minutes']-duration)


def constraint(store,config,entity,actions,scope,reason,source,at):
    initialize(store)
    if entity not in config['entities'] or config['entities'][entity]['role']!='actuator': raise ValueError('Constraint needs an allowlisted actuator')
    if source not in {'app','voice'} or scope not in {'always','night'} or not reason.strip(): raise ValueError('Invalid constraint source/scope/reason')
    if not actions or not set(actions)<={'turn_on','turn_off','set_temperature','set_hvac_mode'}: raise ValueError('Unsupported action')
    value=dict(id=identity([entity,sorted(actions),scope]),entity_id=entity,deny_actions=sorted(actions),scope=scope,
               reason=reason,source=source,created_at=at.isoformat(),active=True)
    current=store.db.execute('SELECT body FROM memory_constraints WHERE id=?',(value['id'],)).fetchone()
    if current:
        prior=json.loads(current[0]); value['created_at']=prior['created_at']
        if all(prior.get(k)==value[k] for k in ('entity_id','deny_actions','scope','reason','active')): return prior
    with store.db:
        put(store,'memory_constraints',value); change(store,at.isoformat(),'explicit_constraint',value)
    return value


def weekly_summary(store,config,asof):
    from .memory import human_actions,event_context
    groups=defaultdict(lambda:dict(occurrences=0,hits=0,misses=0))
    for r in human_actions(store,asof):
        if dt(r['occurred_at'])<asof-timedelta(days=7): continue
        c=event_context(store,r)['features']; key=(c['day_type'],c['slot'],'observation')
        groups[key]['occurrences']+=1
    for issued,body,outcome in store.db.execute("SELECT issued_at,evidence_json,outcome FROM forecasts WHERE outcome IN ('hit','miss')"):
        if not asof-timedelta(days=7)<=dt(issued)<asof: continue
        h=json.loads(body); key=(h['day_type'],h['slot'],h['risk'])
        groups[key]['hits']+=int(outcome=='hit'); groups[key]['misses']+=int(outcome=='miss')
    return dict(schema='moqi.deidentified-week.v1',time_granularity_minutes=30,
                cells=[dict(day_type=k[0],slot=k[1],risk=k[2],**v) for k,v in sorted(groups.items())])


def proposal(store,value,at):
    initialize(store)
    if set(value)!={'kind','feature','value','rationale'} or value['kind']!='context_split' or value['feature'] not in {'weekday','outdoor','slot'}:
        raise ValueError('Only typed weekday/outdoor/slot context-split hypotheses are accepted')
    bounds={'weekday':(0,6),'outdoor':(-60,60),'slot':(0,47)}; low,high=bounds[value['feature']]
    if type(value['value']) is not int or not low<=value['value']<=high: raise ValueError('Invalid proposed feature value')
    if not isinstance(value['rationale'],str) or len(value['rationale'])>1000: raise ValueError('Invalid rationale')
    p=dict(value,id=identity(value),status='shadow',created_at=at.isoformat(),trust_level=1)
    with store.db: put(store,'memory_proposals',p)
    return p


def judge_proposals(store,asof):
    for p in objects(store,'memory_proposals'):
        cohorts=defaultdict(lambda:dict(matched=[],other=[],habit=None))
        for issued,body,outcome in store.db.execute("SELECT issued_at,evidence_json,outcome FROM forecasts WHERE outcome IN ('hit','miss')"):
            if not dt(p['created_at'])<=dt(issued)<asof: continue
            h=json.loads(body); full=h.get('issued_context',{})
            if p['feature'] not in full or full[p['feature']]=='unknown': continue
            key=(h['entity_id'],h.get('property','state'),h['target'],None if p['feature']=='slot' else h['slot'])
            cohort=cohorts[key]; cohort['habit']=h
            cohort['matched' if full[p['feature']]==p['value'] else 'other'].append(int(outcome=='hit'))
        p['cohorts']=[dict(entity_id=k[0],property=k[1],target=k[2],slot=k[3],
            matched=len(v['matched']),comparison=len(v['other'])) for k,v in cohorts.items()]
        p['status']='shadow'
        for cohort in cohorts.values():
            matched,other=cohort['matched'],cohort['other']
            if len(matched)<8 or len(other)<8: continue
            a,b=sum(matched)/len(matched),sum(other)/len(other)
            error=max(.0001,a*(1-a)/len(matched)+b*(1-b)/len(other))**.5
            if a-b>max(.15,2*error) and beta_tail(1+sum(matched),1+len(matched)-sum(matched),.7)>.8:
                p['status']='validated_shadow'
                h=cohort['habit']; ctx=dict(h['context']); ctx[p['feature']]=p['value']
                family=identity([h['entity_id'],h['property'],h['target'],ctx,'hypothesis'])
                if not store.db.execute('SELECT 1 FROM memory_habits WHERE id=?',(family+'-v1',)).fetchone():
                    candidate={k:v for k,v in h.items() if k not in {'issued_context','probability','trust'}}
                    candidate.update(id=family+'-v1',family=family,version=1,context=ctx,specificity=1,
                        created_at=asof.isoformat(),start_at=asof.isoformat(),status='active',trust_level=1,
                        alpha=1.,beta=1.,shadow_alpha=1.,shadow_beta=1.,accept_alpha=1.,accept_beta=1.,
                        successes=0,failures=0,hypothesis_id=p['id'])
                    if p['feature']=='slot':
                        candidate['slot']=p['value']
                        candidate['time_slot']=f"{p['value']//2:02d}:{p['value']%2*30:02d}"
                    put(store,'memory_habits',candidate)
                    change(store,asof.isoformat(),'data_validated_hypothesis',dict(proposal=p['id'],habit=candidate['id']))
                break
            if a-b < -max(.15,2*error): p['status']='rejected_by_holdout'
        p['evaluated_at']=asof.isoformat()
        put(store,'memory_proposals',p)


def retain(store,asof):
    cutoff=asof-timedelta(days=30); groups=defaultdict(list)
    old=[r for r in store.events() if dt(r['occurred_at'])<cutoff and r['raw_json']!='{}']
    for r in old:
        if r['role'] in {'temperature','power','energy','light','co2'}:
            bucket=dt(r['occurred_at']).replace(second=0,microsecond=0); bucket-=timedelta(minutes=bucket.minute%15)
            groups[(r['entity_id'],bucket.isoformat())].append(r)
    for (entity,bucket),rows in groups.items():
        prior=store.db.execute('SELECT body FROM downsampled WHERE entity_id=? AND bucket=?',(entity,bucket)).fetchone()
        value=json.loads(prior[0]) if prior else dict(count=0,sum=0.,min=None,max=None,unavailable=0)
        values=[number(r['new_state']) for r in rows if number(r['new_state']) is not None]
        value['count']+=len(values); value['sum']+=sum(values)
        value['unavailable']+=sum(r['kind'] in {'unavailable','removed'} for r in rows)
        if values:
            value['min']=min(values+[value['min']] if value['min'] is not None else values)
            value['max']=max(values+[value['max']] if value['max'] is not None else values)
        value['last']=rows[-1]['new_state']; value['mean']=value['sum']/value['count'] if value['count'] else None
        store.db.execute('INSERT OR REPLACE INTO downsampled VALUES (?,?,?)',(entity,bucket,canonical(value)))
        for r in rows[:-1]:
            store.db.execute('INSERT OR IGNORE INTO event_receipts VALUES (?)',(r['event_key'],))
            store.db.execute('DELETE FROM events WHERE event_key=?',(r['event_key'],))
    for r in old:
        store.db.execute("UPDATE events SET raw_json='{}',context_json='{}' WHERE event_key=?",(r['event_key'],))
    return dict(raw_payloads_removed=len(old),sensor_bins=len(groups))


def write_understanding(store,config,asof,directory,import_edits=True):
    import yaml
    from .memory import snapshot
    directory=Path(directory)
    for name in ('rooms','routines','journal'): (directory/name).mkdir(parents=True,exist_ok=True)
    path=directory/'constraints.yaml'
    if import_edits and path.exists():
        edited=yaml.safe_load(path.read_text(encoding='utf-8')) or []
        if not isinstance(edited,list): raise ValueError('constraints.yaml must contain a list')
        for value in edited:
            if not isinstance(value,dict): raise ValueError('Invalid constraint')
            if value.get('active',True) is False:
                current=store.db.execute('SELECT body FROM memory_constraints WHERE id=?',(value.get('id'),)).fetchone()
                if current: put(store,'memory_constraints',dict(json.loads(current[0]),active=False))
            else: constraint(store,config,value['entity_id'],value['deny_actions'],value['scope'],value['reason'],'app',asof)
    for room in sorted({s['room'] for s in config['entities'].values()}):
        name=identity(room); path=directory/'rooms'/f'{name}.md'
        if not path.exists(): path.write_text(f'# {room}\n\nEditable household notes.\n',encoding='utf-8')
        rows=[h for h in objects(store,'memory_habits') if h['context']['room']==room]
        # Preserve editable notes and put machine evidence in its own generated files.
        notes=directory/'routines'/f'{name}-notes.yaml'
        if not notes.exists(): notes.write_text('notes: []\n',encoding='utf-8')
        (directory/'routines'/f'{name}.yaml').write_text(yaml.safe_dump(rows,allow_unicode=True,sort_keys=False),encoding='utf-8')
        lines=[f'# Learned routines · {room}','']
        for h in rows: lines.append(f"- {h['entity_id']} → {h['target']} {h['time_slot']}: α={h['alpha']:.3f}, β={h['beta']:.3f}, trust={h['trust_level']}, risk={h['risk']}, {h['status']}, v{h['version']}.")
        (directory/'routines'/f'{name}.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    qs=['# Questions and archive','']
    for q in objects(store,'memory_questions'): qs.append(f"- [{q['status']}] {q['text']} Count: {q.get('occurrences',0)}. {canonical(q.get('explanation',{}))}")
    (directory/'questions.md').write_text('\n'.join(qs)+'\n',encoding='utf-8')
    for filename,table in (('constraints.yaml','memory_constraints'),('models.yaml','memory_models'),('proposals.yaml','memory_proposals')):
        (directory/filename).write_text(yaml.safe_dump(objects(store,table),allow_unicode=True,sort_keys=False),encoding='utf-8')
    data=snapshot(store,config,asof); date=asof.astimezone(ZoneInfo(config.get('timezone','Asia/Shanghai'))).date().isoformat()
    (directory/'journal'/f'{date}.json').write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    (directory/'journal'/f'{date}.md').write_text(f'# Consolidation {date}\n\n{len(data["habits"])} habit strata, '+
        f'{sum(q["status"]=="open" for q in data["questions"])} open questions.\n\nPhysical execution awaits hardware acceptance.\n',encoding='utf-8')
    store.db.commit()
    return data
