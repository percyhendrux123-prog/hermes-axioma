"""Card fingerprint, spec 5.6 "Shown equals staged". Synthetic data only; no network, no host."""
import html
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_card import CARD

ARGS = {'text': 'SYNTHETIC BODY', 'chat_id': 42, 'opts': {'b': 2, 'a': [1, 'x']}}
CODE = re.compile(r'^card code ([0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4})$', re.M)
SURFACES = ('cli', 'tui', 'desktop', 'acp', 'telegram', 'discord', 'slack', 'matrix', 'sms',
            'whatsapp', 'signal', 'webui', 'api_server')
LOCAL = ('cli', 'tui', 'desktop', 'acp')
MDV2 = re.compile(r'([_*\[\]()~`>#+\-=|{}.!\\])')  # Telegram MarkdownV2 reserved characters


def code_of(message):
    found = CODE.findall(message)
    assert len(found) == 1, message
    return found[0]


class FingerprintCore(unittest.TestCase):
    def fp(self, key=b'k' * 32):
        from axioma.fingerprint import Fingerprint
        return Fingerprint(key)

    def test_deterministic_and_readable(self):
        a, b = self.fp(), self.fp()
        one = a.code('c1', 'send_message', ARGS, 'CAUTION\nQ?')
        self.assertEqual(one, b.code('c1', 'send_message', ARGS, 'CAUTION\nQ?'))
        self.assertRegex(one, r'^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$')
        # Canonical JSON: key order in the arguments does not matter; values do.
        reordered = {'opts': {'a': [1, 'x'], 'b': 2}, 'chat_id': 42, 'text': 'SYNTHETIC BODY'}
        self.assertEqual(one, a.code('c1', 'send_message', reordered, 'CAUTION\nQ?'))
        self.assertNotEqual(one, self.fp(b'z' * 32).code('c1', 'send_message', ARGS, 'CAUTION\nQ?'))

    def test_any_change_to_text_tool_args_or_card_id_changes_it(self):
        fp = self.fp()
        base = fp.code('c1', 'send_message', ARGS, 'CAUTION\nQ?')
        variants = [('c2', 'send_message', ARGS, 'CAUTION\nQ?'),
                    ('c1', 'send_email', ARGS, 'CAUTION\nQ?'),
                    ('c1', 'send_message', {**ARGS, 'text': 'SYNTHETIC BODY.'}, 'CAUTION\nQ?'),
                    ('c1', 'send_message', {**ARGS, 'chat_id': '42'}, 'CAUTION\nQ?'),
                    ('c1', 'send_message', {**ARGS, 'opts': {'b': 2, 'a': ['x', 1]}}, 'CAUTION\nQ?'),
                    ('c1', 'send_message', {**ARGS, 'extra': None}, 'CAUTION\nQ?'),
                    ('c1', 'send_message', ARGS, 'GO\nQ?'),
                    ('c1', 'send_message', ARGS, 'CAUTION\nQ? '),
                    ('c1', 'send_message', ARGS, 'CAUTION\n\nQ?')]
        codes = [fp.code(*v) for v in variants]
        self.assertNotIn(base, codes)
        self.assertEqual(len(set(codes)), len(codes))

    def test_parse_code_accepts_what_a_human_types_back(self):
        from axioma.fingerprint import parse_code
        for typed in ('7Q4K-2MPD', '7q4k2mpd', ' 7Q4K 2MPD ', 'card code 7Q4K-2MPD', '#7Q4K-2MPD',
                      '7Q4K-2MPD'.replace('0', 'O')):
            self.assertEqual(parse_code(typed), '7Q4K-2MPD', typed)
        self.assertEqual(parse_code('O1LI-0000'), '0111-0000')  # Crockford: O->0, I/L->1
        for bad in ('', '7Q4K', '7Q4K-2MPDX', 'UUUU-UUUU', None, 'card code'):
            self.assertIsNone(parse_code(bad), bad)

    def test_seal_detects_edited_fields(self):
        fp = self.fp()
        row = {'event': 'presented_to_host', 'card_id': 'c', 'light': 'yellow', 'fingerprint': 'AAAA-BBBB'}
        row['seal'] = fp.seal(row)
        self.assertTrue(fp.sealed(row))
        for k, v in (('light', 'green'), ('fingerprint', 'AAAA-BBBC'), ('card_id', 'd'), ('seal', '0' * 32)):
            self.assertFalse(fp.sealed({**row, k: v}), k)


class FingerprintFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'audit.sqlite3'

    def advisor(self, surface='cli'):
        from axioma.advisor import Advisor
        from axioma.audit import Audit
        return Advisor({}, Audit(self.db), surface=lambda: surface)

    def shown(self, a, card=CARD, args=ARGS, call='c', answer='once'):
        if card is not None:
            a.submit({'tool': 'send_message', 'arguments': args, 'card': card}, session_id='s')
        d = a.before('send_message', args, session_id='s', tool_call_id=call)
        if answer:
            a.respond(pattern_key='plugin_rule:' + d['rule_key'], choice=answer, surface='synthetic',
                      session_id='s', tool_call_id=call)
        return d['message']

    def test_every_card_and_notice_carries_the_code_under_the_question_on_every_surface(self):
        from axioma.card import NOTICE_QUESTION
        from axioma.fingerprint import unstamp
        for surface in SURFACES:
            for card in ({**CARD, 'light': 'red'}, {**CARD, 'light': 'green', 'affects': ['self'], 'told': True},
                         None):
                with self.subTest(surface=surface, card=card and card['light']):
                    a = self.advisor(surface)
                    msg = self.shown(a, card=card, answer=None)
                    code = code_of(msg)
                    lines = msg.splitlines()
                    question = CARD['question'] if card else NOTICE_QUESTION
                    q = lines.index(question)
                    self.assertEqual(lines[q + 1], 'card code ' + code, 'code sits right under the question')
                    self.assertEqual(q, 1 if surface in LOCAL else 0)
                    self.assertNotIn('card code', unstamp(msg))
        # The fallback notice (advisor failure) carries one too.
        for surface in ('cli', 'telegram'):
            a = self.advisor(surface)
            a.policy.classify = lambda *x: (_ for _ in ()).throw(RuntimeError('synthetic'))
            msg = a.before('send_message', ARGS, session_id='s', tool_call_id='f')['message']
            self.assertIn('advisory unavailable', msg)
            lines = msg.splitlines()
            self.assertEqual(lines[lines.index(NOTICE_QUESTION) + 1], 'card code ' + code_of(msg))

    def test_code_is_the_fingerprint_of_what_the_host_receives(self):
        from axioma.fingerprint import unstamp
        a = self.advisor('telegram')
        msg = self.shown(a, answer=None)
        row = [r for r in a.audit.card_rows() if r['event'] == 'presented_to_host'][0]
        self.assertEqual(code_of(msg), a.fp.code(row['card_id'], 'send_message', ARGS, unstamp(msg)))
        self.assertNotEqual(code_of(msg), a.fp.code(row['card_id'], 'send_message', ARGS, unstamp(msg) + ' '))

    def test_code_survives_each_surface_renderer(self):
        from axioma.audit import Audit
        from axioma.signal import Signal
        long_q = 'Is ' + 'this really the audience you intended for the synthetic draft and ' * 5 + 'now?'
        long_q = long_q[:399].rstrip(' ?') + '?'
        for surface in SURFACES:
            for card in (CARD, {**CARD, 'question': long_q}):
                with self.subTest(surface=surface, long=card is not CARD):
                    msg = self.shown(self.advisor(surface), card=card, answer=None)
                    code = code_of(msg)
                    line = 'card code ' + code
                    # Only letters, digits, space and one dash: nothing Markdown/HTML treats as syntax.
                    self.assertRegex(line, r'^[a-z ]+[0-9A-Z]{4}-[0-9A-Z]{4}$')
                    # Telegram HTML card: escaped on the wire, identical once rendered.
                    self.assertIn(line, html.escape(msg))
                    self.assertIn(line, html.unescape(html.escape(msg)))
                    # Telegram MarkdownV2 (text /approve fallback): escaped, then rendered back.
                    wire = MDV2.sub(r'\\\1', msg)
                    self.assertIn(line, re.sub(r'\\(.)', r'\1', wire))
                    # Adapter budgets keep a prefix of the description: Discord 300, Telegram 500.
                    if surface not in LOCAL:
                        self.assertIn(line, msg[:300])
                    lines = msg.splitlines()
                    q = lines.index(card['question'])
                    self.assertEqual(lines[q + 1] if card is CARD else lines[q - 1], line,
                                     'under a short question, directly above a long one')
                    # Quoted in a normal reply, the plugin's own transform leaves it alone.
                    out = Signal(Audit(self.db)).transform('The card said ' + line + '. Run it?',
                                                           session_id='s', platform=surface)
                    self.assertTrue(out is None or line in out, out)

    def test_log_round_trip_staged_shown_answered(self):
        a = self.advisor('telegram')
        msg = self.shown(a)
        code = code_of(msg)
        rows = a.audit.card_rows()
        shown = [r for r in rows if r['event'] == 'presented_to_host']
        answered = [r for r in rows if r['event'] == 'answer']
        self.assertEqual([r['fingerprint'] for r in shown], [code])
        self.assertEqual([r['fingerprint'] for r in answered], [code])
        self.assertEqual(answered[0]['card_id'], shown[0]['card_id'])
        self.assertEqual(shown[0]['surface'], 'telegram')
        report = a.command('verify ' + code)
        self.assertIn('staged: card from the agent', report)
        self.assertIn('shown: CAUTION, handed to Hermes on telegram', report)
        self.assertIn('answered: yes (once)', report)
        self.assertTrue(report.splitlines()[-1].startswith('OK:'), report)
        self.assertNotIn('MISMATCH', report)
        # The pasted card, wrapped in the host's framing, matches line by line.
        framed = 'Approval required\nsend_message\nReason: ' + msg + '\nNot answering means it will NOT run.'
        report = a.command('verify ' + code.lower().replace('-', ' ') + '\n' + framed)
        self.assertIn('words: all', report)
        self.assertTrue(report.splitlines()[-1].startswith('OK:'), report)
        self.assertIn(code, a.command('cards'))
        # A fresh advisor on the same log (restart) still verifies.
        self.assertTrue(self.advisor().command('verify ' + code).splitlines()[-1].startswith('OK:'))
        # Still no bodies in the log.
        text = json.dumps(a.audit.card_rows())
        for body in ('SYNTHETIC BODY', CARD['question'], CARD['intent'], CARD['signal']):
            self.assertNotIn(body, text)

    def tamper(self, event, **changes):
        db = sqlite3.connect(str(self.db))
        with db:
            for rid, meta in db.execute('SELECT id, metadata FROM events').fetchall():
                m = json.loads(meta)
                if m.get('event') == event:
                    m.update(changes)
                    db.execute('UPDATE events SET metadata = ? WHERE id = ?', (json.dumps(m, sort_keys=True), rid))
        db.close()

    def test_mismatches_are_reported_in_plain_words(self):
        a = self.advisor('discord')
        msg = self.shown(a)
        code = code_of(msg)
        # Unknown code.
        other = 'ZZZZ-ZZZZ' if code != 'ZZZZ-ZZZZ' else 'YYYY-YYYY'
        self.assertIn('MISMATCH: no card with this code was shown', a.command('verify ' + other))
        self.assertIn('Usage', a.command('verify'))
        # Words changed in transit, a line added, lines reordered, a line cut.
        cases = {'changed': msg.replace('audience', 'crowd'),
                 'added': msg.replace('\nintent:', '\nsignal: Safe to send.\nintent:'),
                 'reordered': '\n'.join([msg.splitlines()[0]] + msg.splitlines()[1:][::-1]),
                 'cut': '\n'.join(msg.splitlines()[:-1])}
        for name, pasted in cases.items():
            with self.subTest(pasted=name):
                report = a.command('verify ' + code + '\n' + pasted)
                self.assertIn('MISMATCH: the pasted card differs from what was staged', report)
                self.assertFalse(report.splitlines()[-1].startswith('OK'))
        # Log edited after writing: shown light, answer code, staged light.
        for event, change, needle in (
                ('presented_to_host', {'light': 'green'}, 'shown record was changed after it was written'),
                ('presented_to_host', {'text_digest': '0' * 32}, 'does not produce this code'),
                ('answer', {'fingerprint': other}, 'answer was recorded against code ' + other),
                ('card', {'light': 'green'}, 'staged record was changed after it was written')):
            with self.subTest(event=event, change=change):
                self.tmp2 = None
                self.tamper(event, **change)
                self.assertIn(needle, a.command('verify ' + code))
        # An answer whose shown record was removed.
        db = sqlite3.connect(str(self.db))
        with db:
            db.execute("DELETE FROM events WHERE metadata LIKE '%presented_to_host%'")
            db.execute('UPDATE events SET metadata = ? WHERE metadata LIKE ?',
                       (json.dumps({'event': 'answer', 'fingerprint': code, 'card_id': 'x'}), '%"answer"%'))
        db.close()
        self.assertIn('answer is recorded under this code but no card with this code was ever shown',
                      a.command('verify ' + code))

    def test_signals_command_routes_verify_and_cards(self):
        spec = importlib.util.spec_from_file_location('axioma_plugin_fp', ROOT / '__init__.py',
                                                      submodule_search_locations=[str(ROOT)])
        module = importlib.util.module_from_spec(spec)
        sys.modules['axioma_plugin_fp'] = module
        spec.loader.exec_module(module)

        class Context:
            session_surface = staticmethod(lambda: 'telegram')

            def __init__(self):
                self.hooks, self.commands = {}, {}

            def get_config(self, key, default=None):
                return default

            def register_hook(self, key, fn):
                self.hooks[key] = fn

            def register_tool(self, **kw):
                self.tool = kw

            def register_command(self, key, fn, **kw):
                self.commands[key] = fn
        ctx = Context()
        with patch.object(module, 'data_root', return_value=Path(self.tmp.name)):
            module.register(ctx)
        ctx.tool['handler']({'tool': 'send_message', 'arguments': ARGS, 'card': CARD}, session_id='s')
        d = ctx.hooks['pre_tool_call']('send_message', ARGS, session_id='s', tool_call_id='c')
        code = code_of(d['message'])
        ctx.hooks['post_approval_response'](pattern_key='plugin_rule:' + d['rule_key'], choice='deny',
                                            session_id='s', tool_call_id='c')
        report = ctx.commands['signals']('verify ' + code)
        self.assertIn('answered: no (deny)', report)
        self.assertTrue(report.splitlines()[-1].startswith('OK:'))
        self.assertIn(code, ctx.commands['signals']('cards'))
        self.assertIn('No signals logged yet', ctx.commands['signals'](''))
        self.assertIn('No signals logged yet', ctx.commands['whispers'](''))


if __name__ == '__main__':
    unittest.main()
