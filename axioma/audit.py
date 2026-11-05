"""Local transactional metadata only. No card, command, argument or answer bodies."""
from contextlib import contextmanager
import json
import os
import sqlite3
import time
import uuid

FIELDS = {'event', 'card_id', 'categories', 'light', 'valid', 'answer', 'choice',
          'answered_with_question', 'reason', 'span_hash', 'scope_hash', 'checks',
          'span_id', 'level', 'surface', 'shown', 'check_ok'}


class Audit:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(self.path), timeout=2)
        try:
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, at REAL, metadata TEXT)')
                db.execute('CREATE TABLE IF NOT EXISTS whispers (scope TEXT, span TEXT, reason TEXT, PRIMARY KEY(scope, span))')
                db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value BLOB)')
                yield db
        finally:
            db.close()

    def salt(self):
        """Random per-database salt for whisper span hashes (created once, never logged)."""
        if getattr(self, '_salt', None) is None:
            with self.connect() as db:
                db.execute('INSERT OR IGNORE INTO meta VALUES (?, ?)', ('salt', os.urandom(32)))
                self._salt = bytes(db.execute("SELECT value FROM meta WHERE key = 'salt'").fetchone()[0])
        return self._salt

    def record(self, **metadata):
        if set(metadata) - FIELDS:
            raise ValueError('unexpected audit field')
        with self.connect() as db:
            db.execute('INSERT INTO events VALUES (?, ?, ?)',
                       (uuid.uuid4().hex, time.time(), json.dumps(metadata, sort_keys=True)))

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
