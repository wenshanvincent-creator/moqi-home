"""Plan §9 independent deterministic review process. No HA service-call capability."""
import argparse
import json
import sys
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from .core import Store
from .contexts import dt,latest,number
from .decision import Proposal
from .memory_store import objects


def review(store,config,policy,value,at):
    try: p=Proposal(**value)
    except (TypeError,ValueError): return dict(allowed=False,reason='malformed_proposal')
    deny=lambda reason: dict(id=p.id,allowed=False,reason=reason)
    if abs((at-dt(p.issued_at)).total_seconds())>30: return deny('stale_or_future_proposal')
    spec=config['entities'].get(p.entity_id,{})
    protected=spec.get('protected') or spec.get('category') in {'fridge','router','gas','lock','medical'}
    if protected or p.entity_id.startswith(('lock.','gas.')): return deny('protected_device')
    rule=policy.get('devices',{}).get(p.entity_id)
    if not rule or p.action not in rule.get('actions',[]): return deny('outside_action_allowlist')
    live=store.db.execute('SELECT last_seen_at FROM sessions WHERE status=\'connected\' ORDER BY started_at DESC LIMIT 1').fetchone()
    if not live or not live[0] or not 0<=(at-dt(live[0])).total_seconds()<=60: return deny('ha_offline_or_clock_jump')
    h=next((h for h in objects(store,'memory_habits') if h['id']==p.habit_id),None)
    if not h or h['entity_id']!=p.entity_id or h['trust_level']<2 or h['status']!='active': return deny('unearned_trust')
    if h['risk'] in {'prohibited','unclassified'}: return deny('risk_unclassified')
    expected='set_temperature' if h['property']=='temperature' else 'turn_'+h['target'] if h['target'] in {'on','off'} else 'set_hvac_mode'
    mismatch=number(p.value)!=number(h['target']) if p.action=='set_temperature' else str(p.value)!=h['target'] if p.action=='set_hvac_mode' else False
    if p.action!=expected or mismatch:
        return deny('proposal_does_not_match_earned_habit')
    probability=h['alpha']/(h['alpha']+h['beta'])
    if probability<{'low':.7,'medium':.85,'high':.95}[h['risk']]: return deny('risk_threshold')
    night=at.astimezone(ZoneInfo(config.get('timezone','Asia/Shanghai'))).hour in {23,0,1,2,3,4,5,6}
    if night and probability<.95: return deny('night_high_risk_threshold')
    if night and spec.get('category')=='light' and p.action=='turn_on': return deny('night_light_invariant')
    if night: return deny('night_announcement_conflict')
    for c in objects(store,'memory_constraints'):
        if c.get('active',True) and c['entity_id']==p.entity_id and p.action in c['deny_actions'] and (c['scope']=='always' or night):
            return deny('explicit_constraint')
    lease=store.db.execute('SELECT until_at FROM human_leases WHERE entity_id=?',(p.entity_id,)).fetchone()
    if lease and at<dt(lease[0]): return deny('human_lease')
    events=store.events(); state=latest(events,p.entity_id,at)
    if not state or state['new_state'] in {None,'unknown','unavailable'}: return deny('device_unavailable')
    if p.action=='set_temperature':
        mode=state['new_state']; bounds=rule.get('temperature',{}).get(mode)
        if not bounds or not bounds[0]<=number(p.value)<=bounds[1]: return deny('temperature_bounds')
        # A hard bound is separate from the range the household has accepted.
        preferences=[m for m in objects(store,'memory_models') if m.get('entity_id')==p.entity_id and m.get('mode')==mode and 'accepted_range' in m]
        if not preferences or not any(m['accepted_range'][0]<=number(p.value)<=m['accepted_range'][1] for m in preferences):
            return deny('outside_accepted_temperature_range')
    if spec.get('category')=='hvac':
        for entity in rule.get('windows',[]):
            window=latest(events,entity,at)
            if not window or window['new_state'] in {None,'unknown','unavailable'}: return deny('window_unknown')
            if window['new_state']=='on' and at-dt(window['occurred_at'])>timedelta(minutes=5) and p.action!='turn_off':
                return deny('window_open_over_five_minutes')
    if spec.get('category')=='ventilation':
        presence=latest(events,rule.get('presence',''),at); co2=latest(events,rule.get('co2',''),at)
        if not presence or not co2 or number(co2['new_state']) is None: return deny('ventilation_context_unknown')
        if presence['new_state']=='on' and number(co2['new_state'])>1200 and (p.action=='turn_off' or
            p.action not in {'turn_on'}): return deny('occupied_high_co2')
    recent=[(dt(t),s) for t,s in store.db.execute('SELECT issued_at,status FROM execution_ledger WHERE entity_id=?',(p.entity_id,))
            if at-timedelta(hours=1)<=dt(t)<=at and s in {'acknowledged','reserved'}]
    if len(recent)>=min(4,int(rule.get('max_actions_per_hour',4))): return deny('hourly_rate_limit')
    if spec.get('category')=='hvac' and recent and at-max(t for t,s in recent)<timedelta(minutes=max(10,rule.get('min_cycle_minutes',10))):
        return deny('compressor_minimum_cycle')
    return dict(id=p.id,allowed=True,reason='review_passed_execution_disabled',announce=not night and
                (h['risk']=='high' or h['trust_level']==2),execution_enabled=False)


def main():
    parser=argparse.ArgumentParser(description='Independent safety reviewer; JSON lines on stdin, no device control')
    parser.add_argument('--config',default='config.local.json'); parser.add_argument('--policy',default='safety-policy.local.json')
    args=parser.parse_args()
    config=json.load(open(args.config,encoding='utf-8-sig')); policy=json.load(open(args.policy,encoding='utf-8-sig'))
    store=Store(config['database'])
    try:
        for line in sys.stdin:
            try: result=review(store,config,policy,json.loads(line),datetime.now(timezone.utc))
            except (ValueError,KeyError,TypeError): result=dict(allowed=False,reason='invalid_input')
            print(json.dumps(result),flush=True)
    finally: store.close()


if __name__=='__main__': main()
