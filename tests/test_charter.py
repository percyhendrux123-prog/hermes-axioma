from fnmatch import fnmatchcase
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from axioma import charter  # noqa: E402
from axioma.audit import Audit  # noqa: E402
from axioma.advisor import Advisor  # noqa: E402
from axioma.checks import Checks  # noqa: E402
from axioma.policy import DEFAULTS, Policy  # noqa: E402

EMPTY = {'policy': {}, 'checks': {}}
PROBES = {
    'policy.add': ('add', [{'id': 'p', 'category': 'spend', 'tool': 'buy_widgets'}]),
    'policy.remove': ('remove', ['scrub']),
    'policy.workspace': ('workspace', '/Users/example/projects/demo'),
    'policy.output_dir': ('output_dir', '/Users/example/projects/demo/output'),
    'checks.deny': ('deny', [{'tool': '*send*', 'pattern': 'x'}]),
    'checks.non_reversible': ('non_reversible', [{'tool': '*send*', 'pattern': 'x'}]),
    'checks.senders': ('senders', {'a@example.invalid': True}),
}


def full_answers(**changes):
    answers = dict((q['id'], q['example']) for q in charter.QUESTIONS)
    answers['skip_inside'] = 'yes'
    answers.update(changes)
    return answers


def categories(settings, calls):
    policy = Policy(settings['policy'])
    return [policy.classify(tool, args) for tool, args in calls]


CALLS = [
    ('send_message', {'target': 'x'}), ('connectors__gmail__send_email', {}), ('post_tweet', {}),
    ('mcp__stripe__create_payment', {}), ('mcp__stripe__create_refund', {}), ('cronjob', {'action': 'create'}),
    ('delegate_task', {'tasks': [{}]}), ('kanban_create', {}), ('terminal', {'command': 'git push origin main'}),
    ('terminal', {'command': 'netlify deploy --prod'}), ('terminal', {'command': 'rm -rf /tmp/anything'}),
    ('terminal', {'command': 'rm notes.txt'}), ('terminal', {'command': 'mv /a/b /c/d'}),
    ('terminal', {'command': 'rm /Users/example/projects/demo/old.txt'}),
    ('read_file', {}), ('terminal', {'command': 'ls'}),
]



def loaded_settings(yaml, text):
    """The settings a YAML reader gets from the file. An empty block is left out of the file on
    purpose (a pasted `policy: {}` would erase a live policy), so it is filled in here."""
    loaded = yaml.safe_load(text) or {}
    found = loaded.get('plugins', {}).get('entries', {}).get('hermes-axioma', {}).get('settings', {})
    return dict({'policy': {}, 'checks': {}}, **found)


class QuestionTests(unittest.TestCase):
    def test_plain_english_and_complete(self):
        qs = charter.questions()
        self.assertTrue(8 <= len(qs) <= 12)
        self.assertEqual(len(set(q['id'] for q in qs)), len(qs))
        for q in qs:
            with self.subTest(q=q['id']):
                for key in ('id', 'ask', 'shape', 'example', 'maps_to', 'ask_when'):
                    self.assertTrue(q[key], key)
                self.assertTrue(q['ask'].rstrip().endswith(('.', '?', '"')))
                for jargon in ('regex', 'glob', 'yaml', 'json', 'fnmatch', 'category', 'rule id', 'sqlite'):
                    self.assertNotIn(jargon, q['ask'].lower())

    def test_every_question_maps_to_a_setting_the_plugin_reads(self):
        for q in charter.QUESTIONS:
            for target in q['maps_to']:
                with self.subTest(q=q['id'], target=target):
                    self.assertIn(target, PROBES, 'unverified setting')
                    key, sample = PROBES[target]
                    block, validator = target.split('.')[0], (Policy if target.startswith('policy.') else Checks)
                    validator({key: sample})  # the plugin accepts this key...
                    with self.assertRaises(ValueError):
                        validator({'not_a_real_key': sample})  # ...and rejects an invented one

    def test_every_mapped_setting_appears_in_the_example_compile(self):
        settings = charter.compile_charter(full_answers(scrub='turn off'))['settings']
        for q in charter.QUESTIONS:
            for target in q['maps_to']:
                block, key = target.split('.')
                with self.subTest(target=target):
                    self.assertIn(key, settings[block])

    def test_action_tools_cover_every_default_tool_rule(self):
        for rule in DEFAULTS:
            if rule['tool'] != 'terminal':
                with self.subTest(rule=rule['id']):
                    self.assertTrue(any(fnmatchcase(rule['tool'], g) for g in charter.ACTION_TOOLS))


class CompileTests(unittest.TestCase):
    def test_full_example_is_accepted_by_the_plugin_validators(self):
        result = charter.compile_charter(full_answers())
        self.assertEqual(result['problems'], [])
        self.assertTrue(result['complete'])
        self.assertEqual(set(result['settings']), {'policy', 'checks'})
        Policy(result['settings']['policy'])
        Checks(result['settings']['checks'])
        self.assertFalse(Policy.lenient(result['settings']['policy'])[1])
        self.assertFalse(Checks.lenient(result['settings']['checks'])[1])
        with tempfile.TemporaryDirectory() as tmp:
            advisor = Advisor(result['settings']['policy'], Audit(Path(tmp) / 'a.sqlite3'),
                              checks_config=result['settings']['checks'])
            self.assertFalse(advisor.config_error, 'would turn every card RED with axioma_config: fail')

    def test_compiled_rules_do_what_the_charter_says(self):
        settings = charter.compile_charter(full_answers())['settings']
        policy, checks = Policy(settings['policy']), Checks(settings['checks'])
        self.assertEqual(policy.classify('buy_widgets', {}), ('spend',))
        self.assertEqual(policy.classify('schedule_report', {}), ('spin',))
        self.assertEqual(policy.classify('terminal', {'command': 'rm /Users/example/projects/demo/old.txt'}), ())
        self.assertEqual(policy.classify('terminal', {'command': 'rm /Users/example/other/old.txt'}), ('scrub',))
        self.assertTrue(checks.hard_red('send_message', {'target': 'JORDAN EXAMPLE'}))
        self.assertTrue(checks.hard_red('connectors__gmail__send_email', {'to': 'legal@example.invalid'}))
        self.assertTrue(checks.hard_red('terminal', {'command': 'deploy to prod-database'}))
        self.assertTrue(checks.hard_red('mcp__x__create_payment', {'note': 'close-account'}))
        self.assertFalse(checks.hard_red('read_file', {'path': 'prod-database'}), 'reads are not scoped in')
        self.assertFalse(checks.hard_red('send_message', {'target': 'someone else'}))
        card = {'intent': 'i', 'light': 'green', 'signal': 's', 'question': 'q?', 'affects': ['me']}
        _, results = checks.apply('send_message', {'target': 't', 'sender': 'other@example.invalid'}, card, ('send',))
        self.assertEqual([r for r in results if r['check'] == 'sender_rights'], [{'check': 'sender_rights', 'pass': False}])
        _, results = checks.apply('send_message', {'sender': 'Assistant@Example.invalid'}, card, ('send',))
        self.assertTrue(all(r['pass'] for r in results if r['check'] == 'sender_rights'))

    def test_special_characters_in_a_word_still_match_literally(self):
        settings = charter.compile_charter({'deny_words': ['a.b', 'say "hi"', 'back\\slash', '(x)']})['settings']
        checks = Checks(settings['checks'])
        for text in ('a.b', 'say "hi"', 'back\\slash', '(x)', 'A.B'):
            self.assertTrue(checks.hard_red('terminal', {'command': text}), text)
        self.assertFalse(checks.hard_red('terminal', {'command': 'aXb'}))

    def test_bad_answers_make_no_rule_and_name_a_problem(self):
        bad = {
            'never_message': [None, 123, [], '', '   ', {}, 'x' * 121, ['a', 5], 'bad\x07', ['ok', ''], 7.5,
                              ['n%d' % i for i in range(21)]],
            'senders': [None, [], '', 'none', 'maybe me', ['two words@example.invalid'], 5, ['a\x00']],
            'spend_tools': [None, [], '', 'rm -rf /', '*', '**', 'a b', ['ok_tool', 'bad tool'], 5, 'x'],
            'spin_tools': [None, [], '', '*', '??', 'a;b', 7],
            'scrub': [None, '', 'maybe', 'off please', 'remove it', 'no', 'yes', True, ['turn off'], 5],
            'deny_words': [None, [], '', 7, {'a': 1}, ['x', None]],
            'never_undo': [None, [], '', 7, ['\n']],
        }
        for qid, values in bad.items():
            for value in values:
                with self.subTest(qid=qid, value=value):
                    result = charter.compile_charter({qid: value})
                    self.assertEqual(result['settings'], EMPTY)
                    self.assertIn(qid, [p['question'] for p in result['problems']])

    def test_bad_folders_make_no_rule(self):
        bad = [None, 5, '', 'relative/dir', '~/work', '/', '/work', '/Users', '/Users/example', '/home/example',
               '/a/../b/c', '/x/y/\x07', ['/a/b/c']]
        for qid in ('workspace', 'output_dir'):
            for value in bad:
                with self.subTest(qid=qid, value=value):
                    result = charter.compile_charter({qid: value, 'skip_inside': 'yes'})
                    self.assertEqual(result['settings'], EMPTY)
                    self.assertIn(qid, [p['question'] for p in result['problems']])

    def test_folder_needs_an_explicit_yes(self):
        folder = {'workspace': '/Users/example/projects/demo'}
        for value in (None, '', 'maybe', 'sure', 5, ['yes'], 'no', 'NO', False):
            with self.subTest(skip_inside=value):
                answers = dict(folder, skip_inside=value) if value is not None else dict(folder)
                result = charter.compile_charter(answers)
                self.assertNotIn('workspace', result['settings']['policy'])
                if value in ('no', 'NO', False):
                    self.assertNotIn('skip_inside', [p['question'] for p in result['problems']])
                else:
                    self.assertIn('skip_inside', [p['question'] for p in result['problems']])
        for value in ('yes', 'YES', ' Yes ', True):
            result = charter.compile_charter(dict(folder, skip_inside=value))
            self.assertEqual(result['settings']['policy']['workspace'], folder['workspace'])

    def test_missing_answers_are_problems_not_rules(self):
        result = charter.compile_charter({})
        self.assertEqual(result['settings'], EMPTY)
        named = set(p['question'] for p in result['problems'])
        self.assertEqual(named, set(charter.IDS) - {'skip_inside'})
        self.assertFalse(result['complete'])
        self.assertEqual(charter.compile_charter(None)['settings'], EMPTY)
        self.assertEqual(charter.compile_charter('yes')['settings'], EMPTY)

    def test_unknown_question_id_is_named_and_ignored(self):
        result = charter.compile_charter(dict(full_answers(), remove=['scrub'], invented='x'))
        self.assertEqual(sorted(p['question'] for p in result['problems']), ['unknown key invented', 'unknown key remove'])
        self.assertNotIn('remove', result['settings']['policy'])

    def test_a_partly_bad_set_keeps_only_the_good_answers(self):
        result = charter.compile_charter(full_answers(spend_tools='*', senders='no limit'))
        self.assertEqual([p['question'] for p in result['problems']], ['spend_tools'])
        self.assertNotIn('senders', result['settings']['checks'])
        self.assertEqual([r['id'] for r in result['settings']['policy']['add']], ['charter-spin-1'])

    def test_none_answers_are_not_problems(self):
        answers = {'never_message': 'none', 'senders': 'no limit', 'spend_tools': 'None', 'scrub': 'keep',
                   'workspace': 'none', 'output_dir': 'none', 'spin_tools': ['none'], 'deny_words': 'nothing',
                   'never_undo': 'none'}
        result = charter.compile_charter(answers)
        self.assertEqual(result['problems'], [])
        self.assertEqual(result['settings'], EMPTY)

    def test_senders_none_is_not_read_as_no_limit(self):
        result = charter.compile_charter({'senders': 'none'})
        self.assertIn('senders', [p['question'] for p in result['problems']])

    def test_no_answer_set_drops_a_default_rule_without_an_explicit_answer(self):
        junk = [None, '', 'maybe', 'no', 'yes', 'off', 'remove', 5, True, False, [], ['turn off'], 'turn offf',
                'turn-off', 'turn_off', 'turnoff',
                'keep', 'none', '/Users/example/projects/demo', ['a_tool'], 'x@example.invalid']
        explicit_removal = ('turn off',)
        for scrub, skip, folder in itertools.product(junk + ['turn off'], junk + ['yes'], junk):
            other = 'maybe'
            answers = {'scrub': scrub, 'skip_inside': skip, 'workspace': folder, 'output_dir': folder,
                       'spend_tools': other, 'spin_tools': other, 'never_message': other, 'senders': other,
                       'deny_words': other, 'never_undo': other}
            result = charter.compile_charter(answers)
            policy = result['settings']['policy']
            said_turn_off = isinstance(scrub, str) and ' '.join(scrub.lower().split()) in explicit_removal
            if said_turn_off:
                self.assertEqual(policy['remove'], ['scrub'])
            else:
                self.assertNotIn('remove', policy, answers)
            said_yes = isinstance(skip, (str, bool)) and str(skip).strip().lower() in ('yes', 'true')
            if not said_yes:
                self.assertFalse(set(policy) & {'workspace', 'output_dir'}, answers)
            if not said_turn_off and not set(policy) & {'workspace', 'output_dir'}:
                # Without those two answers the compiled policy classifies at least what the default does.
                for default, compiled in zip(categories(EMPTY, CALLS), categories(result['settings'], CALLS)):
                    self.assertTrue(set(default) <= set(compiled), answers)

    def test_only_the_scrub_answer_ever_changes_remove_and_it_removes_only_scrub(self):
        policy = charter.compile_charter(full_answers(scrub='turn off'))['settings']['policy']
        self.assertEqual(policy['remove'], ['scrub'])
        self.assertEqual(Policy(policy).classify('terminal', {'command': 'rm -rf /tmp/x'}), ())
        self.assertEqual(Policy(policy).classify('send_message', {}), ('send',))

    def test_deterministic_and_fingerprinted(self):
        a = charter.compile_charter(full_answers())
        shuffled = dict(reversed(list(full_answers().items())))
        b = charter.compile_charter(shuffled)
        self.assertEqual(a, b)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        digest = hashlib.sha256(json.dumps(a['settings'], sort_keys=True, separators=(',', ':'),
                                           ensure_ascii=True).encode()).hexdigest()[:12]
        self.assertEqual(a['fingerprint'], 'AXC-' + digest)
        self.assertIn(a['fingerprint'], a['charter'])
        self.assertIn(a['fingerprint'], a['settings_yaml'])
        c = charter.compile_charter(full_answers(deny_words=['something_else']))
        self.assertNotEqual(a['fingerprint'], c['fingerprint'])

    def test_charter_is_honest_and_one_page(self):
        text = charter.compile_charter(full_answers())['charter']
        low = text.lower()
        for word in ('enforce', 'blocked', 'guarantee', 'prevents'):
            self.assertNotIn(word, low)
        self.assertIn('rules the axiōma card warns on', low)
        self.assertIn('nothing on this page has been applied', low)
        self.assertLessEqual(len(text.splitlines()), 60)
        for number, qid in enumerate(charter.IDS, 1):
            self.assertIn('%d. (%s)' % (number, qid), text, 'every answer has a traceable line')

    def test_yaml_matches_settings_when_a_yaml_reader_is_present(self):
        try:
            import yaml
        except ImportError:
            self.skipTest('PyYAML not installed')
        for answers in (full_answers(), full_answers(scrub='turn off', deny_words=['ü "q"', 'a: b']), {}):
            result = charter.compile_charter(answers)
            self.assertEqual(loaded_settings(yaml, result['settings_yaml']), result['settings'])


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.dir = self.home / 'plugin-data' / 'charter'
        self.call = charter.make_handler(lambda: self.dir)

    def run_tool(self, **args):
        return json.loads(self.call(args))

    def assertNothingApplied(self, out):
        self.assertIs(out['applied'], False)
        self.assertIn('Nothing was applied', out['note'])
        self.assertIn('by hand', out['note'])
        self.assertIn('no config.yaml', out['note'])

    def test_questions_action(self):
        out = self.run_tool(action='questions')
        self.assertEqual([q['id'] for q in out['questions']], charter.IDS)
        self.assertIn('one at a time', out['intro'])
        self.assertNothingApplied(out)
        self.assertFalse(self.dir.exists(), 'asking questions writes nothing')

    def test_compile_writes_exactly_two_files_inside_the_charter_dir(self):
        before = sorted(p for p in self.home.rglob('*'))
        out = self.run_tool(action='compile', answers=full_answers())
        self.assertNothingApplied(out)
        self.assertEqual(out['status'], 'compiled')
        self.assertEqual(out['problems'], [])
        after = sorted(p for p in self.home.rglob('*') if p not in before)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ['CHARTER.md', 'charter-settings.yaml'])
        self.assertEqual(sorted(str(p) for p in after),
                         sorted([str(self.home / 'plugin-data'), str(self.dir), str(self.dir / 'CHARTER.md'),
                                 str(self.dir / 'charter-settings.yaml')]))
        self.assertEqual(sorted(out['files']), sorted(str(p) for p in self.dir.iterdir()))
        self.assertEqual((self.dir / 'CHARTER.md').read_text(encoding='utf-8'), out['charter'])
        self.assertEqual((self.dir / 'charter-settings.yaml').read_text(encoding='utf-8'), out['settings_yaml'])
        if os.name == 'posix':
            self.assertEqual((self.dir / 'CHARTER.md').stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.dir.stat().st_mode & 0o777, 0o700)

    def test_a_second_compile_replaces_the_files_and_leaves_no_temp_file(self):
        self.run_tool(action='compile', answers=full_answers())
        out = self.run_tool(action='compile', answers=full_answers(deny_words='something_else'))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ['CHARTER.md', 'charter-settings.yaml'])
        self.assertIn(out['fingerprint'], (self.dir / 'CHARTER.md').read_text(encoding='utf-8'))

    def test_the_caller_cannot_pick_a_path(self):
        for extra in ({'path': str(self.home / 'elsewhere')}, {'dir': '/'}, {'output': 'x'}):
            out = self.run_tool(action='compile', answers=full_answers(), **extra)
            self.assertIn('error', out)
            self.assertNothingApplied(out)
        self.assertFalse(self.dir.exists())

    def test_preview_writes_nothing(self):
        out = self.run_tool(action='compile', answers=full_answers(), preview=True)
        self.assertEqual(out['files'], [])
        self.assertIn('Axiōma Charter', out['charter'])
        self.assertFalse(self.dir.exists())
        self.assertNothingApplied(out)

    def test_compile_with_problems_still_says_so_and_applies_nothing(self):
        out = self.run_tool(action='compile', answers={'scrub': 'maybe'})
        self.assertFalse(out['complete'])
        self.assertIn('scrub', [p['question'] for p in out['problems']])
        self.assertNothingApplied(out)

    def test_show_and_the_slash_command(self):
        command = charter.command(lambda: self.dir)
        none = self.run_tool(action='show')
        self.assertEqual(none['status'], 'none')
        self.assertNothingApplied(none)
        self.assertIn('interview', command(''))
        self.assertIn('Nothing is applied', command(''))
        compiled = self.run_tool(action='compile', answers=full_answers())
        shown = self.run_tool(action='show')
        self.assertEqual(shown['status'], 'shown')
        self.assertEqual(shown['charter'], compiled['charter'])
        self.assertTrue(shown['files_match'])
        self.assertNothingApplied(shown)
        self.assertIn(compiled['fingerprint'], command(''))
        (self.dir / 'charter-settings.yaml').write_text(compiled['settings_yaml'].replace(
            compiled['fingerprint'], 'AXC-000000000000'), encoding='utf-8')
        self.assertFalse(self.run_tool(action='show')['files_match'])

    def test_every_result_states_nothing_was_applied(self):
        for args in ({'action': 'questions'}, {'action': 'compile', 'answers': {}}, {'action': 'compile'},
                     {'action': 'show'}, {'action': 'apply'}, {}, {'action': 'compile', 'answers': 'x'}):
            with self.subTest(args=args):
                self.assertNothingApplied(self.run_tool(**args))
        self.assertNothingApplied(json.loads(self.call('not a dict')))

    def test_handler_never_raises_on_an_unwritable_dir(self):
        blocked = self.home / 'file'
        blocked.write_text('x')
        call = charter.make_handler(lambda: blocked / 'charter')
        out = json.loads(call({'action': 'compile', 'answers': full_answers()}))
        self.assertIn('error', out)
        self.assertNothingApplied(out)

    def test_schema_tells_the_agent_how_to_run_the_interview(self):
        text = charter.SCHEMA['description'].lower()
        for needle in ('one at a time', 'plain english', 'read', 'before compile', 'nothing was applied', 'by hand'):
            self.assertIn(needle, text)
        self.assertEqual(charter.SCHEMA['parameters']['properties']['action']['enum'], ['questions', 'compile', 'show'])

    def test_module_names_no_network_or_model_imports(self):
        source = (ROOT / 'axioma' / 'charter.py').read_text(encoding='utf-8')
        for needle in ('import socket', 'urllib', 'requests', 'http.client', 'subprocess', 'import yaml', 'get_config',
                       'expanduser', 'Path.home'):
            self.assertNotIn(needle, source)



class ReviewFindingTests(unittest.TestCase):
    """One regression per independent-review finding (A327)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.dir = self.home / 'plugin-data' / 'charter'
        self.outside = self.home / 'outside.txt'
        self.outside.write_text('KEEP', encoding='utf-8')
        self.call = charter.make_handler(lambda: self.dir)

    def run_tool(self, **args):
        return json.loads(self.call(args))

    # P1: symlinks are never written or read through.
    def test_planted_tmp_and_final_symlinks_do_not_reach_outside(self):
        self.dir.mkdir(parents=True)
        os.chmod(str(self.dir), 0o700)
        for name in ('CHARTER.md.tmp', 'charter-settings.yaml.tmp', 'CHARTER.md', 'charter-settings.yaml'):
            os.symlink(str(self.outside), str(self.dir / name))
        out = self.run_tool(action='compile', answers=full_answers())
        self.assertEqual(out.get('status'), 'compiled', out)
        self.assertEqual(self.outside.read_text(encoding='utf-8'), 'KEEP')
        for name in ('CHARTER.md', 'charter-settings.yaml'):
            self.assertFalse((self.dir / name).is_symlink(), name)
            self.assertEqual((self.dir / name).stat().st_mode & 0o777, 0o600)

    def test_symlinked_charter_dir_is_refused_for_write_and_show(self):
        real = self.home / 'elsewhere'
        real.mkdir()
        self.dir.parent.mkdir(parents=True)
        os.symlink(str(real), str(self.dir))
        out = self.run_tool(action='compile', answers=full_answers())
        self.assertIn('error', out)
        self.assertEqual(list(real.iterdir()), [])
        (real / 'CHARTER.md').write_text('SECRET', encoding='utf-8')
        (real / 'charter-settings.yaml').write_text('SECRET', encoding='utf-8')
        self.assertEqual(self.run_tool(action='show')['status'], 'none')

    def test_show_does_not_follow_a_final_file_symlink(self):
        self.run_tool(action='compile', answers=full_answers())
        (self.dir / 'CHARTER.md').unlink()
        self.outside.write_text('SECRET', encoding='utf-8')
        os.symlink(str(self.outside), str(self.dir / 'CHARTER.md'))
        out = self.run_tool(action='show')
        self.assertEqual(out['status'], 'none')
        self.assertNotIn('SECRET', json.dumps(out))

    def test_loose_existing_dir_is_refused_not_chmodded_and_no_temporaries_are_left(self):
        self.dir.mkdir(parents=True)
        os.chmod(str(self.dir), 0o755)
        out = self.run_tool(action='compile', answers=full_answers())
        self.assertIn('error', out)
        self.assertEqual(self.dir.stat().st_mode & 0o777, 0o755, 'an existing folder is never chmod-ed')
        self.assertEqual(list(self.dir.iterdir()), [])
        os.chmod(str(self.dir), 0o700)
        self.run_tool(action='compile', answers=full_answers())
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ['CHARTER.md', 'charter-settings.yaml'])

    def test_symlinked_parent_folder_is_refused_for_write_and_show(self):
        real = self.home / 'outside'
        real.mkdir()
        os.symlink(str(real), str(self.home / 'plugin-data'))
        out = self.run_tool(action='compile', answers=full_answers())
        self.assertIn('error', out)
        self.assertEqual(list(real.iterdir()), [], 'nothing was created through the link')
        (real / 'charter').mkdir(mode=0o700)
        for name in ('CHARTER.md', 'charter-settings.yaml'):
            (real / 'charter' / name).write_text('SECRET', encoding='utf-8')
        out = self.run_tool(action='show')
        self.assertEqual(out['status'], 'none')
        self.assertNotIn('SECRET', json.dumps(out))

    def swapped(self, swap):
        """Run compile with `swap()` fired once, between the look at `charter` and its open."""
        real_open, fired = os.open, []

        def swapping_open(path, flags, mode=0o777, *, dir_fd=None):
            if path == 'charter' and dir_fd is not None and not fired:
                fired.append(1)
                swap()
            return real_open(path, flags, mode, dir_fd=dir_fd)
        # The capability check looks os.open up in os.supports_dir_fd; a wrapper is not in that set,
        # so the check is stood down here and tested on its own below.
        with unittest.mock.patch.object(charter, '_require_safe_io', lambda: None), \
                unittest.mock.patch.object(charter.os, 'open', swapping_open):
            out = self.run_tool(action='compile', answers=full_answers())
        self.assertEqual(fired, [1], 'the swap really ran inside the folder walk')
        return out

    def test_a_folder_swapped_between_look_and_open_is_refused(self):
        other = self.home / 'other'
        other.mkdir(mode=0o700)
        self.dir.mkdir(parents=True, mode=0o700)

        def swap():
            os.rmdir(str(self.dir))
            os.rename(str(other), str(self.dir))
        out = self.swapped(swap)
        self.assertIn('changed while it was being opened', out.get('error', ''), out)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_a_folder_loosened_between_look_and_open_is_refused(self):
        self.dir.mkdir(parents=True, mode=0o700)
        out = self.swapped(lambda: os.chmod(str(self.dir), 0o755))
        self.assertIn('open to other users', out.get('error', ''), out)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_a_loose_folder_swapped_in_right_after_this_call_made_it_is_refused(self):
        other = self.home / 'other'
        other.mkdir()
        os.chmod(str(other), 0o755)
        real_mkdir, fired = os.mkdir, []

        def swapping_mkdir(path, mode=0o777, *, dir_fd=None):
            real_mkdir(path, mode, dir_fd=dir_fd)
            if path == 'charter' and dir_fd is not None:
                fired.append(1)
                os.rmdir(str(self.dir))
                os.rename(str(other), str(self.dir))
        with unittest.mock.patch.object(charter, '_require_safe_io', lambda: None), \
                unittest.mock.patch.object(charter.os, 'mkdir', swapping_mkdir):
            out = self.run_tool(action='compile', answers=full_answers())
        self.assertEqual(fired, [1])
        self.assertIn('open to other users', out.get('error', ''), out)
        self.assertEqual(list(self.dir.iterdir()), [])
        self.assertEqual(self.dir.stat().st_mode & 0o777, 0o755, 'never chmod-ed')

    def test_missing_no_follow_support_fails_before_anything_is_created(self):
        with unittest.mock.patch.object(charter.os, 'O_NOFOLLOW', 0):
            out = self.run_tool(action='compile', answers=full_answers())
            self.assertIn('error', out)
            self.assertFalse((self.home / 'plugin-data').exists())
            self.assertEqual(self.run_tool(action='show')['status'], 'none')

    def test_a_pipe_at_the_file_name_does_not_hang_show(self):
        self.run_tool(action='compile', answers=full_answers())
        (self.dir / 'CHARTER.md').unlink()
        os.mkfifo(str(self.dir / 'CHARTER.md'))
        self.assertEqual(self.run_tool(action='show')['status'], 'none')

    # P2: what the file says is what a YAML reader gets.
    UNICODE = [{'workspace': '/tmp/\U0001F600', 'skip_inside': 'yes'}, {'deny_words': ['\U0001F600']},
               {'never_message': ['Zo\u00eb "Q" \\ back', 'na\u00efve: #x', "it's {a}, [b]"]},
               {'senders': ['\u00fcser@example.invalid']}, {'never_undo': ['\u2028line']},
               {'deny_words': ['\ud83d']}, {'deny_words': ['a\u0085b']}, {'deny_words': ['\ufeffbom']}]

    def test_unicode_answers_survive_a_yaml_load_or_make_no_rule(self):
        try:
            import yaml
        except ImportError:
            yaml = None
        for answers in self.UNICODE:
            result = charter.compile_charter(answers)
            text = result['settings_yaml']
            text.encode('utf-8')   # a lone surrogate would raise here
            self.assertNotRegex(text, r'\\u[dD][89abAB]', 'no JSON surrogate escapes in YAML')
            if yaml is None:
                continue
            loaded = loaded_settings(yaml, text)
            self.assertEqual(loaded, result['settings'], answers)
            self.assertEqual(charter.validate(loaded), [], answers)

    def test_emoji_word_still_matches_after_the_round_trip(self):
        result = charter.compile_charter({'deny_words': ['\U0001F600']})
        self.assertIn('\U0001F600', result['settings_yaml'])
        settings = result['settings']
        try:
            import yaml
            settings = loaded_settings(yaml, result['settings_yaml'])
        except ImportError:
            pass
        checks = Checks(settings['checks'])
        self.assertTrue(checks.hard_red('send_message', {'text': 'ship \U0001F600 now'}))
        self.assertFalse(checks.hard_red('send_message', {'text': 'ship now'}))
        with tempfile.TemporaryDirectory() as tmp:
            advisor = Advisor(settings['policy'], Audit(Path(tmp) / 'a.sqlite3'), settings['checks'])
            self.assertFalse(advisor.config_error)

    def test_characters_yaml_cannot_hold_make_no_rule(self):
        for bad in ('\ud83d', 'a\u2028line', 'a\u0085b', '\ufeffbom'):
            result = charter.compile_charter({'deny_words': [bad]})
            self.assertEqual(result['settings'], EMPTY, repr(bad))
            self.assertIn('validation', [p['question'] for p in result['problems']])

    # P2: one phrase removes the default; aliases do not.
    def test_only_the_exact_phrase_turns_the_delete_warning_off(self):
        for alias in ('turn-off', 'turn_off', 'turnoff', 'off', 'disable', 'turn it off'):
            policy = charter.compile_charter({'scrub': alias})['settings']['policy']
            self.assertNotIn('remove', policy, alias)
        self.assertEqual(charter.compile_charter({'scrub': 'Turn  Off'})['settings']['policy']['remove'], ['scrub'])

    # P2: an unknown key cannot write markdown into the charter.
    def test_unknown_key_cannot_inject_markdown(self):
        key = 'x)\n\n# Injected charter heading\n```'
        result = charter.compile_charter({key: 'v', '`': 'v', '': 'v'})
        page = result['charter']
        self.assertNotIn('Injected charter heading\n', page.replace('unknown key xInjectedcharterheading', ''))
        self.assertNotIn('```', page)
        self.assertEqual([l for l in page.splitlines() if l.startswith('#')],
                         [l for l in charter.compile_charter({})['charter'].splitlines() if l.startswith('#')])
        self.assertIn('## Limits', page)

    # P2: the page never promises a card after the warning was turned off.
    def test_page_does_not_promise_cards_after_the_warning_is_off(self):
        for extra in ({'workspace': 'none', 'output_dir': 'none'},
                      {'workspace': '/Users/example/projects/demo', 'output_dir': 'none', 'skip_inside': 'no'},
                      {'workspace': '/Users/example/projects/demo', 'output_dir': 'none', 'skip_inside': 'yes'},
                      {'workspace': '/Users/example/projects/demo', 'output_dir': 'none'}):
            page = charter.compile_charter(dict({'scrub': 'turn off'}, **extra))['charter']
            self.assertNotIn('Every delete and move', page, extra)
            self.assertNotIn('still shows one', page, extra)
            self.assertNotIn('show no card', page, extra)
            self.assertIn('other rules you set can still show a card', page, extra)
        kept = charter.compile_charter({'scrub': 'keep', 'workspace': 'none', 'output_dir': 'none'})['charter']
        self.assertIn('Every delete and move still shows a card', kept)

    # P3: the note does not claim files were written when none were.
    def test_note_never_claims_a_write_and_files_says_what_was_written(self):
        for args in ({'action': 'questions'}, {'action': 'show'},
                     {'action': 'compile', 'answers': full_answers(), 'preview': True}):
            out = self.run_tool(**args)
            self.assertEqual(out['files'], [], args)
            self.assertNotIn('wrote two files', out['note'])
        self.assertFalse(self.dir.exists())
        self.assertEqual(len(self.run_tool(action='compile', answers=full_answers())['files']), 2)



class ProseAnswerTests(unittest.TestCase):
    """A sentence can never match a call's text, so it must be a named problem, not a dead rule."""
    PROSE = ("once a message is sent to a human, that can't be undone. anything deleted completely "
             "without a backup, fallback or rollback. any spending that was not approved.")

    def test_prose_makes_no_rule_and_is_a_problem(self):
        for qid, key in (('never_undo', 'non_reversible'), ('deny_words', 'deny')):
            r = charter.compile_charter({qid: self.PROSE})
            self.assertFalse(r['complete'])
            mine = [p for p in r['problems'] if p['question'] == qid]
            self.assertEqual(len(mine), 1)
            self.assertIn('reads like a description', mine[0]['problem'])
            self.assertFalse(r['settings'].get('checks', {}).get(key))
            self.assertIn('OPEN: no rule made', r['charter'])

    def test_one_long_item_refuses_the_whole_answer(self):
        r = charter.compile_charter({'never_undo': ['close-account', 'anything deleted completely without a backup or rollback']})
        self.assertFalse(r['settings'].get('checks', {}).get('non_reversible'))

    def test_short_triggers_still_make_rules(self):
        r = charter.compile_charter({'never_undo': 'rm -rf, close-account, drop table',
                                     'deny_words': ['Bank of New York Mellon']})
        self.assertFalse([p for p in r['problems'] if p['question'] in ('never_undo', 'deny_words')])
        self.assertTrue(r['settings']['checks']['non_reversible'])
        self.assertTrue(self.fires(r, 'deny', 'buy shares at bank of new york mellon'))

    @staticmethod
    def fires(result, key, text):
        import json as _json
        import re as _re
        rules = result['settings']['checks'][key]
        return all(_re.search(rule['pattern'], _json.dumps({'note': text})) for rule in rules)

    def test_six_words_pass_seven_are_refused(self):
        for qid in ('never_message', 'deny_words', 'never_undo'):
            ok = charter.compile_charter({qid: ['one two three four five six']})
            self.assertFalse([p for p in ok['problems'] if p['question'] == qid], qid)
            bad = charter.compile_charter({qid: ['one two three four five six seven']})
            self.assertEqual(len([p for p in bad['problems'] if p['question'] == qid]), 1, qid)
            self.assertFalse(bad['settings'].get('checks'), qid)

    def test_quoted_exact_text_skips_the_guard_and_matches(self):
        text = 'delete every backup older than seven days now'
        r = charter.compile_charter({'never_undo': ['"%s"' % text]})
        self.assertFalse(r['problems'] and [p for p in r['problems'] if p['question'] == 'never_undo'])
        self.assertTrue(self.fires(r, 'non_reversible', 'run: ' + text.upper()))
        self.assertNotIn('\\"', r['settings']['checks']['non_reversible'][0]['pattern'])
        empty = charter.compile_charter({'never_undo': ['"  "']})
        self.assertTrue([p for p in empty['problems'] if p['question'] == 'never_undo'])

    def test_quoted_text_with_a_comma_stays_whole_in_a_plain_answer(self):
        from axioma.checks import Checks
        for answer in ('"New York, New York"', 'Jordan Example, "New York, New York"', ['"New York, New York"']):
            r = charter.compile_charter({'never_message': answer})
            self.assertFalse([p for p in r['problems'] if p['question'] == 'never_message'], answer)
            checks = Checks(r['settings']['checks'])
            self.assertTrue(checks.hard_red('send_message', {'target': 'New York, New York'}), answer)
            self.assertFalse(checks.hard_red('send_message', {'target': 'New York'}), answer)
        both = Checks(charter.compile_charter({'never_message': 'Jordan Example, "New York, New York"'})['settings']['checks'])
        self.assertTrue(both.hard_red('send_message', {'target': 'jordan example'}))

    def test_unmatched_or_empty_quotes_are_a_problem_not_a_rule(self):
        for answer in ('"New York, New York', 'a, "b', '""', ['""'], '"  "'):
            r = charter.compile_charter({'deny_words': answer})
            self.assertEqual(len([p for p in r['problems'] if p['question'] == 'deny_words']), 1, answer)
            self.assertFalse(r['settings'].get('checks'), answer)

    def test_inner_quotes_are_not_an_exact_text_marker(self):
        r = charter.compile_charter({'deny_words': ['"a" and "b" one two three four five']})
        self.assertTrue([p for p in r['problems'] if p['question'] == 'deny_words'])

    def test_short_description_still_compiles_and_the_page_says_so(self):
        """Known limit, kept honest: the guard is length only."""
        for answer in ('spending without my approval',
                       'never send messages, never erase backups, never spend unapproved money'):
            r = charter.compile_charter({'never_undo': answer})
            self.assertFalse([p for p in r['problems'] if p['question'] == 'never_undo'])
            self.assertIn('it does not understand it', r['charter'])
            self.assertIn('shorter ones are not checked', r['charter'])
        self.assertIn('ask again', charter.INTRO)




class ApplyWordingTests(unittest.TestCase):
    """The compiled files must never tell an owner to paste an empty block over live settings."""
    KEY = re.compile(r'^\s*(policy|checks):', re.M)

    def keys(self, text):
        return self.KEY.findall(text)

    def test_a_charter_with_no_rule_gives_nothing_to_copy(self):
        result = charter.compile_charter({})
        self.assertEqual(result['settings'], {'policy': {}, 'checks': {}})
        self.assertEqual(self.keys(result['settings_yaml']), [])
        self.assertNotIn('{}', result['settings_yaml'])
        self.assertNotIn('plugins:', result['settings_yaml'])
        self.assertIn('nothing to copy', result['settings_yaml'])
        use = result['charter'].split('## To use this')[1]
        self.assertIn('nothing to copy', use)
        self.assertNotIn('Add the rules', use)

    def test_an_empty_block_is_never_written_as_a_mapping(self):
        result = charter.compile_charter({'never_undo': ['wipe-prod']})
        self.assertEqual(result['settings']['policy'], {})
        self.assertTrue(result['settings']['checks'])
        self.assertEqual(self.keys(result['settings_yaml']), ['checks'])
        self.assertNotIn('{}', result['settings_yaml'].replace('{tool', ''))
        self.assertNotIn('policy: {}', result['settings_yaml'])
        use = result['charter'].split('## To use this')[1]
        self.assertIn('under `checks` in', use)
        self.assertNotIn('`policy` and', use)
        only_policy = charter.compile_charter({'spend_tools': ['buy_widgets']})
        self.assertEqual(self.keys(only_policy['settings_yaml']), ['policy'])
        self.assertIn('under `policy` in', only_policy['charter'])

    def test_use_section_says_add_not_replace_and_back_up(self):
        for answers in (full_answers(), {'never_undo': ['wipe-prod']}, {'spend_tools': ['buy_widgets']}):
            result = charter.compile_charter(answers)
            use = result['charter'].split('## To use this')[1]
            for needle in ('Keep a copy of your Hermes config', 'Add, do not replace', 'erases the rules in it',
                           'does not edit any config'):
                self.assertIn(needle, use, answers)
            self.assertIn('ADD, do not replace', result['settings_yaml'])
        self.assertIn('pasted over an existing policy or checks block replaces it', charter.NOTHING_APPLIED)

    def test_terminal_warning_only_when_a_rule_covers_terminal(self):
        needle = 'no one watching'
        for answers in ({'never_undo': ['wipe-prod']}, {'deny_words': ['receive_only']}):
            result = charter.compile_charter(answers)
            self.assertIn('tool: "terminal"', result['settings_yaml'])
            self.assertIn(needle, result['charter'], answers)
        for answers in ({'never_message': ['nobody@example.invalid']}, {'spend_tools': ['buy_widgets']}, {}):
            result = charter.compile_charter(answers)
            self.assertNotIn('tool: "terminal"', result['settings_yaml'])
            self.assertNotIn(needle, result['charter'], answers)

    def test_a_merge_of_the_file_into_live_settings_keeps_a_live_policy(self):
        try:
            import yaml
        except ImportError:
            self.skipTest('PyYAML not installed')
        live = {'policy': {'remove': ['scrub'], 'workspace': '/Users/example/work'}, 'checks': {}}
        for answers in ({'never_undo': ['wipe-prod']}, {}):
            text = charter.compile_charter(answers)['settings_yaml']
            found = ((yaml.safe_load(text) or {}).get('plugins', {}).get('entries', {})
                     .get('hermes-axioma', {}).get('settings', {}))
            self.assertNotIn('policy', found)
            merged = dict(live, **found)   # the worst case: each block in the file replaces the live one
            self.assertEqual(merged['policy'], live['policy'], answers)

if __name__ == '__main__':
    unittest.main()
