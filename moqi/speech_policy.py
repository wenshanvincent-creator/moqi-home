"""Plan §8.2 deterministic speech budget. No audio, speech text or HA calls.

Reserve immediately before playback, after synthesizing in memory and measuring
the actual audio duration. A reservation consumes budget even if playback fails;
this conservative choice prevents retries/restarts from repeating announcements.
Presence must come from a verified occupancy adapter; motion alone is insufficient.
"""
import math
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


KINDS = {'new_habit', 'safety', 'explanation', 'memory_changes', 'correction', 'question'}
PROACTIVE = {'new_habit', 'safety'}


def reserve(store, config, *, request_id, at, room, kind, duration_seconds,
            occupied, occupancy_at, user_engaged=False, habit_id=None):
    """Authorize one playback attempt; does not authorize device execution.

Arguments are internal typed observations, never unrestricted model output.
Caller invokes this for each audio buffer just before playback, not at queue time.
"""
    def deny(reason):
        return {'allowed': False, 'reason': reason, 'execution_enabled': False}

    if not isinstance(at, datetime) or at.tzinfo is None:
        return deny('invalid_time')
    if (not isinstance(request_id, str) or not request_id or len(request_id) > 200 or
            not isinstance(room, str) or room not in {s.get('room') for s in config.get('entities', {}).values()} or
            not isinstance(kind, str) or kind not in KINDS or not isinstance(user_engaged, bool)):
        return deny('invalid_request')
    if (isinstance(duration_seconds, bool) or not isinstance(duration_seconds, (int, float)) or
            not math.isfinite(duration_seconds) or not 0 < duration_seconds <= 8):
        return deny('invalid_or_overlong_audio')
    if occupied is not True:
        return deny('occupancy_not_verified')
    if not isinstance(occupancy_at, datetime) or occupancy_at.tzinfo is None:
        return deny('occupancy_not_verified')
    if not 0 <= (at - occupancy_at).total_seconds() <= 60:
        return deny('occupancy_stale_or_future')
    local = at.astimezone(ZoneInfo(config.get('timezone', 'Asia/Shanghai')))
    if local.hour >= 23 or local.hour < 7:
        return deny('night_silence')
    if kind not in PROACTIVE and not user_engaged:
        return deny('user_conversation_required')
    if kind == 'new_habit' and (not isinstance(habit_id, str) or not habit_id):
        return deny('habit_required')
    if store.db.in_transaction:
        return deny('uncommitted_observations')
    # Separate connection + write lock makes daily/first-habit limits atomic
    # across processes. This operational ledger is intentionally outside rollback.
    path = store.db.execute('PRAGMA database_list').fetchone()[2]
    if not path:
        return deny('persistent_database_required')
    connection = sqlite3.connect(path, timeout=5)
    utc_at = at.astimezone(timezone.utc).isoformat()
    day = local.date().isoformat()
    try:
        connection.execute('BEGIN IMMEDIATE')
        if connection.execute('SELECT 1 FROM speech_reservations WHERE id=?', (request_id,)).fetchone():
            return deny('already_reserved')
        latest = connection.execute('SELECT MAX(at) FROM speech_reservations').fetchone()[0]
        if latest and datetime.fromisoformat(latest) > at:
            return deny('clock_moved_backwards')
        if kind == 'new_habit':
            # A genuine first acknowledged execution is required; a prediction
            # or forged model request cannot manufacture a first-use message.
            executions = connection.execute(
                "SELECT issued_at FROM execution_ledger WHERE habit_id=? AND status='acknowledged' ORDER BY issued_at",
                (habit_id,)).fetchall()
            if len(executions) != 1 or not 0 <= (at-datetime.fromisoformat(executions[0][0])).total_seconds() <= 60:
                return deny('first_execution_not_verified')
            if connection.execute("SELECT 1 FROM speech_reservations WHERE kind='new_habit' AND habit_id=?", (habit_id,)).fetchone():
                return deny('habit_already_announced')
        if kind in PROACTIVE:
            count = connection.execute(
                "SELECT COUNT(*) FROM speech_reservations WHERE local_day=? AND kind IN ('new_habit','safety')", (day,)).fetchone()[0]
            if count >= 2:
                return deny('daily_proactive_budget')
        if kind == 'question':
            if connection.execute("SELECT 1 FROM speech_reservations WHERE local_day=? AND kind='question'", (day,)).fetchone():
                return deny('daily_question_budget')
        connection.execute('INSERT INTO speech_reservations VALUES (?,?,?,?,?,?,?)',
                           (request_id, utc_at, day, room, kind, habit_id if kind == 'new_habit' else None, duration_seconds))
        connection.commit()
        return {'allowed': True, 'reason': 'speech_reserved', 'request_id': request_id,
                'local_day': day, 'execution_enabled': False}
    except (sqlite3.Error, ValueError, TypeError):
        return deny('speech_ledger_unavailable')
    finally:
        connection.rollback()
        connection.close()
