"""Real host dispatch on BOTH paths with a synthetic handler. No model, network or client action.

Run: hermes --run-module unittest discover -s /absolute/repo/tests -v
Paths covered:
  registry: model_tools.handle_function_call (pre_tool_call runs before execution middleware)
  native:   agent.tool_executor._run_agent_tool_execution_middleware (execution middleware first,
            then pre_tool_call inside the authorized dispatch, with the final arguments)
The plugin loads into a temporary HERMES_HOME. Private manager wiring and the simulated human
at Hermes's own approval prompt are test-only and never shipped.
"""
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_card import CARD

HOST = importlib.util.find_spec('hermes_cli') is not None
GREEN = {**CARD, 'light': 'green', 'affects': ['self'], 'told': True}


def native_agent():
    import run_agent as _ra

    class _Stub:
        _interrupt_requested = False
        _interrupt_message = None
        log_prefix = ''
        quiet_mode = True
        verbose_logging = False
        log_prefix_chars = 200
        _checkpoint_mgr = MagicMock(enabled=False)
        tool_progress_callback = None
        tool_start_callback = None
        tool_complete_callback = None
        tool_progress_mode = 'off'
        _todo_store = MagicMock()
        _session_db = None
        valid_tool_names = set()
        _turns_since_memory = 0
        _iters_since_skill = 0
        _current_tool = None
        _last_activity = 0.0
        session_id = 'synthetic-session'
        _current_turn_id = ''
        _current_api_request_id = ''

        def __init__(self):
            self._tool_worker_threads = set()
            self._tool_worker_threads_lock = threading.Lock()
            self._active_children_lock = threading.Lock()

        def _touch_activity(self, desc):
            self._last_activity = time.time()

        def _vprint(self, msg, force=False):
            pass

        def _safe_print(self, msg):
            pass

        def _should_emit_quiet_tool_messages(self):
            return False

        def _should_start_quiet_spinner(self):
            return False

        def _has_stream_consumers(self):
            return False

    stub = _Stub()
    stub._tool_guardrails = MagicMock(before_call=lambda name, args: MagicMock(allows_execution=True))
    stub._guardrail_block_result = lambda d: json.dumps({'error': 'blocked'})
    stub.interrupt = _ra.AIAgent.interrupt.__get__(stub)
    stub.clear_interrupt = _ra.AIAgent.clear_interrupt.__get__(stub)
    return stub


@unittest.skipUnless(HOST, 'Requires Hermes runtime; run hermes --run-module unittest')
class HostTests(unittest.TestCase):
    def setUp(self):
        from hermes_cli import plugins
        from tools.registry import registry
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name)
        plugin_root = home / 'plugins'
        plugin_root.mkdir()
        (plugin_root / 'hermes-axioma').symlink_to(ROOT, target_is_directory=True)
        self.enterContext(patch.dict(os.environ, {'HERMES_HOME': str(home),
                                                  'HERMES_BUNDLED_PLUGINS': str(home / 'none')}))
        self.manager = plugins.PluginManager()
        manifests = self.manager._scan_directory(plugin_root, source='user')
        self.assertEqual(len(manifests), 1)
        self.manager._load_plugin(manifests[0])
        self.addCleanup(self.manager.unload)
        loaded = self.manager._plugins['hermes-axioma']
        self.assertFalse(loaded.error, loaded.error)
        self.assertNotIn('tool_execution', [k for k, v in self.manager._middleware.items() if v],
                         'the advisor registers no execution middleware')
        self.advisor = self.manager._hooks['pre_tool_call'][0].__self__
        self.enterContext(patch.object(plugins, '_delivery_manager', return_value=self.manager))
        self.enterContext(patch.object(plugins, 'get_plugin_manager', return_value=self.manager))
        self.ran = []
        self.name = 'axioma_synthetic_send_email'
        self.handler = lambda args, **kw: self.ran.append(args) or json.dumps({'ok': True})
        self.register(self.name)

    def register(self, name):
        from tools.registry import registry
        registry.register(name=name, toolset='axioma_test', schema={
            'name': name, 'parameters': {'type': 'object', 'properties': {}}},
            handler=self.handler, scope=self.manager.scope_key)
        self.addCleanup(lambda: registry.deregister(name, scope=self.manager.scope_key))

    def human(self, choice, prompts, mode='manual', yolo=False, present=True, real_allowlist=False):
        """Simulated human answering Hermes's own approval prompt. Returns an ExitStack."""
        from tools import approval, approval_context

        def prompt(*a, **k):
            prompts.append(json.dumps([a, k], default=str))
            return choice
        presence = (prompt, True, False, False) if present else (None, False, False, False)
        stack = ExitStack()
        stack.enter_context(patch.object(approval, '_presence', return_value=presence))
        stack.enter_context(patch.object(approval, '_yolo_active', return_value=yolo))
        stack.enter_context(patch.object(approval_context, '_get_approval_mode', return_value=mode))
        if not real_allowlist:
            stack.enter_context(patch.object(approval, 'is_approved', return_value=False))
        stack.enter_context(patch.object(approval, 'prompt_dangerous_approval', side_effect=prompt))
        return stack

    def call(self, path, tool, args, call='target'):
        if path == 'registry':
            from model_tools import handle_function_call
            return handle_function_call(tool, args, session_id='synthetic-session', tool_call_id=call)
        from agent import tool_executor
        from model_tools import handle_function_call

        def execute(final):
            # Mirrors agent_runtime_helpers.invoke_tool: pre_tool_call already fired in the
            # authorized dispatch, so the registry call skips it (single-fire contract).
            return handle_function_call(tool, final, 'synthetic-task', tool_call_id=call,
                                        session_id='synthetic-session', skip_pre_tool_call_hook=True,
                                        skip_tool_request_middleware=True,
                                        skip_tool_execution_middleware=True)
        state = tool_executor._run_agent_tool_execution_middleware(
            native_agent(), function_name=tool, function_args=args, effective_task_id='synthetic-task',
            tool_call_id=call, execute=execute)
        return state.result

    def stage(self, path, args, card=GREEN):
        out = self.call(path, 'axioma_card', {'tool': self.name, 'arguments': args, 'card': card}, call='card')
        self.assertIn('staged', out)

    # -----------------------------------------------------------------------------------------
    def test_card_reaches_hermes_prompt_and_the_human_decides_on_both_paths(self):
        for path in ('registry', 'native'):
            for choice, count in (('once', 1), ('deny', 0)):
                with self.subTest(path=path, choice=choice):
                    self.ran.clear()
                    prompts = []
                    with self.human(choice, prompts):
                        self.stage(path, {'text': 'SYNTHETIC'})
                        self.call(path, self.name, {'text': 'SYNTHETIC'}, call=path + choice)
                    self.assertEqual(len(self.ran), count)
                    self.assertEqual(len(prompts), 1, 'Hermes asked the human exactly once')
                    self.assertIn(CARD['question'], prompts[0])
                    self.assertIn('GO', prompts[0])
                    self.assertIn('advice only', prompts[0])

    def test_no_card_still_reaches_the_human_with_a_notice_on_both_paths(self):
        for path in ('registry', 'native'):
            with self.subTest(path=path):
                self.ran.clear()
                prompts = []
                with self.human('once', prompts):
                    self.call(path, self.name, {'text': 'SYNTHETIC'}, call='nocard-' + path)
                self.assertEqual(len(prompts), 1)
                self.assertIn('NO CARD', prompts[0])
                self.assertEqual(len(self.ran), 1, 'the advisor does not block; the human chose once')

    def test_unclassified_tools_are_untouched_on_both_paths(self):
        from tools import approval
        name = 'axioma_synthetic_read'
        self.register(name)
        with patch.object(approval, 'request_tool_approval', side_effect=AssertionError('must not ask')):
            self.call('registry', name, {'q': 1})
            self.call('native', name, {'q': 2})
        self.assertEqual(self.ran, [{'q': 1}, {'q': 2}])

    def test_native_card_is_matched_against_final_arguments_after_middleware(self):
        def rewrite(tool_name, args, next_call, **kwargs):
            if tool_name == self.name:
                return next_call({**args, 'text': 'SYNTHETIC_REWRITTEN'})
            return next_call(args)
        self.manager._middleware.setdefault('tool_execution', []).append(rewrite)
        prompts = []
        with self.human('once', prompts):
            self.stage('native', {'text': 'SYNTHETIC'})
            self.call('native', self.name, {'text': 'SYNTHETIC'})
        self.assertEqual(len(prompts), 1)
        self.assertIn('NO CARD', prompts[0], 'the card was for other arguments; the human is told so')
        self.assertEqual(self.ran, [{'text': 'SYNTHETIC_REWRITTEN'}])

    def test_host_policy_decides_unattended_and_yolo(self):
        prompts = []
        with self.human('once', prompts, present=False):
            self.stage('registry', {'text': 'SYNTHETIC'})
            out = self.call('registry', self.name, {'text': 'SYNTHETIC'})
        self.assertFalse(self.ran, 'no human present: Hermes fails closed (host behavior)')
        self.assertIn('BLOCKED', out)
        self.assertEqual(prompts, [])
        with self.human('once', prompts, yolo=True):
            self.stage('registry', {'text': 'SYNTHETIC'})
            self.call('registry', self.name, {'text': 'SYNTHETIC'})
        self.assertEqual(len(self.ran), 1, 'YOLO is a Hermes decision; the advisor does not override it')

    def test_red_card_never_offers_yes_and_answers_are_logged_without_bodies(self):
        for path in ('registry', 'native'):
            with self.subTest(path=path):
                prompts = []
                with self.human('deny', prompts):
                    self.stage(path, {'text': 'SYNTHETIC'}, {**CARD, 'light': 'red'})
                    self.call(path, self.name, {'text': 'SYNTHETIC'}, call='red-' + path)
                self.assertEqual(len(prompts), 1)
                card_text = json.loads(prompts[0])[1].get('description') or prompts[0]
                self.assertIn('STOP', card_text)
                self.assertIn('proceed: no', card_text)
        rows = self.advisor.audit.rows()
        self.assertGreaterEqual(sum(1 for r in rows if r['event'] == 'answer' and r['answer'] == 'no'), 2)
        self.assertNotIn('SYNTHETIC', json.dumps(rows))

    def test_remembered_session_approval_never_covers_a_later_call(self):
        """Real Hermes allowlist: 'session' on one GREEN card does not skip the next card."""
        for path in ('registry', 'native'):
            with self.subTest(path=path):
                self.ran.clear()
                prompts = []
                with self.human('session', prompts, real_allowlist=True):
                    for i in range(2):
                        self.stage(path, {'text': 'SYNTHETIC'})
                        self.call(path, self.name, {'text': 'SYNTHETIC'}, call='%s-mem-%d' % (path, i))
                self.assertEqual(len(prompts), 2, 'each card reached the human')
                self.assertEqual(len(self.ran), 2)

    def test_question_and_proceed_survive_the_cli_approval_panel(self):
        """Hermes's CLI panel puts the description last and truncates it; ours leads with them."""
        import hermes_cli.cli_tui_mixin as mixin
        from axioma.card import render_card, render_notice
        cls = next(getattr(mixin, n) for n in dir(mixin)
                   if hasattr(getattr(mixin, n), '_get_approval_display_fragments'))
        long_text = 'Synthetic ' + 'detail ' * 18
        red = dict(CARD, light='red', intent=long_text.strip()[:140], signal=(long_text.strip()[:139] + '.'))
        cases = [(render_card(red, kind=('send',), checks=[{'check': 'sender_rights', 'pass': False},
                                                         {'check': 'device_lock', 'pass': False}]),
                  CARD['question'], 'proceed: no'),
                 (render_notice('send_message', ('send',)), 'What do you need to know', 'proceed: yes / no'),
                 (render_notice('send_message', ('send',), checks=[{'check': 'standing_rule', 'pass': False}],
                                red_signal='A standing rule forbids this action; revise the target before re-review.'),
                  'What do you need to know', 'proceed: no')]

        class Panel:
            pass
        for desc, question, proceed in cases:
            for rows in (24, 40):
                with self.subTest(rows=rows, head=desc.splitlines()[0]):
                    p = Panel()
                    p._approval_state = {'command': '<send_message> (plugin approval rule)', 'description': desc,
                                         'choices': ['once', 'session', 'always', 'deny'], 'selected': 0}
                    with patch.object(mixin, '_term_rows', return_value=rows):
                        text = ''.join(x[1] for x in cls._get_approval_display_fragments(p))
                    flat = ' '.join(line.strip('│ ') for line in text.splitlines())
                    self.assertIn(proceed, flat)
                    self.assertIn(question, flat)

    def test_card_code_survives_the_real_approval_renderers(self):
        """Spec 5.6: the card code reaches the human intact on the real CLI panel at 16-40 rows
        (whenever any card line is visible, the code is too) and through the real Telegram and
        Discord approval formatters (escaping and length budgets included)."""
        import re
        import hermes_cli.cli_tui_mixin as mixin
        from axioma.advisor import Advisor
        from axioma.audit import Audit
        from gateway.config import PlatformConfig
        from plugins.platforms.telegram.adapter import TelegramAdapter, _escape_mdv2, _strip_mdv2
        from plugins.platforms.discord.adapter import DiscordAdapter
        cls = next(getattr(mixin, n) for n in dir(mixin)
                   if hasattr(getattr(mixin, n), '_get_approval_display_fragments'))
        long_q = ('Is ' + 'this really the audience you intended for the synthetic draft and ' * 6)[:398] + '?'
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        def message(surface, card):
            a = Advisor({}, Audit(Path(tmp.name) / 'audit.sqlite3'), surface=lambda: surface)
            if card is not None:
                a.submit({'tool': 'send_message', 'arguments': {'text': 'SYNTHETIC'}, 'card': card}, session_id='s')
            msg = a.before('send_message', {'text': 'SYNTHETIC'}, session_id='s', tool_call_id='c')['message']
            return msg, re.search(r'card code [0-9A-Z]{4}-[0-9A-Z]{4}$', msg, re.M).group(0)

        class Panel:
            pass
        for card in (CARD, dict(CARD, light='red', question=long_q), None):
            msg, line = message('cli', card)
            first_words = msg.splitlines()[0].split(' \u00b7 ')[0]
            for rows in (16, 18, 20, 24, 40):
                with self.subTest(surface='cli', rows=rows, card=card and card['question'][:20]):
                    p = Panel()
                    p._approval_state = {'command': '<send_message> (plugin approval rule)', 'description': msg,
                                         'choices': ['once', 'session', 'always', 'deny'], 'selected': 0}
                    with patch.object(mixin, '_term_rows', return_value=rows):
                        text = ''.join(x[1] for x in cls._get_approval_display_fragments(p))
                    flat = ' '.join(x.strip('│ ') for x in text.splitlines())
                    card_visible = any(x in flat for x in (first_words, 'intent:', 'signal:', '?'))
                    if rows >= 18:
                        self.assertIn(line, flat)
                    elif card_visible:
                        self.assertIn(line, flat, 'a card line is visible without its code')
            for adapter, surface in ((TelegramAdapter, 'telegram'), (DiscordAdapter, 'discord')):
                msg, line = message(surface, card)
                with self.subTest(surface=surface, card=card and card['question'][:20]):
                    # The real adapter object and its real formatter; no budget emulation.
                    a = adapter(PlatformConfig(enabled=True, token='synthetic-not-a-token'))
                    wire = a._format_exec_approval('send_message', msg)
                    self.assertIn(line, wire, 'the code survives escaping and the reason budget')
                    if adapter is TelegramAdapter:  # MarkdownV2 text fallback
                        self.assertIn(line, _strip_mdv2(_escape_mdv2(msg)))
                    else:
                        self.assertIn(line, a.format_message(wire))

    # -- inline signal color through the real host seams (A229) --------------------------------
    def transform(self, text, platform, turn='turn-1'):
        from types import SimpleNamespace
        from agent.turn_finalizer import apply_llm_output_transform
        agent = SimpleNamespace(session_id='synthetic-session', model='synthetic', platform=platform)
        out, transformed, original = apply_llm_output_transform(agent, text, turn_id=turn, platform=platform)
        return out, transformed, original

    def test_inline_signal_renders_through_the_real_output_transform(self):
        text = ('Shipping [signal:stop;why=no_eval]without an eval or a test[/signal] puts the '
                '[signal:caution]merge into Hermes[/signal] under your name. Run the eval first?')
        for platform, needle in (('cli', '\x1b[38;2;255;69;58m'),
                                 ('desktop', r'$\color{#FF453A}{\underline{\textsf{\textbf{without an eval or a test}}}}$ (stop)'),
                                 ('telegram', '**without an eval or a test** (stop)'),
                                 ('sms', 'without an eval or a test (stop)')):
            with self.subTest(platform=platform):
                out, transformed, original = self.transform(text, platform, turn='t-' + platform)
                self.assertTrue(transformed)
                self.assertEqual(original, text)
                self.assertIn(needle, out)
                self.assertNotIn('[signal', out)
                self.assertNotIn('[/signal]', out)
        out, transformed, _ = self.transform('No marks here.', 'desktop', turn='t-plain')
        self.assertFalse(transformed, 'untagged replies are left to the host')

    def test_cli_final_renderer_keeps_color_in_raw_mode_and_words_in_every_mode(self):
        """Hermes's own CLI final-response renderer: `raw` keeps the truecolor styling; the default
        `strip` mode and `render` mode drop ANSI, so the word is what carries the signal there."""
        from hermes_cli.cli_render import _render_final_assistant_content
        out, _, _ = self.transform('Shipping [signal:stop;why=x]without a test[/signal] is risky. Proceed?',
                                   'cli', turn='t-cli-render')
        raw = _render_final_assistant_content(out, mode='raw')
        styles = ' '.join(str(span.style) for span in raw.spans).lower()
        self.assertIn('#ff453a', styles)
        self.assertIn('bold', styles)
        self.assertIn('underline', styles)
        self.assertIn('without a test (stop)', raw.plain)
        strip = _render_final_assistant_content(out, mode='strip')
        self.assertIn('without a test (stop)', strip.plain)
        self.assertNotIn('\x1b', strip.plain)
        rendered = _render_final_assistant_content(out, mode='render')
        self.assertIn('without a test (stop)', rendered.markup)

    def test_green_only_from_a_tool_call_the_host_reported_as_passing(self):
        from tools.registry import registry
        from model_tools import handle_function_call
        ok, bad = 'axioma_synthetic_run_tests', 'axioma_synthetic_failing_check'
        for name, result in ((ok, {'passed': 41, 'failed': 0}), (bad, {'error': 'synthetic failure'})):
            registry.register(name=name, toolset='axioma_test', schema={
                'name': name, 'parameters': {'type': 'object', 'properties': {}}},
                handler=lambda args, _r=result, **kw: json.dumps(_r), scope=self.manager.scope_key)
            self.addCleanup(lambda n=name: registry.deregister(n, scope=self.manager.scope_key))
        handle_function_call(ok, {}, session_id='synthetic-session', tool_call_id='call_ok', turn_id='turn-go')
        handle_function_call(bad, {}, session_id='synthetic-session', tool_call_id='call_bad', turn_id='turn-go')
        for check, green in ((ok, True), ('call_ok', True), (bad, False), ('call_bad', False), ('invented', False)):
            with self.subTest(check=check):
                out, _, _ = self.transform('[signal:go;check=%s]41 of 41 passed[/signal]' % check, 'telegram',
                                           turn='turn-go')
                self.assertEqual(out, '**41 of 41 passed** (go)' if green else '41 of 41 passed')

    def test_cronjob_alias_is_classified_after_canonicalization_on_both_paths(self):
        from tools.registry import registry
        real = registry.dispatch
        for path, name in (('registry', 'cronjob'), ('native', 'cronjob_manage')):
            # The real native executor canonicalizes `cronjob` -> `cronjob_manage` before hooks
            # (agent/tool_executor.py ~461), upstream of the function this test drives.
            with self.subTest(path=path, name=name):
                prompts, hit = [], []

                def dispatch(name, *a, **k):
                    if name in ('cronjob', 'cronjob_manage'):
                        hit.append(name)
                        return '{}'
                    return real(name, *a, **k)
                with self.human('deny', prompts), patch.object(registry, 'dispatch', side_effect=dispatch):
                    self.call(path, name, {'action': 'create', 'schedule': 'every 1h', 'prompt': 'x'},
                              call='cron-' + path)
                self.assertEqual(len(prompts), 1, 'cronjob/cronjob_manage still shows a card')
                self.assertFalse(hit, 'the human denied at the Hermes prompt')


if __name__ == '__main__':
    unittest.main()
