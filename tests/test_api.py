import copy
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from moqi.api import HomeMemory, Observation, validate_config


CONFIG = {'site': 'synthetic', 'timezone': 'Asia/Shanghai', 'entities': {
    'switch.lamp': {'role': 'actuator', 'room': 'dining', 'risk': 'low', 'category': 'light'},
    'sensor.power': {'role': 'power', 'room': 'dining'}}}
AT = datetime(2026, 3, 2, 10, tzinfo=timezone.utc)


class PublicApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = HomeMemory(CONFIG, str(Path(self.temp.name)/'db.sqlite3'))

    def tearDown(self):
        self.engine.close(); self.temp.cleanup()

    def test_configuration_is_owned_and_validated(self):
        config = copy.deepcopy(CONFIG)
        validated = validate_config(config)
        config['entities']['switch.lamp']['risk'] = 'high'
        self.assertEqual(validated['entities']['switch.lamp']['risk'], 'low')
        for update in [{'forgetting_gamma': True}, {'forgetting_gamma': 0},
                       {'holidays': ['2026-03-02'], 'workdays': ['2026-03-02']}, {'entities': {}}]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_config(dict(CONFIG, **update))

    def test_generic_adapter_and_deduplication(self):
        baseline = Observation('switch.lamp', AT, 'off')
        self.assertTrue(self.engine.ingest(baseline)); self.assertFalse(self.engine.ingest(baseline))
        action = Observation('switch.lamp', AT+timedelta(minutes=2), 'on', 'off',
                             source='human', evidence='Synthetic physical button')
        self.assertTrue(self.engine.ingest(action))
        self.assertEqual(self.engine.store.events()[-1]['attributed_source'], 'human')

    def test_missing_attribution_and_baseline_are_rejected(self):
        for observation in [Observation('switch.lamp', AT, 'on', 'off', source='human'),
                            Observation('switch.lamp', AT, 'on', source='human', evidence='not a change'),
                            Observation('sensor.power', AT, '2', '1', source='human', evidence='bad attribution')]:
            with self.subTest(observation=observation), self.assertRaises(ValueError):
                self.engine.ingest(observation)
        self.assertEqual(self.engine.store.events(), [])

    def test_unknown_actuator_is_not_human(self):
        self.engine.ingest(Observation('switch.lamp', AT, 'on', 'off'))
        self.assertEqual(self.engine.store.events()[0]['attributed_source'], 'unknown')

    def test_allowlist_camera_and_nonfinite(self):
        with self.assertRaises(ValueError):
            self.engine.ingest(Observation('switch.other', AT, 'on'))
        with self.assertRaises(ValueError):
            validate_config(dict(CONFIG, entities={'camera.home': {'room': 'home', 'role': 'actuator'}}))
        with self.assertRaises(ValueError):
            self.engine.ingest(Observation('sensor.power', AT, '1', attributes={'value': float('nan')}))

    def test_coverage_clock_and_learning(self):
        with self.assertRaises(ValueError):
            self.engine.observe_interval(AT, AT)
        with self.assertRaises(ValueError):
            self.engine.learn(AT.replace(tzinfo=None))
        self.engine.observe_interval(AT, AT+timedelta(minutes=30))
        self.engine.ingest(Observation('switch.lamp', AT, 'off'))
        self.engine.learn(AT+timedelta(minutes=31))
        self.assertEqual(self.engine.inspect(AT+timedelta(minutes=31))['event_count'], 1)

    def test_future_database_version_is_rejected_without_schema_edits(self):
        path = Path(self.temp.name)/'future.sqlite3'
        connection = sqlite3.connect(path)
        connection.execute('PRAGMA user_version=999'); connection.close()
        with self.assertRaisesRegex(RuntimeError, 'newer'):
            HomeMemory(CONFIG, str(path))
        connection = sqlite3.connect(path)
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()[0], 0)
        self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 999)
        connection.close()

    def test_legacy_database_is_marked_after_compatible_migration(self):
        self.assertEqual(self.engine.store.db.execute('PRAGMA user_version').fetchone()[0], 1)

    def test_versioned_json_adapter_event(self):
        payload = {'schema_version': 1, 'entity_id': 'switch.lamp', 'at': AT.isoformat(),
                   'state': 'on', 'previous': 'off', 'source': 'human', 'evidence': 'Synthetic JSON event'}
        self.assertTrue(self.engine.ingest(Observation.from_dict(payload)))
        for update in [{'schema_version': True}, {'schema_version': 2}, {'at': '2026-03-02T10:00:00'}, {'source': []}, {'unknown_field': 1}]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                Observation.from_dict(dict(payload, **update))


if __name__ == '__main__': unittest.main()
