"""Manual acceptance: discover entities and observe a single operator-led trial."""
import argparse
import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

from .core import utc
from .ha import receive, websocket_url


def authenticate(ws, token):
    if receive(ws).get("type") != "auth_required":
        raise RuntimeError("Unexpected HA handshake")
    ws.send(json.dumps({"type": "auth", "access_token": token}))
    if receive(ws).get("type") != "auth_ok":
        raise PermissionError("Authentication failed; check HA_TOKEN")


def snapshot(ws):
    ws.send(json.dumps({"id": 1, "type": "get_states"}))
    reply = receive(ws)
    if reply.get("id") != 1 or not reply.get("success"):
        raise RuntimeError("HA refused entity snapshot")
    return reply["result"]


def inventory(states):
    # Only minimal metadata from relevant domains; never save camera URLs or frames.
    result = []
    for state in states:
        entity = state["entity_id"]
        if entity.split(".")[0] not in {"sensor", "binary_sensor", "switch", "light"}:
            continue
        attrs = state.get("attributes", {})
        result.append({"entity_id": entity, "state": state["state"],
                       "name": attrs.get("friendly_name"),
                       "device_class": attrs.get("device_class"),
                       "unit": attrs.get("unit_of_measurement"),
                       "state_class": attrs.get("state_class")})
    return sorted(result, key=lambda row: row["entity_id"])


def observation(message, entity, started):
    event = message.get("event", message)
    if event.get("event_type") != "state_changed":
        return None
    data = event.get("data", {})
    if data.get("entity_id") != entity:
        return None
    stamp = utc(event["time_fired"])
    if stamp < utc(started):
        return None
    old, new = data.get("old_state"), data.get("new_state")
    attrs = (new or {}).get("attributes", {})
    return {"occurred_at": stamp, "old_state": (old or {}).get("state"),
            "new_state": (new or {}).get("state"),
            "context": (new or {}).get("context") or event.get("context") or {},
            "unit": attrs.get("unit_of_measurement")}


def report(entity, expected, started, rows, initial=None, note="", complete=True):
    matches = [r for r in rows if (expected == "*" or r["new_state"] == expected) and
               r["old_state"] not in (None, "unknown", "unavailable") and
               r["new_state"] not in (None, "unknown", "unavailable", r["old_state"])]
    delay = None
    if matches:
        delay = (datetime.fromisoformat(min(r["occurred_at"] for r in matches)) -
                 datetime.fromisoformat(utc(started))).total_seconds()
    return {"entity_id": entity, "expected_state": expected, "started_at": utc(started),
            "initial_state": initial, "operator_note": note,
            "result": "expected_transition_observed" if matches else
                      ("not_observed" if complete else "incomplete"),
            "observation_complete": complete,
            "seconds_from_arm_to_ha_event": delay,
            "timing_note": "Includes operator reaction time; clocks must be synchronized. Not device latency.",
            "attribution": "Operator-led trial; HA context alone does not prove human origin.",
            "events": rows}


def write_report(folder, result):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    (folder / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if "entity_id" in result:
        text = (f"# Acceptance observation\n\nEntity: `{result['entity_id']}`\n\n"
                f"Result: **{result['result']}**\n\nExpected state: `{result['expected_state']}`\n\n"
                f"Operator note: {result['operator_note']}\n\n"
                f"Arm-to-event seconds: {result['seconds_from_arm_to_ha_event']}\n\n"
                f"{result['timing_note']}\n\n{result['attribution']}\n\n"
                "This report does not certify electrical safety, local/offline operation or energy accuracy.\n")
        (folder / "report.md").write_text(text, encoding="utf-8")


def live_trial(ws, entity, expected, seconds, note):
    states = snapshot(ws)
    selected = next((s for s in states if s["entity_id"] == entity), None)
    if selected is None:
        raise ValueError("Entity not found; run discover and copy its exact ID")
    ws.send(json.dumps({"id": 2, "type": "subscribe_events", "event_type": "state_changed"}))
    reply = receive(ws)
    if reply.get("id") != 2 or not reply.get("success"):
        raise RuntimeError("HA refused event subscription")
    started = datetime.now(timezone.utc).isoformat()
    deadline = time.monotonic() + seconds
    print(f"ARMED: {entity}; initial={selected['state']}; expected={expected}. Perform the manual action now.", flush=True)
    rows, complete = [], True
    try:
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                payload = json.loads(ws.recv(timeout=remaining))
            except TimeoutError:
                break
            row = observation(payload, entity, started)
            if row:
                rows.append(row)
                print(f"{row['occurred_at']} {row['old_state']} -> {row['new_state']}", flush=True)
    except KeyboardInterrupt:
        complete = False
    except Exception:
        # Keep partial evidence if the network drops, without saving exception payloads.
        complete = False
        print("Trial interrupted by a connection/protocol failure; saving partial evidence.")
    return report(entity, expected, started, rows, selected["state"], note, complete)


def main():
    parser = argparse.ArgumentParser(description="Read-only dining-room hardware acceptance")
    parser.add_argument("--url", default="http://127.0.0.1:8123")
    parser.add_argument("--output", required=True, help="New private report directory (must not exist)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("discover")
    for name in ("test", "replay"):
        trial = commands.add_parser(name)
        trial.add_argument("--entity", required=True)
        trial.add_argument("--expected", required=True, help="Exact HA state (on/off), or '*' for any valid change")
        trial.add_argument("--note", default="")
        if name == "test":
            trial.add_argument("--seconds", type=int, default=60)
        else:
            trial.add_argument("--input", required=True)
            trial.add_argument("--since", required=True, help="Timezone-aware ISO timestamp")
    args = parser.parse_args()
    if Path(args.output).exists():
        parser.error("Output directory already exists; choose a new trial name")
    if args.command == "test" and not 1 <= args.seconds <= 600:
        parser.error("Trial duration must be 1–600 seconds")
    if args.command != "discover" and args.entity.split(".")[0] not in {"sensor", "binary_sensor", "switch", "light"}:
        parser.error("Only sensor, binary_sensor, switch and light entities are supported")
    try:
        if args.command == "replay":
            rows = []
            with open(args.input, encoding="utf-8-sig") as source:
                for line in source:
                    if line.strip():
                        row = observation(json.loads(line), args.entity, args.since)
                        if row:
                            rows.append(row)
            rows.sort(key=lambda r: r["occurred_at"])
            result = report(args.entity, args.expected, args.since, rows, note=args.note)
            result["mode"] = "offline_replay"
        else:
            token = os.environ.get("HA_TOKEN")
            if not token:
                parser.error("Set HA_TOKEN in the local environment first")
            from websockets.sync.client import connect
            with connect(websocket_url(args.url), open_timeout=20, ping_interval=20, ping_timeout=20) as ws:
                authenticate(ws, token)
                if args.command == "discover":
                    result = {"captured_at": datetime.now(timezone.utc).isoformat(),
                              "client_architecture": platform.machine(), "entities": inventory(snapshot(ws))}
                    for row in result["entities"]:
                        print(f"{row['entity_id']} | {row['name']} | {row['state']} | {row['unit']}")
                else:
                    result = live_trial(ws, args.entity, args.expected, args.seconds, args.note)
        write_report(args.output, result)
        print(f"Saved {args.output}/result.json")
    except (ValueError, PermissionError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")
    except (OSError, TimeoutError):
        parser.exit(1, "Connection or file operation failed; check HA URL and output permissions.\n")
    except Exception:
        # Do not print server exception payloads into operator logs.
        parser.exit(1, "HA protocol or input data error; no complete acceptance result was produced.\n")


if __name__ == "__main__":
    main()
