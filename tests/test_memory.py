import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

from moqi.core import Store, normalize
from moqi.memory import context, habits, predict, evaluate, episodes, coverage, consolidate
from moqi.dashboard import export_html


CONFIG = dict(site='test',timezone='Asia/Shanghai',holidays=[],entities={
    'switch.lamp':dict(room='dining_room',role='actuator')})
AT = datetime(2026,10,9,2,tzinfo=timezone.utc)


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name)/'db.sqlite3')

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def add(self,at,before='off',after='on',source=None):
        row = normalize(dict(event_type='state_changed',time_fired=at.isoformat(),data=dict(
            entity_id='switch.lamp',old_state=None if before is None else dict(state=before),
            new_state=dict(state=after))),CONFIG)
        self.store.add(row)
        if source:
            self.store.annotate(row['event_key'],source,'observed physical test')
        return row['event_key']

    def train(self,verified=True,with_coverage=True):
        for n in (1,2,3,4):
            day = AT-timedelta(days=n)
            self.add(day,before=None,after='off')
            self.add(day+timedelta(minutes=5),source='human' if verified else None)
            if with_coverage:
                self.store.db.execute('INSERT INTO sessions(started_at,ended_at,status) VALUES (?,?,?)',
                                     (day.isoformat(),(day+timedelta(minutes=30)).isoformat(),'test'))
        self.store.db.commit()
        consolidate(self.store,CONFIG,AT)

    def test_unknown_actions_never_create_habits(self):
        self.train(verified=False)
        self.assertEqual(habits(self.store,CONFIG,AT),[])

    def test_four_days_shadow_and_beta_counts(self):
        self.train()
        result = habits(self.store,CONFIG,AT)[0]
        self.assertEqual((result['successes'],result['failures']),(4,0))
        self.assertGreater(result['alpha'],0)
        self.assertEqual(result['trust_level'],1)

    def test_no_coverage_does_not_generate_negative_evidence(self):
        self.train(with_coverage=False)
        result = habits(self.store,CONFIG,AT)[0]
        self.assertEqual(result['failures'],0)
        self.assertEqual(result['trust_level'],1)

    def test_unknown_change_invalidates_covered_opportunity(self):
        self.train()
        day=AT-timedelta(days=7)
        self.add(day,before=None,after='off')
        self.store.db.execute('INSERT INTO sessions(started_at,ended_at,status) VALUES (?,?,?)',
                             (day.isoformat(),(day+timedelta(minutes=15)).isoformat(),'test'))
        self.store.db.commit()
        # This predates the candidate's first observed evidence, so create an upcoming
        # covered opportunity with an uncertain actuator change instead.
        self.add(AT,before=None,after='off')
        self.add(AT+timedelta(minutes=3),before='off',after='on')
        self.store.db.execute('INSERT INTO sessions(started_at,ended_at,status) VALUES (?,?,?)',
                             (AT.isoformat(),(AT+timedelta(minutes=15)).isoformat(),'test'))
        self.store.db.commit()
        consolidate(self.store,CONFIG,AT+timedelta(minutes=16))
        self.assertEqual(habits(self.store,CONFIG,AT)[0]['failures'],0)

    def test_future_human_events_not_used(self):
        self.train()
        self.assertEqual(habits(self.store,CONFIG,AT-timedelta(days=3)),[])

    def test_four_occurrences_on_one_day_match_plan(self):
        for m in (1,3,5,7):
            self.add(AT-timedelta(days=1)+timedelta(minutes=m),source='human')
        consolidate(self.store,CONFIG,AT)
        self.assertTrue(habits(self.store,CONFIG,AT))
        self.assertEqual(habits(self.store,CONFIG,AT)[0]['observed_days'],1)

    def test_prediction_idempotence_and_unscored_gap(self):
        self.train()
        self.add(AT,before=None,after='off')
        predict(self.store,CONFIG,AT)
        predict(self.store,CONFIG,AT)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM forecasts').fetchone()[0],1)
        evaluate(self.store,AT+timedelta(minutes=16))
        self.assertEqual(self.store.db.execute('SELECT outcome FROM forecasts').fetchone()[0],'unscored')

    def test_forecast_hit_requires_coverage_and_verified_change(self):
        self.train()
        self.add(AT,before=None,after='off')
        predict(self.store,CONFIG,AT)
        self.add(AT+timedelta(minutes=3),source='human')
        self.store.db.execute('INSERT INTO sessions(started_at,ended_at,status) VALUES (?,?,?)',
                             (AT.isoformat(),(AT+timedelta(minutes=16)).isoformat(),'test'))
        self.store.db.commit()
        evaluate(self.store,AT+timedelta(minutes=16))
        self.assertEqual(self.store.db.execute('SELECT outcome FROM forecasts').fetchone()[0],'hit')

    def test_timezone_holiday_and_naive_timestamp(self):
        self.assertEqual(context(AT,CONFIG),('weekday',20))
        config = dict(CONFIG,holidays=['2026-10-09'])
        self.assertEqual(context(AT,config),('holiday',20))

    def test_bad_annotation_preserves_raw_data(self):
        key = self.add(AT)
        self.store.annotate(key,'human','observed')
        self.assertEqual(self.store.events()[0]['source'],'unknown')
        self.assertEqual(self.store.events()[0]['attributed_source'],'human')
        self.store.annotate(key,'unknown','evidence withdrawn')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM annotation_history').fetchone()[0],2)
        with self.assertRaises(ValueError):
            self.store.annotate('nonexistent','human','observed')

    def test_dashboard_export_escapes_embedded_data_and_refuses_overwrite(self):
        self.add(datetime.now(timezone.utc)-timedelta(minutes=1),after='</script><script>alert(1)</script>')
        path = Path(self.temp.name)/'preview.html'
        export_html(self.store,CONFIG,path)
        text = path.read_text(encoding='utf-8')
        self.assertIn('\\u003c/script>',text)
        self.assertNotIn('</script><script>alert',text)
        with self.assertRaises(FileExistsError):
            export_html(self.store,CONFIG,path)

    def test_episode_gaps_and_incomplete_session(self):
        self.add(AT)
        self.add(AT+timedelta(minutes=31))
        self.assertEqual(len(episodes(self.store,AT+timedelta(hours=1),CONFIG)),1)
        self.store.db.execute('INSERT INTO sessions(started_at,ended_at,last_seen_at,status) VALUES (?,?,?,?)',
                             (AT.isoformat(),(AT+timedelta(minutes=30)).isoformat(),
                              (AT+timedelta(minutes=10)).isoformat(),'disconnected'))
        self.assertEqual(coverage(self.store)[0][1],AT+timedelta(minutes=10))
