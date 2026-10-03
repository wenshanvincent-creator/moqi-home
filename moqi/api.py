"""Small device-independent entry point for verified observations and learning.

Adapters supply observations and connection coverage, never device commands.
Home Assistant remains supported by the existing read-only adapter.
"""
from copy import deepcopy
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from .contexts import dt
from .core import Store, normalize
from .memory import consolidate, predict, snapshot
from .memory_store import canonical

ROLES = frozenset({'motion', 'contact', 'leak', 'actuator', 'power', 'energy',
                   'temperature', 'presence', 'light', 'co2', 'sleep'})


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return an owned configuration; reject invalid inputs before creating a DB."""
    if not isinstance(config, dict) or not isinstance(config.get('site'), str) or not config['site'].strip():
        raise ValueError('Configure a nonempty site')
    entities = config.get('entities')
    if not isinstance(entities, dict) or not entities:
        raise ValueError('Configure a nonempty entities allowlist')
    for entity, spec in entities.items():
        if not isinstance(entity, str) or not entity or entity.startswith(('camera.', 'image.')):
            raise ValueError('Entity must be nonempty and cannot be a camera or image')
        if (not isinstance(spec, dict) or not isinstance(spec.get('role'), str) or spec.get('role') not in ROLES or
                not isinstance(spec.get('room'), str) or not spec['room'].strip()):
            raise ValueError('Each entity needs a supported role and room')
        if 'aliases' in spec and (not isinstance(spec['aliases'], list) or
                                  any(not isinstance(alias, str) or not alias.strip() for alias in spec['aliases'])):
            raise ValueError('Entity aliases must be a list of nonempty strings')
    ZoneInfo(config.get('timezone', 'Asia/Shanghai'))
    gamma = config.get('forgetting_gamma', .9)
    if isinstance(gamma, bool) or not isinstance(gamma, (int, float)) or not 0 < gamma <= 1:
        raise ValueError('forgetting_gamma must be in (0, 1]')
    for key in ('holidays', 'workdays'):
        values = config.get(key, [])
        if not isinstance(values, list):
            raise ValueError(key + ' must be a list of ISO dates')
        for value in values:
            if not isinstance(value, str) or datetime.strptime(value, '%Y-%m-%d').date().isoformat() != value:
                raise ValueError(key + ' must contain ISO dates')
    if set(config.get('holidays', [])) & set(config.get('workdays', [])):
        raise ValueError('A date cannot be both holiday and workday')
    canonical(config)  # JSON serializable, finite data only.
    return deepcopy(config)


@dataclass(frozen=True)
class Observation:
    entity_id: str
    at: datetime
    state: str | None
    previous: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    previous_attributes: dict[str, Any] = field(default_factory=dict)
    source: Literal['sensor', 'human', 'device', 'unknown'] = 'unknown'
    evidence: str = ''

    @classmethod
    def from_dict(cls, payload: dict[str, Any]):
        """Versioned JSON event interface for non-Python device adapters."""
        if not isinstance(payload, dict) or type(payload.get('schema_version')) is not int or payload['schema_version'] != 1:
            raise ValueError('Observation schema_version must be 1')
        allowed = {item.name for item in fields(cls)} | {'schema_version'}
        if set(payload) - allowed:
            raise ValueError('Unknown observation fields')
        values = {key: value for key, value in payload.items() if key != 'schema_version'}
        if not isinstance(values.get('at'), str):
            raise ValueError('JSON observation time must be an ISO string with timezone')
        values['at'] = dt(values['at'])
        try:
            observation = cls(**values)
        except TypeError as exc:
            raise ValueError('Missing required observation fields') from exc
        observation.event()
        return observation

    def event(self) -> dict[str, Any]:
        if not isinstance(self.at, datetime) or self.at.tzinfo is None:
            raise ValueError('Observation timestamp must be timezone-aware')
        if not isinstance(self.entity_id, str) or not self.entity_id:
            raise ValueError('Observation entity_id must be nonempty')
        if not isinstance(self.source, str) or self.source not in {'sensor', 'human', 'device', 'unknown'}:
            raise ValueError('Unsupported observation source')
        if not isinstance(self.evidence, str) or len(self.evidence) > 4096:
            raise ValueError('Evidence must be a string of at most 4096 characters')
        if self.source in {'human', 'device'} and (not isinstance(self.evidence, str) or not self.evidence.strip()):
            raise ValueError('Attributed actuator changes require an evidence note')
        if any(value is not None and not isinstance(value, str) for value in (self.state, self.previous)):
            raise ValueError('States must be strings or null')
        if not isinstance(self.attributes, dict) or not isinstance(self.previous_attributes, dict):
            raise ValueError('Attributes must be objects')
        result = {'event_type': 'state_changed', 'time_fired': self.at.isoformat(), 'data': {
            'entity_id': self.entity_id,
            'old_state': None if self.previous is None else {'state': self.previous, 'attributes': self.previous_attributes},
            'new_state': None if self.state is None else {'state': self.state, 'attributes': self.attributes}}}
        if len(canonical(result).encode('utf-8')) > 65536:
            raise ValueError('Observation exceeds the 64 KiB adapter limit')
        return result


class HomeMemory:
    """Explicit event time; isolated database; no hidden clock or execution API.

    This initial API is experimental. Config and data formats are versioned in
    documentation; pre-1.0 changes must carry migration notes.
    """
    def __init__(self, config: dict[str, Any], database: str):
        self.config = validate_config(config)
        self.store = Store(database)

    def ingest(self, observation: Observation) -> bool:
        if observation.entity_id not in self.config['entities']:
            raise ValueError('Observation entity is outside the allowlist')
        spec = self.config['entities'][observation.entity_id]
        if spec['role'] != 'actuator' and observation.source in {'human', 'device'}:
            raise ValueError('Only actuator changes can be human/device attributed')
        if spec['role'] == 'actuator' and observation.source == 'sensor':
            raise ValueError('Actuator attribution must be human/device/unknown')
        row = normalize(observation.event(), self.config)
        if observation.source in {'human', 'device'} and row['kind'] not in {'transition', 'attributes'}:
            raise ValueError('A baseline or unavailable state is not an attributed action')
        inserted = self.store.add(row)
        if inserted and observation.source in {'human', 'device'}:
            self.store.annotate(row['event_key'], observation.source, observation.evidence)
        return inserted

    def observe_interval(self, start: datetime, end: datetime) -> None:
        """Declare verified continuous adapter coverage, not inferred occupancy."""
        if not isinstance(start, datetime) or not isinstance(end, datetime) or start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError('Coverage must be an increasing timezone-aware interval')
        with self.store.db:
            self.store.db.execute('INSERT INTO sessions(started_at,ended_at,last_seen_at,status) VALUES (?,?,?,?)',
                                  (dt(start.isoformat()).isoformat(), dt(end.isoformat()).isoformat(),
                                   dt(end.isoformat()).isoformat(), 'adapter_coverage'))

    @staticmethod
    def _at(at: datetime) -> datetime:
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise ValueError('Use a timezone-aware learning/query timestamp')
        return dt(at.isoformat())

    def learn(self, at: datetime) -> dict[str, Any]:
        return consolidate(self.store, self.config, self._at(at))

    def predict(self, at: datetime) -> list[dict[str, Any]]:
        return predict(self.store, self.config, self._at(at))

    def inspect(self, at: datetime) -> dict[str, Any]:
        return snapshot(self.store, self.config, self._at(at))

    def close(self) -> None:
        self.store.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
