import copy
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from moqi.core import Store,normalize
from moqi.memory_store import put
from moqi.safety import review
from moqi.voice import LocalCorrectionParser

AT=datetime(2026,10,9,2,tzinfo=timezone.utc)


class SafetyFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.store=Store(Path(self.temp.name)/'db.sqlite3')
        self.config=dict(site='test',timezone='Asia/Shanghai',entities={
            'switch.lamp':dict(room='room',role='actuator',category='light',risk='low'),
            'climate.ac':dict(room='room',role='actuator',category='hvac',risk='high'),
            'binary_sensor.window':dict(room='room',role='contact')})
        self.policy=dict(devices={
            'switch.lamp':dict(actions=['turn_on','turn_off']),
            'climate.ac':dict(actions=['turn_off','set_hvac_mode'],windows=['binary_sensor.window'])})
        self.habit=dict(id='earned',entity_id='switch.lamp',property='state',target='on',risk='low',
            trust_level=3,status='active',alpha=100.,beta=1.)
        put(self.store,'memory_habits',self.habit)
        self.store.db.execute('INSERT INTO sessions(started_at,last_seen_at,status) VALUES (?,?,?)',
            ((AT-timedelta(minutes=1)).isoformat(),AT.isoformat(),'connected'))
        self.add('switch.lamp','off',AT)
        self.p=dict(id='proposal',entity_id='switch.lamp',action='turn_on',value=None,habit_id='earned',
                    issued_at=AT.isoformat(),probability=.99,risk='low',announce=False)
        self.store.db.commit()

    def tearDown(self): self.store.close(); self.temp.cleanup()

    def add(self,entity,state,at,before=None):
        row=normalize(dict(event_type='state_changed',time_fired=at.isoformat(),data=dict(entity_id=entity,
            old_state=None if before is None else dict(state=before),new_state=dict(state=state))),self.config)
        self.store.add(row)

    def check(self,reason,at=AT):
        result=review(self.store,self.config,self.policy,self.p,at)
        self.assertFalse(result['allowed']); self.assertEqual(result['reason'],reason)

    def test_review_does_not_execute_or_mutate(self):
        result=review(self.store,self.config,self.policy,self.p,AT)
        self.assertTrue(result['allowed']); self.assertFalse(result['execution_enabled'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM execution_ledger').fetchone()[0],0)

    def test_network_loss_and_ha_restart_fail_closed(self):
        self.store.db.execute("UPDATE sessions SET status='disconnected'")
        self.check('ha_offline_or_clock_jump')

    def test_clock_jump_and_stale_proposal(self):
        self.check('stale_or_future_proposal',AT+timedelta(minutes=1))
        self.store.db.execute('UPDATE sessions SET last_seen_at=?',((AT+timedelta(hours=1)).isoformat(),))
        self.check('ha_offline_or_clock_jump')

    def test_sensor_battery_loss(self):
        self.add('switch.lamp','unavailable',AT+timedelta(seconds=1),'off')
        self.check('device_unavailable',AT+timedelta(seconds=1))

    def test_human_agent_race_lease_wins(self):
        self.store.db.execute('INSERT INTO human_leases VALUES (?,?,?)',('switch.lamp',(AT+timedelta(minutes=90)).isoformat(),'physical control'))
        self.check('human_lease')

    def test_forged_probability_or_different_action_cannot_authorize(self):
        h=dict(self.habit,alpha=1.,beta=100.); put(self.store,'memory_habits',h)
        self.check('risk_threshold')
        put(self.store,'memory_habits',self.habit); self.p['action']='turn_off'
        self.check('proposal_does_not_match_earned_habit')

    def test_protected_device_and_empty_allowlist(self):
        self.config['entities']['switch.lamp']['category']='router'; self.check('protected_device')
        self.config['entities']['switch.lamp']['category']='light'; self.policy['devices']={}; self.check('outside_action_allowlist')

    def test_duplicate_and_out_of_order_events_use_event_time(self):
        self.add('switch.lamp','unavailable',AT+timedelta(seconds=2),'off')
        self.add('switch.lamp','off',AT-timedelta(seconds=20))
        self.add('switch.lamp','off',AT-timedelta(seconds=20))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],3)
        self.check('device_unavailable',AT+timedelta(seconds=2))

    def test_rate_limit(self):
        for i in range(4):
            self.store.db.execute('INSERT INTO execution_ledger(id,entity_id,issued_at,status) VALUES (?,?,?,?)',
                (str(i),'switch.lamp',(AT-timedelta(minutes=10+i)).isoformat(),'acknowledged'))
        self.check('hourly_rate_limit')

    def test_window_five_minutes_and_compressor(self):
        h=dict(self.habit,entity_id='climate.ac',target='heat',risk='high',trust_level=2); put(self.store,'memory_habits',h)
        self.p.update(entity_id='climate.ac',action='set_hvac_mode',value='heat')
        self.add('climate.ac','off',AT); self.add('binary_sensor.window','on',AT-timedelta(minutes=6))
        self.check('window_open_over_five_minutes')
        self.add('binary_sensor.window','off',AT)
        self.store.db.execute('INSERT INTO execution_ledger(id,entity_id,issued_at,status) VALUES (?,?,?,?)',
            ('prior','climate.ac',(AT-timedelta(minutes=9)).isoformat(),'acknowledged'))
        self.check('compressor_minimum_cycle')

    def test_night_lights(self):
        night=AT.replace(hour=15)
        self.p['issued_at']=night.isoformat()
        self.store.db.execute('UPDATE sessions SET last_seen_at=?',(night.isoformat(),))
        self.check('night_light_invariant',night)

    def test_typed_input_rejects_nan_and_unknown_actions(self):
        self.p['probability']=True; self.check('malformed_proposal')
        self.p['probability']=.99; self.p['action']='set_temperature'; self.p['value']=True
        self.check('malformed_proposal')
        self.p['action']='turn_on'; self.p['value']=None
        self.p['probability']=float('nan'); self.check('malformed_proposal')
        self.p['probability']=.99; self.p['action']='unlock'; self.check('malformed_proposal')

    def test_temperature_float_matches_integer_target_and_accepted_bounds(self):
        h=dict(self.habit,entity_id='climate.ac',property='temperature',target='22',risk='medium')
        put(self.store,'memory_habits',h)
        put(self.store,'memory_models',dict(id='preference',entity_id='climate.ac',mode='heat',accepted_range=[21,23]))
        self.policy['devices']['climate.ac']=dict(actions=['set_temperature'],temperature={'heat':[18,24]})
        self.add('climate.ac','heat',AT)
        self.p.update(entity_id='climate.ac',action='set_temperature',value=22.0)
        self.assertTrue(review(self.store,self.config,self.policy,self.p,AT)['allowed'])
        self.p['value']=27
        self.check('proposal_does_not_match_earned_habit')


class FakeAgent:
    def system_one(self,text,questions):
        chosen={'intent':'constraint','device':'switch.lamp','action':'turn_off','scope':'night'}
        return dict(answers={key:dict(choice=value,probabilities={value:.99}) for key,value in chosen.items()})


class VoiceAdapterTests(unittest.TestCase):
    def test_model_interpretation_is_bounded_candidate_until_calibration(self):
        config=dict(entities={'switch.lamp':dict(role='actuator',aliases=['餐厅灯'])})
        result=LocalCorrectionParser(config,agent=FakeAgent()).parse('我睡下之后这盏灯就不要再自己关了')
        self.assertEqual(result['intent'],'constraint_candidate')
        self.assertTrue(result['requires_explicit_app_acceptance'])

    def test_missing_artifacts_report_block(self):
        with tempfile.TemporaryDirectory() as path:
            with self.assertRaisesRegex(RuntimeError,'missing local artifact'):
                LocalCorrectionParser(dict(entities={}),model_path=path)
