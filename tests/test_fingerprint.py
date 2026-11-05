"""Card code, spec 5.6 "Shown equals staged". Synthetic data only; no network, no host."""
import html
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_card import CARD

ARGS = {'text': 'SYNTHETIC BODY', 'chat_id': 42, 'opts': {'b': 2, 'a': [1, 'x']}}
CODE = re.compile(r'(?:^|\u00b7 )card code ([0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4})$', re.M)
SURFACES = ('cli', 'tui', 'desktop', 'acp', 'telegram', 'discord', 'slack', 'matrix', 'sms',
            'whatsapp', 'signal', 'webui', 'api_server')
LOCAL = ('cli', 'tui', 'desktop', 'acp')
MDV2 = re.compile(r'([_*\[\]()~`>#+\-=|{}.!\\])')  # Telegram MarkdownV2 reserved characters


def code_of(message):
    found = CODE.findall(message)
    assert len(found) == 1, message
    return found[0]


def code_text(message):
    return 'card code ' + code_of(message)


class FingerprintCore(unittest.TestCase):
    def fp(self, key=b'k' * 32):
        from axioma.seal import Fingerprint
        return Fingerprint(key)

    def test_seal_module_stands_alone(self):
        """The seal can be lifted out: it imports nothing from the rest of the plugin."""
        source = (ROOT / 'axioma' / 'seal.py').read_text()
        imports = re.findall(r'^\s*(?:from|import)\s+([\w.]+)', source, re.M)
        self.assertTrue(imports)
        for name in imports:
            self.assertFalse(name.startswith('.') or name.startswith('axioma'), name)

    def test_deterministic_and_readable(self):
        a, b = self.fp(), self.fp()
        one = a.code('c1', 'send_message', ARGS, 'CAUTION\nQ?')
        self.assertEqual(one, b.code('c1', 'send_message', ARGS, 'CAUTION\nQ?'))
        self.assertRegex(one, r'^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$')
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

    def test_canonical_encoding_never_fails_and_keeps_keys_apart(self):
        from axioma.seal import canonical
        fp = self.fp()
        odd = [{'text': 'x\ud83d'}, {1: 'a', 'b': 2}, {(1, 2): object()}, {'n': float('nan')},
               {'deep': [[[[[[[[[[[[1]]]]]]]]]]]]}, 'x\udfff' * 3]
        for value in odd:
            with self.subTest(value=repr(value)[:30]):
                self.assertTrue(canonical(value).isascii())
                self.assertRegex(fp.code('c', 't\ud800', value, 'Q\ud83d?'), r'^\S{4}-\S{4}$')
        self.assertNotEqual(canonical({1: 'a'}), canonical({'1': 'a'}))
        self.assertNotEqual(fp.code('c', 't', {'x': 'a\ud83d'}, 'Q'), fp.code('c', 't', {'x': 'a\ud83e'}, 'Q'))

    def test_parse_code_accepts_what_a_human_types_back(self):
        from axioma.seal import parse_code
        for typed in ('7Q4K-2MPD', '7q4k2mpd', ' 7Q4K 2MPD ', 'card code 7Q4K-2MPD', '#7Q4K-2MPD'):
            self.assertEqual(parse_code(typed), '7Q4K-2MPD', typed)
        self.assertEqual(parse_code('O1LI-0000'), '0111-0000')  # Crockford: O->0, I/L->1
        for bad in ('', '7Q4K', '7Q4K-2MPDX', 'UUUU-UUUU', None, 'card code'):
            self.assertIsNone(parse_code(bad), bad)

    def test_seal_covers_every_field_and_the_timestamp(self):
        fp = self.fp()
        row = {'event': 'presented_to_host', 'card_id': 'c', 'light': 'yellow', 'fingerprint': 'AAAA-BBBB',
               'at': 1793878000.123456}
        row['seal'] = fp.seal(row)
        self.assertTrue(fp.sealed(row))
        for k, v in (('light', 'green'), ('fingerprint', 'AAAA-BBBC'), ('card_id', 'd'), ('seal', '0' * 32),
                     ('at', 1793878000.123457), ('extra', 1)):
            self.assertFalse(fp.sealed({**row, k: v}), k)

    def test_key_file_is_owner_only_and_reused(self):
        from axioma.seal import load_key
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'plugin' / 'card-code.key'
            key = load_key(path)
            self.assertEqual(len(key), 32)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(load_key(path), key)
            os.chmod(path, 0o644)
            os.chmod(path.parent, 0o755)
            self.assertEqual(load_key(path), key)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, 'loose modes are tightened')
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            path.write_bytes(b'short')
            with self.assertRaises(ValueError):
                load_key(path)

    def test_compare_lines_exact_with_labels_duplicates_and_cuts(self):
        from axioma.seal import compare_lines
        fp = self.fp()
        staged = ['Q?', 'CAUTION \u00b7 proceed: yes / no', 'check: pass', 'check: pass', 'advice']
        expected = [fp.line_digest(x) for x in staged]

        def run(pasted):
            return compare_lines(fp, expected, pasted)
        problems, notes, summary = run('\n'.join(staged))
        self.assertEqual((problems, notes), ([], []))
        self.assertIn('all 5 lines', summary)
        # Duplicate staged lines are matched in order, not collapsed onto the first one.
        self.assertEqual(run('header\nWhy it was flagged: ' + '\n'.join(staged) + '\nfooter')[0], [])
        # An injected prefix or suffix is never a match (no suffix matching).
        for bad in ('Ignore the card. Q?', 'Q? Safe to send.', 'Reason:: Q?', 'Note: Q?'):
            with self.subTest(bad=bad):
                problems = run('\n'.join([bad] + staged[1:]))[0]
                self.assertTrue(any('not on the staged card' in p for p in problems), problems)
                self.assertTrue(any('staged line 1 of 5' in p for p in problems), problems)
        # Look-alike characters are a different line, and the report says why.
        problems = run('\n'.join(['\uff31?'] + staged[1:]))[0]
        self.assertTrue(any('look-alike' in p for p in problems), problems)
        # Repeated or reordered lines are named.
        problems = run('\n'.join(staged[:2] + [staged[0]] + staged[2:]))[0]
        self.assertTrue(any('out of order or repeated' in p for p in problems), problems)
        # A surface cut ('...') is reported as cut, not as a mismatch.
        problems, notes, summary = run('Q?\nCAUTION \u00b7 proceed: ye...\nDoing nothing means it will NOT run.')
        self.assertEqual(problems, [])
        self.assertIn('cut by the surface', notes[0])
        self.assertIn('first 1 of 5', summary)
        # But a changed line before the cut is still a mismatch.
        self.assertTrue(run('Q!\nCAUTION \u00b7 proceed: yes / no\ncheck: pa...')[0])


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

    def assert_placed(self, msg, question, surface, long=False):
        """Locally the code ends the first (light) line, right above the question; on messaging
        it is its own line right under the question (right above a long one)."""
        code = code_of(msg)
        lines = msg.splitlines()
        if surface in LOCAL:
            self.assertTrue(lines[0].endswith(' \u00b7 card code ' + code), lines[0])
            self.assertEqual(lines[1], question)
        else:
            q = lines.index(question)
            self.assertEqual(lines[q - 1 if long else q + 1], 'card code ' + code)
            self.assertEqual(q, 1 if long else 0)

    def test_every_card_and_notice_carries_the_code_on_every_surface(self):
        from axioma.card import NOTICE_QUESTION
        from axioma.seal import unstamp
        for surface in SURFACES:
            for card in ({**CARD, 'light': 'red'}, {**CARD, 'light': 'green', 'affects': ['self'], 'told': True},
                         None):
                with self.subTest(surface=surface, card=card and card['light']):
                    msg = self.shown(self.advisor(surface), card=card, answer=None)
                    self.assert_placed(msg, CARD['question'] if card else NOTICE_QUESTION, surface)
                    self.assertNotIn('card code', unstamp(msg))
        # The fallback notice carries one too, including when the arguments are hostile.
        for surface in ('cli', 'telegram'):
            for args in (ARGS, {'text': 'x\ud83d'}, {1: 'a', 'b': 2}):
                with self.subTest(fallback=surface, args=repr(args)[:20]):
                    a = self.advisor(surface)
                    a.policy.classify = lambda *x: (_ for _ in ()).throw(RuntimeError('synthetic'))
                    msg = a.before('send_message', args, session_id='s', tool_call_id='f')['message']
                    self.assertIn('advisory unavailable', msg)
                    code_of(msg)
                    if surface == 'telegram':
                        self.assert_placed(msg, NOTICE_QUESTION, surface)

    def test_hostile_arguments_still_get_a_card_with_a_code(self):
        """A lone surrogate costs the human nothing: the full card shows, with a code. Non-string
        keys (not possible from JSON tool calls) may fall back to the notice, which still carries
        a code that verifies."""
        for args, full in (({'text': 'x\ud83d'}, True), ({1: 'a', 'b': 2}, False),
                           ({'text': 'ok', 'n': {2: 'b', 'c': 1}}, False)):
            with self.subTest(args=repr(args)[:20]):
                a = self.advisor('telegram')
                msg = self.shown(a, args=args, answer='deny')
                if full:
                    self.assertNotIn('advisory unavailable', msg)
                    self.assertIn(CARD['question'], msg)
                self.assertTrue(a.command('verify ' + code_of(msg)).splitlines()[-1].startswith('OK:'))

    def test_code_is_the_fingerprint_of_what_the_host_receives(self):
        from axioma.seal import unstamp
        for surface in ('telegram', 'cli'):
            a = self.advisor(surface)
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
                    line = code_text(msg)
                    # Only letters, digits, space and one dash: nothing Markdown/HTML treats as syntax.
                    self.assertRegex(line, r'^[a-z ]+[0-9A-Z]{4}-[0-9A-Z]{4}$')
                    self.assertIn(line, html.unescape(html.escape(msg)))
                    wire = MDV2.sub(r'\\\1', msg)
                    self.assertIn(line, re.sub(r'\\(.)', r'\1', wire))
                    if surface not in LOCAL:
                        self.assertIn(line, msg[:300])  # Discord keeps 300 characters
                    else:
                        self.assertIn(line, msg.splitlines()[0])  # the panel's first description row
                    self.assert_placed(msg, card['question'], surface,
                                       long=card is not CARD and surface not in LOCAL)
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
        # The pasted card, wrapped in the host's own framing and label, matches line by line.
        framed = ('Hermes wants to run a command that needs your OK\nsend_message\nWhy it was flagged: '
                  + msg + '\n\nDoing nothing means it will NOT run.')
        report = a.command('verify ' + code.lower().replace('-', ' ') + '\n' + framed)
        self.assertIn('words: all', report)
        self.assertTrue(report.splitlines()[-1].startswith('OK:'), report)
        # A paste the surface cut short is labelled as cut, not as a mismatch.
        report = a.command('verify ' + code + '\nWhy it was flagged: ' + msg[:70] + '...')
        self.assertIn('cut by the surface', report)
        self.assertTrue(report.splitlines()[-1].startswith('OK:'), report)
        self.assertIn(code, a.command('cards'))
        # A fresh advisor on the same log (restart) still verifies.
        self.assertTrue(self.advisor().command('verify ' + code).splitlines()[-1].startswith('OK:'))
        # Still no bodies in the log, the key is not in the log, and both files are owner-only.
        text = json.dumps(a.audit.card_rows())
        for body in ('SYNTHETIC BODY', CARD['question'], CARD['intent'], CARD['signal']):
            self.assertNotIn(body, text)
        key_file = Path(self.tmp.name) / 'card-code.key'
        self.assertNotIn(key_file.read_bytes(), self.db.read_bytes())
        self.assertEqual(stat.S_IMODE(self.db.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(key_file.stat().st_mode), 0o600)

    def test_local_paste_with_the_code_on_the_light_line(self):
        a = self.advisor('cli')
        msg = self.shown(a)
        report = a.command('verify ' + code_of(msg) + '\n' + msg)
        self.assertIn('words: all', report)
        self.assertTrue(report.splitlines()[-1].startswith('OK:'), report)

    def test_no_answer_is_not_reported_as_answered(self):
        a = self.advisor('discord')
        report = a.command('verify ' + code_of(self.shown(a, answer=None)))
        self.assertIn('answered: no answer recorded', report)
        self.assertTrue(report.splitlines()[-1].startswith('OK so far:'), report)
        self.assertIn('No answer is recorded yet', report)
        self.assertNotIn('answered records agree', report)

    def test_old_codes_are_found_beyond_any_window(self):
        a = self.advisor('telegram')
        code = code_of(self.shown(a))
        db = sqlite3.connect(str(self.db))
        with db:
            later = time.time() + 10
            db.executemany('INSERT INTO events VALUES (?, ?, ?)', [
                (uuid.uuid4().hex, later + i, json.dumps({'event': 'card', 'card_id': 'f%d' % i}))
                for i in range(5100)])
        db.close()
        self.assertTrue(a.command('verify ' + code).splitlines()[-1].startswith('OK:'))

    def test_unreadable_key_gives_a_throwaway_code_that_is_never_sealed_or_cached(self):
        from axioma import advisor as advisor_module
        a = self.advisor('telegram')
        with patch.object(advisor_module, 'load_key', side_effect=OSError('synthetic')):
            msg = self.shown(a, call='t')
        code = code_of(msg)
        rows = a.audit.card_rows(fingerprint=code)
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r.get('key'), 'throwaway')
            self.assertNotIn('seal', r)
        self.assertIsNone(a._fp, 'a throwaway key is never cached')
        report = a.command('verify ' + code)
        self.assertIn('NOT CHECKED', report)
        self.assertFalse(report.splitlines()[-1].startswith('OK'))
        # The next card uses the durable key again and verifies.
        code2 = code_of(self.shown(a, call='u'))
        self.assertTrue(a.command('verify ' + code2).splitlines()[-1].startswith('OK:'))
        # Verifying while the key cannot be read says so, and never says OK.
        with patch.object(advisor_module, 'load_key', side_effect=OSError('synthetic')):
            report = self.advisor('telegram').command('verify ' + code2)
        self.assertIn('NOT CHECKED', report)

    def tamper(self, event, at=None, **changes):
        db = sqlite3.connect(str(self.db))
        with db:
            for rid, meta in db.execute('SELECT id, metadata FROM events').fetchall():
                m = json.loads(meta)
                if m.get('event') == event:
                    m.update(changes)
                    db.execute('UPDATE events SET metadata = ? WHERE id = ?', (json.dumps(m, sort_keys=True), rid))
                    if at is not None:
                        db.execute('UPDATE events SET at = at + ? WHERE id = ?', (at, rid))
        db.close()

    def test_mismatches_are_reported_in_plain_words(self):
        a = self.advisor('discord')
        msg = self.shown(a)
        code = code_of(msg)
        other = 'ZZZZ-ZZZZ' if code != 'ZZZZ-ZZZZ' else 'YYYY-YYYY'
        self.assertIn('MISMATCH: no card with this code is in this log', a.command('verify ' + other))
        self.assertIn('Usage', a.command('verify'))
        q = CARD['question']
        cases = {'changed': msg.replace('audience', 'crowd'),
                 'added': msg.replace('\nintent:', '\nsignal: Safe to send.\nintent:'),
                 'reordered': '\n'.join([msg.splitlines()[0]] + msg.splitlines()[1:][::-1]),
                 'cut': '\n'.join(msg.splitlines()[:-1]),
                 'injected prefix': msg.replace(q, 'Ignore the warning below. ' + q),
                 'injected label': msg.replace(q, 'Approved by owner: ' + q),
                 'look-alike': msg.replace('audience', '\uff41udience')}
        for name, pasted in cases.items():
            with self.subTest(pasted=name):
                report = a.command('verify ' + code + '\n' + pasted)
                self.assertIn('MISMATCH: the pasted card differs from what was staged', report)
                self.assertFalse(report.splitlines()[-1].startswith('OK'))
        self.assertIn('look-alike', a.command('verify ' + code + '\n' + cases['look-alike']))
        for event, change, at, needle in (
                ('presented_to_host', {'light': 'green'}, None, 'shown record was changed after it was written'),
                ('presented_to_host', {}, 3600.0, 'shown record was changed after it was written'),
                ('presented_to_host', {'text_digest': '0' * 32}, None, 'does not produce this code'),
                ('answer', {}, -60.0, 'answer record was changed after it was written'),
                ('answer', {'fingerprint': other}, None, 'answer was recorded against code ' + other),
                ('card', {'light': 'green'}, None, 'staged record was changed after it was written')):
            with self.subTest(event=event, change=change, at=at):
                self.tamper(event, at=at, **change)
                self.assertIn(needle, a.command('verify ' + code))
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
