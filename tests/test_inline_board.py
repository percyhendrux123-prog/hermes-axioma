"""0.6.0 regressions. Synthetic data; no live profile, message or tool execution."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def entrypoint():
    spec = importlib.util.spec_from_file_location('axioma_inline_test', ROOT / '__init__.py',
                                                submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Context:
    surface = ''

    def __init__(self):
        self.hooks = {}

    def session_surface(self):
        return self.surface

    def get_config(self, key, default=None):
        return default

    def register_hook(self, name, handler):
        self.hooks[name] = handler

    def register_tool(self, **kw):
        pass

    def register_command(self, *args, **kw):
        pass


class AuditBoardTests(unittest.TestCase):
    def setUp(self):
        from axioma.audit import Audit
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audit = Audit(Path(self.tmp.name) / 'audit.sqlite3')

    def test_task_id_read_at_each_record_without_changing_sealed_metadata(self):
        import json
        with patch.dict('os.environ', {'HERMES_KANBAN_TASK': 't_11111111'}):
            self.audit.record(at=1, event='card', seal='synthetic')
        with patch.dict('os.environ', {'HERMES_KANBAN_TASK': 't_22222222'}):
            self.audit.record(at=2, event='signal', level='stop', shown=True)
        with self.audit.connect() as db:
            rows = db.execute('SELECT task_id, metadata FROM events ORDER BY at').fetchall()
        self.assertEqual([r[0] for r in rows], ['t_11111111', 't_22222222'])
        self.assertEqual(json.loads(rows[0][1]), {'event': 'card', 'seal': 'synthetic'})
        self.assertNotIn('task_id', self.audit.rows()[0], 'old seals must keep verifying')

    def test_upgrade_old_database_additive_idempotent_and_preserves_old_rows(self):
        import sqlite3
        db = sqlite3.connect(self.audit.path)
        try:
            db.execute('CREATE TABLE events (id TEXT PRIMARY KEY, at REAL, metadata TEXT)')
            db.execute('INSERT INTO events VALUES (?, ?, ?)', ('old', 1, '{"event":"card","seal":"old"}'))
            db.commit()
        finally:
            db.close()
        for _ in range(2):
            with self.audit.connect() as db:
                self.assertIn('task_id', [r[1] for r in db.execute('PRAGMA table_info(events)')])
                self.assertEqual(db.execute('SELECT * FROM events').fetchone(),
                                 ('old', 1.0, '{"event":"card","seal":"old"}', None))
        self.assertEqual(self.audit.board_lights(), {})

    def test_worst_light_count_and_latest_sentence_are_independent(self):
        with patch.dict('os.environ', {'HERMES_KANBAN_TASK': 't_11111111'}):
            self.audit.record(at=1, event='presented_to_host', light='red', signal='Run tests first.')
            self.audit.record(at=2, event='answer', light='red')  # not another signal
            self.audit.record(at=3, event='card', light='green', valid=True)  # not shown yet
            self.audit.record(at=4, event='signal', level='go', shown=True, signal='The test passed.')
            self.audit.record(at=5, event='signal', level='stop', shown=False, signal='Not displayed.')
        with patch.dict('os.environ', {'HERMES_KANBAN_TASK': 't_22222222'}):
            self.audit.record(at=6, event='signal', level='caution', shown=True, signal='Check the audience.')
        self.assertEqual(self.audit.board_lights(), {
            't_11111111': {'light': 'stop', 'count': 2, 'signal': 'The test passed.', 'at': 4.0},
            't_22222222': {'light': 'caution', 'count': 1, 'signal': 'Check the audience.', 'at': 6.0}})

    def test_bad_task_ids_and_unsupported_lights_are_not_exposed(self):
        for task in ('', '../secret', 't_123\n', '/private/path'):
            with patch.dict('os.environ', {'HERMES_KANBAN_TASK': task}):
                self.audit.record(event='signal', level='stop', shown=True)
        with patch.dict('os.environ', {'HERMES_KANBAN_TASK': 't_11111111'}):
            self.audit.record(event='signal', level='intent', shown=True)
            self.audit.record(event='signal', level='garbage', shown=True)
        self.assertEqual(self.audit.board_lights(), {})

    def test_only_bounded_plain_signal_is_stored_for_board_tooltips(self):
        import json
        with patch.dict('os.environ', {'HERMES_KANBAN_TASK': 't_11111111'}):
            self.audit.record(event='signal', level='caution', shown=True,
                              signal='<b>Check</b>\u202e\x00 ' + 'x' * 300)
        row = self.audit.board_lights()['t_11111111']
        self.assertLessEqual(len(row['signal']), 160)
        for bad in ('<b>', '\u202e', '\x00'):
            self.assertNotIn(bad, json.dumps(row, ensure_ascii=False))
        self.assertEqual(set(row), {'light', 'count', 'signal', 'at'})



class GuidanceTests(unittest.TestCase):
    def test_inline_instruction_only_on_desktop_and_rechecked_each_turn(self):
        module, ctx = entrypoint(), Context()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(module, 'data_root', return_value=Path(tmp)):
                module.register(ctx)
            for surface in ('desktop', 'telegram', 'cli', 'discord', 'acp', 'dashboard', '', ' Desktop '):
                with self.subTest(surface=surface):
                    ctx.surface = surface
                    text = ctx.hooks['pre_llm_call']()['context']
                    self.assertIn('AXIOMA SIGNAL', text)
                    self.assertEqual('::axioma{' in text, surface.strip().lower() == 'desktop')
                    if surface.strip().lower() == 'desktop':
                        self.assertIn('MAY', text)
                        self.assertIn('stop or caution', text)
                        self.assertIn('never permission', text)

    def test_missing_or_failing_surface_does_not_advertise_inline_cards(self):
        module, ctx = entrypoint(), Context()
        ctx.session_surface = lambda: (_ for _ in ()).throw(RuntimeError('synthetic'))
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(module, 'data_root', return_value=Path(tmp)):
                module.register(ctx)
            self.assertNotIn('::axioma{', ctx.hooks['pre_llm_call']()['context'])
