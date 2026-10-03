"""Event-time context extraction; absent/unavailable sensors remain unknown."""
import json
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def dt(value):
    parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp needs a timezone')
    return parsed.astimezone(timezone.utc)


def context(at, config):
    local = at.astimezone(ZoneInfo(config.get('timezone','Asia/Shanghai')))
    date=local.date().isoformat()
    if date in config.get('holidays',[]) and date in config.get('workdays',[]):
        raise ValueError('A date cannot be both holiday and workday')
    day_type = 'holiday' if local.date().isoformat() in config.get('holidays',[]) else (
        'weekday' if date in config.get('workdays',[]) else 'weekend' if local.weekday() >= 5 else 'weekday')
    return day_type,local.hour*2+local.minute//30


def number(value):
    if isinstance(value,bool): return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError,ValueError):
        return None


def attributes(row):
    if not row:
        return {}
    return (json.loads(row.get('raw_json') or '{}').get('data',{}).get('new_state') or {}).get('attributes',{})


def latest(events, entity, at):
    rows = [r for r in events if r['entity_id'] == entity and dt(r['occurred_at']) <= at]
    return rows[-1] if rows else None


def boundary(row, config):
    if row['kind'] != 'transition':
        return None
    spec = config['entities'].get(row['entity_id'],{})
    if spec.get('boundary') == 'home':
        home = spec.get('home_states',['home','on'])
        away = spec.get('away_states',['not_home','off'])
        if row['new_state'] in home and row['old_state'] in away:
            return 'arrival'
        if row['new_state'] in away and row['old_state'] in home:
            return 'departure'
    if spec.get('boundary') == 'sleep':
        asleep = spec.get('asleep_states',['on','asleep'])
        awake = spec.get('awake_states',['off','awake'])
        if row['new_state'] in asleep and row['old_state'] in awake:
            return 'sleep'
        if row['new_state'] in awake and row['old_state'] in asleep:
            return 'waking'
    return None


def features(events, config, at, room):
    day_type,slot = context(at,config)
    local = at.astimezone(ZoneInfo(config.get('timezone','Asia/Shanghai')))
    result = dict(day_type=day_type,slot=slot,weekday=local.weekday(),room=room,
                  occupancy='unknown',arrival_elapsed='unknown',indoor='unknown',
                  outdoor='unknown',light='unknown',mobile_home='unknown',devices={})
    states = {}
    for row in events:
        if dt(row['occurred_at']) <= at:
            states[row['entity_id']] = row
    presence = []
    for entity,spec in config['entities'].items():
        row = states.get(entity)
        if not row or row['new_state'] in (None,'unknown','unavailable'):
            continue
        state = row['new_state']
        feature = spec.get('feature')
        if spec['room'] == room:
            if spec['role'] == 'presence':
                true = state in spec.get('present_states',['on','home'])
                false = state in spec.get('absent_states',['off','not_home'])
                presence.append('present' if true else 'absent' if false else 'unknown')
            elif spec['role'] == 'motion' and state == 'on':
                # Active motion is positive evidence, but motion OFF never means absence.
                presence.append('present')
            if spec['role'] == 'actuator':
                result['devices'][entity] = state
        if feature in {'indoor','outdoor','light'} and (feature == 'outdoor' or spec['room'] == room):
            value = number(state)
            unit = attributes(row).get('unit_of_measurement') or spec.get('unit')
            if value is not None and (feature == 'light' and unit in {'lx','lux'} or
                                      feature != 'light' and unit in {'°C','C'}):
                result[feature] = ('dark' if value < 50 else 'bright' if value > 300 else 'dim') if feature == 'light' else int(value//2)*2
        if feature == 'mobile_home':
            result['mobile_home'] = 'home' if state == 'home' else 'away' if state == 'not_home' else 'unknown'
    result['occupancy'] = 'present' if 'present' in presence else (
        'absent' if presence and all(p == 'absent' for p in presence) else 'unknown')
    boundaries = [(dt(r['occurred_at']),boundary(r,config)) for r in events if dt(r['occurred_at']) <= at]
    boundaries = [(t,b) for t,b in boundaries if b in {'arrival','departure'}]
    if boundaries and boundaries[-1][1] == 'arrival':
        minutes = (at-boundaries[-1][0]).total_seconds()/60
        result['arrival_elapsed'] = '0-15' if minutes < 15 else '15-60' if minutes < 60 else '60+'
    return result


def hierarchy(value):
    # Stable nested strata; sparse specific contexts fall back to day type then time.
    full = {k:v for k,v in value.items() if k != 'devices'}
    full['devices'] = value['devices']
    return [full, {k:value[k] for k in ('room','day_type','weekday','slot','occupancy','outdoor')},
            {k:value[k] for k in ('room','day_type','slot')}, {k:value[k] for k in ('room','slot')}]


def matches(partial, full):
    return all(full.get(k) == v for k,v in partial.items())
