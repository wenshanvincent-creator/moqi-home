import json
import tempfile
import unittest
from pathlib import Path
from moqi.playground import Sandbox
from moqi.memory_store import objects, state, restore_state


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.sandbox = Sandbox(str(Path(self.temp.name)/'db.sqlite3'))

    def tearDown(self):
        self.sandbox.close(); self.temp.cleanup()

    def train(self):
        for _ in range(7): self.sandbox.observe_day()

    def test_habits_emerge_from_real_engine_not_fixture_values(self):
        self.assertEqual(self.sandbox.view()['habits'], [])
        for _ in range(3): self.sandbox.observe_day()
        self.assertEqual(self.sandbox.view()['habits'], [])
        self.sandbox.observe_day()
        self.assertTrue(self.sandbox.view()['habits'])
        h = self.sandbox.view()['habits'][0]
        self.assertEqual(h['successes'], 4)
        self.assertGreater(h['probability'], .7)
        self.assertTrue(self.sandbox.view()['synthetic'])
        self.assertFalse(self.sandbox.view()['physical_execution'])

    def test_unknown_cause_does_not_train_or_score(self):
        self.train()
        before = len(objects(self.sandbox.engine.store, 'memory_habits'))
        self.sandbox.observe_day('unknown')
        self.assertEqual(len(objects(self.sandbox.engine.store, 'memory_habits')), before)
        self.assertEqual(self.sandbox.view()['forecasts'][0]['outcome'], 'unscored')

    def test_context_absence_preserves_evidence(self):
        self.train()
        before = {h['id']: (h['alpha'],h['beta']) for h in self.sandbox.view()['habits']}
        self.sandbox.quiet_days()
        after = self.sandbox.view()['habits']
        self.assertEqual({h['id']: (h['alpha'],h['beta']) for h in after}, before)
        self.assertTrue(all(h['status']=='seasonal_dormant' for h in after))

    def test_covered_misses_reduce_confidence(self):
        self.train()
        h = next(h for h in self.sandbox.view()['habits'] if h['specificity']==3)
        self.sandbox.observe_day('skip')
        revised = next(x for x in self.sandbox.view()['habits'] if x['id']==h['id'])
        self.assertGreater(revised['failures'], h['failures'])
        self.assertLess(revised['probability'], h['probability'])

    def test_rollback_removes_constraint_not_observations(self):
        self.train()
        count = self.sandbox.view()['event_count']
        parsed = self.sandbox.correct('不要自动开餐厅灯')
        self.assertEqual(parsed['intent'], 'constraint')
        self.assertEqual(len(self.sandbox.view()['constraints']), 1)
        self.sandbox.restore()
        self.assertEqual(self.sandbox.view()['constraints'], [])
        self.assertEqual(self.sandbox.view()['event_count'], count)

    def test_simulated_undo_real_beta_and_lease(self):
        self.train()
        self.sandbox.undo()
        undo = [e for e in objects(self.sandbox.engine.store, 'memory_evidence') if e.get('signal')=='undo']
        self.assertTrue(undo)
        self.assertEqual(undo[0]['beta'], 3)
        self.assertTrue(self.sandbox.view()['leases'])

    def test_dispatch_rejects_unknown_commands_and_view_does_not_write(self):
        with self.assertRaises(ValueError): self.sandbox.dispatch_json('{"action":"execute"}')
        before = self.sandbox.engine.store.db.total_changes
        json.loads(self.sandbox.dispatch_json('{"action":"inspect"}'))
        self.assertEqual(self.sandbox.engine.store.db.total_changes, before)

    def test_invalid_snapshot_cannot_partially_replace_memory(self):
        self.train()
        before = state(self.sandbox.engine.store)
        bad = dict(before, memory_episodes=[[1]])
        with self.assertRaises(ValueError): restore_state(self.sandbox.engine.store, bad)
        self.assertEqual(state(self.sandbox.engine.store), before)

    def test_week_limit_rejects_before_any_partial_observation(self):
        self.sandbox.steps=85
        with self.assertRaises(ValueError): self.sandbox.dispatch_json('{"action":"week"}')
        self.assertEqual(self.sandbox.steps,85)
        self.assertEqual(self.sandbox.engine.store.events(),[])
        self.sandbox.steps=90
        with self.assertRaisesRegex(ValueError, '90'):
            self.sandbox.undo()
        with self.assertRaisesRegex(ValueError, '90'):
            self.sandbox.observe_day()
        self.assertEqual(self.sandbox.engine.store.events(),[])


if __name__ == '__main__': unittest.main()
