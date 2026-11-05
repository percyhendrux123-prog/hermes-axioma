"""Inline signal color inside the agent's normal reply (Axiōma Signal Spec v0.1, sections 2-5).

Synthetic text only. No model, network or client action.
"""
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PERCY = ('I can do that, but shipping [signal:stop;why=no_eval]without an eval or a test[/signal] '
         'means the [signal:caution]merge into Hermes[/signal] lands under your name. '
         'Do you want me to run the eval first?')
ESC = '\x1b'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def signal(self, env=None, **config):
        from axioma.audit import Audit
        from axioma.signal import Signal
        return Signal(Audit(Path(self.tmp.name) / 'audit.sqlite3'), env=env or {}, **config)

    def assertNoTags(self, text):
        self.assertIsNotNone(text)
        self.assertNotRegex(text, r'(?i)\[\s*/?\s*(signal|whisper)\b')


class TerminalTests(Base):
    def test_untagged_reply_is_left_to_the_host(self):
        s = self.signal()
        self.assertIsNone(s.transform('Plain **reply** with [brackets] and $5.', session_id='a', platform='cli'))
        self.assertEqual(s.audit.rows(), [])

    def test_percy_example_night_truecolor_plus_style_plus_word(self):
        out = self.signal().transform(PERCY, session_id='a', platform='cli')
        self.assertNoTags(out)
        stop = out.index('without an eval or a test')
        caution = out.index('merge into Hermes')
        self.assertIn(ESC + '[38;2;255;69;58m', out[:stop])          # night stop #FF453A
        self.assertIn(ESC + '[1;4m', out[:stop])                     # second cue: bold + underline
        self.assertIn('without an eval or a test' + ESC + '[22;24m (stop)' + ESC + '[39m', out)
        self.assertIn(ESC + '[38;2;255;204;0m', out[stop:caution])    # night caution #FFCC00
        self.assertIn('merge into Hermes' + ESC + '[24m (caution)', out)
        self.assertNotIn(ESC + '[0m', out, 'never wipe the user styling with a full reset')
        self.assertTrue(out.endswith('Do you want me to run the eval first?'))

    def test_day_palette(self):
        out = self.signal(theme='light').transform(PERCY, session_id='a', platform='tui')
        self.assertIn(ESC + '[38;2;215;0;21m', out)    # #D70015
        self.assertIn(ESC + '[38;2;166;107;0m', out)   # #A66B00

    def test_no_color_keeps_style_and_words(self):
        out = self.signal(env={'NO_COLOR': '1'}).transform(PERCY, session_id='a', platform='cli')
        self.assertNotIn('38;2;', out)
        self.assertIn(ESC + '[1;4m', out)
        self.assertIn('(stop)', out)

    def test_colorblind_safe_palettes(self):
        night = self.signal(palette='cvd').transform(PERCY, session_id='a', platform='cli')
        self.assertIn('38;2;232;96;60m', night)    # #E8603C
        self.assertIn('38;2;240;228;66m', night)   # #F0E442
        day = self.signal(palette='cvd', theme='light').transform(PERCY, session_id='b', platform='cli')
        self.assertIn('38;2;202;22;58m', day)      # #CA163A
        self.assertIn('38;2;104;75;8m', day)       # #684B08
        none = self.signal(palette='none').transform(PERCY, session_id='c', platform='cli')
        self.assertNotIn('38;2;', none)
        self.assertIn('(caution)', none)

    def test_span_cannot_carry_its_own_escape_codes(self):
        out = self.signal().transform('[signal:stop]a\x1b[0mb\x07c[/signal]?', session_id='a', platform='cli')
        self.assertIn('abc' + ESC + '[22;24m (stop)', out)
        self.assertEqual(out.count(ESC), 4, 'only the codes the plugin set')

    def test_aliases_and_intent(self):
        out = self.signal().transform('[signal:white]Ship the demo[/signal]; [signal:RED]skip tests[/signal]?',
                                      session_id='a', platform='cli')
        self.assertIn(ESC + '[38;2;240;240;238m' + ESC + '[1m' + 'Ship the demo', out)
        self.assertNotIn('(intent)', out)
        self.assertIn('skip tests' + ESC + '[22;24m (stop)', out)


class DesktopTests(Base):
    def test_katex_color_with_word_outside_math(self):
        out = self.signal().transform(PERCY, session_id='a', platform='desktop')
        self.assertNoTags(out)
        self.assertIn(r'$\color{#FF453A}{\underline{\textsf{\textbf{without an eval or a test}}}}$ (stop)', out)
        self.assertIn(r'$\color{#FFCC00}{\underline{\textsf{merge into Hermes}}}$ (caution)', out)

    def test_katex_escaping(self):
        span = r'pay $5 {now} \ 100% #1 & a_b ^ ~'
        out = self.signal().transform('[signal:caution]' + span + '[/signal]?', session_id='a', platform='desktop')
        inner = re.search(r'\\textsf\{(.*)\}\}\}\$ \(caution\)', out).group(1)
        self.assertEqual(inner, r'pay \textdollar{}5 \{now\} \textbackslash{} 100\% \#1 \& a\_b \textasciicircum{} \textasciitilde{}')
        self.assertEqual(out.count('$'), 2, 'only the two math delimiters: a literal $ inside breaks Desktop')

    def test_markdown_inside_span_falls_back_to_bold_and_word(self):
        out = self.signal().transform('Run [signal:caution]`rm -rf build`[/signal] now?', session_id='a',
                                      platform='desktop')
        self.assertEqual(out, 'Run **`rm -rf build`** (caution) now?')

    def test_light_theme_on_desktop(self):
        out = self.signal(theme='light').transform(PERCY, session_id='a', platform='desktop')
        self.assertIn(r'\color{#D70015}', out)


class PlainSurfaceTests(Base):
    def test_telegram_bold_plus_word_no_emoji(self):
        out = self.signal().transform(PERCY, session_id='a', platform='telegram')
        self.assertIn('**without an eval or a test** (stop)', out)
        self.assertIn('**merge into Hermes** (caution)', out)
        self.assertNotIn(ESC, out)
        self.assertTrue(out.isascii(), 'no emoji or symbols in place of words')

    def test_trailing_backslash_never_breaks_bold(self):
        out = self.signal().transform('Path [signal:caution]C:\\temp\\[/signal] here?', session_id='a',
                                      platform='telegram')
        self.assertEqual(out, 'Path C:\\temp\\ (caution) here?')

    def test_sms_words_only(self):
        out = self.signal().transform(PERCY, session_id='a', platform='sms')
        self.assertIn('without an eval or a test (stop)', out)
        self.assertNotIn('**', out)

    def test_whisper_word_on_messaging_and_off_switch(self):
        text = 'About [whisper:unverified_figure]4,200 users[/whisper].'
        self.assertEqual(self.signal().transform(text, session_id='a', platform='telegram'),
                         'About 4,200 users (second look).')
        self.assertEqual(self.signal(messaging_marker=False).transform(text, session_id='b', platform='telegram'),
                         'About 4,200 users.')


class NeverLeakTests(Base):
    CASES = {
        'unclosed': ('A [signal:stop]B', 'A B'),
        'empty': ('A [signal:stop][/signal]B', 'A B'),
        'stray close': ('A [/signal] B', 'A  B'),
        'unknown level': ('[signal:purple]X[/signal]', 'X'),
        'mismatched close': ('[signal:stop]X[/whisper]', 'X'),
        'nested': ('[signal:stop]X [signal:go]Y[/signal] Z[/signal]', None),
        'across lines': ('[signal:stop]X\nY[/signal]', 'X\nY'),
        'upper case kind': ('[SIGNAL:STOP]X[/SIGNAL]', None),
        'spaced': ('[ signal : stop ]X[ /signal ]', None),
        'truncated at end': ('done [signal:sto', 'done '),
        'unknown whisper reason': ('[whisper:hunch]X[/whisper]', 'X'),
    }

    def test_malformed_tags_strip_cleanly_on_every_surface(self):
        for surface in ('cli', 'desktop', 'telegram', 'sms', ''):
            for name, (text, plain) in self.CASES.items():
                with self.subTest(surface=surface, case=name):
                    out = self.signal().transform(text, session_id=name + surface, platform=surface)
                    self.assertNoTags(out)
                    if plain is not None:
                        self.assertEqual(out, plain)

    def test_lookalikes_without_a_value_are_not_tags(self):
        s = self.signal()
        for text in ('array[signal] = 1', 'see [signal:]', 'x = y[whisper]'):
            self.assertIsNone(s.transform(text, session_id='s', platform='cli'), text)

    def test_tag_only_reply_is_a_short_placeholder(self):
        for text in ('[signal:stop][/signal]', '[signal:caution]   [/signal]', '[/whisper]'):
            self.assertEqual(self.signal().transform(text, session_id='s', platform='cli'), '(empty reply)')

    def test_tags_inside_code_keep_the_word_and_never_markup(self):
        # A229 pass 10: tags are parsed everywhere so a wrong code guess can't leak one; inside
        # code a span is plain text plus its word, with no markup to break the code.
        text = 'Use `[signal:stop]x[/signal]` like this:\n```\n[signal:go]y[/signal]\n```\n[signal:caution]real[/signal]?'
        out = self.signal().transform(text, session_id='s', platform='telegram')
        self.assertIn('`x (stop)`', out)
        self.assertIn('\ny\n', out)
        self.assertIn('**real** (caution)?', out)
        desk = self.signal().transform('```\n[signal:stop;why=x]rm -rf build[/signal]\n```', session_id='d',
                                       platform='desktop')
        self.assertEqual(desk, '```\nrm -rf build (stop)\n```')


class IntegrityTests(Base):
    def test_go_without_a_check_renders_plain_and_is_logged(self):
        s = self.signal()
        out = s.transform('Suite [signal:go]passed 41 of 41[/signal].', session_id='s', platform='telegram')
        self.assertEqual(out, 'Suite passed 41 of 41.')
        row = [r for r in s.audit.rows() if r.get('level') == 'go'][0]
        self.assertFalse(row['shown'])
        self.assertEqual(row['reason'], 'no_check')

    def test_go_only_from_a_check_observed_in_this_session(self):
        s = self.signal()
        s.observe(tool_name='terminal', tool_call_id='call_ok', session_id='s', turn_id='t1', status='ok')
        s.observe(tool_name='run_tests', tool_call_id='call_bad', session_id='s', turn_id='t1', status='error')
        s.observe(tool_name='axioma_card', tool_call_id='call_card', session_id='s', turn_id='t1', status='ok')
        def go(check, session='s', turn='t1'):
            return s.transform('[signal:go;check=%s]passed[/signal]' % check, session_id=session,
                               platform='telegram', turn_id=turn)
        self.assertEqual(go('call_ok'), '**passed** (go)')
        self.assertEqual(go('terminal'), '**passed** (go)', 'tool name of a passing call this turn')
        self.assertEqual(go('call_bad'), 'passed')
        self.assertEqual(go('run_tests'), 'passed')
        self.assertEqual(go('axioma_card'), 'passed', 'staging a card is not a check')
        self.assertEqual(go('call_ok', session='other'), 'passed')
        self.assertEqual(go('terminal', turn='t2'), 'passed', 'a tool name only counts in its own turn')
        self.assertEqual(go('call_ok', turn='t2'), '**passed** (go)', 'a call id counts for the session')
        self.assertEqual(go('mcp__terminal'), '**passed** (go)', 'provider-prefixed name of a built-in tool')
        s.observe(tool_name='mcp__github__run_ci', tool_call_id='call_mcp', session_id='s', turn_id='t1', status='ok')
        self.assertEqual(go('mcp__github__run_ci'), '**passed** (go)')
        self.assertEqual(go('run_ci'), 'passed', 'a real MCP tool keeps its server segment')
        s.finalize(session_id='s')
        self.assertEqual(go('call_ok'), 'passed')

    def test_every_flag_logged_without_bodies(self):
        s = self.signal()
        s.transform(PERCY + ' [whisper:assumption]secret figure 99[/whisper]', session_id='s', platform='desktop')
        rows = s.audit.rows()
        levels = sorted(r['level'] for r in rows if r['event'] == 'signal')
        self.assertEqual(levels, ['caution', 'stop', 'whisper'])
        for r in rows:
            if r['event'] != 'signal':
                continue
            self.assertEqual(len(r['span_id']), 32)
            self.assertEqual(len(r['span_hash']), 64)
            self.assertEqual(r['surface'], 'desktop')
            self.assertTrue(r['shown'])
        self.assertEqual([r['reason'] for r in rows if r.get('level') == 'stop'], ['no_eval'])
        self.assertNotIn('eval or a test', str(rows))
        self.assertNotIn('secret figure', str(rows))
        self.assertIn('stop', s.listing())
        self.assertNotIn('eval or a test', s.listing())

    def test_whisper_once_per_session(self):
        s = self.signal()
        text = '[whisper:low_confidence]maybe[/whisper]'
        self.assertIn('38;2;', s.transform(text, session_id='s', platform='cli'))
        self.assertEqual(s.transform(text, session_id='s', platform='cli'), 'maybe')
        self.assertIn('38;2;', s.transform(text, session_id='other', platform='cli'))

    def test_logging_failure_hides_no_stop(self):
        s = self.signal()
        s.audit.record = lambda **kw: (_ for _ in ()).throw(OSError('disk full'))
        out = s.transform(PERCY, session_id='s', platform='telegram')
        self.assertIn('(stop)', out, 'a failed log must not hide a stop from the human')


class BudgetTests(Base):
    def test_cap_keeps_the_most_severe_and_logs_the_rest(self):
        s = self.signal()
        text = ('[signal:caution]c1[/signal] [signal:caution]c2[/signal] [signal:caution]c3[/signal] '
                '[signal:stop]s1[/signal] [signal:caution]c4[/signal]?')
        out = s.transform(text, session_id='s', platform='sms')
        self.assertEqual(out, 'c1 (caution) c2 (caution) c3 s1 (stop) c4?')
        dropped = [r for r in s.audit.rows() if r.get('reason') == 'over_budget']
        self.assertEqual(len(dropped), 2)
        self.assertTrue(all(not r['shown'] for r in dropped))

    def test_whisper_cap_and_span_length(self):
        s = self.signal()
        text = ' '.join('[whisper:assumption]w%d[/whisper]' % i for i in range(3))
        self.assertEqual(s.transform(text, session_id='s', platform='sms'), 'w0 (second look) w1 (second look) w2')
        long = ' '.join(['word'] * 17)
        out = s.transform('[signal:stop]%s[/signal]?' % long, session_id='s', platform='sms')
        self.assertEqual(out, long + '?')
        self.assertTrue(any(r.get('reason') == 'too_long' for r in s.audit.rows()))

    def test_budget_is_configurable_and_bad_values_fall_back(self):
        s = self.signal(budget={'max_spans': 1})
        out = s.transform('[signal:caution]a[/signal] [signal:caution]b[/signal]?', session_id='s', platform='sms')
        self.assertEqual(out, 'a (caution) b?')
        s = self.signal(budget='lots', theme=7, palette='neon', words=None)
        self.assertIn('(caution)', s.transform('[signal:caution]a[/signal]?', session_id='t', platform='sms'))


class WordsSettingTests(Base):
    def test_words_plain_only_drops_words_on_rich_surfaces(self):
        s = self.signal(words='plain_only')
        out = s.transform(PERCY, session_id='s', platform='cli')
        self.assertNotIn('(stop)', out)
        self.assertIn(ESC + '[1;4m', out)
        self.assertIn('(stop)', s.transform(PERCY, session_id='t', platform='telegram'))


class Pass9Findings(Base):
    """Regressions for docs/review/pass-9.txt (fresh Claude reviewer, A229)."""
    SURFACES = ('cli', 'desktop', 'telegram', 'sms')

    def test_p2_1_fence_detection_follows_commonmark(self):
        for text in ('```npm test``` passed.\nThen [signal:stop;why=x]do not deploy[/signal] today?',
                     '~~~\n```\n~~~\nProse [signal:caution]merge[/signal] now?',
                     '````\n```\n````\nAfter [signal:caution]merge[/signal] now?'):
            for surface in self.SURFACES:
                with self.subTest(text=text, surface=surface):
                    self.assertNoTags(self.signal().transform(text, session_id='s', platform=surface))
        out = self.signal().transform('```\n[signal:go]y[/signal]\n```\nok [signal:caution]z[/signal]?',
                                      session_id='s', platform='sms')
        self.assertIn('\ny\n', out, 'inside a real fence: tags removed, no markup')

    def test_p2_1_backtick_runs_must_match_in_length(self):
        for surface in self.SURFACES:
            with self.subTest(surface=surface):
                out = self.signal().transform('Run `[signal:stop;why=x]rm -rf[/signal]`` more?', session_id='s',
                                              platform=surface)
                self.assertNoTags(out)
        out = self.signal().transform('Use ``a ` [signal:stop]b[/signal]`` here', session_id='s', platform='cli')
        self.assertEqual(out, 'Use ``a ` b (stop)`` here', 'inside code: the word, never ANSI')

    def test_p2_2_long_params_and_cut_off_closers_never_leak(self):
        long = '[signal:stop;why=' + 'w' * 64 + ';check=' + 'c' * 64 + ';id=' + 'i' * 64 + ']phrase[/signal]?'
        self.assertEqual(self.signal().transform(long, session_id='s', platform='sms'), 'phrase (stop)?')
        for surface in self.SURFACES:
            with self.subTest(surface=surface):
                out = self.signal().transform('Do not [signal:stop;why=x]delete it[/signal', session_id='s',
                                              platform=surface)
                self.assertEqual(out, 'Do not delete it')
                self.assertEqual(self.signal().transform('end [/whisper', session_id='t', platform=surface), 'end ')

    def test_p2_3_desktop_falls_back_when_the_context_would_break_math(self):
        cases = {
            'dollar before': 'It costs $[whisper:unverified_figure]4,200[/whisper] a month.',
            'cjk': '请 [signal:stop;why=x]不要删除[/signal] 好吗?',
            'fullwidth': 'Note [signal:caution]a，b[/signal] here?',
            'backslash before': 'C:\\[signal:stop;why=x]Windows[/signal] gone?',
            'lone dollar earlier': 'It costs 5$ and [signal:caution]x[/signal] now?',
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                out = self.signal().transform(text, session_id=name, platform='desktop')
                self.assertNoTags(out)
                self.assertNotIn('\\color', out)
                self.assertRegex(out, r'\((stop|caution|second look)\)')
                self.assertNotIn('\\**', out, 'a backslash before the span must not eat the bold marker')
        s = self.signal(words='plain_only')
        out = s.transform('a [signal:stop;why=x]x[/signal][signal:caution]b[/signal] c?', session_id='p', platform='desktop')
        self.assertNotIn('$$', out)
        out = s.transform('[signal:caution]x[/signal]5 units?', session_id='q', platform='desktop')
        self.assertNotIn('\\color', out)
        ok = self.signal().transform('costs $5 and [signal:caution]x[/signal] then $10?', session_id='r', platform='desktop')
        self.assertIn('$\\color{#FFCC00}', ok, 'ordinary leading currency keeps the color path')

    def test_p3_2_valueless_opener_with_a_closer_is_stripped(self):
        s = self.signal()
        self.assertEqual(s.transform('[signal]x[/signal]', session_id='s', platform='sms'), 'x')
        self.assertEqual(s.transform('[signal:]x[/signal]', session_id='s', platform='sms'), 'x')
        self.assertIsNone(s.transform('array[signal] = 1', session_id='s', platform='sms'))

    def test_p3_3_code_only_tags_are_removed_without_markup(self):
        out = self.signal().transform('Docs: `[signal:stop]x[/signal]` is the syntax.', session_id='s', platform='cli')
        self.assertEqual(out, 'Docs: `x (stop)` is the syntax.')
        self.assertIsNone(self.signal().transform('Docs: `array[signal]` here.', session_id='s', platform='cli'))

    def test_p3_5_whisper_budget_counts_only_new_whispers(self):
        s = self.signal(budget={'max_whispers': 1})
        a = '[whisper:assumption]alpha[/whisper]'
        self.assertEqual(s.transform(a, session_id='s', platform='sms'), 'alpha (second look)')
        out = s.transform(a + ' ' + '[whisper:assumption]beta[/whisper]', session_id='s', platform='sms')
        self.assertEqual(out, 'alpha beta (second look)')


class Pass10Findings(Base):
    """Regressions for docs/review/pass-10.txt (fresh Claude reviewer, A229)."""
    SURFACES = ('cli', 'desktop', 'telegram', 'sms')

    def test_p2_1_list_quote_and_indented_code_never_hide_a_stop(self):
        texts = ('Two options:\n\n- ```bash\n  npm test\n  ```\n\nBut merging [signal:stop;why=no_eval]without a test[/signal] is risky. Proceed?',
                 '> ```\n> code\n> ```\n\nThen [signal:stop;why=x]do not deploy[/signal]?',
                 '1. ```\n   x\n   ```\n2. [signal:caution]merge now[/signal]?')
        for text in texts:
            for surface in self.SURFACES:
                with self.subTest(text=text[:20], surface=surface):
                    out = self.signal().transform(text, session_id='s', platform=surface)
                    self.assertNoTags(out)
                    self.assertRegex(out, r'\((stop|caution)\)')
        out = self.signal().transform('Example:\n\n    [signal:stop]rm -rf x[/signal]\n', session_id='i',
                                      platform='desktop')
        self.assertEqual(out, 'Example:\n\n    rm -rf x (stop)\n', 'indented code: word only, no math')

    def test_p2_2_any_value_length_is_a_tag(self):
        for n in (395, 2000):
            text = 'Ship it? [signal:stop;why=' + 'a' * n + ']not tested[/signal] ok'
            for surface in self.SURFACES:
                with self.subTest(n=n, surface=surface):
                    out = self.signal().transform(text, session_id='s', platform=surface)
                    self.assertNoTags(out)
                    self.assertIn('(stop)', out)

    def test_p2_3_agent_math_in_the_reply_disables_the_math_path(self):
        for text in ('see \\([signal:caution]y[/signal]\\)?', 'where \\(x = [signal:caution]y[/signal]\\) holds?',
                     '$$\n[signal:caution]x[/signal]\n$$', '\\[\n[signal:caution]x[/signal]\n\\]',
                     'Let $x$ be [signal:caution]y[/signal]?'):
            with self.subTest(text=text):
                out = self.signal().transform(text, session_id='s', platform='desktop')
                self.assertNotIn('\\color', out)
                self.assertNotIn('**', out, 'inside agent math, markdown bold would print literally')
                self.assertIn('(caution)', out)

    def test_p2_4_control_and_separator_characters_never_reach_desktop_math(self):
        for ch in ('\x07', '\x7f', '\x85', '\u2028', '\u202e'):
            with self.subTest(ch=repr(ch)):
                out = self.signal().transform('a [signal:caution]x' + ch + 'y[/signal] ok?', session_id='s',
                                              platform='desktop')
                self.assertNotIn(ch, out)
                self.assertIn('(caution)', out)

    def test_p3_bidi_controls_cannot_reorder_the_word_in_a_terminal(self):
        out = self.signal().transform('[signal:stop]a\u202eb\u2066c[/signal]?', session_id='s', platform='cli')
        self.assertNotIn('\u202e', out)
        self.assertNotIn('\u2066', out)

    def test_p3_markdown_adjacency_never_makes_four_asterisks(self):
        for text in ('**bold**[signal:caution]x[/signal]?', '[signal:intent]i[/signal][signal:caution]x[/signal]?',
                     '[signal:caution]x[/signal]**bold**?'):
            for surface in ('telegram', 'desktop'):
                with self.subTest(text=text, surface=surface):
                    self.assertNotIn('****', self.signal().transform(text, session_id='s', platform=surface))

    def test_p3_repeated_whisper_is_logged_not_shown(self):
        s = self.signal()
        s.transform('[whisper:assumption]alpha[/whisper]', session_id='s', platform='sms')
        s.transform('[whisper:assumption]alpha[/whisper]', session_id='s', platform='sms')
        rows = [r for r in s.audit.rows() if r.get('level') == 'whisper']
        self.assertEqual(sorted(r['reason'] for r in rows), ['assumption', 'repeat'])

    def test_p3_zero_width_characters_inside_a_tag_do_not_hide_it(self):
        out = self.signal().transform('[signal\u200b:stop]a[/signal]?', session_id='s', platform='sms')
        self.assertEqual(out, 'a (stop)?')


class Pass11Findings(Base):
    """Regressions for docs/review/pass-11.txt (fresh Claude reviewer, A229)."""

    def test_p2_1_a_dollar_inside_any_span_disables_the_math_path(self):
        for text in ('Export [signal:caution]$TOKEN to `env`[/signal], then [signal:stop]deploy to prod[/signal] now?',
                     'Then [signal:go;check=none]set $PATH[/signal] then [signal:stop]wipe prod[/signal]?',
                     '[signal:caution]a[/signal] [signal:caution]b[/signal] [signal:caution]c[/signal] '
                     '[signal:caution]costs $X[/signal] then [signal:stop]halt[/signal]?'):
            with self.subTest(text=text[:30]):
                out = self.signal().transform(text, session_id='s', platform='desktop')
                self.assertNotIn('\\color', out)
                self.assertIn('(stop)', out)
        ok = self.signal().transform('It [signal:stop;why=x]charges $49 on renewal[/signal]?', session_id='c',
                                     platform='desktop')
        self.assertIn('\\color', ok, 'a currency amount in a span keeps the color path')

    def test_p2_2_only_characters_katex_renders_take_the_math_path(self):
        for span in ('staging \u2260 production', '\u2211 of 3 invoices', 'e\u0301clair', 'price \u00a5100',
                     'wow \u203c', '\u03b1 release', 'deploy \U0001f680'):
            with self.subTest(span=span):
                out = self.signal().transform('Note [signal:stop;why=x]' + span + '[/signal] here?', session_id='s',
                                              platform='desktop')
                self.assertNotIn('\\color', out)
                self.assertIn('(stop)', out)
        for span in ('Axi\u014dma fa\u00e7ade \u2014 \u201cquoted\u201d \u2026 \u20ac5 \u2192 next', 'na\u00efve caf\u00e9'):
            with self.subTest(span=span):
                out = self.signal().transform('Note [signal:stop;why=x]' + span + '[/signal] here?', session_id='t',
                                              platform='desktop')
                self.assertIn('\\color', out)

    def test_p3_1_invisible_characters_inside_a_tag_keyword(self):
        for tag in ('[sig\u200bnal:stop]', '[sig\u00adnal:stop]', '[\u2060signal:stop]', '[signal:st\u200bop]'):
            with self.subTest(tag=repr(tag)):
                out = self.signal().transform('x ' + tag + 'a[/sig\u200bnal] y?', session_id='s', platform='sms')
                self.assertNoTags(out.replace('\u200b', '').replace('\u00ad', '').replace('\u2060', ''))
                self.assertIn('a (stop)', out)

    def test_p3_2_a_keyword_cut_off_at_the_end_of_the_reply(self):
        for text, want in (('ok [signal', 'ok '), ('ok [/sig', 'ok '), ('ok [whisp', 'ok '), ('done [/signal]', 'done ')):
            with self.subTest(text=text):
                self.assertEqual(self.signal().transform(text, session_id='s', platform='cli'), want)
        self.assertIsNone(self.signal().transform('see [s', session_id='s', platform='cli'), 'too short to be a tag')


class Pass12Findings(Base):
    """Regressions for docs/review/pass-12.txt (fresh Claude Code reviewer, A229)."""

    def test_p2_1_a_tag_cut_off_mid_reply_is_removed_even_when_it_is_the_only_tag(self):
        for text in ('Plan:\n- migrate now [signal:stop;why=no_backup\n- then deploy', 'Plan [whisper:assumption\nnext line',
                     'a [/signal\nb', 'x [ signal : \n more'):
            for surface in ('cli', 'desktop', 'telegram', 'plain'):
                with self.subTest(text=text[:20], surface=surface):
                    self.assertNoTags(self.signal().transform(text, session_id='s', platform=surface))

    def test_p2_2_a_pipe_in_a_span_never_takes_the_math_path(self):
        for span in ('x|y', 'x\\|y'):
            text = '| a | b |\n|---|---|\n| one | [signal:stop]' + span + '[/signal] |'
            with self.subTest(span=span):
                out = self.signal().transform(text, session_id='s', platform='desktop')
                self.assertNotIn('\\color', out)
                self.assertNotIn('**', out)
                self.assertIn('(stop)', out)
        out = self.signal().transform('| a |\n|---|\n| [signal:stop]x|y[/signal] |', session_id='t', platform='telegram')
        self.assertNotIn('**', out)

    def test_p2_3_an_escaped_backslash_before_a_dollar_is_agent_math(self):
        for text in ('Empty C:\\\\$Recycle.Bin first, then [signal:stop]drop the table[/signal] ok?',
                     'Use \\\\$ then [signal:caution]x[/signal]'):
            with self.subTest(text=text[:20]):
                out = self.signal().transform(text, session_id='s', platform='desktop')
                self.assertNotIn('\\color', out)
        ok = self.signal().transform('Price \\$5 then [signal:stop;why=x]drop the table[/signal]?', session_id='c',
                                     platform='desktop')
        self.assertIn('\\color', ok, 'an escaped dollar (odd backslashes) is not math')

    def test_p3_more_invisible_characters_inside_a_tag(self):
        for ch in ('\u2061', '\u2063', '\u180e', '\u034f', '\ufe0f'):
            with self.subTest(ch=hex(ord(ch))):
                out = self.signal().transform('x [signal' + ch + ':stop]a[/signal] y?', session_id='s', platform='sms')
                self.assertNoTags(out.replace(ch, ''))
                self.assertIn('a (stop)', out)

    def test_p3_lookalike_with_a_value_inside_code_is_left_alone(self):
        text = '```python\nchunk = samples[signal:end]\n```\nThen [signal:stop]wipe prod[/signal]?'
        out = self.signal().transform(text, session_id='s', platform='cli')
        self.assertIn('chunk = samples[signal:end]', out)

    def test_p3_terminal_resets_only_what_it_set(self):
        out = self.signal().transform('a [signal:caution]b[/signal] c [signal:go;check=nope]d[/signal]?',
                                      session_id='s', platform='cli')
        self.assertIn('b' + ESC + '[24m (caution)', out)
        self.assertNotIn('22;23;24', out)


class Pass13Findings(Base):
    """Regressions for docs/review/pass-13.txt (fresh Claude Code reviewer, A229)."""

    def test_p2_1_every_math_form_desktop_normalizes_disables_the_math_path(self):
        # @assistant-ui/react-streamdown normalizeMathDelimiters: \\{1,2}( ), \\{1,2}[ ], [/math], [/inline].
        for text in ('[/inline]see [signal:stop;why=x]halt now[/signal] then[/inline] ok?',
                     'Use \\\\(a [signal:stop;why=x]halt now[/signal] b\\\\) ok?',
                     '[/math]\nx [signal:stop;why=x]halt now[/signal] y\n[/math]',
                     '\\\\[a [signal:stop;why=x]halt now[/signal] b\\\\]'):
            with self.subTest(text=text[:20]):
                out = self.signal().transform(text, session_id='s', platform='desktop')
                self.assertNotIn('\\color', out)
                self.assertIn('(stop)', out)

    def test_p3_loose_and_cut_off_tags_never_leak(self):
        for text in ('[signal stop]x[/signal] y?', '[signal=stop]x[/signal] y?', '[signal-stop]x[/signal] y?',
                     '[signal:stop]x[/signal and more] y?', 'a [/sig\nb', 'x [sig\x00nal:stop]a[/signal] y?'):
            for surface in ('cli', 'desktop', 'sms'):
                with self.subTest(text=text[:16], surface=surface):
                    out = self.signal().transform(text, session_id='s', platform=surface)
                    self.assertNoTags((out or '').replace('\x00', ''))
        self.assertIsNone(self.signal().transform('use array[signal-1] here', session_id='s', platform='cli'))


class Pass14Findings(Base):
    """Regressions for docs/review/pass-14.txt (fresh Claude Code reviewer, A229)."""

    def test_p2_1_any_dollar_with_cjk_anywhere_disables_the_math_path(self):
        for text in ('It was $5 and is [signal:caution]rising fast[/signal] \u7ea6 $10 now?',
                     'Budget $5 then [signal:stop;why=cost]do not deploy[/signal]\uff0c\u8d39\u7528 $8?'):
            with self.subTest(text=text[:16]):
                out = self.signal().transform(text, session_id='s', platform='desktop')
                self.assertNotIn('\\color', out)
                self.assertRegex(out, r'\((stop|caution)\)')
        ok = self.signal().transform('It costs $49 and [signal:stop;why=x]renews yearly[/signal]?', session_id='c',
                                     platform='desktop')
        self.assertIn('\\color', ok, 'currency without CJK keeps the color path')

    def test_p3_every_loose_keyword_form_strips_cleanly(self):
        for text in ('[signal_stop]x[/signal] y?', '[signal.stop]x[/signal] y?', '[signal;stop]x[/signal] y?',
                     '[signal|stop]x[/signal] y?', '[signal/stop]x[/signal] y?', '[whisper(assumption)]x[/whisper] y?',
                     '[signal\uff1astop]x[/signal] y?', '[signal\\:stop]x[/signal] y?', '[signal:stop]x[\\/signal] y?'):
            for surface in ('cli', 'telegram', 'sms'):
                with self.subTest(text=text[:16], surface=surface):
                    out = self.signal().transform(text, session_id='s', platform=surface)
                    self.assertNoTags((out or '').replace('\\', ''))
        for text in ('use array[signal_1] here', 'see cfg[whisper.level] now'):
            with self.subTest(text=text):
                self.assertIsNone(self.signal().transform(text, session_id='s', platform='cli'))


class Pass15Findings(Base):
    """Regressions for docs/review/pass-15.txt (fresh Claude Code reviewer, A229)."""

    def test_p2_1_brackets_or_bang_in_a_span_never_take_the_math_path(self):
        for text in ('Careful: [signal:stop]see ![x[/signal] before merging', 'Run [signal:caution]step [2 of 3[/signal]?',
                     'Use [signal:stop]see [x[/signal] then [y] ok', 'A [signal:stop]x] y[/signal] z?'):
            with self.subTest(text=text[:20]):
                out = self.signal().transform(text, session_id='s', platform='desktop')
                self.assertNotIn('\\color', out)
                self.assertRegex(out, r'\((stop|caution)\)')

    def test_p2_2_an_opener_missing_its_bracket_never_swallows_later_tags(self):
        for text in ('Do not [signal stop ship it[/signal] yet.', '[signal x[/whisper] y'):
            for surface in ('cli', 'desktop', 'telegram', 'sms'):
                with self.subTest(text=text[:16], surface=surface):
                    self.assertNoTags(self.signal().transform(text, session_id='s', platform=surface))
        s = self.signal()
        out = s.transform('The [signal:caution merge into Hermes[/signal] lands, but [signal:stop]there is no eval[/signal]. '
                          'Run it first?', session_id='s', platform='sms')
        self.assertNoTags(out)
        self.assertIn('merge into Hermes', out)
        self.assertIn('there is no eval (stop)', out)
        out = self.signal().transform('(see [signal: notes) and [signal:stop]never ship[/signal]', session_id='t',
                                      platform='sms')
        self.assertIn('never ship (stop)', out)

    def test_p2_2_fuzz_no_tag_survives(self):
        import random
        rng = random.Random(15)
        frags = ['[signal:stop]', '[signal:caution]', '[/signal]', '[whisper:assumption]', '[/whisper]', '[signal',
                 '[signal ', '[/sig', '[', ']', 'x', ' ', 'word ', '[signal:', '[whisper', ':stop', 'stop]', '\n',
                 '[signal stop', '[signal=go]', '`', '$', '\\']
        for n in range(4000):
            text = ''.join(rng.choice(frags) for _ in range(rng.randint(1, 12)))
            s = self.signal()
            out = s.transform(text, session_id='f', platform='sms')
            if out is None:
                # A231: None means no exact tag and no cut-off tag in prose (code is never changed).
                self.assertFalse(s.prose_has_tags(s.prepare(text)) or s.cut_off(text), text)
                continue
            # A231: inside code, only exact tags are read; everything else stays as written.
            got = ''.join(piece for code, piece in s.segments(out) if not code)
            # A valueless [signal] / [whisper] with no closer is a documented lookalike (array[signal]).
            got = re.sub(r'(?i)\[\s*(signal|whisper)\s*:?\s*\]', '', got)
            # Contract: no closer and no tag-shaped opener ([signal: [signal= [signal\ [signal <word>)
            # survives. Other punctuation with no closer ([signal_1], [whisper`x]) is a lookalike.
            if re.search(r'(?i)\[\s*\\?/\s*(signal|whisper)\b|\[\s*(signal|whisper)\s*[:=\\]|\[\s*(signal|whisper)\s+\S',
                         got):
                self.fail('leak for %r -> %r' % (text, got))

    def test_p3_cut_off_closer_keeps_the_rest_of_the_line(self):
        out = self.signal().transform('[signal:stop]never deploy[/signal on friday, ask first', session_id='s',
                                      platform='sms')
        self.assertNoTags(out)
        self.assertIn('ask first', out)

    def test_p3_span_length_budget_counts_characters_too(self):
        out = self.signal().transform('[signal:stop;why=x]' + '\u4e0d' * 200 + '[/signal]?', session_id='s', platform='sms')
        self.assertNotIn('(stop)', out)


class Pass16Findings(Base):
    """Regressions for docs/review/pass-16.txt (fresh Claude Code reviewer, A229)."""

    def test_p2_1_a_stray_backtick_turns_the_math_path_off(self):
        for text in ('Type the ` key, then [signal:stop]delete the prod bucket[/signal] only after a backup?',
                     'Use ``x` and [signal:caution]the old page[/signal] now?'):
            with self.subTest(text=text[:16]):
                out = self.signal().transform(text, session_id='s', platform='desktop')
                self.assertNotIn('\\color', out)
                self.assertRegex(out, r'\((stop|caution)\)')
        for text in ('Run `ls` then [signal:stop;why=x]delete the bucket[/signal]?',
                     '```\ncode\n```\nThen [signal:stop;why=x]delete the bucket[/signal]?'):
            with self.subTest(text=text[:16]):
                self.assertIn('\\color', self.signal().transform(text, session_id='c', platform='desktop'))

    def test_p2_2_a_link_touching_the_span_turns_the_math_path_off(self):
        for text in ('See www.example.com/docs\u2014[signal:caution]the old page[/signal] is stale?',
                     'Docs: (www.example.com)[signal:stop]not reviewed[/signal] yet?',
                     'At https://x.io/a\u2014[signal:stop]not reviewed[/signal] yet?',
                     'Mail ops@example.com\u2014[signal:stop]not reviewed[/signal] yet?'):
            with self.subTest(text=text[:16]):
                out = self.signal().transform(text, session_id='s', platform='desktop')
                self.assertNotIn('\\color', out)
                self.assertRegex(out, r'\((stop|caution)\)')

    def test_p3_1_invisible_tag_after_an_unclosed_bracket(self):
        out = self.signal().transform('Note [draft [sig\u200bnal:stop]not reviewed[/signal] ok?', session_id='s',
                                      platform='sms')
        self.assertNoTags(out.replace('\u200b', ''))
        self.assertIn('not reviewed (stop)', out)

    def test_p3_2_parsing_is_linear(self):
        import time
        start = time.monotonic()
        self.signal().transform('[signal] ' * 32000, session_id='s', platform='cli')
        self.signal().transform('`[signal:zz]` ' * 32000, session_id='s', platform='cli')
        self.assertLess(time.monotonic() - start, 5.0)


class Pass17Findings(Base):
    """Regressions for docs/review/pass-17.txt (fresh Claude Code reviewer, A229)."""

    def test_p2_1_a_raw_html_block_turns_the_math_path_off(self):
        for text in ('<details>\n<summary>Plan</summary>\n[signal:caution]this touches billing[/signal]\n</details>',
                     '<div>\n[signal:stop]delete prod[/signal]\n</div>',
                     '<table><tr><td>\n[signal:stop]delete prod[/signal]\n</td></tr></table>',
                     '<!-- note -->\n[signal:stop]delete prod[/signal]?'):
            with self.subTest(text=text[:12]):
                out = self.signal().transform(text, session_id='s', platform='desktop')
                self.assertNotIn('\\color', out)
                self.assertRegex(out, r'\((stop|caution)\)')
        ok = self.signal().transform('Use a <b>bold</b> word and [signal:stop;why=x]delete prod[/signal]?', session_id='c',
                                     platform='desktop')
        self.assertIn('\\color', ok, 'inline HTML mid-line is not an HTML block')

    def test_p3_1_removing_an_inner_tag_never_splices_a_visible_tag(self):
        for text in ('a [sig[/signal]nal:go;check=terminal]tests pass[/signal]', 'see [/[signal:stop]whisper] ok',
                     'x [/sig[whisper:assumption]y[/whisper] z'):
            for surface in ('cli', 'desktop', 'telegram', 'sms'):
                with self.subTest(text=text[:12], surface=surface):
                    out = self.signal().transform(text, session_id='s', platform=surface)
                    self.assertNotRegex(out, r'(?i)\[\s*/?\s*(signal|whisper)\s*[:\]]')
                    self.assertNotRegex(out, r'(?i)\[/sig')

    def test_p3_3_katex_ligatures_take_the_bold_path(self):
        for span in ('git push --force-with-lease', 'a --- b', "it''s"):
            with self.subTest(span=span):
                out = self.signal().transform('Run [signal:caution]' + span + '[/signal] now?', session_id='s',
                                              platform='desktop')
                self.assertNotIn('\\color', out)
                self.assertIn(span + '** (caution)', out)


class Pass18Findings(Base):
    """Regressions for docs/review/pass-18.txt (fresh Claude Code reviewer, A229)."""

    def test_p2_1_a_dollar_before_a_non_ascii_digit_turns_the_math_path_off(self):
        for money in ('$\u0665\u0660', '$\u096b', '$\u0e55', '$\U0001d7d3'):
            with self.subTest(money=money):
                out = self.signal().transform('Price ' + money + ' a month. [signal:caution]this bills the team card[/signal] ok?',
                                              session_id='s', platform='desktop')
                self.assertNotIn('\\color', out)
                self.assertIn('(caution)', out)
        ok = self.signal().transform('It costs $49 a month. [signal:caution]this bills the team card[/signal] ok?',
                                     session_id='c', platform='desktop')
        self.assertIn('\\color', ok, 'an ASCII currency amount still takes the color path')

    def test_p3_1_an_empty_check_never_matches_an_empty_call_id(self):
        s = self.signal()
        s.observe(tool_name='read_file', tool_call_id='', session_id='', turn_id='T1', status='ok')
        for check in ('mcp__', ''):
            with self.subTest(check=check):
                self.assertFalse(s.check_passed(check, '', 'T2'))
        out = s.transform('[signal:go;check=mcp__]tests passed[/signal]', session_id='', platform='cli', turn_id='T2')
        self.assertNotIn('(go)', out or '')

    def test_p3_2_no_bold_markers_inside_a_link(self):
        for text in ('see www.example.com/[signal:stop]delete prod[/signal] ok?',
                     'see <http://x.y/[signal:stop]delete prod[/signal]> ok?'):
            for surface in ('desktop', 'telegram'):
                with self.subTest(text=text[:12], surface=surface):
                    out = self.signal().transform(text, session_id='s', platform=surface)
                    self.assertNotIn('**', out)
                    self.assertIn('(stop)', out)

    def test_p3_3_a_closer_with_several_backslashes_never_leaks(self):
        for closer in ('[\\\\/signal]', '[\\\\\\/signal]'):
            for surface in ('cli', 'desktop', 'telegram', 'sms'):
                with self.subTest(closer=closer, surface=surface):
                    out = self.signal().transform('[signal:stop]x' + closer + ' ok?', session_id='s', platform=surface)
                    self.assertNotRegex(out, r'(?i)/\s*signal')


class Pass19Findings(Base):
    """Regressions for docs/review/pass-19.txt (fresh Claude Code reviewer, A229)."""
    SURFACES = ('cli', 'desktop', 'telegram', 'sms')
    TAGISH = r'(?i)\[[\s\u200b-\u200d\u2060\ufeff\\]*/?[\s\u200b-\u200d\u2060\ufeff]*(?:signal|whisper)'

    def test_p2_1_a_spliced_copy_of_a_used_tag_never_leaks(self):
        for text in ('ok [[/signal]/signal] done',
                     'Real [signal:stop]a[/signal] then [[/signal]signal:stop]x',
                     'x [signal:go;check=terminal]a[/signal] [[/whisper]signal:go;check=terminal]passed'):
            for surface in self.SURFACES:
                with self.subTest(text=text, surface=surface):
                    out = self.signal().transform(text, session_id='s', platform=surface)
                    self.assertNotRegex(out, self.TAGISH)

    def test_p2_1_a_spliced_tag_with_invisible_chars_or_backslashes_never_leaks(self):
        for text in ('ok [\u200b[/whisper]signal:stop]rm -rf build',
                     'ok [\\\\[/whisper]/signal] done',
                     'ok [/[/whisper]whisper$ more'):
            for surface in self.SURFACES:
                with self.subTest(text=text, surface=surface):
                    out = self.signal().transform(text, session_id='s', platform=surface)
                    self.assertNotRegex(out or '', self.TAGISH)

    def test_p2_1_lookalikes_the_reply_wrote_as_text_survive(self):
        # A lookalike AFTER the last closer (one before a closer is a weak opener, by design).
        for text, kept in (('[signal:stop]this[/signal] then array[signal_1] ok', 'array[signal_1]'),
                           ('[signal:caution]c[/signal] b [whisper:] a', '[whisper:]'),
                           ('[signal:stop]x[/signal] and [signal] y', '[signal] y')):
            with self.subTest(text=text):
                out = self.signal().transform(text, session_id='s', platform='sms')
                self.assertIn(kept, out)
                self.assertIn('(stop)' if 'stop' in text else '(caution)', out)

    def test_p2_1_splice_fuzz_never_leaks(self):
        import random
        rng = random.Random(19)
        parts = ['[', ']', '/', '\\', '\u200b', 'signal', 'whisper', ':stop', ':go;check=terminal', ':caution',
                 '[/signal]', '[/whisper]', '[signal:stop]', 'x', ' ', 'sig', '$']
        for _ in range(4000):
            text = ''.join(rng.choice(parts) for _ in range(rng.randint(3, 14)))
            for surface in self.SURFACES:
                out = self.signal().transform(text, session_id='s', platform=surface)
                if out is None:
                    continue  # untouched: the original had no tag the parse consumed
                # Idempotent: what is left holds no tag the parser would consume (only lookalikes
                # the reply wrote as text), so a second pass changes nothing.
                self.assertIsNone(self.signal().transform(out, session_id='t', platform='sms'), (text, surface, out))

    def test_p3_intent_bold_only_where_markdown_reads_it_as_bold(self):
        for text in ('x[signal:intent]ship it.[/signal]Next', 'word[signal:intent](ship) it[/signal] now'):
            with self.subTest(text=text):
                out = self.signal().transform(text, session_id='s', platform='desktop')
                self.assertNotIn('**', out)
        out = self.signal().transform('Plan: [signal:intent]ship it[/signal] next.', session_id='s', platform='desktop')
        self.assertIn('**ship it**', out)


class Pass20Findings(Base):
    """Regressions for docs/review/pass-20.txt (fresh Claude Code reviewer, A229)."""
    VISIBLE = re.compile(r'\x1b\[[0-9;]*m|\*\*|\$\\color\{#[0-9A-Fa-f]{6}\}\{|\\(?:underline|textsf|textbf|textit)\{|\}+\$')

    def test_p2_1_a_tag_spliced_across_the_plugins_own_styling_never_leaks(self):
        for text in ('Run it [[signal:caution]signal:stop]now[/signal] please?',
                     'Run it [[signal:caution]/signal]now[/signal] please?',
                     'Run it [[signal:stop]whisper:assumption]x[/signal] please?'):
            for surface in ('cli', 'desktop', 'telegram', 'sms'):
                for words in ('always', 'plain_only'):
                    with self.subTest(text=text, surface=surface, words=words):
                        out = self.signal(words=words).transform(text, session_id='s', platform=surface)
                        seen = self.VISIBLE.sub('', out)  # what the human reads, styling removed
                        self.assertNotRegex(seen, r'(?i)\[\s*/?\s*(signal|whisper)\b')
                        self.assertRegex(seen, r'\((stop|caution)\)' if words == 'always' or surface == 'sms' else '.')

    def test_p2_2_an_html_block_inside_a_quote_or_list_turns_the_math_path_off(self):
        for text in ('> <div> Do not run the [signal:stop]unsafe step[/signal] yet.',
                     '- <div>Do not run the [signal:stop]unsafe step[/signal] yet.</div>',
                     '1. <div>\n   Do not run the [signal:stop]unsafe step[/signal] yet.',
                     '> - <table>\n>   Do not run the [signal:stop]unsafe step[/signal] yet.'):
            with self.subTest(text=text):
                out = self.signal().transform(text, session_id='s', platform='desktop')
                self.assertNotIn('\\color', out)
                self.assertIn('(stop)', out)

    def test_p2_3_plain_only_shows_the_word_when_no_color_is_applied(self):
        text = 'Run [signal:stop;why=x]the migration[/signal], [signal:caution]email list[/signal], [whisper:assumption]about 4,200 users[/whisper]?'
        for env, cfg in (({'NO_COLOR': '1'}, {}), ({}, {'palette': 'none'})):
            with self.subTest(env=env, cfg=cfg):
                out = self.signal(env=env, words='plain_only', **cfg).transform(text, session_id=repr(env), platform='cli')
                for word in ('(stop)', '(caution)', '(second look)'):
                    self.assertIn(word, out)
        colored = self.signal(words='plain_only').transform(text, session_id='c', platform='cli')
        self.assertNotIn('(stop)', colored, 'with color applied, plain_only still drops the word')

    def test_p2_1_styled_splice_fuzz_never_leaks(self):
        import random
        rng = random.Random(20)
        parts = ['[', '[[', ']', '/', '\\', '\u200b', 'signal', 'whisper', ':stop', ':caution', ':go;check=terminal',
                 '[/signal]', '[/whisper]', '[signal:stop]', '[signal:caution]', '[whisper:assumption]', 'x', ' ', 'sig', 'now']
        for i in range(3000):
            text = ''.join(rng.choice(parts) for _ in range(rng.randint(3, 14)))
            for surface in ('cli', 'desktop', 'telegram'):
                out = self.signal().transform(text, session_id=str(i), platform=surface)
                if out is None:
                    continue
                seen = self.VISIBLE.sub('', out)
                self.assertIsNone(self.signal().transform(seen, session_id='t', platform='sms'), (text, surface, out))


class Pass21Findings(Base):
    """Regressions for docs/review/pass-21.txt (fresh Claude Code reviewer, A229)."""

    def test_p2_1_a_lookalike_earlier_on_the_line_never_swallows_a_real_span(self):
        for text, kept, word in (('Call `buf[signal:x]` then [signal:stop]do not deploy[/signal].', 'buf[signal:x]', '(stop)'),
                                 ('Index with arr[signal] and [signal:stop]do not deploy[/signal].', 'arr[signal]', '(stop)'),
                                 ('Index with arr[signal_1] and [signal:caution]this touches prod[/signal].', 'arr[signal_1]', '(caution)'),
                                 ('Use [signal:foo] then [signal:stop]do not deploy[/signal].', None, '(stop)')):
            for surface in ('cli', 'desktop', 'telegram', 'sms'):
                with self.subTest(text=text, surface=surface):
                    s = self.signal()
                    out = s.transform(text, session_id=surface + text, platform=surface)
                    self.assertIn(word, out)
                    if kept:
                        self.assertIn(kept, out)
                    self.assertTrue(any(r['event'] == 'signal' for r in s.audit.rows(50)))

    def test_p2_2_output_is_idempotent_when_removal_changes_code_or_reuses_a_lookalike(self):
        for text in ('x [[signal:stop]signal:end]y[/signal] and `samples[signal:end]`',
                     'x [[signal:stop]signal:end]y[/signal] and\n\n    samples[signal:end]',
                     '```\n[signal:stop]```\nsamples[signal:end]',
                     '`[signal``samples[signal:end]`'):
            for surface in ('sms', 'telegram', 'cli', 'desktop'):
                with self.subTest(text=text, surface=surface):
                    out = self.signal().transform(text, session_id='s', platform=surface)
                    if out is None:
                        continue
                    seen = Pass20Findings.VISIBLE.sub('', out)
                    self.assertIsNone(self.signal().transform(seen, session_id='t', platform='sms'), (out,))

    def test_p2_2_idempotence_fuzz_with_code(self):
        import random
        rng = random.Random(21)
        parts = ['[', ']', '/', '`', '``', '```', '\n', '    ', 'signal', 'whisper', ':stop', ':end', ':x',
                 '[/signal]', '[/whisper]', '[signal:stop]', '[signal:end]', '[signal]', '[signal_1]', 'x', ' ', 'sig']
        for i in range(4000):
            text = ''.join(rng.choice(parts) for _ in range(rng.randint(3, 16)))
            out = self.signal().transform(text, session_id=str(i), platform='sms')
            if out is None:
                continue
            self.assertIsNone(self.signal().transform(out, session_id='t', platform='sms'), (text, out))


class Pass22Findings(Base):
    """A231: docs/review/pass-22.txt P3. Untagged replies are never changed, and nothing inside
    code (fenced, indented, inline) is stripped; only exact tags are read there."""
    SURFACES = ('cli', 'tui', 'desktop', 'telegram', 'sms', '')
    REPROS = ('```python\nlong = df[signal > 0]\nshort = df[signal == -1]\n```',
              'Use `df[signal > 0]` to filter.',
              'x = values[signal[idx]]',
              'y = mask[sig[0]]',
              'see buf[signal - 1]',
              'z = arr[whisper = 3]',
              'long = df[signal > 0]\nshort = df[signal == -1]')
    CODE = (
        'long = df[signal > 0]', 'short = df[signal == -1]', 'x = values[signal[idx]]', 'y = mask[sig[0]]',
        'buf[signal - 1]', 'arr[whisper = 3]', 'chunk = samples[signal:end]', 'out = sig[sig > 0.5]',
        "df.loc[df['signal'] > 0, 'pos'] = 1", 'w = weights[signal\\n]', 'rows[signal_1]', 'x[signal:stop]',
        'peaks = signal[signal.argmax()]', 'data[whisper[i]]', 'a[sig[0]][sig[1]]', 'arr[signal]',
        'const s = state[signal ? 1 : 0];', 'items[sig[i]] = signals[i] || [];', 'el[whisper = "x"]',
        "SELECT [signal] FROM t WHERE [whisper] = 1;", 'SELECT a[signal + 1] FROM ticks;',
        'if [ "$signal" = "stop" ]; then kill -[sig "$pid"]; fi', 'echo ${arr[signal]} ${arr[sig]}',
        'trap "[sig" EXIT', 'm = re.compile(r"[signal:]+")', 'x = cfg[signal: int = 3]', 'q = d[/signal]',
        'print(table[sig][ 0 ])', 'v = arr[signal\\]', 'grid[sig[0]][sig[1]] = [signal, whisper]')

    def test_untagged_repros_are_returned_unchanged_on_every_surface(self):
        for text in self.REPROS:
            for surface in self.SURFACES:
                with self.subTest(text=text, surface=surface):
                    s = self.signal()
                    self.assertIsNone(s.transform(text, session_id='s', platform=surface))
                    self.assertEqual(s.audit.rows(), [])

    def test_code_in_a_tagged_reply_is_never_stripped(self):
        tag = 'Then [signal:stop;why=no_eval]do not deploy[/signal] yet?'
        for code in self.CODE:
            for wrap in ('```python\n%s\n```', '`%s`', '    %s'):
                block = wrap % code
                if wrap == '`%s`' and '`' in code:
                    continue
                for surface in ('cli', 'desktop', 'telegram', 'sms'):
                    with self.subTest(code=code, wrap=wrap, surface=surface):
                        out = self.signal().transform(block + '\n\n' + tag, session_id='s', platform=surface)
                        self.assertIn(block, out)
                        self.assertIn('(stop)', out)

    def test_fuzz_untagged_code_never_changes(self):
        import random
        rng = random.Random(231)
        joins = ('\n', ' ', '\n\n', '\n    ', ' `', '` ', '\n```\n', '\n```sql\n', '\n~~~\n', '; ', ' && ')
        for i in range(3000):
            # Every common-code form except the two exact tag forms (x[signal:stop], d[/signal]).
            loose = [c for c in self.CODE if c not in ('x[signal:stop]', 'q = d[/signal]')]
            parts = [rng.choice(loose) for _ in range(rng.randint(1, 6))]
            text = parts[0] + ''.join(rng.choice(joins) + p for p in parts[1:])
            out = self.signal().transform(text, session_id=str(i), platform=rng.choice(self.SURFACES))
            self.assertIsNone(out, (text, out))

    def test_fuzz_code_in_fences_survives_a_tagged_reply(self):
        import random
        rng = random.Random(2310)
        for i in range(1500):
            code = '\n'.join(rng.choice(self.CODE) for _ in range(rng.randint(1, 5)))
            block = '```\n' + code + '\n```'
            tag = rng.choice(('[signal:caution]merge now[/signal]?', '[whisper:assumption]about 4,200[/whisper]',
                              '[signal:stop]wipe prod[/signal]?'))
            text = rng.choice((block + '\n' + tag, tag + '\n' + block, tag + '\n' + block + '\n' + tag))
            out = self.signal().transform(text, session_id=str(i), platform=rng.choice(('cli', 'desktop', 'telegram', 'sms')))
            self.assertIsNotNone(out)
            self.assertIn(block, out, text)

    def test_pass23_shapes_in_code_are_never_cut_by_the_second_parse(self):
        # Pass 23 P3-a and P3-b: unsplice never removes a shape that starts inside code.
        cases = (('`[signal:`[signal:stop]wipe[/signal]', '`[signal:`', 'wipe'),
                 ('`x[sig\u200bnal:stop]y`\n\n[signal:stop]wipe[/signal]', '`x[sig\u200bnal:stop]y`', 'wipe'),
                 ('```\na[/sig\u200bnal]\n```\nok [sig', '```\na[/sig\u200bnal]\n```', 'ok'))
        for text, code, phrase in cases:
            for surface in ('cli', 'desktop', 'telegram', 'sms'):
                with self.subTest(text=text, surface=surface):
                    out = self.signal().transform(text, session_id='s', platform=surface)
                    self.assertIn(code, out)
                    self.assertIn(phrase, out)
                    self.assertIsNone(self.signal().transform(Pass20Findings.VISIBLE.sub('', out),
                                                              session_id='t', platform='sms'), out)

    def test_pass24_joined_tags_in_code_never_survive_and_output_is_stable(self):
        # Pass 24 P3-1: removal that joins text into a live tag inside code is still cleaned.
        for text in ('`[signal:intent][sig[/signal]nal:stop]drop prod[/signal]`',
                     '```\n[signal:intent][sig[/signal]nal:stop]drop prod[/signal]\n```',
                     '[signal:danger]```\nsee `[signal:caution]` then [signal:stop]wipe[/signal]` x[/signal]` ok'):
            for surface in ('cli', 'desktop', 'telegram', 'sms'):
                with self.subTest(text=text, surface=surface):
                    s = self.signal()
                    out = s.transform(text, session_id='s', platform=surface)
                    self.assertIsNotNone(out)
                    seen = Pass20Findings.VISIBLE.sub('', out)
                    self.assertFalse(s.joined(seen), out)
                    self.assertIsNone(self.signal().transform(seen, session_id='t', platform='sms'), out)

    def test_pass24_unknown_level_pair_in_code_stays(self):
        # Pass 24 P3-2: inside code only known-value openers are tags.
        for code in ('`d = q[signal:end] + w[/signal]`', '```\nx = a[signal:danger] if b else c[/signal]\n```'):
            with self.subTest(code=code):
                out = self.signal().transform(code + '\n\n[signal:stop]wipe prod[/signal]?', session_id='s', platform='sms')
                self.assertIn(code, out)
                self.assertIn('wipe prod (stop)', out)

    def test_pass24_many_lookalikes_stay_fast(self):
        # Pass 24 P2: the code map is built once per round, not once per bracket.
        import time
        for text in ('[signal:stop]x[/signal]\n' + 'arr[signal] ' * 20000,
                     '[signal:caution]a[/signal]?\n```\n' + '[SIGNAL] worker 1 got SIGTERM\n' * 3000 + '```',
                     '`a[signal:end]` ' * 10000 + '[signal:stop]x[/signal]'):
            start = time.time()
            self.signal().transform(text, session_id='s', platform='cli')
            self.assertLess(time.time() - start, 5.0)

    def test_pass25_prose_on_both_sides_of_code_never_joins_into_a_tag(self):
        # Pass 25: '[' before inline code (or a line end) and '/signal]' after it are not a tag.
        untagged = ('see [`k`/signal] and buf[signal - 1]', 'x = buf[signal - 1]\ny = [\n/signal]',
                    'pick [`i`/whisper] then\nbuf[signal - 1] ok')
        for text in untagged:
            with self.subTest(text=text):
                self.assertIsNone(self.signal().transform(text, session_id='s', platform='sms'))
        tagged = (('`x[sig\u200bnal:stop]y`\n\n[signal:stop]wipe[/signal]? see [`k`/signal]', '`x[sig\u200bnal:stop]y`'),
                  ('`[signal:`[signal:stop]wipe[/signal] and [`i`/signal]', '`[signal:`'),
                  ('```\na[/sig\u200bnal]\n```\n[signal:stop]wipe[/signal]? and [`i`/signal]', '```\na[/sig\u200bnal]\n```'))
        for text, code in tagged:
            for surface in ('cli', 'desktop', 'telegram', 'sms'):
                with self.subTest(text=text, surface=surface):
                    out = self.signal().transform(text, session_id='s', platform=surface)
                    self.assertIn(code, out)
                    self.assertIn('wipe', out)

    def test_pass26_empty_or_mismatched_pair_in_code_stays(self):
        cases = (('Mark it [signal:stop]like this[/signal]? The empty form `[signal:stop][/signal]` does nothing.',
                  '`[signal:stop][/signal]`'),
                 ('[signal:stop]wipe[/signal]?\n    tpl = "[signal:caution][/signal]"', '    tpl = "[signal:caution][/signal]"'),
                 # A closer of another kind inside a span in code is code text; the span itself is exact.
                 ('[signal:stop]wipe[/signal]?\n```\nfoo [signal:stop]x[/whisper][/signal] bar\n```',
                  '```\nfoo x[/whisper] (stop) bar\n```'),
                 ('[signal:stop]wipe[/signal]?\n~~~\n~~~[signal:stop] [/signal]\nk = [/signal]\n~~~\nend',
                  '~~~\n~~~[signal:stop] [/signal]\nk = [/signal]\n~~~'))
        for text, code in cases:
            for surface in ('cli', 'desktop', 'telegram', 'sms'):
                with self.subTest(text=text, surface=surface):
                    out = self.signal().transform(text, session_id='s', platform=surface)
                    self.assertIn(code, out)
                    self.assertIsNone(self.signal().transform(Pass20Findings.VISIBLE.sub('', out),
                                                              session_id='t', platform='sms'), out)

    def test_pass27_nested_opener_and_other_kind_closer_in_code_stay(self):
        cases = (('[signal:stop]never run `[signal:go]` here[/signal]', '`[signal:go]`', '(stop)'),
                 ('[signal:stop]a `[signal:go]b[/whisper]` c[/signal]', '`[signal:go]b[/whisper]`', '(stop)'),
                 ('[signal:stop]run `rm [/whisper]` now[/signal]', '`rm [/whisper]`', '(stop)'),
                 # A complete exact pair in code is a span (read, never left as half a tag), even nested.
                 ('[signal:stop]a `[signal:go]b[/signal]` c[/signal]', '`b` c', '(stop)'),
                 ('[signal:stop]a `[signal:caution]b[/signal]` c', '`b`', ' c'))
        for text, code, word in cases:
            for surface in ('cli', 'desktop', 'telegram', 'sms'):
                with self.subTest(text=text, surface=surface):
                    out = self.signal().transform(text, session_id='s', platform=surface)
                    self.assertIn(code, out)
                    self.assertIn(word, out)
                    self.assertNotRegex(out, r'\[signal:(go|caution)\]b`')  # never half a tag
                    self.assertIsNone(self.signal().transform(Pass20Findings.VISIBLE.sub('', out),
                                                              session_id='t', platform='sms'), out)

    def test_pass29_nested_span_in_code_keeps_the_outer_stop(self):
        cases = (('`[signal:stop]a [signal:go]b c[/signal] d[/signal]`', '(stop)'),
                 ('```\n[signal:stop]rm -rf / [signal:go]dry run[/signal] for real[/signal]\n```', '(stop)'),
                 ('    [signal:stop]a [signal:caution]b[/signal] c[/signal]', '(stop)'),
                 ('`[signal:stop]a [signal:go]b c[/signal]`', '`[signal:stop]a [signal:go]b c[/signal]`'))
        for text, want in cases:
            for surface in ('cli', 'desktop', 'telegram', 'sms'):
                with self.subTest(text=text, surface=surface):
                    out = self.signal().transform(text, session_id='s', platform=surface)
                    self.assertIn(want, text if out is None else out)
                    if out is not None:
                        self.assertIsNone(self.signal().transform(Pass20Findings.VISIBLE.sub('', out),
                                                                  session_id='t', platform='sms'), out)


class GuidanceTests(unittest.TestCase):
    def test_guidance_teaches_markup_and_rules_briefly(self):
        from axioma.signal import GUIDANCE as g
        for needle in ('[signal:stop', '[signal:caution]', '[signal:go;check=', '[whisper:', 'question',
                       'at most 3', 'never', 'code'):
            self.assertIn(needle, g)
        self.assertLess(len(g), 1400, 'short: it rides every turn')


if __name__ == '__main__':
    unittest.main()
