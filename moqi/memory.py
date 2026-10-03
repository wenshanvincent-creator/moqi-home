"""Persistent plan §5–6 memory. No device commands are sent by this module."""
import json
import math
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from .contexts import dt, context, features, hierarchy, matches, boundary, attributes, number, latest
from .memory_store import initialize, canonical, identity, objects, put, meta, set_meta, change, commit, history, rollback
from .statistics import beta_tail


def coverage(store):
    intervals = []
    for start,end,seen in store.db.execute('SELECT started_at,ended_at,last_seen_at FROM sessions'):
        if end or seen:
            stop = min(dt(end),dt(seen)) if end and seen else dt(end or seen)
            intervals.append((dt(start),stop))
    merged = []
    for start,end in sorted(intervals):
        if end <= start: continue
        if merged and start <= merged[-1][1]: merged[-1] = (merged[-1][0],max(end,merged[-1][1]))
        else: merged.append((start,end))
    return merged


def covered(intervals,start,end):
    return any(a <= start and end <= b for a,b in intervals)


def eligible(events,intervals,entity,start,end):
    previous = latest(events,entity,start)
    uncertain = any(r['entity_id']==entity and start <= dt(r['occurred_at']) < end and
        (r['kind'] in {'unavailable','removed'} or r['kind'] in {'transition','attributes'} and
         r['attributed_source']=='unknown') for r in events)
    return bool(covered(intervals,start,end) and previous and
                previous['new_state'] not in (None,'unknown','unavailable') and not uncertain)


def human_actions(store,asof):
    cached={k:json.loads(b) for k,b in store.db.execute('SELECT event_key,body FROM memory_contexts')}
    return [r for r in store.events() if r['attributed_source']=='human' and r['role']=='actuator' and
            (r['kind']=='transition' or r['kind']=='attributes' and
             cached.get(r['event_key'],{}).get('property',action(r)[0])=='temperature') and
            r['new_state'] not in (None,'unknown','unavailable') and dt(r['occurred_at']) < asof]


def spontaneous_actions(store,asof):
    executions=store.db.execute("SELECT entity_id,issued_at FROM execution_ledger WHERE status='acknowledged'").fetchall()
    return [r for r in human_actions(store,asof) if not any(entity==r['entity_id'] and
            dt(issued)<dt(r['occurred_at'])<=dt(issued)+timedelta(minutes=10) for entity,issued in executions)]


def action(row):
    data = json.loads(row['raw_json'] or '{}').get('data',{})
    old = (data.get('old_state') or {}).get('attributes',{})
    new = attributes(row)
    if number(new.get('temperature')) is not None and old.get('temperature') != new.get('temperature'):
        return 'temperature',format(number(new['temperature']),'.15g')
    return 'state',row['new_state']


def ingest_contexts(store,config,asof):
    events = store.events()
    for row in events:
        if dt(row['occurred_at']) >= asof or row['role'] != 'actuator': continue
        if store.db.execute('SELECT 1 FROM memory_contexts WHERE event_key=?',(row['event_key'],)).fetchone(): continue
        value = features(events,config,dt(row['occurred_at']),row['room'])
        value['devices'].pop(row['entity_id'],None)  # Other devices, not the action's own resulting state.
        prop,target = action(row)
        store.db.execute('INSERT INTO memory_contexts VALUES (?,?)',(row['event_key'],
            canonical(dict(features=value,property=prop,target=target))))


def event_context(store,row):
    return json.loads(store.db.execute('SELECT body FROM memory_contexts WHERE event_key=?',(row['event_key'],)).fetchone()[0])


def episodes(store,asof,config=None):
    initialize(store)
    if config is not None:
        current = None
        for row in store.events():
            if dt(row['occurred_at']) >= asof: continue
            b = boundary(row,config)
            if not b and not (row['role']=='actuator' and row['kind'] in {'transition','attributes'}): continue
            if current is None or b:
                if current:
                    current.update(end=row['occurred_at'],closed=True)
                    store.db.execute('INSERT OR REPLACE INTO memory_episodes VALUES (?,?,?,?)',
                                     (current['id'],current['start'],current['end'],canonical(current)))
                current = dict(id=identity(['episode',row['event_key']]),start=row['occurred_at'],end=row['occurred_at'],
                    boundary=b or 'observation_start',closed=False,events=0,rooms=[],sequence=[])
            current.update(end=row['occurred_at'],events=current['events']+1,rooms=sorted(set(current['rooms']+[row['room']])))
            current['sequence'].append({k:row[k] for k in ('event_key','entity_id','occurred_at','old_state','new_state','attributed_source')})
        if current:
            store.db.execute('INSERT OR REPLACE INTO memory_episodes VALUES (?,?,?,?)',
                             (current['id'],current['start'],current['end'],canonical(current)))
    return sorted(objects(store,'memory_episodes'),key=lambda e:e['start'])


def risk_for(config,entity,prop,at):
    spec = config['entities'][entity]
    if spec.get('protected') or spec.get('category') in {'fridge','router','gas','lock','medical'}: return 'prohibited'
    if spec.get('risk') not in {'low','medium','high'}: return 'unclassified'
    local = at.astimezone(ZoneInfo(config.get('timezone','Asia/Shanghai')))
    if local.hour>=23 or local.hour<7 or spec.get('category')=='hvac' and prop=='state': return 'high'
    return spec['risk']


def mine(store,config,asof):
    groups = defaultdict(list)
    for row in spontaneous_actions(store,asof):
        if dt(row['occurred_at']) < asof-timedelta(days=14): continue
        value = event_context(store,row)
        for level,ctx in enumerate(hierarchy(value['features'])):
            groups[canonical([row['entity_id'],value['property'],value['target'],ctx,level])].append(row)
    existing = objects(store,'memory_habits')
    for key,rows in sorted(groups.items()):
        if len(rows)<4: continue
        entity,prop,target,ctx,level = json.loads(key)
        family = identity(json.loads(key))
        found=[h for h in existing if h['family']==family and h['status']!='drift_dormant']
        if found:
            h=found[-1]
            h['occurrences']=len(rows)
            h['observed_days']=len({dt(r['occurred_at']).astimezone(ZoneInfo(config.get('timezone','Asia/Shanghai'))).date() for r in rows})
            h['risk']=risk_for(config,entity,prop,dt(rows[-1]['occurred_at']))
            put(store,'memory_habits',h)
            continue
        h = dict(id=family+'-v1',family=family,version=1,entity_id=entity,property=prop,target=target,context=ctx,
            specificity=level,day_type=ctx.get('day_type','all'),slot=ctx['slot'],
            time_slot=f"{ctx['slot']//2:02d}:{ctx['slot']%2*30:02d}",created_at=asof.isoformat(),
            start_at=min(r['occurred_at'] for r in rows),status='active',trust_level=1,
            risk=risk_for(config,entity,prop,dt(rows[-1]['occurred_at'])),alpha=1.,beta=1.,shadow_alpha=1.,shadow_beta=1.,
            accept_alpha=1.,accept_beta=1.,successes=0,failures=0,occurrences=len(rows),
            observed_days=len({dt(r['occurred_at']).astimezone(ZoneInfo(config.get('timezone','Asia/Shanghai'))).date() for r in rows}))
        put(store,'memory_habits',h)
        existing.append(h)
        change(store,asof.isoformat(),'candidate',dict(id=h['id'],occurrences=len(rows)))


def evidence(store,h,key,at,**body):
    identifier = identity([h['id'],key])
    store.db.execute('INSERT OR REPLACE INTO memory_evidence VALUES (?,?,?,?)',
        (identifier,h['id'],at,canonical(dict(id=identifier,habit_id=h['id'],at=at,**body))))


def opportunities(store,config,asof):
    events,actions,intervals = store.events(),spontaneous_actions(store,asof),coverage(store)
    previous=meta(store,'consolidated_at')
    annotation_revision=store.db.execute('SELECT COALESCE(MAX(id),0) FROM annotation_history').fetchone()[0]
    received=meta(store,'input_received_at','')
    late=store.db.execute('SELECT 1 FROM events WHERE received_at>? AND occurred_at<? LIMIT 1',
                         (received,previous or asof.isoformat())).fetchone()
    changed=annotation_revision!=meta(store,'annotation_revision',-1) or bool(late)
    context_cache={}
    entity_events=defaultdict(list)
    for r in events: entity_events[r['entity_id']].append(r)
    for h in objects(store,'memory_habits'):
        if h['status']=='drift_dormant': continue
        # Re-evaluate prior trials when attribution changes; an ambiguous window is
        # voided, not frozen as a previous negative/positive observation.
        if changed:
            for e in objects(store,'memory_evidence'):
                if e['habit_id']==h['id'] and e.get('channel')=='habit' and e.get('opportunity',True) and dt(e['at'])>=asof-timedelta(days=30):
                    store.db.execute('DELETE FROM memory_evidence WHERE id=?',(e['id'],))
        start = max(dt(h['start_at']),asof-timedelta(days=30))
        if previous and not changed and dt(h['created_at'])<=dt(previous):
            start=max(start,dt(previous)-timedelta(minutes=15))
        cursor = start.replace(second=0,microsecond=0)
        cursor -= timedelta(minutes=cursor.minute%15)
        while cursor+timedelta(minutes=15)<=asof:
            stop = cursor+timedelta(minutes=15)
            day_type,slot=context(cursor,config)
            if slot!=h['slot'] or h['context'].get('day_type',day_type)!=day_type:
                cursor=stop
                continue
            current=latest(entity_events[h['entity_id']],h['entity_id'],cursor)
            if current and (h['property']=='state' and current['new_state']==h['target'] or
                h['property']=='temperature' and str(attributes(current).get('temperature'))==h['target']):
                cursor=stop
                continue  # No opportunity to repeat an action whose target is already satisfied.
            execution_overlap=any(e==h['entity_id'] and cursor<dt(t)+timedelta(minutes=10) and dt(t)<stop
                for e,t in store.db.execute("SELECT entity_id,issued_at FROM execution_ledger WHERE status='acknowledged'"))
            if not execution_overlap and covered(intervals,cursor,stop) and eligible(entity_events[h['entity_id']],intervals,h['entity_id'],cursor,stop):
                cache_key=(cursor,h['context']['room'])
                if cache_key not in context_cache:
                    context_cache[cache_key]=features(events,config,cursor,h['context']['room'])
                full = dict(context_cache[cache_key],devices=dict(context_cache[cache_key]['devices']))
                full['devices'].pop(h['entity_id'],None)
                if matches(h['context'],full):
                    found = [r['event_key'] for r in actions if r['entity_id']==h['entity_id'] and
                        cursor <= dt(r['occurred_at']) < stop and
                        (event_context(store,r)['property'],event_context(store,r)['target'])==(h['property'],h['target'])]
                    evidence(store,h,'exposure:'+cursor.isoformat(),cursor.isoformat(),channel='habit',
                        exposure=True,alpha=len(found),beta=int(not found),events=found)
            cursor = stop
        attached = {key for e in objects(store,'memory_evidence') if e['habit_id']==h['id'] and
                    e.get('opportunity',True) and e.get('channel')=='habit' for key in e.get('events',[])}
        for r in actions:
            value = event_context(store,r)
            if r['entity_id'] != h['entity_id'] or dt(r['occurred_at']) < dt(h['start_at']): continue
            if (value['property'],value['target']) != (h['property'],h['target']) or not matches(h['context'],value['features']): continue
            eid = identity([h['id'],'action:'+r['event_key']])
            if r['event_key'] in attached:
                store.db.execute('DELETE FROM memory_evidence WHERE id=?',(eid,))
            else:
                evidence(store,h,'action:'+r['event_key'],r['occurred_at'],channel='habit',exposure=True,
                         alpha=1,beta=0,events=[r['event_key']],opportunity=False)
    set_meta(store,'annotation_revision',annotation_revision)
    set_meta(store,'input_received_at',store.db.execute('SELECT COALESCE(MAX(received_at),\'\') FROM events').fetchone()[0])


def reconcile_attribution(store,asof):
    sources = {r['event_key']:r['attributed_source'] for r in store.events() if dt(r['occurred_at']) < asof}
    for e in objects(store,'memory_evidence'):
        if e.get('channel')!='habit' or not e.get('events'): continue
        valid = [key for key in e['events'] if sources.get(key)=='human']
        if valid != e['events']:
            e.update(events=valid,alpha=len(valid))
            if not valid: store.db.execute('DELETE FROM memory_evidence WHERE id=?',(e['id'],))
            else: store.db.execute('UPDATE memory_evidence SET body=? WHERE id=?',(canonical(e),e['id']))


def learn(store,config,asof):
    gamma = float(config.get('forgetting_gamma',.9))
    if not 0<gamma<=1: raise ValueError('forgetting_gamma must be in (0,1]')
    ledger = objects(store,'memory_evidence')
    for h in objects(store,'memory_habits'):
        if h['status']=='drift_dormant': continue
        rows = sorted([e for e in ledger if e['habit_id']==h['id'] and dt(e['at'])<asof],key=lambda e:(e['at'],e['id']))
        a=b=sa=sb=aa=ab=1.
        successes=failures=0
        exposures = set()
        for e in rows:
            channel = e.get('channel')
            if channel=='habit':
                # An exposure is a reappearance of the context, not elapsed wall time.
                exposure_time=dt(e['at']).replace(second=0,microsecond=0)
                exposure_time-=timedelta(minutes=exposure_time.minute%15)
                exposure_id=exposure_time.isoformat()
                if e.get('exposure') and exposure_id not in exposures:
                    a*=gamma; b*=gamma; exposures.add(exposure_id)
                a+=e.get('alpha',0); b+=e.get('beta',0)
                successes+=e.get('alpha',0); failures+=e.get('beta',0)
            elif channel=='shadow': sa+=e['alpha']; sb+=e['beta']
            elif channel=='acceptance':
                aa+=e['alpha']; ab+=e['beta']; a+=e['alpha']; b+=e['beta']
        h.update(alpha=max(a,1e-9),beta=max(b,1e-9),shadow_alpha=sa,shadow_beta=sb,accept_alpha=aa,
                 accept_beta=ab,successes=successes,failures=failures)
        h['last_exposed']=max((e['at'] for e in rows if e.get('exposure')),default=h['start_at'])
        h['status']='seasonal_dormant' if asof-dt(h['last_exposed'])>timedelta(days=30) else 'active'
        if h['risk'] in {'low','medium','high'}:
            if h['trust_level']<2 and beta_tail(sa,sb,.85)>.8: h['trust_level']=2
            if h['trust_level']>=2 and h['risk']!='high' and beta_tail(aa,ab,.9)>.8: h['trust_level']=3
        recent = [e for e in rows if e.get('signal')=='undo' and asof-dt(e['at'])<=timedelta(days=7)]
        if len(recent)>=2: h['trust_level']=1
        elif recent: h['trust_level']=min(h['trust_level'],2)
        if h['risk']=='high': h['trust_level']=min(h['trust_level'],2)
        if h['risk'] in {'prohibited','unclassified'}: h['trust_level']=min(h['trust_level'],1)
        scores = [e for e in rows if e.get('channel') in {'shadow','acceptance'} and e['alpha']+e['beta']>0]
        recent_scores = [e for e in scores if dt(e['at'])>=asof-timedelta(days=7)]
        earlier = [e for e in scores if dt(e['at'])<asof-timedelta(days=7)]
        if len(recent_scores)>=8 and len(earlier)>=8:
            def rate(values): return sum(e['alpha'] for e in values)/sum(e['alpha']+e['beta'] for e in values)
            r,l=rate(recent_scores),rate(earlier)
            error=math.sqrt(max(.0001,r*(1-r)/len(recent_scores)+l*(1-l)/len(earlier)))
            if abs(r-l)>=max(.25,2*error):
                h['status']='drift_dormant'
                new=dict(h,id=h['family']+f"-v{h['version']+1}",version=h['version']+1,status='active',trust_level=1,
                    start_at=asof.isoformat(),created_at=asof.isoformat(),alpha=1.,beta=1.,shadow_alpha=1.,shadow_beta=1.,
                    accept_alpha=1.,accept_beta=1.,successes=0,failures=0,previous_version=h['id'],last_exposed=asof.isoformat())
                put(store,'memory_habits',new)
                change(store,asof.isoformat(),'drift_split',dict(old=h['id'],new=new['id'],recent=r,previous=l))
        put(store,'memory_habits',h)


def habits(store,config,asof):
    initialize(store)
    return sorted([dict(h,probability=h['alpha']/(h['alpha']+h['beta']),trust=f"L{h['trust_level']}")
                   for h in objects(store,'memory_habits') if dt(h['created_at'])<=asof and h['status']!='drift_dormant'],
                  key=lambda h:(h['entity_id'],h['specificity'],h['id']))


def predict(store,config,at):
    initialize(store)
    consolidated=meta(store,'consolidated_at')
    if consolidated and at<dt(consolidated):
        raise ValueError('Historical prediction requires an isolated chronological replay database')
    events,chosen=store.events(),{}
    for h in habits(store,config,at):
        current=latest(events,h['entity_id'],at)
        if current and (h['property']=='state' and current['new_state']==h['target'] or
            h['property']=='temperature' and str(attributes(current).get('temperature'))==h['target']): continue
        full=features(events,config,at,h['context']['room']); full['devices'].pop(h['entity_id'],None)
        if matches(h['context'],full): chosen.setdefault((h['entity_id'],h['property'],h['target']),h)
    end=at+timedelta(minutes=15)
    with store.db:
        for h in chosen.values():
            if not store.db.execute('SELECT 1 FROM forecasts WHERE entity_id=? AND target=? AND issued_at<=? AND window_end>?',
                                    (h['entity_id'],h['target'],at.isoformat(),at.isoformat())).fetchone():
                full=features(events,config,at,h['context']['room']); full['devices'].pop(h['entity_id'],None)
                store.db.execute('INSERT INTO forecasts(entity_id,target,issued_at,window_end,probability,evidence_json) VALUES (?,?,?,?,?,?)',
                    (h['entity_id'],h['target'],at.isoformat(),end.isoformat(),h['probability'],canonical(dict(h,issued_context=full))))
    return list(chosen.values())


def evaluate(store,asof):
    initialize(store)
    actions,events,intervals=human_actions(store,asof),store.events(),coverage(store)
    cached={key:json.loads(body) for key,body in store.db.execute('SELECT event_key,body FROM memory_contexts')}
    def observed_action(row):
        c=cached.get(row['event_key'])
        return (c['property'],c['target']) if c else action(row)
    for key,entity,target,issued,end,body in store.db.execute(
        'SELECT id,entity_id,target,issued_at,window_end,evidence_json FROM forecasts').fetchall():
        start,stop=dt(issued),dt(end)
        if stop>asof: continue
        h=json.loads(body); outcome='unscored'
        if eligible(events,intervals,entity,start,stop):
            hit=any(r['entity_id']==entity and start<=dt(r['occurred_at'])<stop and
                    observed_action(r)==(h.get('property','state'),target) for r in actions)
            outcome='hit' if hit else 'miss'
            if h.get('id'): evidence(store,h,'forecast:'+str(key),end,channel='shadow',alpha=int(hit),beta=int(not hit))
        elif h.get('id'):
            store.db.execute('DELETE FROM memory_evidence WHERE id=?',(identity([h['id'],'forecast:'+str(key)]),))
        store.db.execute('UPDATE forecasts SET outcome=? WHERE id=?',(outcome,key))


def register_execution(store,identifier,entity,target,before,at,habit_id,context_id=None,prop='state'):
    initialize(store)
    if not store.db.execute('SELECT 1 FROM memory_habits WHERE id=?',(habit_id,)).fetchone(): raise ValueError('Unknown habit')
    if at.tzinfo is None or prop not in {'state','temperature'}: raise ValueError('Invalid execution receipt')
    if prop=='temperature':
        if number(target) is None or number(before) is None: raise ValueError('Temperature receipt needs finite target and previous value')
        target,before=format(number(target),'.15g'),format(number(before),'.15g')
    with store.db:
        store.db.execute('INSERT INTO execution_ledger(id,entity_id,target,before_state,issued_at,habit_id,status,context_id,property) VALUES (?,?,?,?,?,?,?,?,?)',
            (identifier,entity,str(target),str(before),at.isoformat(),habit_id,'acknowledged',context_id,prop))


def feedback(store,config,asof):
    events,intervals,humans=store.events(),coverage(store),human_actions(store,asof)
    for identifier,entity,target,before,issued,habit_id,prop in store.db.execute(
        "SELECT id,entity_id,target,before_state,issued_at,habit_id,property FROM execution_ledger WHERE status='acknowledged' AND feedback IS NULL").fetchall():
        start,end=dt(issued),dt(issued)+timedelta(minutes=10)
        corrections=[r for r in humans if r['entity_id']==entity and start<dt(r['occurred_at'])<=min(end,asof) and
                     action(r)[0]==prop and action(r)[1]!=target]
        row=store.db.execute('SELECT body FROM memory_habits WHERE id=?',(habit_id,)).fetchone()
        if not row: continue
        h=json.loads(row[0])
        if corrections:
            r=corrections[0]; new=action(r)[1]
            signal='correction' if prop=='temperature' and new!=before and number(new) is not None else 'undo'
            evidence(store,h,'execution:'+identifier,r['occurred_at'],channel='acceptance',alpha=0,beta=3 if signal=='undo' else 0,signal=signal)
            store.db.execute('UPDATE execution_ledger SET feedback=? WHERE id=?',(signal,identifier))
        elif end<=asof:
            outcome='unscored'
            final=latest(events,entity,end)
            reached=bool(final and (final['new_state']==target if prop=='state' else
                number(attributes(final).get('temperature'))==number(target)))
            if reached and eligible(events,intervals,entity,start,end):
                evidence(store,h,'execution:'+identifier,end.isoformat(),channel='acceptance',alpha=.5,beta=0,signal='default_acceptance')
                outcome='default_acceptance'
            store.db.execute('UPDATE execution_ledger SET feedback=? WHERE id=?',(outcome,identifier))
    for r in humans:
        until=dt(r['occurred_at'])+timedelta(minutes=90)
        current=store.db.execute('SELECT until_at FROM human_leases WHERE entity_id=?',(r['entity_id'],)).fetchone()
        if not current or dt(current[0])<until:
            store.db.execute('INSERT OR REPLACE INTO human_leases VALUES (?,?,?)',(r['entity_id'],until.isoformat(),'human operation'))


def snapshot(store,config,asof):
    initialize(store)
    events=[r for r in store.events() if dt(r['occurred_at'])<asof]
    return dict(mode='structured memory; physical execution disabled pending acceptance',asof=asof.isoformat(),
        timezone=config.get('timezone','Asia/Shanghai'),event_count=len(events),
        unverified_actions=sum(r['role']=='actuator' and r['attributed_source']=='unknown' and r['kind'] in {'transition','attributes'} for r in events),
        habits=habits(store,config,asof),episodes=episodes(store,asof)[-20:],questions=objects(store,'memory_questions'),
        models=objects(store,'memory_models'),constraints=objects(store,'memory_constraints'),revision=meta(store,'revision'),
        changes=[dict(at=a,kind=k,details=json.loads(b)) for a,k,b in store.db.execute('SELECT at,kind,body FROM memory_changes ORDER BY id DESC LIMIT 30')],
        forecasts=[dict(entity_id=e,target=t,issued_at=a,probability=p,outcome=o) for e,t,a,p,o in store.db.execute(
            'SELECT entity_id,target,issued_at,probability,outcome FROM forecasts ORDER BY issued_at DESC LIMIT 50')],
        recent_events=[{k:r[k] for k in ('event_key','entity_id','occurred_at','old_state','new_state','attributed_source')} for r in events[-50:]])


def consolidate(store,config,asof):
    from .understanding import update_questions, world_models, judge_proposals, retain
    from .attribution import match_echoes
    initialize(store)
    previous=meta(store,'consolidated_at')
    if previous and asof<dt(previous): raise ValueError('Consolidation clock moved backwards; use an isolated replay database')
    with store.db:
        match_echoes(store,config,asof)
        ingest_contexts(store,config,asof)
        episodes(store,asof,config)
        mine(store,config,asof)
        opportunities(store,config,asof)
        evaluate(store,asof)
        feedback(store,config,asof)
        reconcile_attribution(store,asof)
        learn(store,config,asof)
        update_questions(store,config,asof)
        world_models(store,config,asof)
        judge_proposals(store,asof)
        retained=retain(store,asof)
        set_meta(store,'consolidated_at',asof.isoformat())
    if retained['raw_payloads_removed']:
        retained['wal_checkpoint']=list(store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone())
    return retained


def reflect(store,config,asof,output):
    from .understanding import write_understanding
    initialize(store)
    done=store.db.execute("SELECT body FROM memory_runs WHERE at=? AND status='complete'",(asof.isoformat(),)).fetchone()
    if done:
        return snapshot(store,config,asof)
    retained=consolidate(store,config,asof)
    data=write_understanding(store,config,asof,output)
    date=asof.astimezone(ZoneInfo(config.get('timezone','Asia/Shanghai'))).date().isoformat()
    revision=commit(store,output,asof.isoformat(),f'{date} consolidation: {len(data["habits"])} habits; '+
                    f'{sum(q["status"]=="open" for q in data["questions"])} open questions')
    with store.db:
        store.db.execute('INSERT OR REPLACE INTO memory_runs VALUES (?,?,?,?)',(date,asof.isoformat(),'complete',
            canonical(dict(id=date,at=asof.isoformat(),revision=revision,retention=retained))))
    data['revision']=revision
    return data


def due(store,config,at):
    initialize(store)
    local=at.astimezone(ZoneInfo(config.get('timezone','Asia/Shanghai')))
    scheduled=local.replace(hour=3,minute=0,second=0,microsecond=0)
    if local<scheduled: scheduled-=timedelta(days=1)
    run=store.db.execute("SELECT 1 FROM memory_runs WHERE status='complete' AND at>=? AND at<=?",
                         (scheduled.astimezone(at.tzinfo).isoformat(),at.isoformat())).fetchone()
    return not run
