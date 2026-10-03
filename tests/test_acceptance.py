import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from moqi.acceptance import authenticate, inventory, live_trial, observation, report, write_report


START = "2026-09-30T12:00:00Z"
ENTITY = "switch.dining_plug"


def message(before="off", after="on", entity=ENTITY, stamp="2026-09-30T12:00:03Z"):
    return {"event": {"event_type": "state_changed", "time_fired": stamp,
                      "data": {"entity_id": entity,
                               "old_state": None if before is None else {"state": before},
                               "new_state": None if after is None else {
                                   "state": after, "context": {"id": "test"}}}}}


class AcceptanceTests(unittest.TestCase):
    def test_filter_other_entities_and_queued_old_events(self):
        self.assertIsNone(observation(message(entity="switch.other"), ENTITY, START))
        self.assertIsNone(observation(message(stamp="2026-09-30T11:59:59Z"), ENTITY, START))

    def test_evidence_and_timing(self):
        row = observation(message(), ENTITY, START)
        result = report(ENTITY, "on", START, [row])
        self.assertEqual(result["result"], "expected_transition_observed")
        self.assertEqual(result["seconds_from_arm_to_ha_event"], 3)

    def test_baselines_recovery_and_attributes_do_not_pass(self):
        for before, after in [(None, "on"), ("unavailable", "on"), ("on", "on"), ("on", None)]:
            row = observation(message(before, after), ENTITY, START)
            self.assertEqual(report(ENTITY, "on", START, [row])["result"], "not_observed")

    def test_interrupted_trial_not_mislabeled_as_failure(self):
        self.assertEqual(report(ENTITY, "on", START, [], complete=False)["result"], "incomplete")

    def test_meter_any_change_preserves_unit(self):
        msg = message("0", "12.5")
        msg["event"]["data"]["new_state"]["attributes"] = {"unit_of_measurement": "W"}
        row = observation(msg, ENTITY, START)
        self.assertEqual(row["unit"], "W")
        self.assertEqual(report(ENTITY, "*", START, [row])["result"], "expected_transition_observed")

    def test_inventory_omits_camera_and_arbitrary_metadata(self):
        rows = inventory([
            {"entity_id": "camera.private", "state": "idle", "attributes": {"access_token": "secret"}},
            {"entity_id": ENTITY, "state": "off", "attributes": {"friendly_name": "Dining", "secret": "no"}}])
        self.assertEqual(len(rows), 1)
        self.assertNotIn("secret", rows[0])

    def test_report_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "trial"
            result = report(ENTITY, "on", START, [])
            write_report(folder, result)
            self.assertTrue((folder / "report.md").exists())
            with self.assertRaises(FileExistsError):
                write_report(folder, result)

    def test_live_trial_readonly_and_saves_disconnect(self):
        class Socket:
            def __init__(self):
                self.sent = []
                self.replies = iter([
                    {"id": 1, "success": True, "result": [{"entity_id": ENTITY, "state": "off"}]},
                    {"id": 2, "success": True}])

            def send(self, raw):
                self.sent.append(json.loads(raw))

            def recv(self, timeout=None):
                try:
                    return json.dumps(next(self.replies))
                except StopIteration:
                    raise OSError("Disconnected")

        ws = Socket()
        with redirect_stdout(io.StringIO()):
            result = live_trial(ws, ENTITY, "on", 60, "button")
        self.assertEqual(result["result"], "incomplete")
        self.assertEqual([r["type"] for r in ws.sent], ["get_states", "subscribe_events"])

    def test_auth_rejection_no_control_commands(self):
        class Socket:
            replies = iter([{"type": "auth_required"}, {"type": "auth_invalid"}])
            sent = []

            def recv(self, timeout=None):
                return json.dumps(next(self.replies))

            def send(self, raw):
                self.sent.append(json.loads(raw))

        ws = Socket()
        with self.assertRaises(PermissionError):
            authenticate(ws, "private")
        self.assertEqual([r["type"] for r in ws.sent], ["auth"])
