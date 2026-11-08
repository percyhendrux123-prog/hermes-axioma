"""Marketplace regressions. Temporary synthetic data only; commands are never executed."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_card import CARD
from test_fingerprint import code_of


class KeyPermissions(unittest.TestCase):
    def test_loose_key_or_parent_is_refused_when_chmod_fails_or_does_nothing(self):
        from axioma.seal import load_key
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / 'plugin'
            parent.mkdir(mode=0o700)
            key = parent / 'card-code.key'
            key.write_bytes(b's' * 32)
            for target, mode in ((key, 0o644), (parent, 0o755)):
                for effect in (PermissionError('synthetic chmod refusal'), None):
                    with self.subTest(target=target.name, effect=effect):
                        os.chmod(key, 0o600)
                        os.chmod(parent, 0o700)
                        os.chmod(target, mode)
                        with patch('axioma.seal.os.chmod', side_effect=effect):
                            with self.assertRaisesRegex(PermissionError, 'owner-only'):
                                load_key(key)

    def test_symlink_is_refused_without_changing_its_target(self):
        from axioma.seal import load_key
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'
            target.write_bytes(b's' * 32)
            os.chmod(target, 0o644)
            key = Path(tmp) / 'card-code.key'
            key.symlink_to(target)
            with self.assertRaisesRegex(PermissionError, 'owner-only'):
                load_key(key)
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)

    def test_other_owner_is_refused_even_with_owner_only_modes(self):
        from axioma.seal import load_key
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / 'card-code.key'
            key.write_bytes(b's' * 32)
            os.chmod(key, 0o600)
            with patch('axioma.seal.os.getuid', return_value=os.getuid() + 1):
                with self.assertRaisesRegex(PermissionError, 'owner-only'):
                    load_key(key)

    def test_cached_key_does_not_bypass_permission_recheck(self):
        from axioma.advisor import Advisor
        from axioma.audit import Audit
        with tempfile.TemporaryDirectory() as tmp:
            a = Advisor({}, Audit(Path(tmp) / 'audit.sqlite3'))
            a.submit({'tool': 'send_message', 'arguments': {}, 'card': CARD}, session_id='s')
            message = a.before('send_message', {}, session_id='s', tool_call_id='c')['message']
            code = code_of(message)
            self.assertIn('OK so far:', a.command('verify ' + code))
            os.chmod(a.key_path(), 0o644)
            with patch('axioma.seal.os.chmod', side_effect=PermissionError('synthetic')):
                report = a.command('verify ' + code)
            self.assertIn('NOT CHECKED', report)
            self.assertIn('owner-only', report)
            self.assertNotIn('OK', report)
            self.assertIsNone(a._fp)


class ContinuedCommands(unittest.TestCase):
    def test_continued_push_and_deploy_get_advisories(self):
        from axioma.advisor import Advisor
        from axioma.audit import Audit
        from axioma.policy import Policy
        cases = [('git \\\npush origin main', 'send'),
                 ('git pu\\\nsh origin main', 'send'),
                 ('git \\\r\npush origin main', 'send'),
                 ('gh pr \\\ncreate --title synthetic', 'send'),
                 ('netlify \\\ndeploy --prod', 'spin'),
                 ('npm run de\\\nploy', 'spin'),
                 ('docker stack \\\ndeploy synthetic', 'spin')]
        for command, category in cases:
            with self.subTest(command=repr(command)), tempfile.TemporaryDirectory() as tmp:
                args = {'command': command}
                self.assertEqual(Policy().classify('terminal', args), (category,))
                a = Advisor({}, Audit(Path(tmp) / 'audit.sqlite3'))
                result = a.before('terminal', args, session_id='s', tool_call_id='c')
                self.assertEqual(result['action'], 'approve')
                self.assertNotIn('advisory unavailable', result['message'])
                row = a.audit.card_rows()[0]
                self.assertEqual(row['categories'], [category])
                # Classification normalization must not change the exact staged arguments.
                parts = a.fp.digests(row['card_id'], 'terminal', args, '')
                self.assertEqual(row['args_digest'], parts['args_digest'])
                self.assertEqual(args['command'], command)


if __name__ == '__main__':
    unittest.main()
