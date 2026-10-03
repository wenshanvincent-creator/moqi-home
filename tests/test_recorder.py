import io
import json
import tempfile
import unittest
from pathlib import Path

from moqi.core import Store, normalize
from moqi.ha import capture_session, websocket_url


CONFIG = {"site": "test", "entities": {
    "switch.test_plug": {"role": "actuator", "room": "living"},
    "binary_sensor.test_motion": {"role": "motion", "room": "living"}}}


def event(entity="switch.test_plug", before="off", after="on", time="2026-09-30T12:00:00Z"):
    return {"event_type": "state_changed", "time_fired": time,
            "data": {"entity_id": entity,
                     "old_state": None if before is None else {"state": before},
                     "new_state": None if after is None else {
                         "entity_id": entity, "state": after, "attributes": {},
                         "last_updated": time, "context": {"id": "ctx", "user_id": "user"}}}}


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "events.sqlite3"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_unknown_actuator_not_human_even_with_user_context(self):
        row = normalize(event(), CONFIG)
        self.assertEqual(row["source"], "unknown")
        self.assertEqual(json.loads(row["context_json"])["user_id"], "user")

    def test_allowlist_excludes_camera(self):
        self.assertIsNone(normalize(event("camera.private"), CONFIG))

    def test_sensor_is_not_a_human_action(self):
        self.assertEqual(normalize(event("binary_sensor.test_motion"), CONFIG)["source"], "sensor")

    def test_lifecycle_and_attributes_not_actions(self):
        for before, after, expected in [(None, "on", "baseline"), ("unavailable", "on", "baseline"),
                                        ("on", "unavailable", "unavailable"), ("on", None, "removed"),
                                        ("on", "on", "attributes")]:
            self.assertEqual(normalize(event(before=before, after=after), CONFIG)["kind"], expected)

    def test_duplicates_restart_and_out_of_order_export(self):
        later = normalize(event(time="2026-09-30T12:01:00Z"), CONFIG)
        earlier = normalize(event(), CONFIG)
        self.assertTrue(self.store.add(later))
        self.assertTrue(self.store.add(earlier))
        self.store.close()
        self.store = Store(self.path)
        self.assertFalse(self.store.add(earlier))
        output = io.StringIO()
        self.store.export(output)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[0]["time_fired"], "2026-09-30T12:00:00Z")
        self.assertEqual(len(rows), 2)

    def test_rejects_naive_timestamps(self):
        with self.assertRaises(ValueError):
            normalize(event(time="2026-09-30T12:00:00"), CONFIG)

    def test_websocket_url_and_credentials(self):
        self.assertEqual(websocket_url("https://ha.example:8123/"), "wss://ha.example:8123/api/websocket")
        with self.assertRaises(ValueError):
            websocket_url("http://user:secret@ha.example")


class FakeSocket:
    def __init__(self, auth="auth_ok"):
        self.sent = []
        self.handshake = iter([{"type": "auth_required"}, {"type": auth},
                               {"type": "result", "id": 1, "success": True}])
        live = event()
        state = event(before=None, after="off")["data"]["new_state"]
        self.messages = iter([{"type": "event", "id": 1, "event": live},
                              {"type": "result", "id": 2, "success": True, "result": [state]}])

    def recv(self, timeout=None):
        try:
            return json.dumps(next(self.handshake))
        except StopIteration:
            return json.dumps(next(self.messages))

    def send(self, message):
        self.sent.append(json.loads(message))

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return json.dumps(next(self.messages))
        except StopIteration:
            raise StopIteration


class AdapterTests(unittest.TestCase):
    def test_handshake_interleaved_snapshot_and_readonly_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "events.db")
            try:
                ws = FakeSocket()
                capture_session(ws, "test-token", CONFIG, store)
                self.assertEqual([m["type"] for m in ws.sent], ["auth", "subscribe_events", "get_states"])
                self.assertEqual(sum(row["count"] for row in store.summary()), 2)
                status = store.db.execute("SELECT status FROM sessions").fetchone()[0]
                self.assertEqual(status, "disconnected")
            finally:
                store.close()

    def test_bad_auth_stops_without_subscribing(self):
        ws = FakeSocket(auth="auth_invalid")
        with self.assertRaises(PermissionError):
            capture_session(ws, "wrong", CONFIG, None)
        self.assertEqual(len(ws.sent), 1)
