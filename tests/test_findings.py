"""Red-to-green regressions for codereview pass-1 findings 3-9 (docs/review/pass-1.txt).

Synthetic data only. No command in this file is executed; strings are classified.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_card import CARD

GREEN = {**CARD, 'light': 'green', 'affects': ['self'], 'told': True}


class Finding3CronjobManageAlias(unittest.TestCase):
    def test_canonical_cronjob_manage_is_spin(self):
        from axioma.policy import Policy
        p = Policy()
        for tool in ('cronjob', 'cronjob_manage'):
            for action in ('create', 'add', 'update', 'resume'):
                with self.subTest(tool=tool, action=action):
                    self.assertIn('spin', p.classify(tool, {'action': action}))
            with self.subTest(tool=tool, action='list'):
                self.assertEqual(p.classify(tool, {'action': 'list'}), ())


class Finding4UnknownCwd(unittest.TestCase):
    def test_relative_operand_without_workdir_is_not_proven_contained(self):
        from axioma.policy import Policy
        p = Policy({'workspace': '/synthetic/workspace'})
        # Persistent terminal cwd is unknown when workdir is omitted.
        self.assertIn('scrub', p.classify('terminal', {'command': 'rm victim'}))
        self.assertIn('scrub', p.classify('terminal', {'command': 'mv a.txt b.txt'}))
        # Explicit workdir inside the workspace is proven containment.
        self.assertEqual(p.classify('terminal', {'command': 'rm victim', 'workdir': '/synthetic/workspace'}), ())
        # Absolute operands inside the workspace need no cwd.
        self.assertEqual(p.classify('terminal', {'command': 'rm /synthetic/workspace/out.txt'}), ())
        # Explicit workdir outside is flagged.
        self.assertIn('scrub', p.classify('terminal', {'command': 'rm victim', 'workdir': '/synthetic/outside'}))


class Finding5LockFailsClosed(unittest.TestCase):
    def test_unreadable_lock_is_not_available(self):
        from axioma.checks import Checks
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / 'device.lock'
            c = Checks({'locks': [{'tool': '*', 'path': str(lock)}]})
            card, results = c.apply('send_message', {}, GREEN, categories=('send',))
            self.assertTrue(next(r for r in results if r['check'] == 'device_lock')['pass'])
            real_lstat = os.lstat

            def denied(path, *a, **k):
                if str(path) == str(lock):
                    raise PermissionError('synthetic')
                return real_lstat(path, *a, **k)
            with patch('os.lstat', side_effect=denied), patch('os.stat', side_effect=denied), \
                 patch.object(Path, 'stat', side_effect=PermissionError('synthetic')):
                card, results = c.apply('send_message', {}, GREEN, categories=('send',))
            self.assertFalse(next(r for r in results if r['check'] == 'device_lock')['pass'])
            self.assertEqual(card['light'], 'red')


class Finding6Normalization(unittest.TestCase):
    def test_assignee_and_provider_are_normalized(self):
        from axioma.checks import Checks
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'skills': {'builder': {'root': tmp, 'required': ['safety']}},
                   'provider_conflicts': [{'provider': 'anthropic', 'key_envs': ['SYNTHETIC_KEY']}]}
            c = Checks(cfg, secret_present=lambda n: True)
            for assignee in ('builder', 'Builder', ' builder '):
                with self.subTest(assignee=assignee):
                    card, results = c.apply('kanban_create', {'assignee': assignee}, GREEN, categories=('spin',))
                    self.assertEqual(card['light'], 'red')
                    self.assertFalse(next(r for r in results if r['check'] == 'skills')['pass'])
            for provider in ('anthropic', ' anthropic ', 'Anthropic'):
                with self.subTest(provider=provider):
                    card, results = c.apply('kanban_create', {'provider': provider}, GREEN, categories=('spin',))
                    self.assertEqual(card['light'], 'red')
            # Config keys are normalized too.
            c2 = Checks({'skills': {' Builder ': {'root': tmp, 'required': ['safety']}}})
            card, _ = c2.apply('kanban_create', {'assignee': 'builder'}, GREEN, categories=('spin',))
            self.assertEqual(card['light'], 'red')


class Finding7SenderByCategory(unittest.TestCase):
    def test_custom_send_tool_gets_sender_check(self):
        from axioma.checks import Checks
        c = Checks({'senders': {'receive-only@example.invalid': False, 'ok@example.invalid': True}})
        card, results = c.apply('deliver_mail', {'from': 'receive-only@example.invalid'}, GREEN,
                                categories=('send',))
        self.assertEqual(card['light'], 'red')
        self.assertFalse(next(r for r in results if r['check'] == 'sender_rights')['pass'])
        card, _ = c.apply('deliver_mail', {'from': 'ok@example.invalid'}, GREEN, categories=('send',))
        self.assertEqual(card['light'], 'green')
        # A tool named *send* that is not classified SEND is not sender-checked.
        _, results = c.apply('resend_report_preview', {}, GREEN, categories=())
        self.assertFalse(any(r['check'] == 'sender_rights' for r in results))

    def test_advisor_passes_policy_category_to_checks(self):
        from axioma.advisor import Advisor
        from axioma.audit import Audit
        with tempfile.TemporaryDirectory() as tmp:
            a = Advisor({'add': [{'id': 'mail', 'category': 'send', 'tool': 'deliver_mail'}]},
                        Audit(Path(tmp) / 'a.sqlite3'),
                        checks_config={'senders': {'receive-only@example.invalid': False}})
            args = {'from': 'receive-only@example.invalid'}
            a.submit({'tool': 'deliver_mail', 'arguments': args, 'card': GREEN}, session_id='s')
            d = a.before('deliver_mail', args, session_id='s', tool_call_id='c')
            self.assertIn('STOP', d['message'])
            self.assertIn('sender_rights: fail', d['message'])


class Finding8MvTargetDirectory(unittest.TestCase):
    def test_attached_and_separate_target_forms(self):
        from axioma.policy import Policy
        p = Policy({'workspace': '/synthetic/workspace'})
        base = {'workdir': '/synthetic/workspace'}
        for command in ('mv -t/synthetic/outside local', 'mv -t /synthetic/outside local',
                        'mv --target-directory=/synthetic/outside local',
                        'mv --target-directory /synthetic/outside local',
                        'mv -ft/synthetic/outside local', 'mv -vt /synthetic/outside local'):
            with self.subTest(command=command):
                self.assertIn('scrub', p.classify('terminal', {**base, 'command': command}))
        self.assertEqual(p.classify('terminal', {**base, 'command': 'mv -t /synthetic/workspace/out local'}), ())


class Finding9TagOnlyWhisper(unittest.TestCase):
    def test_tag_only_output_never_yields_empty_replacement(self):
        from axioma.audit import Audit
        from axioma.whisper import Whisper
        with tempfile.TemporaryDirectory() as tmp:
            w = Whisper(Audit(Path(tmp) / 'a.sqlite3'))
            for text in ('[whisper:assumption][/whisper]', '[whisper:low_confidence]', '[/whisper]'):
                with self.subTest(text=text):
                    out = w.transform(text, session_id='s', platform='cli')
                    self.assertIsInstance(out, str)
                    self.assertTrue(out)
                    self.assertNotIn('[whisper', out)
                    self.assertNotIn('[/whisper', out)


class Pass2Findings(unittest.TestCase):
    """Regressions for docs/review/pass-2.txt (Claude reviewer, A224)."""

    def policy(self):
        from axioma.policy import Policy
        return Policy({'workspace': '/synthetic/workspace'})

    def test_p2_1_any_cd_pushd_popd_makes_cwd_unknown(self):
        p, base = self.policy(), {'workdir': '/synthetic/workspace'}
        for command in ('cd; rm victim', 'cd&&rm victim', 'pushd /synthetic/outside && rm victim',
                        'popd; rm victim', 'cd /synthetic/outside;mv a b'):
            with self.subTest(command=command):
                self.assertIn('scrub', p.classify('terminal', {**base, 'command': command}))

    def test_p2_2_brace_and_bracket_expansion_is_unknown(self):
        p, base = self.policy(), {'workdir': '/synthetic/workspace'}
        for command in ('rm /synthetic/workspace/{x,../../outside/victim}',
                        'mv /synthetic/workspace/{a,../../outside/b} /synthetic/workspace/c',
                        'rm /synthetic/workspace/[ab]'):
            with self.subTest(command=command):
                self.assertIn('scrub', p.classify('terminal', {**base, 'command': command}))

    def test_p2_3_non_ascii_deny_patterns_match(self):
        from axioma.checks import Checks
        c = Checks({'deny': [{'tool': 'send_message', 'pattern': 'Zoë'}]})
        self.assertTrue(c.hard_red('send_message', {'target': 'Zoë'}))
        card, _ = c.apply('send_message', {'target': 'Zoë'}, GREEN, categories=('send',))
        self.assertEqual(card['light'], 'red')

    def test_p3_4_abbreviated_long_options(self):
        p, base = self.policy(), {'workdir': '/synthetic/workspace'}
        for command in ('mv --target=/synthetic/outside local', 'mv --targ /synthetic/outside local',
                        'rm --recur build', 'rm --r build'):
            with self.subTest(command=command):
                self.assertIn('scrub', p.classify('terminal', {**base, 'command': command}))

    def test_p3_6_whitespace_only_and_untagged_transform(self):
        from axioma.audit import Audit
        from axioma.whisper import Whisper
        with tempfile.TemporaryDirectory() as tmp:
            w = Whisper(Audit(Path(tmp) / 'a.sqlite3'))
            for text in (' [whisper:assumption][/whisper] ', '\n[whisper:low_confidence]\n'):
                with self.subTest(text=text):
                    out = w.transform(text, session_id='s', platform='cli')
                    self.assertTrue(out and out.strip())
            # Untagged text: return None so the host keeps the original and other plugins' transforms run.
            self.assertIsNone(w.transform('plain text', session_id='s', platform='cli'))

    def test_p3_7_invalid_config_turns_card_red_with_fresh_key(self):
        from axioma.advisor import Advisor
        from axioma.audit import Audit
        with tempfile.TemporaryDirectory() as tmp:
            a = Advisor({}, Audit(Path(tmp) / 'a.sqlite3'), checks_config={'senders': {'x@example.invalid': 'true'}})
            self.assertTrue(a.config_error)
            args = {'text': 'SYNTHETIC'}
            keys = set()
            for i in range(2):
                a.submit({'tool': 'send_message', 'arguments': args, 'card': GREEN}, session_id='s')
                d = a.before('send_message', args, session_id='s', tool_call_id=str(i))
                self.assertIn('STOP', d['message'])
                self.assertIn('axioma_config: fail', d['message'])
                self.assertNotIn('yes', d['message'].lower())
                keys.add(d['rule_key'])
            self.assertEqual(len(keys), 2)

    def test_p3_10_card_staged_under_legacy_cron_name_matches_canonical(self):
        from axioma.advisor import Advisor
        from axioma.audit import Audit
        with tempfile.TemporaryDirectory() as tmp:
            a = Advisor({}, Audit(Path(tmp) / 'a.sqlite3'))
            args = {'action': 'create', 'schedule': 'every 1h', 'prompt': 'x'}
            a.submit({'tool': 'cronjob', 'arguments': args, 'card': GREEN}, session_id='s')
            d = a.before('cronjob_manage', args, session_id='s', tool_call_id='c')
            self.assertIn('GO', d['message'])
            self.assertNotIn('NO CARD', d['message'])

    def test_p3_12_whisper_span_hash_is_salted(self):
        import hashlib
        from axioma.audit import Audit
        from axioma.whisper import Whisper
        with tempfile.TemporaryDirectory() as tmp:
            w = Whisper(Audit(Path(tmp) / 'a.sqlite3'))
            w.transform('[whisper:unverified_figure]42[/whisper] units', session_id='s', platform='cli')
            row = [r for r in w.audit.rows() if r.get('level') == 'whisper'][0]
            self.assertNotEqual(row['span_hash'], hashlib.sha256(b'42').hexdigest())
            self.assertEqual(len(row['span_hash']), 64)


class Pass3Findings(unittest.TestCase):
    """Regressions for docs/review/pass-3.txt (Claude reviewer, A224)."""

    def test_p2_1_rule_key_and_card_name_every_category(self):
        from axioma.advisor import Advisor
        from axioma.audit import Audit
        with tempfile.TemporaryDirectory() as tmp:
            a = Advisor({'workspace': '/syn/ws'}, Audit(Path(tmp) / 'a.sqlite3'))
            push = {'command': 'git push origin main', 'workdir': '/syn/ws'}
            both = {'command': 'git push origin main && mv /syn/ws/a /syn/outside/b', 'workdir': '/syn/ws'}
            keys = []
            for i, args in enumerate((push, both)):
                a.submit({'tool': 'terminal', 'arguments': args, 'card': GREEN}, session_id='s')
                d = a.before('terminal', args, session_id='s', tool_call_id=str(i))
                keys.append(d['rule_key'])
            self.assertTrue(keys[0].startswith('axioma:send:terminal:green:'))
            self.assertTrue(keys[1].startswith('axioma:send+scrub:terminal:green:'))
            self.assertIn('kind: send+scrub', d['message'])

    def test_p2_2_subshell_and_command_substitution_cd(self):
        from axioma.policy import Policy
        p, base = Policy({'workspace': '/syn/ws'}), {'workdir': '/syn/ws'}
        for command in ('(cd /syn/outside; rm f)', '(cd /syn/outside && mv a b)',
                        'x=$(cd /syn/outside; rm f)', '`cd /syn/outside`; rm f',
                        '(rm -rf /syn/ws/x)', 'echo $(rm /syn/outside/f)', '`rm /syn/outside/f`'):
            with self.subTest(command=command):
                self.assertIn('scrub', p.classify('terminal', {**base, 'command': command}))
        self.assertEqual(p.classify('terminal', {**base, 'command': '(rm /syn/ws/f)'}), ())

    def test_p3_3_standing_rule_named_alongside_preflight(self):
        from axioma.checks import Checks
        c = Checks({'deny': [{'tool': '*', 'pattern': 'café'}], 'senders': {'ok@example.invalid': False}})
        card, results = c.apply('send_message', {'text': 'café', 'from': 'ok@example.invalid'}, GREEN,
                                categories=('send',))
        self.assertEqual(card['light'], 'red')
        names = {r['check'] for r in results if not r['pass']}
        self.assertIn('standing_rule', names)
        self.assertIn('sender_rights', names)
        self.assertIn('standing rule', card['signal'].lower())

    def test_p3_5_error_fallback_question_first_on_messaging(self):
        from axioma.advisor import Advisor
        from axioma.audit import Audit
        with tempfile.TemporaryDirectory() as tmp:
            a = Advisor({}, Audit(Path(tmp) / 'a.sqlite3'), surface=lambda: 'telegram')
            a.policy.classify = lambda *x: (_ for _ in ()).throw(RuntimeError('boom'))
            d = a.before('send_message', {}, session_id='s', tool_call_id='c')
            self.assertTrue(d['message'].startswith('What do you need to know'))

    def test_p3_6_quoted_command_names(self):
        from axioma.policy import Policy
        p = Policy({'workspace': '/syn/ws'})
        self.assertIn('scrub', p.classify('terminal', {'command': 'm""v /syn/ws/a /syn/outside/b', 'workdir': '/syn/ws'}))
        self.assertIn('scrub', p.classify('terminal', {'command': "'rm' -r /syn/ws/x", 'workdir': '/syn/ws'}))

    def test_p3_7_cron_run_is_spin(self):
        from axioma.policy import Policy
        for tool in ('cronjob', 'cronjob_manage'):
            self.assertIn('spin', Policy().classify(tool, {'action': 'run'}))

    def test_p3_8_underscore_audiences_count_as_downstream(self):
        from axioma.checks import Checks
        for who in ('all_users', 'public_followers', 'my_clients'):
            with self.subTest(who=who):
                card, _ = Checks({}).apply('send_message', {}, {**GREEN, 'affects': [who], 'told': False},
                                           categories=('send',))
                self.assertEqual(card['light'], 'yellow')

    def test_p3_9_whisper_lookalike_text_is_untouched(self):
        from axioma.audit import Audit
        from axioma.whisper import Whisper
        with tempfile.TemporaryDirectory() as tmp:
            w = Whisper(Audit(Path(tmp) / 'a.sqlite3'))
            self.assertIsNone(w.transform('[whisperer] hi', session_id='s', platform='cli'))


class Pass4Findings(unittest.TestCase):
    """Regressions for docs/review/pass-4.txt (Claude reviewer, A224)."""

    def test_p2_1_action_values_normalized_like_hermes(self):
        from axioma.policy import Policy
        p = Policy()
        for tool, action in (('cronjob_manage', 'Create'), ('cronjob_manage', ' create '),
                             ('cronjob', 'CREATE'), ('delegate_task', None), ('delegate_task', ''),
                             ('delegate_task', 'Spawn')):
            with self.subTest(tool=tool, action=action):
                self.assertIn('spin', p.classify(tool, {'action': action, 'tasks': [{}]}))
        self.assertIn('spin', p.classify('delegate_task', {'tasks': [{}]}))
        self.assertEqual(p.classify('cronjob_manage', {'action': ' List '}), ())

    def test_p2_2_backslash_newline_continuation(self):
        from axioma.policy import Policy
        p, base = Policy({'workspace': '/tmp/ws'}), {'workdir': '/tmp/ws'}
        for command in ('mv /tmp/ws/a \\\n/out/b', 'rm /tmp/ws/a \\\n/out/b',
                        'r\\\nm -r /tmp/ws/a', 'rm\\\n -r /tmp/ws/a'):
            with self.subTest(command=command):
                self.assertIn('scrub', p.classify('terminal', {**base, 'command': command}))

    def test_p3_3_none_session_matches_empty(self):
        from axioma.advisor import Advisor
        from axioma.audit import Audit
        with tempfile.TemporaryDirectory() as tmp:
            a = Advisor({}, Audit(Path(tmp) / 'a.sqlite3'))
            a.submit({'tool': 'send_message', 'arguments': {'t': 1}, 'card': GREEN}, session_id=None)
            self.assertNotIn('NO CARD', a.before('send_message', {'t': 1}, session_id='', tool_call_id='c')['message'])

    def test_p3_4_bad_whisper_settings_do_not_break_registration(self):
        from axioma.audit import Audit
        from axioma.whisper import Whisper
        with tempfile.TemporaryDirectory() as tmp:
            w = Whisper(Audit(Path(tmp) / 'a.sqlite3'), theme='Dark', messaging_marker='false')
            self.assertEqual(w.theme, 'dark')
            self.assertFalse(w.messaging_marker)

    def test_p3_5_whisper_shading_resets_to_default_color(self):
        from axioma.audit import Audit
        from axioma.whisper import Whisper
        with tempfile.TemporaryDirectory() as tmp:
            w = Whisper(Audit(Path(tmp) / 'a.sqlite3'))
            out = w.transform('[whisper:assumption]x[/whisper] y', session_id='s', platform='cli')
            self.assertIn('x (second look)\x1b[39m', out)  # A229: the word rides with the color

    def test_p3_6_rm_without_operands_is_not_proven_contained(self):
        from axioma.policy import Policy
        p = Policy({'workspace': '/tmp/ws'})
        self.assertIn('scrub', p.classify('terminal', {'command': 'echo /out/b | xargs rm', 'workdir': '/tmp/ws'}))


class Pass5Findings(unittest.TestCase):
    """Regressions for docs/review/pass-5.txt (Claude reviewer, A224)."""

    def test_p2_1_cron_run_aliases(self):
        from axioma.policy import Policy
        for action in ('run_now', 'trigger', ' Trigger '):
            with self.subTest(action=action):
                self.assertIn('spin', Policy().classify('cronjob_manage', {'action': action}))

    def test_p2_2_config_error_keeps_the_valid_rules(self):
        from axioma.advisor import Advisor
        from axioma.audit import Audit
        with tempfile.TemporaryDirectory() as tmp:
            a = Advisor({}, Audit(Path(tmp) / 'a.sqlite3'), checks_config={
                'non_reversible': [{'tool': 'change_handle', 'pattern': '.*'}],
                'locks': [{'tool': '*', 'path': 'relative/lock'}]})
            self.assertTrue(a.config_error)
            d = a.before('change_handle', {'handle': 'x'}, session_id='s', tool_call_id='c')
            self.assertIsNotNone(d)
            self.assertIn('STOP', d['message'])
            b = Advisor({'workspace': 'relative', 'add': [{'id': 'buy', 'category': 'spend', 'tool': 'buy_widgets'}]},
                        Audit(Path(tmp) / 'b.sqlite3'))
            self.assertTrue(b.config_error)
            d = b.before('buy_widgets', {}, session_id='s', tool_call_id='c')
            self.assertIsNotNone(d)
            self.assertIn('axioma_config: fail', d['message'])

    def test_p2_3_every_card_gets_a_fresh_rule_key(self):
        from axioma.advisor import Advisor
        from axioma.audit import Audit
        with tempfile.TemporaryDirectory() as tmp:
            a = Advisor({}, Audit(Path(tmp) / 'a.sqlite3'))
            keys = set()
            for i in range(3):
                a.submit({'tool': 'send_message', 'arguments': {'t': 1}, 'card': GREEN}, session_id='s')
                keys.add(a.before('send_message', {'t': 1}, session_id='s', tool_call_id=str(i))['rule_key'])
            self.assertEqual(len(keys), 3, 'a remembered approval must never cover a later call')

    def test_p3_4_case_insensitive_command_names(self):
        from axioma.policy import Policy
        p, base = Policy({'workspace': '/syn/ws'}), {'workdir': '/syn/ws'}
        for command in ('RM -rf /syn/outside', 'MV /syn/ws/a /syn/outside', 'Rm /syn/outside/f', 'CD /x; rm f'):
            with self.subTest(command=command):
                self.assertIn('scrub', p.classify('terminal', {**base, 'command': command}))

    def test_p3_5_indirect_command_names_are_unknown(self):
        from axioma.policy import Policy
        p, base = Policy({'workspace': '/syn/ws'}), {'workdir': '/syn/ws'}
        for command in ('"$(which rm)" -rf /syn/outside', 'x=rm; $x -rf /syn/outside', 'rm${IFS}-rf${IFS}/syn/outside'):
            with self.subTest(command=command):
                self.assertIn('scrub', p.classify('terminal', {**base, 'command': command}))

    def test_p3_6_other_destructive_forms(self):
        from axioma.policy import Policy
        p, base = Policy({'workspace': '/syn/ws'}), {'workdir': '/syn/ws'}
        for command in ('find /syn/outside -delete', 'unlink /syn/outside/f', 'rmdir /syn/outside/d',
                        'rsync -a --delete /syn/ws/ /syn/outside/', 'git clean -fdx',
                        'find /syn -name x -exec rm {} +'):
            with self.subTest(command=command):
                self.assertIn('scrub', p.classify('terminal', {**base, 'command': command}))
        self.assertEqual(p.classify('terminal', {**base, 'command': 'unlink /syn/ws/f'}), ())
        self.assertEqual(p.classify('terminal', {**base, 'command': 'find /syn/ws -name x'}), ())

    def test_p3_7_whitespace_span_on_cli_is_not_blank(self):
        from axioma.audit import Audit
        from axioma.whisper import Whisper
        with tempfile.TemporaryDirectory() as tmp:
            w = Whisper(Audit(Path(tmp) / 'a.sqlite3'))
            self.assertEqual(w.transform('[whisper:assumption]  [/whisper]', session_id='s', platform='cli'),
                             '(empty reply)')


class Pass6Findings(unittest.TestCase):
    """Regressions for docs/review/pass-6.txt (Claude reviewer, A224). The P2 (CLI panel
    truncation) is covered by tests/test_host.py::test_question_and_proceed_survive_the_cli_approval_panel."""

    def test_p3_6_every_sender_field_is_checked(self):
        from axioma.checks import Checks
        c = Checks({'senders': {'ok@example.invalid': True, 'ro@example.invalid': False}})
        card, results = c.apply('send_message', {'sender': 'ok@example.invalid', 'from': 'ro@example.invalid'},
                                GREEN, categories=('send',))
        self.assertEqual(card['light'], 'red')

    def test_p3_5_more_audience_words(self):
        from axioma.checks import Checks
        for who in ('subscribers', 'followers', 'everyone', 'patients'):
            with self.subTest(who=who):
                card, _ = Checks({}).apply('send_message', {}, {**GREEN, 'affects': [who], 'told': False},
                                           categories=('send',))
                self.assertEqual(card['light'], 'yellow')


class Pass7Findings(unittest.TestCase):
    """Regressions for docs/review/pass-7.txt (Claude reviewer, A224)."""

    def test_p2_1_mid_word_hash_is_not_a_comment(self):
        from axioma.policy import Policy
        p, base = Policy({'workspace': '/synthetic/ws'}), {'workdir': '/synthetic/ws'}
        for command in ('rm -f /synthetic/ws/x#; rm -rf /synthetic/outside',
                        'rm /synthetic/ws/a#x /synthetic/outside/b', 'mv /synthetic/ws/a#x /synthetic/outside/b'):
            with self.subTest(command=command):
                self.assertIn('scrub', p.classify('terminal', {**base, 'command': command}))
        self.assertEqual(p.classify('terminal', {**base, 'command': 'rm /synthetic/ws/a # tidy up'}), ())

    def test_p2_2_command_named_by_expansion_is_flagged(self):
        from axioma.policy import Policy
        p, base = Policy({'workspace': '/synthetic/ws'}), {'workdir': '/synthetic/ws'}
        for command in ('$DEL -rf /synthetic/outside', '${DEL} -rf /synthetic/outside',
                        'a=r; ${a}m -rf /synthetic/outside', "$(printf '\\x72m') -rf /synthetic/outside",
                        '`echo r``echo m` -rf /synthetic/outside'):
            with self.subTest(command=command):
                self.assertIn('scrub', p.classify('terminal', {**base, 'command': command}))
        self.assertEqual(p.classify('terminal', {**base, 'command': 'echo $HOME'}), ())

    def test_p3_4_terminal_push_without_sender_field_is_not_sender_checked(self):
        from axioma.checks import Checks
        c = Checks({'senders': {'ok@example.invalid': True}})
        card, results = c.apply('terminal', {'command': 'git push origin main'}, GREEN, categories=('send',))
        self.assertFalse(any(r['check'] == 'sender_rights' for r in results))
        card, _ = c.apply('send_message', {}, GREEN, categories=('send',))
        self.assertEqual(card['light'], 'red', 'a messaging send with no sender still fails')

    def test_p3_5_only_real_whisper_markers_are_stripped(self):
        from axioma.audit import Audit
        from axioma.whisper import Whisper
        with tempfile.TemporaryDirectory() as tmp:
            w = Whisper(Audit(Path(tmp) / 'a.sqlite3'))
            self.assertIsNone(w.transform('array[whisper] = 1', session_id='s', platform='cli'))
            self.assertIsNone(w.transform('see [whisper:]', session_id='s', platform='cli'))



class Pass8Limits(unittest.TestCase):
    """docs/review/pass-8.txt findings 1-2, kept as tests that DOCUMENT the parser's limit.

    AXIOM decision (A229): SCRUB is best-effort shell parsing, not a shell interpreter. When the
    command has a shape the token walk cannot read (a quoted or escaped separator inside a remove
    or move, or a command word built from an expansion behind a prefix or quotes), the call is still
    classified SCRUB and the card says "could not parse" and is capped at CAUTION: never GO.
    """
    WS = {'workspace': '/synthetic/ws'}

    def test_p2_1_quoted_or_escaped_separators_are_could_not_parse(self):
        from axioma.policy import Policy
        p = Policy(self.WS)
        for command in ("rm /synthetic/ws/a '#' -rf /synthetic/outside",
                        'rm /synthetic/ws/a \\# -rf /synthetic/outside',
                        "rm /synthetic/ws/a '|' -rf /synthetic/outside",
                        "rm /synthetic/ws/a ';' -rf /synthetic/outside",
                        "mv /synthetic/ws/a '&' /synthetic/outside",
                        "rm /synthetic/ws/a '#b'"):
            with self.subTest(command=command):
                args = {'command': command}
                self.assertEqual(p.classify('terminal', args), ('scrub',))
                self.assertTrue(p.unparsed('terminal', args))

    def test_p2_2_expansion_named_commands_behind_prefixes_are_could_not_parse(self):
        from axioma.policy import Policy
        p = Policy({})
        for command in ('"$DEL" -rf /synthetic/outside', "\"$(printf '\\x72m')\" -rf /synthetic/outside",
                        'if true; then $DEL -rf /synthetic/outside; fi', '{ $DEL -rf /synthetic/outside; }',
                        '! $DEL -rf /synthetic/outside', 'time $DEL -rf /synthetic/outside',
                        'sudo $DEL -rf /synthetic/outside', 'sudo -u x "$DEL" -rf /synthetic/outside'):
            with self.subTest(command=command):
                args = {'command': command}
                self.assertEqual(p.classify('terminal', args), ('scrub',))
                self.assertTrue(p.unparsed('terminal', args))

    def test_could_not_parse_caps_the_card_at_caution_never_go(self):
        from axioma.advisor import Advisor
        from axioma.audit import Audit
        with tempfile.TemporaryDirectory() as tmp:
            a = Advisor(self.WS, Audit(Path(tmp) / 'a.sqlite3'), surface=lambda: 'cli')
            args = {'command': "rm /synthetic/ws/a ';' -rf /synthetic/outside"}
            a.submit({'tool': 'terminal', 'arguments': args, 'card': GREEN}, session_id='s')
            message = a.before('terminal', args, session_id='s', tool_call_id='c1')['message']
            self.assertTrue(message.startswith('CAUTION'), message)
            self.assertNotIn('GO', message.split('\n')[0])
            self.assertIn('scrub_parse: could not parse (best-effort parser)', message)
            red = {**GREEN, 'light': 'red'}
            a.submit({'tool': 'terminal', 'arguments': args, 'card': red}, session_id='s')
            self.assertTrue(a.before('terminal', args, session_id='s', tool_call_id='c2')['message'].startswith('STOP'))

    def test_not_noisier_plain_commands_are_unchanged(self):
        from axioma.policy import Policy
        p = Policy(self.WS)
        base = {'workdir': '/synthetic/ws'}
        for command in ('rm /synthetic/ws/a', 'echo "a;b" && ls', "grep -n 'x|y' file", 'sudo ls',
                        'time make', 'echo $HOME', 'rm /synthetic/ws/a # tidy up',
                        '"$HOME/.local/bin/tool" --version', 'mv /synthetic/ws/a.txt "/synthetic/ws/b (copy).txt"',
                        'rm "/synthetic/ws/(x)"', 'rm -- "/synthetic/ws/#notes"',
                        'git commit -m "rm stale files; tidy"', 'sudo -u x "$HOME/bin/tool"',
                        'TS=$(date +%s); echo "$TS"', 'VERSION=$(cat VERSION) && echo $VERSION',
                        'PYTHONPATH="$PWD" python3 -m pytest -q', 'OUT=$(mktemp) && ls > "$OUT"', 'X=1 Y=$Z make',
                        'cat > notes.txt <<EOF\n$HOME is here\nEOF', 'python3 - <<EOF\nprint("$USER")\nEOF',
                        "cat <<'EOF' > x.md\nrm stuff; done\n$DEL -rf /\nEOF", 'tee a.txt <<-END\n\t$X\n\tEND'):
            with self.subTest(command=command):
                args = {**base, 'command': command}
                self.assertEqual(p.classify('terminal', args), ())
                self.assertFalse(p.unparsed('terminal', args))

    def test_literal_remover_behind_an_expanded_directory_is_still_read(self):
        from axioma.policy import Policy
        p = Policy(self.WS)
        base = {'workdir': '/synthetic/ws'}
        for command in ('$BIN/rm -rf /synthetic/outside', '"$BIN/rm" /synthetic/outside/f',
                        'sudo $BIN/mv /synthetic/ws/a /synthetic/outside'):
            with self.subTest(command=command):
                self.assertEqual(p.classify('terminal', {**base, 'command': command}), ('scrub',))
        self.assertEqual(p.classify('terminal', {**base, 'command': '"$BIN/rm" /synthetic/ws/a'}), ())
        # pass 10: an UNQUOTED expansion is word-split by the shell ($V='/bin/rm -rf /etc #'), so a
        # literal last component does not name the command there; it stays could-not-parse.
        for command in ('$V/tool', '$BIN/rm /synthetic/ws/a'):
            with self.subTest(command=command):
                args = {**base, 'command': command}
                self.assertEqual(p.classify('terminal', args), ('scrub',))
                self.assertTrue(p.unparsed('terminal', args))

    def test_heredoc_into_a_shell_is_still_read(self):
        from axioma.policy import Policy
        p = Policy(self.WS)
        for command in ('bash <<EOF\nrm -rf /synthetic/outside\nEOF', 'sh -s <<EOF\n$DEL -rf /synthetic/outside\nEOF',
                        'cat <<EOF\nx\nEOF\nrm -rf /synthetic/outside'):
            with self.subTest(command=command):
                self.assertEqual(p.classify('terminal', {'workdir': '/synthetic/ws', 'command': command}), ('scrub',))

    def test_p3_xargs_remove_and_rmdir_parents(self):
        from axioma.policy import Policy
        p = Policy(self.WS)
        base = {'workdir': '/synthetic/ws'}
        for command in ('echo /synthetic/outside/g | xargs rm /synthetic/ws/b', 'rmdir -p /synthetic/ws/a'):
            with self.subTest(command=command):
                self.assertEqual(p.classify('terminal', {**base, 'command': command}), ('scrub',))


class Pass12Findings(unittest.TestCase):
    """docs/review/pass-12.txt P2-4: a heredoc skip must never hide a command the shell runs."""

    def test_heredoc_bodies_that_reach_a_shell_or_run_expansions_are_read(self):
        from axioma.policy import Policy
        for p in (Policy({}), Policy({'workspace': '/synthetic/ws'})):
            for command in ("cat <<'EOF' | bash\nrm -rf /synthetic/outside\nEOF",
                            'cat <<EOF | ssh prod bash\nrm -rf /synthetic/outside\nEOF',
                            'cat <<EOF > /synthetic/ws/out.txt\nbuilt on $(rm -rf /synthetic/outside)\nEOF',
                            'cat <<EOF-1\nhi\nEOF-1\nrm -rf /synthetic/outside',
                            'cat <<E""OF\nhi\nEOF\nrm -rf /synthetic/outside',
                            'cat <<EOF.md\nhi\nEOF.md\nmv /synthetic/ws/a /synthetic/outside/b'):
                with self.subTest(command=command[:24]):
                    self.assertEqual(p.classify('terminal', {'workdir': '/synthetic/ws', 'command': command}), ('scrub',))

    def test_plain_data_heredocs_stay_quiet(self):
        from axioma.policy import Policy
        p = Policy({'workspace': '/synthetic/ws'})
        for command in ("cat <<'EOF' > /synthetic/ws/notes.md\nrm -rf is dangerous; mv carefully\nEOF",
                        'cat <<EOF > /synthetic/ws/notes.md\nremember: rm old files\nEOF'):
            with self.subTest(command=command[:24]):
                self.assertEqual(p.classify('terminal', {'workdir': '/synthetic/ws', 'command': command}), ())


class Pass13Findings(unittest.TestCase):
    """docs/review/pass-13.txt: heredoc skipping must fail toward reading."""

    def test_heredocs_that_do_not_exist_or_reach_a_shell_are_read(self):
        from axioma.policy import Policy
        for p in (Policy({}), Policy({'workspace': '/synthetic/ws'})):
            for command in ("cat <<'EOF' > >(bash)\nrm -rf /synthetic/outside\nEOF",
                            "tee >(bash) <<'EOF'\nrm -rf /synthetic/outside\nEOF",
                            'cat "<<EOF"\nrm -rf /synthetic/outside\nEOF',
                            "cat '<<EOF'\nrm -rf /synthetic/outside\nEOF",
                            'cat x # <<EOF\nrm -rf /synthetic/outside\nEOF',
                            "cat > /synthetic/ws/clean.sh <<'EOF'\nrm -rf /synthetic/outside\nEOF\nbash /synthetic/ws/clean.sh",
                            "cat > /synthetic/ws/c.sh <<'EOF'\nrm -rf /synthetic/outside\nEOF\nchmod +x c.sh && ./c.sh"):
                with self.subTest(command=command[:28]):
                    self.assertEqual(p.classify('terminal', {'workdir': '/synthetic/ws', 'command': command}), ('scrub',))


class Pass14Findings(unittest.TestCase):
    """docs/review/pass-14.txt P2-2. AXIOM decision: a heredoc body is skipped only when the whole
    command is that one heredoc and nothing else can read it; every other shape reads the body."""

    def test_bodies_reached_by_later_lines_or_groups_are_read(self):
        from axioma.policy import Policy
        for p in (Policy({}), Policy({'workspace': '/synthetic/ws'})):
            for command in ("{\ncat <<'EOF'\nrm -rf /synthetic/outside\nEOF\n} | bash",
                            "(\ncat <<'EOF'\nrm -rf /synthetic/outside\nEOF\n) | sh",
                            "exec > >(bash)\ncat <<'EOF'\nrm -rf /synthetic/outside\nEOF",
                            "cat <<'EOF' >&3\nrm -rf /synthetic/outside\nEOF",
                            "for i in 1; do cat <<'EOF'\nrm -rf /synthetic/outside\nEOF\ndone | bash"):
                with self.subTest(command=command[:24]):
                    self.assertEqual(p.classify('terminal', {'workdir': '/synthetic/ws', 'command': command}), ('scrub',))

    def test_single_data_heredoc_stays_quiet(self):
        from axioma.policy import Policy
        p = Policy({'workspace': '/synthetic/ws'})
        for command in ("cat <<'EOF' > /synthetic/ws/notes.md\nrm -rf is dangerous; mv carefully\nEOF",
                        "cat > /synthetic/ws/notes.md <<'EOF'\nremember: rm old files\nEOF\n",
                        "tee /synthetic/ws/a.txt <<'EOF'\nrm later\nEOF"):
            with self.subTest(command=command[:24]):
                self.assertEqual(p.classify('terminal', {'workdir': '/synthetic/ws', 'command': command}), ())


class Pass15Findings(unittest.TestCase):
    """docs/review/pass-15.txt P2-3: a backslash-newline in a quoted heredoc body is literal."""

    def test_backslash_newline_in_a_heredoc_body_is_never_skipped(self):
        from axioma.policy import Policy
        for p in (Policy({}), Policy({'workspace': '/synthetic/ws'})):
            for command in ("cat <<'EOF'\nx\\\nEOF\nrm -rf /synthetic/outside\nEOF",
                            "cat <<EOF\nx\\\nEOF\nrm -rf /synthetic/outside\nEOF"):
                with self.subTest(command=command[:20]):
                    self.assertEqual(p.classify('terminal', {'workdir': '/synthetic/ws', 'command': command}), ('scrub',))


class Pass17Findings(unittest.TestCase):
    def test_rsync_delete_aliases_are_scrub(self):
        from axioma.policy import Policy
        p = Policy({'workspace': '/synthetic/ws'})
        for command in ('rsync -a --del /synthetic/ws/ /synthetic/outside/',
                        'rsync -a --delete-after /synthetic/ws/ /synthetic/outside/',
                        'rsync -a --delete-excluded /synthetic/ws/ /synthetic/outside/'):
            with self.subTest(command=command):
                self.assertEqual(p.classify('terminal', {'workdir': '/synthetic/ws', 'command': command}), ('scrub',))
        self.assertEqual(p.classify('terminal', {'workdir': '/synthetic/ws',
                                                 'command': 'rsync -a --delay-updates /synthetic/ws/ /synthetic/ws2/'}), ())


class Pass18Findings(unittest.TestCase):
    def test_heredoc_skip_needs_the_bare_data_sink_word(self):
        from axioma.policy import Policy
        p = Policy({'workspace': '/synthetic/ws'})
        command = "/synthetic/tmp/cat <<'EOF'\nrm -rf /synthetic/outside\nEOF"
        self.assertEqual(p.classify('terminal', {'workdir': '/synthetic/ws', 'command': command}), ('scrub',))
        self.assertEqual(p.classify('terminal', {'workdir': '/synthetic/ws',
                                                 'command': "cat > notes.txt <<'EOF'\nrm -rf is a word here\nEOF"}), ())


class Pass19Findings(unittest.TestCase):
    """docs/review/pass-19.txt P2-2: brace or glob expansion in the command word hides the name.
    Strings passed to Policy.classify only; nothing is executed."""
    HIDDEN = ('{rm,-rf,/synthetic/outside}', 'sudo {rm,-f,/synthetic/x}', '{mv,/synthetic/a,/synthetic/b}',
              'echo ok; {rmdir,-p,/synthetic/a/b}', 'r{m,} -f /synthetic/x', 'rm{,} /synthetic/x',
              '/bin/r? -rf /synthetic/outside', '/bin/r[m] -f /synthetic/x', '/bin/m? /synthetic/a /synthetic/b',
              '/bin/r* -rf /synthetic/outside')
    QUIET = ('[ -f notes.txt ] && echo yes', '[[ -d build ]] && ls build', '{ echo a; echo b; } > out.txt',
             'ls *.py', 'echo {a,b}', 'git status', 'cp src/*.txt dst/')

    def test_brace_or_glob_in_the_command_word_is_flagged_and_could_not_parse(self):
        from axioma.policy import Policy
        for label, p in (('no-ws', Policy()), ('ws', Policy({'workspace': '/synthetic/ws'}))):
            for command in self.HIDDEN:
                with self.subTest(policy=label, command=command):
                    args = {'workdir': '/synthetic/ws', 'command': command}
                    self.assertEqual(p.classify('terminal', args), ('scrub',))
                    self.assertTrue(p.unparsed('terminal', args))

    def test_ordinary_brackets_braces_and_globs_stay_quiet(self):
        from axioma.policy import Policy
        p = Policy({'workspace': '/synthetic/ws'})
        for command in self.QUIET:
            with self.subTest(command=command):
                args = {'workdir': '/synthetic/ws', 'command': command}
                self.assertEqual(p.classify('terminal', args), ())
                self.assertFalse(p.unparsed('terminal', args))


class Pass20Findings(unittest.TestCase):
    """docs/review/pass-20.txt P3-1: the pass-19 glob rule must not flag heredoc bodies, case
    patterns or markdown lines whose glob cannot name a remover. Strings only; nothing is executed."""
    QUIET = ('case "$f" in\n  *.py) echo py ;;\n  *) echo other ;;\nesac',
             'read a; case "$a" in\n[yY]) echo yes ;;\nesac',
             "sudo tee /etc/systemd/system/x.service <<'EOF'\n[Unit]\nDescription=x\nEOF",
             "cat > pyproject.toml <<'EOF'\n[project]\nname = \"x\"\nEOF\necho done",
             "mkdir -p cfg && cat > cfg/a.toml <<'EOF'\n[tool]\nEOF",
             "cat <<'EOF' | tee a.ini\n[core]\nEOF",
             "cat > notes.md <<'EOF'\n* item one\n* item two\nEOF\necho done")

    def test_globs_that_cannot_name_a_remover_stay_quiet(self):
        from axioma.policy import Policy
        p = Policy({'workspace': '/synthetic/ws'})
        for command in self.QUIET:
            with self.subTest(command=command):
                args = {'workdir': '/synthetic/ws', 'command': command}
                self.assertEqual(p.classify('terminal', args), ())
                self.assertFalse(p.unparsed('terminal', args))


if __name__ == '__main__':
    unittest.main()
