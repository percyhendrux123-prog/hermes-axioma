"""Local metadata plus a bounded signal excerpt for board lights. No full bodies or arguments."""
from contextlib import contextmanager
import json
import os
import re
import sqlite3
import stat
import time
import uuid
import unicodedata

FIELDS = {'event', 'card_id', 'categories', 'light', 'valid', 'answer', 'choice', 'signal',
          'answered_with_question', 'reason', 'span_hash', 'scope_hash', 'checks',
          'span_id', 'level', 'surface', 'shown', 'check_ok',
          # Card code (spec 5.6): the code, keyed digests of what it covers, a seal, and a mark
          # when the code was made with a throwaway key (the key file could not be read).
          'fingerprint', 'text_digest', 'tool_digest', 'args_digest', 'line_digests', 'prefix_tags', 'seal', 'key'}

TASK_ID = re.compile(r't_[a-zA-Z0-9_-]{1,64}\Z')
RANK = {'whisper': 0, 'go': 1, 'caution': 2, 'stop': 3}
LIGHTS = {'red': 'stop', 'yellow': 'caution', 'green': 'go'}


def current_task():
    value = os.environ.get('HERMES_KANBAN_TASK', '')
    return value if TASK_ID.fullmatch(value) else None


def plain_signal(value):
    """A short plain-text tooltip, never a message body or rendered markup."""
    if not isinstance(value, str):
        return ''
    text = re.sub(r'<[^>]*>', '', value[:4096])
    text = ''.join(c for c in text if unicodedata.category(c) not in ('Cc', 'Cf', 'Cs', 'Zl', 'Zp'))
    return ' '.join(text.split())[:160]


def _owner_only(path, mode):
    """Tighten local paths only, never symlink targets. A refused chmod is best effort."""
    try:
        info = os.stat(path, follow_symlinks=False)
        right_type = stat.S_ISDIR(info.st_mode) if mode == 0o700 else stat.S_ISREG(info.st_mode)
        if right_type and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & ~mode:
            os.chmod(path, mode)
    except OSError:
        pass


class Audit:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _owner_only(self.path.parent, 0o700)
        db = sqlite3.connect(str(self.path), timeout=2)
        try:
            with db:
                # Serialize schema inspection + ALTER across workers upgrading the same old DB.
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, at REAL, metadata TEXT)')
                if 'task_id' not in {r[1] for r in db.execute('PRAGMA table_info(events)')}:
                    db.execute('ALTER TABLE events ADD COLUMN task_id TEXT')
                db.execute('CREATE TABLE IF NOT EXISTS whispers (scope TEXT, span TEXT, reason TEXT, PRIMARY KEY(scope, span))')
                db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value BLOB)')
            _owner_only(self.path, 0o600)
            with db:
                yield db
        finally:
            db.close()

    def salt(self):
        """Random per-database salt for whisper span hashes (created once, never logged)."""
        if getattr(self, '_salt', None) is None:
            self._salt = self.secret('salt')
        return self._salt

    def secret(self, name):
        """A random 32-byte per-database value, created once and never written to an event."""
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO meta VALUES (?, ?)', (name, os.urandom(32)))
            return bytes(db.execute('SELECT value FROM meta WHERE key = ?', (name,)).fetchone()[0])

    def record(self, at=None, **metadata):
        if set(metadata) - FIELDS:
            raise ValueError('unexpected audit field')
        task = current_task()
        if 'signal' in metadata:
            if task:
                metadata['signal'] = plain_signal(metadata['signal'])
            else:
                metadata.pop('signal')
        with self.connect() as db:
            db.execute('INSERT INTO events (id, at, metadata, task_id) VALUES (?, ?, ?, ?)',
                       (uuid.uuid4().hex, time.time() if at is None else float(at),
                        json.dumps(metadata, sort_keys=True), task))

    def board_lights(self):
        """Read-only projection; count observations, not staged cards or repeated answer rows.

        Does not create/migrate a DB on GET. Old unassigned rows cannot be attributed retroactively.
        """
        if not self.path.is_file():
            return {}
        db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
        try:
            if 'task_id' not in {r[1] for r in db.execute('PRAGMA table_info(events)')}:
                return {}
            rows = db.execute('SELECT task_id, at, metadata FROM events WHERE task_id IS NOT NULL '
                              'ORDER BY at, rowid')
            out = {}
            for task, at, raw in rows:
                if not TASK_ID.fullmatch(task):
                    continue
                try:
                    item = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if not isinstance(item, dict):
                    continue
                if item.get('event') == 'presented_to_host':
                    light = LIGHTS.get(item.get('light'))
                elif item.get('event') == 'signal' and item.get('shown') is True:
                    light = item.get('level')
                else:
                    continue
                if not isinstance(light, str) or light not in RANK:
                    continue
                prev = out.get(task)
                worst = light if prev is None or RANK[light] > RANK[prev['light']] else prev['light']
                out[task] = {'light': worst, 'count': (prev['count'] if prev else 0) + 1,
                             'signal': plain_signal(item.get('signal')), 'at': at}
            return out
        finally:
            db.close()

    def whisper_seen(self, scope_hash, span_hash):
        with self.connect() as db:
            return db.execute('SELECT 1 FROM whispers WHERE scope = ? AND span = ?',
                              (scope_hash, span_hash)).fetchone() is not None

    def whisper_once(self, scope_hash, span_hash, reason):
        """True the first time this span is whispered in this session scope. The caller logs it."""
        with self.connect() as db:
            cur = db.execute('INSERT OR IGNORE INTO whispers VALUES (?, ?, ?)', (scope_hash, span_hash, reason))
            return bool(cur.rowcount)

    def rows(self, limit=100):
        with self.connect() as db:
            rows = db.execute('SELECT id, at, metadata FROM events ORDER BY at DESC LIMIT ?', (limit,)).fetchall()
        return [dict({'id': i, 'at': t, 'answered_with_question': None}, **json.loads(m)) for i, t, m in rows]

    def card_rows(self, card_id=None, fingerprint=None, limit=5000):
        """Card lifecycle rows (staged, shown, answered), newest first. A lookup by card id or
        code searches the whole log (no window); the unfiltered list keeps the newest `limit`."""
        where = ["(metadata LIKE '%\"event\": \"card\"%' OR metadata LIKE '%\"event\": \"presented_to_host\"%' "
                 "OR metadata LIKE '%\"event\": \"answer\"%')"]
        params = []
        for key, value in (('card_id', card_id), ('fingerprint', fingerprint)):
            if value is not None:
                where.append('instr(metadata, ?) > 0')
                params.append(json.dumps({key: str(value)})[1:-1])  # '"key": "value"', quotes included
        sql = 'SELECT id, at, metadata FROM events WHERE ' + ' AND '.join(where) + ' ORDER BY at DESC'
        if card_id is None and fingerprint is None:
            sql += ' LIMIT %d' % int(limit)
        with self.connect() as db:
            rows = db.execute(sql, params).fetchall()
        out = [dict({'id': i, 'at': t}, **json.loads(m)) for i, t, m in rows]
        return [r for r in out if (card_id is None or r.get('card_id') == card_id)
                and (fingerprint is None or r.get('fingerprint') == fingerprint)]
