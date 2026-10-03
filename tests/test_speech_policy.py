import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from moqi.core import Store
from moqi.speech_policy import reserve


class SpeechBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'speech.sqlite3'
        self.store = Store(self.path)
        self.config = {'timezone': 'Asia/Shanghai', 'entities': {'switch.light': {'room': 'dining_room'}}}
        self.at = datetime(2026, 10, 1, 2, tzinfo=timezone.utc)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def call(self, **changes):
        args = dict(request_id='one', at=self.at, room='dining_room', kind='safety',
                    duration_seconds=3, occupied=True, occupancy_at=self.at)
        args.update(changes)
        return reserve(self.store, self.config, **args)

    def test_daily_budget_persists_across_restart(self):
        self.assertTrue(self.call()['allowed'])
        self.store.close(); self.store = Store(self.path)
        self.assertFalse(self.call()['allowed'])
        self.assertTrue(self.call(request_id='two')['allowed'])
        self.assertEqual(self.call(request_id='three')['reason'], 'daily_proactive_budget')
        tomorrow = self.at + timedelta(days=1)
        self.assertTrue(self.call(request_id='four', at=tomorrow, occupancy_at=tomorrow)['allowed'])

    def test_night_boundaries_apply_to_all_speech(self):
        for hour, minute, allowed in [(14,59,True),(15,0,False),(22,59,False),(23,0,True)]:
            at = self.at.replace(hour=hour, minute=minute)
            with self.subTest(at=at):
                result = self.call(request_id=f'{hour}-{minute}', at=at, occupancy_at=at,
                                   kind='explanation', user_engaged=True)
                self.assertEqual(result['allowed'], allowed)

    def test_presence_unknown_absent_stale_and_future(self):
        for changes in [dict(occupied=False), dict(occupied=None), dict(occupied=1),
                        dict(occupancy_at=self.at-timedelta(seconds=61)),
                        dict(occupancy_at=self.at+timedelta(seconds=1))]:
            with self.subTest(changes=changes):
                self.assertFalse(self.call(**changes)['allowed'])

    def test_actual_audio_duration_and_typed_request(self):
        for duration in [0, -1, 8.01, float('nan'), float('inf'), True, '3']:
            self.assertFalse(self.call(duration_seconds=duration)['allowed'])
        self.assertFalse(self.call(room='unknown')['allowed'])
        self.assertFalse(self.call(kind='chat')['allowed'])
        self.assertTrue(self.call(duration_seconds=8)['allowed'])

    def test_question_only_in_user_conversation_once_daily(self):
        self.assertEqual(self.call(kind='question')['reason'], 'user_conversation_required')
        self.assertTrue(self.call(kind='question', user_engaged=True)['allowed'])
        self.assertEqual(self.call(request_id='two', kind='question', user_engaged=True)['reason'], 'daily_question_budget')
        self.assertTrue(self.call(request_id='answer', kind='explanation', user_engaged=True)['allowed'])

    def test_first_habit_requires_real_first_receipt(self):
        self.assertEqual(self.call(kind='new_habit', habit_id='h')['reason'], 'first_execution_not_verified')
        self.store.db.execute("INSERT INTO execution_ledger(id,habit_id,issued_at,status) VALUES (?,?,?,?)", ('execution','h',self.at.isoformat(),'acknowledged'))
        self.store.db.commit()
        self.assertTrue(self.call(kind='new_habit', habit_id='h')['allowed'])
        self.assertEqual(self.call(request_id='two', kind='new_habit', habit_id='h')['reason'], 'habit_already_announced')

    def test_later_execution_cannot_be_first_announcement(self):
        for i in range(2):
            self.store.db.execute("INSERT INTO execution_ledger(id,habit_id,issued_at,status) VALUES (?,?,?,?)", (str(i),'h',self.at.isoformat(),'acknowledged'))
        self.store.db.commit()
        self.assertFalse(self.call(kind='new_habit', habit_id='h')['allowed'])

    def test_clock_rollback_does_not_reset_budget(self):
        self.assertTrue(self.call()['allowed'])
        past = self.at-timedelta(minutes=1)
        self.assertEqual(self.call(request_id='past', at=past, occupancy_at=past)['reason'], 'clock_moved_backwards')

    def test_no_text_audio_or_device_execution_recorded(self):
        self.assertFalse(self.call(kind='explanation')['allowed'])
        self.assertTrue(self.call()['allowed'])
        columns = [r[1] for r in self.store.db.execute('PRAGMA table_info(speech_reservations)')]
        self.assertNotIn('text', columns); self.assertNotIn('audio', columns)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM execution_ledger').fetchone()[0], 0)

    def test_concurrent_speakers_share_atomic_daily_limit(self):
        def attempt(index):
            store = Store(self.path)
            try:
                return reserve(store, self.config, request_id=str(index), at=self.at,
                               room='dining_room', kind='safety', duration_seconds=1,
                               occupied=True, occupancy_at=self.at)['allowed']
            finally:
                store.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(attempt, range(4)))
        self.assertEqual(sum(results), 2)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM speech_reservations').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
