import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class PolicyTests(unittest.TestCase):
    def test_classifies_sends_spends_spins_but_not_reads(self):
        self.assertTrue((ROOT / 'axioma' / 'policy.py').is_file(), 'classification module missing')
        from axioma.policy import Policy
        p = Policy()
        for tool, args, category in [
            ('send_message', {}, 'send'), ('connectors__gmail__send_email', {}, 'send'),
            ('mcp__stripe__create_payment', {}, 'spend'), ('cronjob', {'action': 'create'}, 'spin'),
            ('delegate_task', {'tasks': [{}]}, 'spin'), ('kanban_create', {}, 'spin'),
            ('terminal', {'command': 'cd app && netlify deploy --prod'}, 'spin'),
            ('terminal', {'command': 'git push origin main'}, 'send'),
        ]:
            with self.subTest(tool=tool, args=args):
                self.assertIn(category, p.classify(tool, args))
        for tool, args in [('read_file', {}), ('web_search', {}),
                           ('terminal', {'command': 'git status'}),
                           ('cronjob', {'action': 'list'}), ('delegate_task', {'action': 'list'}),
                           ('connectors__gmail__list_messages', {})]:
            self.assertEqual(p.classify(tool, args), ())

    def test_payment_reads_pass_and_common_posts_are_gated(self):
        from axioma.policy import Policy
        p = Policy()
        for tool in ['mcp__stripe__get_payment', 'mcp__stripe__list_payments', 'mcp__stripe__list_refunds']:
            self.assertEqual(p.classify(tool, {}), ())
        for tool in ['connectors__slack__post_message', 'post_tweet', 'mcp__stripe__confirm_payment']:
            self.assertTrue(p.classify(tool, {}))

    def test_config_add_remove_and_invalid_fail_closed(self):
        from axioma.policy import Policy
        p = Policy({'remove': ['message-send'], 'add': [
            {'id': 'custom', 'category': 'spend', 'tool': 'buy_widgets'}]})
        self.assertEqual(p.classify('send_message', {}), ())
        self.assertEqual(p.classify('buy_widgets', {}), ('spend',))
        for config in [None, {'add': 'bad'}, {'remove': ['typo']},
                       {'add': [{'id': 'x', 'category': 'oops', 'tool': '*'}]},
                       {'add': [{'id': 'x', 'category': 'spin', 'tool': 'terminal', 'command': '['}]}]:
            if config is None:
                continue
            with self.subTest(config=config), self.assertRaises(ValueError):
                Policy(config)


if __name__ == '__main__':
    unittest.main()
