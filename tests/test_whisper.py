from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class WhisperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def whisper(self, **config):
        self.assertTrue((Path(__file__).resolve().parents[1] / 'axioma/whisper.py').is_file(), 'whisper missing')
        from axioma.audit import Audit
        from axioma.whisper import Whisper
        return Whisper(Audit(Path(self.tmp.name) / 'audit.sqlite3'), **config)

    def test_untagged_text_is_byte_for_byte_unchanged(self):
        w = self.whisper()
        text = 'Text **bold**\n  code\nÉ 42?'
        self.assertIsNone(w.transform(text, session_id='s', platform='cli'), 'untagged: host keeps original')
        self.assertEqual(w.audit.rows(), [])

    @patch.dict('os.environ', {'HERMES_KANBAN_TASK': ''})  # non-task no-text contract
    def test_strip_log_once_and_no_text_bodies(self):
        w = self.whisper()
        text = 'A [whisper:unverified_figure]123 synthetic[/whisper] claim.'
        # A229: messaging surfaces carry the word '(second look)' by default (spec 4.5).
        self.assertEqual(w.transform(text, session_id='s', platform='telegram'), 'A 123 synthetic (second look) claim.')
        self.assertEqual(w.transform(text, session_id='s', platform='discord'), 'A 123 synthetic claim.')
        rows = w.audit.rows()
        # A229 pass 10: the repeat is logged too (shown: false, reason: repeat).
        self.assertEqual(sorted(r['reason'] for r in rows), ['repeat', 'unverified_figure'])
        rows = [r for r in rows if r['shown']]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['reason'], 'unverified_figure')
        self.assertEqual(len(rows[0]['span_hash']), 64)
        self.assertNotIn('synthetic', str(rows))
        self.assertIn(rows[0]['span_hash'][:12], w.listing())

    def test_dark_light_color_and_optional_messaging_marker(self):
        text = '[whisper:assumption]Synthetic assumption[/whisper]'
        for theme, rgb in [('dark', '234;223;184'), ('light', '138;106;31')]:
            w = self.whisper(theme=theme)
            out = w.transform(text, session_id=theme, platform='cli')
            self.assertIn('\x1b[38;2;' + rgb + 'm', out)
            self.assertNotIn('[whisper:', out)
            again = w.transform(text, session_id=theme, platform='cli')
            self.assertNotIn('\x1b', again)
        w = self.whisper(messaging_marker=True)
        out = w.transform(text, session_id='marker', platform='telegram')
        self.assertIn('(second look)', out)
        self.assertNotIn('\x1b', out)
        off = self.whisper(messaging_marker=False).transform(text, session_id='off', platform='telegram')
        self.assertEqual(off, 'Synthetic assumption')

    def test_failure_never_blocks_and_tags_do_not_leak(self):
        w = self.whisper()
        w.audit.whisper_once = lambda *a: (_ for _ in ()).throw(OSError('full'))
        self.assertEqual(w.transform('[whisper:voice_drift]A[/whisper]', session_id='s', platform='cli'), 'A')
        self.assertEqual(w.transform('[whisper:unknown]B[/whisper]', session_id='s', platform='cli'), 'B')
        self.assertEqual(w.transform('[whisper:low_confidence]C', session_id='s', platform='cli'), 'C')


if __name__ == '__main__':
    unittest.main()
