"""Advisor lifecycle: card in, documented approve directive out. Never blocks or executes."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_card import CARD

ARGS = {'text': 'SYNTHETIC BODY'}


class AdvisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def advisor(self, config=None, checks=None, surface='cli'):
        from axioma.advisor import Advisor
        from axioma.audit import Audit
        return Advisor(config or {}, Audit(self.root / 'audit.sqlite3'), checks_config=checks,
                       surface=lambda: surface)

    def stage(self, a, card=None, args=None, session='s', tool='send_message'):
        return json.loads(a.submit({'tool': tool, 'arguments': ARGS if args is None else args,
                                    'card': CARD if card is None else card}, session_id=session))

    def pre(self, a, args=None, session='s', call='c', tool='send_message'):
        return a.before(tool, ARGS if args is None else args, session_id=session, tool_call_id=call)

    def test_unclassified_calls_pass_untouched(self):
        a = self.advisor()
        for tool, args in [('read_file', {'path': '/x'}), ('web_search', {'query': 'q'}),
                           ('terminal', {'command': 'git status'})]:
            self.assertIsNone(a.before(tool, args, session_id='s', tool_call_id='c'))
        self.assertEqual(a.audit.rows(), [])

    def test_never_blocks_only_documented_approve_directive(self):
        for light in ('red', 'yellow', 'green'):
            with self.subTest(light=light):
                a = self.advisor()
                self.stage(a, {**CARD, 'light': light})
                d = self.pre(a)
                self.assertEqual(d['action'], 'approve')
                self.assertNotEqual(d.get('action'), 'block')
        a = self.advisor()
        d = self.pre(a)  # no card at all
        self.assertEqual(d['action'], 'approve')
        self.assertIn('NO CARD', d['message'])

    def test_card_shows_question_on_every_light_and_question_first_on_messaging(self):
        for surface, first in (('cli', False), ('tui', False), ('telegram', True), ('discord', True)):
            for light in ('red', 'yellow', 'green'):
                with self.subTest(surface=surface, light=light):
                    a = self.advisor(surface=surface)
                    self.stage(a, {**CARD, 'light': light, 'affects': ['self'], 'told': True})
                    msg = self.pre(a)['message']
                    self.assertIn(CARD['question'], msg)
                    if first:
                        self.assertTrue(msg.startswith(CARD['question']))
                    else:
                        self.assertEqual(msg.splitlines()[1], CARD['question'], 'question right after the light')
                    self.assertNotIn('\x1b', msg)

    def test_red_never_offers_yes_and_gets_a_fresh_rule_key(self):
        a = self.advisor()
        keys = set()
        for i in range(3):
            self.stage(a, {**CARD, 'light': 'red'})
            d = self.pre(a, call='c%d' % i)
            self.assertIn('STOP', d['message'])
            self.assertIn('proceed: no', d['message'])
            self.assertNotIn('yes', d['message'].lower())
            keys.add(d['rule_key'])
        self.assertEqual(len(keys), 3, 'a remembered approval must never silently pass RED')
        # NO CARD also never gets a reusable key.
        self.assertNotEqual(self.pre(a, call='x')['rule_key'], self.pre(a, call='y')['rule_key'])

    def test_green_yellow_also_get_fresh_rule_keys(self):
        a = self.advisor()
        green = {**CARD, 'light': 'green', 'affects': ['self'], 'told': True}
        self.stage(a, green)
        k1 = self.pre(a, call='1')['rule_key']
        self.stage(a, green)
        k2 = self.pre(a, call='2')['rule_key']
        self.assertNotEqual(k1, k2, 'a remembered approval never covers a later call')
        self.assertTrue(k1.startswith('axioma:send:send_message:green:'))

    def test_card_binds_to_exact_arguments_and_session(self):
        a = self.advisor()
        self.stage(a)
        self.assertIn('NO CARD', self.pre(a, args={'text': 'changed'})['message'])
        self.assertIn('NO CARD', self.pre(a, session='other')['message'])
        self.assertIn('CAUTION', self.pre(a)['message'])
        self.assertIn('NO CARD', self.pre(a)['message'], 'a card is shown once, not reused')

    def test_card_never_claims_authority(self):
        a = self.advisor()
        self.stage(a, {**CARD, 'light': 'green', 'affects': ['self'], 'told': True})
        msg = self.pre(a)['message'].lower()
        self.assertIn('advice only', msg)
        for claim in ('authorized', 'approved', 'nothing goes out without you', 'held', 'blocked'):
            self.assertNotIn(claim, msg)
        staged = self.stage(a)
        self.assertEqual(staged['status'], 'staged')
        self.assertNotIn('approved', json.dumps(staged).lower())

    def test_malformed_card_is_reported_to_agent_and_logged(self):
        a = self.advisor()
        out = self.stage(a, {**CARD, 'question': 'Do it'})
        self.assertIn('error', out)
        self.assertIn('NO CARD', self.pre(a)['message'])
        rows = a.audit.rows()
        self.assertTrue(any(r['event'] == 'card' and r['valid'] is False for r in rows))

    @patch.dict('os.environ', {'HERMES_KANBAN_TASK': ''})  # non-task no-text contract
    def test_answers_are_logged_as_metadata_and_never_authorize(self):
        a = self.advisor()
        self.stage(a)
        d = self.pre(a)
        self.assertIsNone(a.respond(pattern_key='plugin_rule:' + d['rule_key'], choice='once',
                                    surface='cli', session_id='s', tool_call_id='c'))
        self.stage(a)
        d = self.pre(a, call='c2')
        a.respond(pattern_key='plugin_rule:' + d['rule_key'], choice='deny', surface='gateway',
                  session_id='s', tool_call_id='c2')
        self.stage(a)
        d = self.pre(a, call='c3')
        a.respond(pattern_key='plugin_rule:' + d['rule_key'], choice='smart_approve',
                  session_id='s', tool_call_id='c3')
        # Unrelated approvals are ignored.
        a.respond(pattern_key='plugin_rule:other', choice='once', session_id='s', tool_call_id='c3')
        rows = a.audit.rows()
        answers = sorted(r['answer'] for r in rows if r['event'] == 'answer')
        self.assertEqual(answers, ['auto', 'no', 'yes'])
        text = json.dumps(rows)
        self.assertNotIn('SYNTHETIC BODY', text)
        for key in ('intent', 'signal', 'question'):
            self.assertNotIn(CARD[key], text)
        self.assertTrue(all(r['answered_with_question'] is None for r in rows))

    def test_hard_red_rule_turns_card_and_no_card_notice_red(self):
        checks = {'deny': [{'tool': '*send*', 'pattern': 'receive_only'}]}
        a = self.advisor(checks=checks)
        args = {'sender': 'receive_only'}
        self.stage(a, {**CARD, 'light': 'green', 'affects': ['self'], 'told': True}, args=args)
        self.assertIn('STOP', self.pre(a, args=args)['message'])
        msg = self.pre(a, args=args, call='x')['message']
        self.assertTrue(msg.startswith('STOP'))
        self.assertNotIn('yes', msg.lower())
        # A standing-rule hit fires even on an otherwise unclassified tool.
        a2 = self.advisor(checks={'deny': [{'tool': 'read_file', 'pattern': 'secrets'}]})
        self.assertIsNotNone(a2.before('read_file', {'path': '/secrets'}, session_id='s', tool_call_id='c'))

    def test_internal_errors_still_show_a_notice_never_drop_silently(self):
        a = self.advisor()
        a.policy.classify = lambda *x: (_ for _ in ()).throw(RuntimeError('SECRET EXCEPTION'))
        d = self.pre(a)
        self.assertEqual(d['action'], 'approve')
        self.assertNotIn('SECRET', d['message'])
        a = self.advisor()
        a.audit.record = lambda **kw: (_ for _ in ()).throw(OSError('disk full SECRET'))
        self.stage(a)
        d = self.pre(a)
        self.assertEqual(d['action'], 'approve')
        self.assertIn('CAUTION', d['message'])

    def test_invalid_config_falls_back_to_defaults_and_says_so(self):
        a = self.advisor(config={'remove': ['typo']})
        self.assertTrue(a.config_error)
        msg = self.pre(a)['message']
        self.assertIn('axioma_config: fail', msg)

    def test_ttl_capacity_and_finalize(self):
        a = self.advisor()
        now = [0]
        a.clock = lambda: now[0]
        self.stage(a)
        now[0] = 301
        self.assertIn('NO CARD', self.pre(a)['message'])
        for i in range(1100):
            self.stage(a, args={'text': str(i)})
        self.assertLess(len(a.cards), 1025)
        a.finalize(session_id='s')
        self.assertEqual(a.cards, {})


if __name__ == '__main__':
    unittest.main()
