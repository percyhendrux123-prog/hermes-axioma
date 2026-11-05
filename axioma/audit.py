"""Local transactional metadata only. No card, command, argument or answer bodies."""
from contextlib import contextmanager
import json
import os
import sqlite3
import time
import uuid

FIELDS = {'event', 'card_id', 'categories', 'light', 'valid', 'answer', 'choice',
          'answered_with_question', 'reason', 'span_hash', 'scope_hash', 'checks',
          'span_id', 'level', 'surface', 'shown', 'check_ok',
          # Card fingerprint (spec 5.6): the code, keyed digests of what it covers, and a seal.
          'fingerprint', 'text_digest', 'tool_digest', 'args_digest', 'line_digests', 'seal'}


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
            self._salt = self.secret('salt')
        return self._salt

    def secret(self, name):
        """A random 32-byte per-database value, created once and never written to an event."""
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO meta VALUES (?, ?)', (name, os.urandom(32)))
            return bytes(db.execute('SELECT value FROM meta WHERE key = ?', (name,)).fetchone()[0])

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

    def card_rows(self, card_id=None, fingerprint=None, limit=5000):
        """Card lifecycle rows (staged, shown, answered), newest first, filtered in Python."""
        with self.connect() as db:
            rows = db.execute("SELECT id, at, metadata FROM events WHERE metadata LIKE '%\"event\": \"card\"%' "
                              "OR metadata LIKE '%\"event\": \"presented_to_host\"%' "
                              "OR metadata LIKE '%\"event\": \"answer\"%' ORDER BY at DESC LIMIT ?",
                              (limit,)).fetchall()
        out = [dict({'id': i, 'at': t}, **json.loads(m)) for i, t, m in rows]
        return [r for r in out if (card_id is None or r.get('card_id') == card_id)
                and (fingerprint is None or r.get('fingerprint') == fingerprint)]
