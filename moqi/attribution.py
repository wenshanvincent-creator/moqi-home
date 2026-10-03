"""§4 acknowledged-command echo matching. Unmatched events remain unknown."""
import json
from datetime import datetime,timedelta,timezone
from .contexts import dt


def match_echoes(store,config,asof):
    from .memory import action
    executions=store.db.execute("SELECT id,entity_id,target,issued_at,context_id,property FROM execution_ledger WHERE status='acknowledged'").fetchall()
    matched=0
    for r in store.events():
        if r['role']!='actuator' or r['attributed_source']!='unknown' or r['kind'] not in {'transition','attributes'} or dt(r['occurred_at'])>=asof:
            continue
        delay=30 if config['entities'][r['entity_id']].get('category')=='hvac' else 5
        prop,target=action(r)
        context=json.loads(r['context_json'])
        choices=[identifier for identifier,entity,value,issued,context_id,property_name in executions if
            entity==r['entity_id'] and property_name==prop and value==target and
            dt(issued)<=dt(r['occurred_at'])<=dt(issued)+timedelta(seconds=delay) and
            (not context_id or context_id==context.get('id'))]
        if len(choices)!=1: continue
        stamp=datetime.now(timezone.utc).isoformat(); reason='Acknowledged command echo: '+choices[0]
        store.db.execute('INSERT OR REPLACE INTO annotations VALUES (?,?,?,?)',(r['event_key'],'agent',reason,stamp))
        store.db.execute('INSERT INTO annotation_history(event_key,source,reason,annotated_at) VALUES (?,?,?,?)',
                         (r['event_key'],'agent',reason,stamp))
        matched+=1
    return matched
