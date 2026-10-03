import hashlib
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path


def utc(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Event timestamp must include a timezone")
    return dt.astimezone(timezone.utc).isoformat()


def normalize(message, config):
    event = message.get("event", message)
    if event.get("event_type") != "state_changed":
        return None
    data = event["data"]
    entity = data["entity_id"]
    if entity.startswith(('camera.','image.')):
        return None
    spec = config["entities"].get(entity)
    if spec is None:
        return None
    occurred = utc(event["time_fired"])
    old, new = data.get("old_state"), data.get("new_state")
    context = (new or {}).get("context") or event.get("context") or {}
    before, after = (old or {}).get("state"), (new or {}).get("state")
    kind = "transition"
    if new is None:
        kind = "removed"
    elif after in ("unknown", "unavailable"):
        kind = "unavailable"
    elif old is None or before in ("unknown", "unavailable"):
        kind = "baseline"
    elif before == after:
        kind = "attributes"
    # HA user_id is evidence of an authenticated context, not proof of a human.
    # Physical controls, cloud automations and autonomous devices may look identical.
    source = "sensor" if spec["role"] != "actuator" else "unknown"
    raw = json.dumps(event, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    key = hashlib.sha256((config["site"] + "\n" + raw).encode()).hexdigest()
    return {
        "event_key": key, "site": config["site"], "entity_id": entity,
        "room": spec["room"], "role": spec["role"], "occurred_at": occurred,
        "old_state": before, "new_state": after, "kind": kind,
        "source": source, "context_json": json.dumps(context), "raw_json": raw,
    }


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        schema_version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if schema_version > 1:
            self.db.close()
            raise RuntimeError('Database schema is newer than this version of Moqi; use a compatible release')
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                event_key TEXT PRIMARY KEY, site TEXT NOT NULL,
                entity_id TEXT NOT NULL, room TEXT NOT NULL, role TEXT NOT NULL,
                occurred_at TEXT NOT NULL, received_at TEXT NOT NULL,
                old_state TEXT, new_state TEXT, kind TEXT NOT NULL,
                source TEXT NOT NULL, context_json TEXT NOT NULL, raw_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_time ON events(occurred_at);
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT,
                status TEXT NOT NULL
            );
        """)
        self.db.commit()

        from .memory_store import initialize
        initialize(self)
        if 'last_seen_at' not in {r[1] for r in self.db.execute('PRAGMA table_info(sessions)')}:
            self.db.execute('ALTER TABLE sessions ADD COLUMN last_seen_at TEXT')
            self.db.commit()
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS annotations (
                event_key TEXT PRIMARY KEY REFERENCES events(event_key),
                source TEXT NOT NULL, reason TEXT NOT NULL, annotated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS annotation_history (
                id INTEGER PRIMARY KEY, event_key TEXT NOT NULL, source TEXT NOT NULL,
                reason TEXT NOT NULL, annotated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS forecasts (
                id INTEGER PRIMARY KEY, entity_id TEXT NOT NULL, target TEXT NOT NULL,
                issued_at TEXT NOT NULL, window_end TEXT NOT NULL, probability REAL NOT NULL,
                evidence_json TEXT NOT NULL, outcome TEXT,
                UNIQUE(entity_id,target,issued_at)
            );
        ''')
        self.db.commit()

        self.db.execute('PRAGMA user_version=1')

    def add(self, row):
        if row is None:
            return False
        if self.db.execute('SELECT 1 FROM event_receipts WHERE event_key=?', (row['event_key'],)).fetchone():
            return False
        values = dict(row, received_at=datetime.now(timezone.utc).isoformat())
        columns = list(values)
        with self.db:
            result = self.db.execute(
                f"INSERT OR IGNORE INTO events ({','.join(columns)}) "
                f"VALUES ({','.join('?' for _ in columns)})", list(values.values()))
        return result.rowcount == 1

    def session_start(self):
        with self.db:
            result = self.db.execute(
                "INSERT INTO sessions(started_at,status) VALUES (?,?)",
                (datetime.now(timezone.utc).isoformat(), "connected"))
        return result.lastrowid

    def session_end(self, session):
        with self.db:
            self.db.execute("UPDATE sessions SET ended_at=?,status=? WHERE id=?",
                            (datetime.now(timezone.utc).isoformat(), "disconnected", session))

    def session_seen(self, session):
        with self.db:
            self.db.execute('UPDATE sessions SET last_seen_at=? WHERE id=?',
                            (datetime.now(timezone.utc).isoformat(), session))

    def annotate(self, key, source, reason):
        row = self.db.execute('SELECT role,kind FROM events WHERE event_key=?', (key,)).fetchone()
        if not row or row[0] != 'actuator' or row[1] not in {'transition', 'attributes'}:
            raise ValueError('Only an existing actuator change can be attributed')
        if source not in {'human', 'device', 'unknown'} or not reason.strip():
            raise ValueError('Use human/device/unknown and a nonempty evidence note')
        with self.db:
            timestamp = datetime.now(timezone.utc).isoformat()
            self.db.execute('INSERT OR REPLACE INTO annotations VALUES (?,?,?,?)',
                            (key, source, reason, timestamp))
            self.db.execute('INSERT INTO annotation_history(event_key,source,reason,annotated_at) VALUES (?,?,?,?)',
                            (key, source, reason, timestamp))
            if source=='human':
                entity,occurred=self.db.execute('SELECT entity_id,occurred_at FROM events WHERE event_key=?',(key,)).fetchone()
                until=(datetime.fromisoformat(occurred)+timedelta(minutes=90)).isoformat()
                current=self.db.execute('SELECT until_at FROM human_leases WHERE entity_id=?',(entity,)).fetchone()
                if not current or current[0]<until:
                    self.db.execute('INSERT OR REPLACE INTO human_leases VALUES (?,?,?)',(entity,until,'verified human operation'))

    def events(self):
        self.db.row_factory = sqlite3.Row
        rows = self.db.execute('''SELECT e.*, COALESCE(a.source,e.source) AS attributed_source
            FROM events e LEFT JOIN annotations a USING(event_key)
            ORDER BY occurred_at,event_key''').fetchall()
        self.db.row_factory = None
        return [dict(r) for r in rows]

    def export(self, output):
        for (raw,) in self.db.execute("SELECT raw_json FROM events ORDER BY occurred_at,event_key"):
            output.write(raw + "\n")

    def summary(self):
        return [dict(entity_id=e, source=s, kind=k, count=n) for e, s, k, n in
                self.db.execute("SELECT entity_id,source,kind,COUNT(*) FROM events "
                                "GROUP BY entity_id,source,kind ORDER BY entity_id,source,kind")]

    def close(self):
        self.db.close()
