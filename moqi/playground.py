"""Interactive, deterministic synthetic household using the production engine.

Runnable in CPython or Pyodide. No sockets, Git, models, or actuator calls.
Browser checkpoints restore memory only, not observed reality, just like Git
rollback. Unlike the local memory diary, they last only for this sandbox session.
"""
import json
from datetime import datetime, timedelta, timezone

from .api import HomeMemory, Observation
from .memory import register_execution, habits
from .memory_store import state, restore_state, change
from .understanding import constraint
from .voice import LocalCorrectionParser


CONFIG = {'site': 'SYNTHETIC-PLAYGROUND', 'timezone': 'Asia/Shanghai',
          'forgetting_gamma': .9, 'entities': {
              'switch.dining_lamp': {'role': 'actuator', 'room': 'dining_room', 'category': 'light',
                                     'risk': 'low', 'aliases': ['餐厅灯', 'dining lamp']},
              'binary_sensor.presence': {'role': 'presence', 'room': 'dining_room'},
          }}


class Sandbox:
    def __init__(self, database):
        self.engine = HomeMemory(CONFIG, database)
        self.day = datetime(2026, 3, 2, 10, tzinfo=timezone.utc)  # 18:00 in Shanghai.
        self.at = self.day
        self.steps = 0
        self.audit = []
        self.checkpoints = []
        self.last_message = 'A new synthetic home. Observe before predicting.'

    def _note(self, kind, text):
        self.last_message = text
        self.audit.append({'at': self.at.isoformat(), 'kind': kind, 'text': text})

    def _checkpoint(self, label):
        self.checkpoints.append({'label': label, 'at': self.at.isoformat(), 'memory': state(self.engine.store)})
        if len(self.checkpoints) > 30:
            self.checkpoints.pop(0)

    def _start_day(self):
        self._checkpoint('Before day ' + str(self.steps+1))
        start = self.day
        self.engine.ingest(Observation('switch.dining_lamp', start-timedelta(minutes=1), 'off'))
        self.engine.ingest(Observation('binary_sensor.presence', start-timedelta(minutes=1), 'on'))
        self.engine.observe_interval(start, start+timedelta(minutes=30))
        self.engine.predict(start)
        return start

    def observe_day(self, mode='routine'):
        if self.steps >= 90:
            raise ValueError('This sandbox is limited to 90 observed days; reset for another run')
        if mode not in {'routine', 'skip', 'unknown'}:
            raise ValueError('Unknown day scenario')
        start = self._start_day()
        if mode != 'skip':
            self.engine.ingest(Observation('switch.dining_lamp', start+timedelta(minutes=5), 'on', 'off',
                source='human' if mode == 'routine' else 'unknown',
                evidence='Synthetic button event: selected by the visitor' if mode == 'routine' else ''))
        self.at = start+timedelta(minutes=31)
        self.engine.learn(self.at)
        self.steps += 1
        self.day = start+timedelta(days=1)
        descriptions = {
            'routine': 'A verified synthetic human turned on the lamp at 18:05. Learning uses this evidence.',
            'skip': 'The context was observed, but nobody turned on the lamp. Valid opportunities count against the routine.',
            'unknown': 'The lamp changed with an unknown cause. It does not become a human habit or a scored miss.'}
        self._note(mode, descriptions[mode])

    def quiet_days(self, count=35):
        self._checkpoint('Before absence of context')
        self.at += timedelta(days=count)
        self.day = self.at.replace(hour=10, minute=0, second=0)+timedelta(days=1)
        self.engine.learn(self.at)
        self._note('dormancy', 'No observation coverage or matching-context exposure was added. Evidence is preserved; old habits can become dormant.')

    def undo(self):
        if self.steps >= 90:
            raise ValueError('This sandbox is limited to 90 observed days; reset for another run')
        # A synthetic acknowledgement, explicitly requested by the visitor,
        # exercises the real feedback code. No device executes anything.
        known = [h for h in habits(self.engine.store, self.engine.config, self.at) if h['target']=='on']
        if not known:
            raise ValueError('Observe at least four matching human actions before trying a simulated undo')
        start = self._start_day()
        h = sorted(known, key=lambda h: h['specificity'])[-1]
        register_execution(self.engine.store, 'sandbox-'+str(self.steps), 'switch.dining_lamp', 'on', 'off', start, h['id'])
        self.engine.ingest(Observation('switch.dining_lamp', start, 'on', 'off', source='device',
                                       evidence='Synthetic acknowledgement, not a real device execution'))
        self.engine.ingest(Observation('switch.dining_lamp', start+timedelta(minutes=2), 'off', 'on', source='human',
                                       evidence='Synthetic visitor undo'))
        self.at = start+timedelta(minutes=31)
        self.engine.learn(self.at)
        self.steps += 1
        self.day = start+timedelta(days=1)
        self._note('undo', 'A simulated agent action was undone by the human. The real feedback engine adds β+3 and a 90-minute human lease to the selected habit.')

    def correct(self, text):
        if not isinstance(text, str) or not text.strip() or len(text) > 500:
            raise ValueError('Enter a correction of 1–500 characters')
        parsed = LocalCorrectionParser(self.engine.config).parse(text)
        if parsed.get('intent') == 'constraint':
            self._checkpoint('Before explicit correction')
            constraint(self.engine.store, self.engine.config, parsed['entity_id'], parsed['deny_actions'],
                       parsed['scope'], parsed['reason'], 'voice', self.at)
            self._note('constraint', 'A bounded rule parsed this prohibition. It restricts future proposals; it cannot relax safety policy.')
        else:
            self._note('parse', 'Rule result: '+parsed['intent']+'. EdgeJev weights are not loaded in this browser; no model inference is claimed.')
        return parsed

    def restore(self):
        if not self.checkpoints:
            raise ValueError('No memory checkpoint yet')
        checkpoint = self.checkpoints.pop()
        restore_state(self.engine.store, checkpoint['memory'])
        with self.engine.store.db:
            change(self.engine.store, self.at.isoformat(), 'sandbox_rollback', {'label': checkpoint['label']})
        self._note('rollback', 'Restored '+checkpoint['label']+'. Observations, execution receipts and human leases remain. Later learning can relearn retained evidence.')

    def view(self):
        data = self.engine.inspect(self.at)
        timeline = [{'at': e['occurred_at'], 'before': e['old_state'], 'after': e['new_state'],
                     'source': e['attributed_source'], 'kind': e['kind']} for e in self.engine.store.events()
                    if e['entity_id']=='switch.dining_lamp'][-18:]
        return {'synthetic': True, 'physical_execution': False, 'asof': self.at.isoformat(),
                'observed_days': self.steps, 'event_count': data['event_count'], 'habits': data['habits'],
                'constraints': data['constraints'], 'forecasts': data['forecasts'],
                'leases': [{'entity': e, 'until': t} for e,t in
                    self.engine.store.db.execute('SELECT entity_id,until_at FROM human_leases')],
                'timeline': timeline, 'audit': self.audit[-20:], 'message': self.last_message,
                'checkpoints': len(self.checkpoints), 'edgejev': 'not_loaded',
                'storage': 'Session-only SQLite; session checkpoints, not Git history'}

    def dispatch_json(self, payload):
        command = json.loads(payload)
        if not isinstance(command, dict): raise ValueError('Expected a command object')
        action = command.get('action')
        if action == 'day': self.observe_day(command.get('mode', 'routine'))
        elif action == 'week':
            if self.steps+7 > 90: raise ValueError('Seven days would exceed the 90-day sandbox limit; reset or observe one day')
            for _ in range(7): self.observe_day(command.get('mode', 'routine'))
        elif action == 'quiet': self.quiet_days()
        elif action == 'undo': self.undo()
        elif action == 'correct': parsed = self.correct(command.get('text', ''))
        elif action == 'rollback': self.restore()
        elif action != 'inspect': raise ValueError('Unsupported sandbox command')
        result = self.view()
        if action == 'correct': result['parsed'] = parsed
        return json.dumps(result, ensure_ascii=False, allow_nan=False)

    def close(self):
        self.engine.close()
