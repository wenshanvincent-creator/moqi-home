"""Read-only HA WebSocket adapter. No service-call API exists here."""
import json
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from .core import normalize

log = logging.getLogger(__name__)


def websocket_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("ha_url must be an http(s) URL without credentials")
    if parts.query or parts.fragment or parts.path not in ("", "/"):
        raise ValueError("ha_url must be the Home Assistant base URL")
    return urlunsplit(("wss" if parts.scheme == "https" else "ws", parts.netloc,
                       "/api/websocket", "", ""))


def receive(ws):
    return json.loads(ws.recv(timeout=30))


def capture_session(ws, token, config, store, tick=None):
    if receive(ws).get("type") != "auth_required":
        raise RuntimeError("Unexpected HA authentication handshake")
    ws.send(json.dumps({"type": "auth", "access_token": token}))
    if receive(ws).get("type") != "auth_ok":
        raise PermissionError("HA authentication failed; check HA_TOKEN")
    # Subscribe before snapshot so no live changes are lost during initialization.
    ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"}))
    reply = receive(ws)
    if reply.get("id") != 1 or not reply.get("success"):
        raise RuntimeError("HA refused event subscription")
    session = store.session_start()
    live_seen = {}
    try:
        ws.send(json.dumps({"id": 2, "type": "get_states"}))
        while True:
            if tick:
                tick()
            try:
                message = ws.recv(timeout=30)
            except TimeoutError:
                store.session_seen(session)
                continue
            except StopIteration:  # Test doubles may finish a finite stream.
                break
            store.session_seen(session)
            payload = json.loads(message)
            if payload.get("type") == "event":
                row=normalize(payload,config)
                if row:
                    live_seen[row['entity_id']]=row['occurred_at']
                store.add(row)
            elif payload.get("id") == 2:
                if not payload.get("success"):
                    raise RuntimeError("HA refused state snapshot")
                for state in payload["result"]:
                    from .core import utc
                    # An older get_states result must not overwrite a newer live change
                    # that arrived while this request was in flight.
                    seen=live_seen.get(state['entity_id'])
                    if seen and utc(state['last_updated']) < seen:
                        continue
                    store.add(normalize({"event_type": "state_changed",
                                         "time_fired": datetime.now(timezone.utc).isoformat(),
                                         "data": {"entity_id": state["entity_id"],
                                                  "old_state": None, "new_state": state}}, config))
    finally:
        store.session_end(session)


def collect(config, token, store, tick=None):
    from websockets.sync.client import connect
    from websockets.exceptions import ConnectionClosed
    url = websocket_url(config["ha_url"])
    delay = 1
    while True:
        if tick:
            tick()  # Nightly memory work can proceed even while HA is disconnected.
        try:
            with connect(url, ping_interval=20, ping_timeout=20, open_timeout=20) as ws:
                log.info("Connected; recording allowlisted entities only")
                capture_session(ws, token, config, store, tick)
            delay = 1
        except PermissionError:
            raise
        except (OSError, ConnectionClosed, TimeoutError):
            # Never log exception payloads or authentication messages.
            log.warning("HA unavailable; retry in %s seconds. Gap cannot be recovered.", delay)
        time.sleep(delay)
        delay = min(delay * 2, 60)
