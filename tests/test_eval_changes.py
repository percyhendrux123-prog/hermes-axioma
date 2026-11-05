from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_card import CARD


class EvalChangesTests(unittest.TestCase):
    def test_hard_red_and_downstream_floor(self):
        self.assertTrue((Path(__file__).resolve().parents[1] / 'axioma/checks.py').is_file(), 'preflight module missing')
        from axioma.checks import Checks
        c = Checks({'deny': [{'tool': '*send*', 'pattern': 'receive_only'}],
                    'non_reversible': [{'tool': '*change_handle*', 'pattern': '.*'}]})
        for tool, args in [('send_message', {'sender': 'receive_only'}), ('change_handle', {})]:
            adjusted, results = c.apply(tool, args, {**CARD, 'light': 'green'})
            self.assertEqual(adjusted['light'], 'red')
        for affects in [['end_users'], 'end users', ['public']]:
            adjusted, results = Checks({}).apply('send_message', {}, {**CARD, 'light': 'green', 'affects': affects})
            self.assertEqual(adjusted['light'], 'yellow')
        card = {**CARD, 'light': 'green', 'affects': ['end_users'], 'told': True}
        self.assertEqual(Checks({}).apply('send_message', {}, card)[0]['light'], 'green')

    def test_preflight_skill_secret_presence_and_lock(self):
        from axioma.checks import Checks
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'skill' / 'safety').mkdir(parents=True)
            (root / 'skill' / 'safety' / 'SKILL.md').touch()
            cfg = {'skills': {'builder': {'root': str(root / 'skill'), 'required': ['safety']}},
                   'provider_conflicts': [{'provider': 'subscription', 'key_envs': ['SYNTHETIC_KEY']}],
                   'locks': [{'tool': '*', 'path': str(root / 'device.lock')}]}
            c = Checks(cfg, secret_present=lambda name: False)
            card, results = c.apply('kanban_create', {'assignee': 'builder', 'provider': 'subscription'},
                                    {**CARD, 'light': 'green', 'affects': ['self']})
            self.assertEqual(card['light'], 'green')
            self.assertTrue(all(r['pass'] for r in results))
            (root / 'device.lock').touch()
            card, results = Checks(cfg, secret_present=lambda n: True).apply(
                'kanban_create', {'assignee': 'builder', 'provider': 'subscription'}, {**CARD, 'light': 'green'})
            self.assertEqual(card['light'], 'red')
            self.assertTrue(any(not r['pass'] for r in results))
            (root / 'skill' / 'safety' / 'SKILL.md').unlink()
            card, results = c.apply('kanban_create', {'assignee': 'builder'}, {**CARD, 'light': 'green'})
            self.assertFalse(next(r for r in results if r['check'] == 'skills')['pass'])

    def test_unproved_sender_is_red_and_green_requires_downstream_answer(self):
        from axioma.checks import Checks
        c = Checks({'senders': {'approved@example.invalid': True, 'receive-only@example.invalid': False}})
        card = {**CARD, 'light': 'green', 'affects': ['self'], 'told': True}
        adjusted, results = c.apply('send_email', {'from': 'receive-only@example.invalid'}, card, categories=('send',))
        self.assertEqual(adjusted['light'], 'red')
        self.assertIn('preflight', adjusted['signal'].lower())
        self.assertFalse(next(r for r in results if r['check'] == 'sender_rights')['pass'])
        self.assertEqual(c.apply('send_email', {'from': 'approved@example.invalid'}, card, categories=('send',))[0]['light'], 'green')
        self.assertEqual(Checks({}).apply('send_email', {}, {**CARD, 'light': 'green'})[0]['light'], 'yellow')

    def test_scrub_classifies_recursive_and_outside_moves(self):
        from axioma.policy import Policy
        p = Policy({'workspace': '/synthetic/task'})
        for command in ['rm -rf cache', 'rm -r /synthetic/task/cache', 'rm -R /synthetic/task/cache',
                        'mv /synthetic/task/out.txt /outside/out.txt', 'rm /outside/out.txt']:
            self.assertIn('scrub', p.classify('terminal', {'command': command}))
        self.assertEqual(p.classify('terminal', {'command': 'rm /synthetic/task/output.txt'}), ())
        self.assertEqual(p.classify('terminal', {'command': 'mv a.txt b.txt', 'workdir': '/synthetic/task'}), ())
        # Without an explicit workdir the actual cwd is unknown: flagged (finding 4).
        self.assertIn('scrub', p.classify('terminal', {'command': 'mv a.txt b.txt'}))

    def test_card_accepts_affects_and_question_first_on_messaging(self):
        from axioma.card import validate_card, render_card
        card = {**CARD, 'light': 'green', 'affects': ['end_users'], 'told': False}
        self.assertEqual(validate_card(card), card)
        self.assertTrue(render_card(card, messaging=True).startswith(CARD['question']))
        self.assertIn('skills: fail', render_card(card, checks=[{'check': 'skills', 'pass': False}]))


if __name__ == '__main__':
    unittest.main()
