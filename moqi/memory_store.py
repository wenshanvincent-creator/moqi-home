"""Durable, versioned structured memory. Operational ledgers are never rolled back."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def identity(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()[:24]


SCHEMA = '''
CREATE TABLE IF NOT EXISTS memory_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_episodes(id TEXT PRIMARY KEY,start TEXT,end TEXT,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_habits(id TEXT PRIMARY KEY,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_evidence(id TEXT PRIMARY KEY,habit_id TEXT,at TEXT,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_questions(id TEXT PRIMARY KEY,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_models(id TEXT PRIMARY KEY,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_constraints(id TEXT PRIMARY KEY,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_proposals(id TEXT PRIMARY KEY,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_contexts(event_key TEXT PRIMARY KEY,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_runs(id TEXT PRIMARY KEY,at TEXT,status TEXT,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_changes(id INTEGER PRIMARY KEY,at TEXT,kind TEXT,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS execution_ledger(id TEXT PRIMARY KEY,entity_id TEXT,target TEXT,before_state TEXT,
 issued_at TEXT,habit_id TEXT,status TEXT,feedback TEXT,context_id TEXT,property TEXT DEFAULT 'state');
CREATE TABLE IF NOT EXISTS human_leases(entity_id TEXT PRIMARY KEY,until_at TEXT NOT NULL,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS downsampled(entity_id TEXT,bucket TEXT,body TEXT NOT NULL,PRIMARY KEY(entity_id,bucket));
CREATE TABLE IF NOT EXISTS event_receipts(event_key TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS speech_reservations(
 id TEXT PRIMARY KEY,at TEXT NOT NULL,local_day TEXT NOT NULL,room TEXT NOT NULL,
 kind TEXT NOT NULL,habit_id TEXT,duration_seconds REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS speech_first_habit ON speech_reservations(habit_id)
 WHERE kind='new_habit';
'''


def initialize(store):
    if getattr(store, '_memory_initialized', False):
        return
    store.db.executescript(SCHEMA)
    store.db.commit()
    store._memory_initialized = True


def objects(store, table):
    if table not in {'memory_habits','memory_episodes','memory_evidence','memory_questions',
                     'memory_models','memory_constraints','memory_proposals','memory_runs'}:
        raise ValueError('Unsupported memory table')
    return [json.loads(body) for (body,) in store.db.execute(f'SELECT body FROM {table} ORDER BY id')]


def put(store, table, value):
    if table not in {'memory_habits','memory_questions','memory_models','memory_constraints','memory_proposals'}:
        raise ValueError('Unsupported memory table')
    store.db.execute(f'INSERT OR REPLACE INTO {table}(id,body) VALUES (?,?)', (value['id'],canonical(value)))


def meta(store, key, default=None):
    row = store.db.execute('SELECT value FROM memory_meta WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_meta(store, key, value):
    store.db.execute('INSERT OR REPLACE INTO memory_meta VALUES (?,?)', (key,canonical(value)))


def change(store, at, kind, body):
    store.db.execute('INSERT INTO memory_changes(at,kind,body) VALUES (?,?,?)', (at,kind,canonical(body)))


# Inputs, attribution, execution outcomes, leases and privacy retention stay outside rollback.
VERSIONED = ('memory_habits','memory_evidence','memory_questions','memory_models',
             'memory_constraints','memory_proposals','memory_episodes')


def state(store):
    return {table: [list(row) for row in store.db.execute(f'SELECT * FROM {table} ORDER BY id')]
            for table in VERSIONED}


def restore_state(store, restored):
    """Restore memory tables atomically, retaining observations and operational ledgers.

    Used by Git rollback and the browser sandbox's session checkpoints. This is
    not a database backup/restore API. Validate the entire snapshot before edits.
    """
    if not isinstance(restored, dict) or set(restored) != set(VERSIONED):
        raise ValueError('Incompatible memory snapshot tables')
    widths = {}
    for table in VERSIONED:
        width = len(store.db.execute(f'PRAGMA table_info({table})').fetchall())
        rows = restored[table]
        if not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != width for row in rows):
            raise ValueError('Incompatible memory snapshot rows')
        widths[table] = width
    store.db.execute('SAVEPOINT restore_memory')
    try:
        for table in VERSIONED:
            store.db.execute(f'DELETE FROM {table}')
            store.db.executemany(f'INSERT INTO {table} VALUES ({",".join("?" for _ in range(widths[table]))})', restored[table])
        store.db.execute('RELEASE SAVEPOINT restore_memory')
    except Exception:
        store.db.execute('ROLLBACK TO SAVEPOINT restore_memory')
        store.db.execute('RELEASE SAVEPOINT restore_memory')
        raise


def git(directory, *args):
    if not shutil.which('git'):
        raise RuntimeError('L3 versioning blocked: install git on this host; memory remains in SQLite')
    result = subprocess.run(['git','-C',str(directory),*args], capture_output=True, text=True,
                            encoding='utf-8', timeout=30)
    if result.returncode:
        raise RuntimeError('L3 git operation failed: '+result.stderr.strip()[:500])
    return result.stdout.strip()


def commit(store, directory, at, message):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    # Require a dedicated repository: never commit unrelated household/project files.
    if not (directory/'.git').exists():
        git(directory,'init')
    marker=directory/'.moqi-memory'
    def managed(name):
        return name.startswith(('rooms/','routines/','journal/')) or name in {
            'memory-state.json','questions.md','constraints.yaml','models.yaml','proposals.yaml','.moqi-memory'}
    if not marker.exists():
        tracked=git(directory,'ls-files','-z').split('\0')
        if any(name and not managed(name) for name in tracked):
            raise RuntimeError('L3 needs a dedicated memory repository; this directory contains unrelated tracked files')
        marker.write_text('Moqi structured memory repository v1\n',encoding='utf-8')
    if any(name and not managed(name) for name in git(directory,'diff','--cached','--name-only','-z').split('\0')):
        raise RuntimeError('L3 commit blocked: unrelated files are staged in the memory repository')
    (directory/'memory-state.json').write_text(canonical(state(store))+'\n',encoding='utf-8')
    git(directory,'add','--','.moqi-memory','memory-state.json','rooms','routines','questions.md',
        'constraints.yaml','models.yaml','proposals.yaml','journal')
    if not git(directory,'diff','--cached','--name-only'):
        return git(directory,'rev-parse','HEAD')
    git(directory,'-c','user.name=Moqi local memory','-c','user.email=memory@localhost',
        'commit','-m',message)
    revision = git(directory,'rev-parse','HEAD')
    with store.db:
        set_meta(store,'revision',revision)
        change(store,at,'git_commit',dict(revision=revision,message=message))
    return revision


def history(directory):
    raw = git(directory,'log','-30','--format=%H%x09%aI%x09%s')
    return [dict(zip(('revision','at','message'),line.split('\t',2))) for line in raw.splitlines()]


def rollback(store, directory, revision, at):
    # Resolve a local commit; reject option injection and revision:path selectors.
    if not revision or any(c not in '0123456789abcdefABCDEF' for c in revision) or len(revision) < 7:
        raise ValueError('Use a commit hash from memory-history')
    resolved = git(directory,'rev-parse','--verify',revision+'^{commit}')
    restored = json.loads(git(directory,'show',resolved+':memory-state.json'))
    if set(restored) != set(VERSIONED):
        raise ValueError('This commit has no compatible structured memory snapshot')
    # Back up memory only; never create an unexpired second copy of raw HA payloads.
    import sqlite3
    backup_path = Path(directory).parent/('before-rollback-'+identity([resolved,at])+'.sqlite3')
    if backup_path.exists():
        raise FileExistsError(backup_path)
    backup = sqlite3.connect(backup_path)
    try:
        for table in VERSIONED:
            sql=store.db.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone()[0]
            backup.execute(sql)
            width=len(store.db.execute(f'PRAGMA table_info({table})').fetchall())
            backup.executemany(f'INSERT INTO {table} VALUES ({",".join("?" for _ in range(width))})',
                               store.db.execute(f'SELECT * FROM {table}').fetchall())
        backup.commit()
    finally:
        backup.close()
    root=Path(directory).resolve()
    paths=git(directory,'ls-tree','-r','--name-only','-z',resolved).split('\0')
    # Restore editable notes as well as generated understanding. No Git reset or
    # checkout of user code, raw inputs or operational ledgers is involved.
    for name in paths:
        if not (name.startswith(('rooms/','routines/','journal/')) or name in
                {'questions.md','constraints.yaml','models.yaml','proposals.yaml'}):
            continue
        target=(root/name).resolve()
        if not target.is_relative_to(root): raise ValueError('Unsafe path in memory commit')
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(git(directory,'show',resolved+':'+name)+'\n',encoding='utf-8')
    with store.db:
        set_meta(store,'rollback_from',resolved)
        restore_state(store, restored)
        change(store,at,'rollback',dict(revision=resolved,backup=str(backup_path)))
    # A new commit preserves the audit history, rather than resetting Git history.
    return backup_path
