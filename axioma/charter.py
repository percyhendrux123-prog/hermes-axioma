"""Axiōma Charter: a plain-English interview compiled into one page and a settings block.

ADVISOR ONLY, like the rest of the plugin. The charter lists the rules the card warns on. It does
not enforce, block or approve anything, and it never edits a Hermes config or profile: the only
things this module writes are CHARTER.md and charter-settings.yaml inside one directory the caller
names. Pure standard library; no network, no model call.

STRICT RULE. A missing, unclear or invalid answer makes NO rule and is named as a problem. No answer
can make a rule looser than the plugin defaults, and no default rule is removed, unless the answer
says so in so many words (`scrub` = "turn off"; a folder is only trusted after "yes").
"""
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path
import re

from .checks import Checks
from .policy import DEFAULTS, Policy

CHARTER_FILE = 'CHARTER.md'
SETTINGS_FILE = 'charter-settings.yaml'
MAX_ITEMS, MAX_LEN = 20, 120
# A trigger is matched as exact text inside a call. A long description of a situation never appears
# there, so an item over MAX_WORDS words is refused as a problem instead of becoming a rule that
# cannot fire. This is a LENGTH guard, not prose detection: a short description still makes a rule
# (the charter's Limits say so, and the interviewer is told to catch it). An item the owner wraps in
# double quotes is exact text they vouch for and skips the guard.
MAX_WORDS = 6

NOTHING_APPLIED = (
    'Nothing was applied. This tool changes no setting, no config.yaml and no profile; `files` lists '
    'what this call wrote (an empty list means it wrote nothing). To use a compiled charter, the '
    'owner opens %s in the charter folder and adds the rules in it to the '
    'hermes-axioma settings in the Hermes config by hand, keeping every rule already there (a block '
    'pasted over an existing policy or checks block replaces it and erases its rules), then '
    'restarts Hermes. Read the "To use this" section of the charter back to the owner: it says '
    'what to add and what to watch for. Axiōma then shows the cards described in %s; it still '
    'only advises.' % (SETTINGS_FILE, CHARTER_FILE))

# Tool-name globs a "red card" word is looked for in: sending, posting, paying, starting jobs or
# agents, and terminal commands. Reads and searches are left out on purpose. Every non-terminal
# default rule tool matches one of these (a test keeps it that way).
ACTION_TOOLS = ['*send*', '*post*', '*publish*', '*pay*', '*purchase*', '*charge*', '*refund*',
                '*checkout*', '*cron*', '*job*', 'delegate_task', 'kanban_create', 'terminal']
MESSAGE_TOOLS = ['*send*', '*post*', '*publish*']

INTRO = ('Axiōma shows a card before the agent sends, spends, starts something or deletes. It never '
         'blocks and never allows: there is no list of people the agent may message without a card. '
         'These questions only tell the card what to warn about. Ask them one at a time, in plain '
         'English, and use the owner\'s own words as the answer. If the owner has not answered, '
         'leave that answer out; do not guess. For the never-message, red-card and never-undone '
         'questions the card only looks for the exact text given; it does not understand it. If an '
         'answer describes a situation (such as "spending I did not approve") and is not text that '
         'would appear in the action, say that it cannot be matched and ask again; the tool only '
         'catches items over 6 words.')

QUESTIONS = [
    {'id': 'never_message',
     'ask': 'Is there anyone the agent must never message on your behalf, such as a person, an email '
            'address or a chat handle? Name each one, or say "none".',
     'shape': 'A list of names, addresses or handles (up to 20), or "none".',
     'example': ['legal@example.invalid', 'Jordan Example'],
     'maps_to': ['checks.deny']},
    {'id': 'senders',
     'ask': 'Which email addresses or accounts may the agent send from? Name each one, or say '
            '"no limit". If you name any, a message that does not say it is from one of them will '
            'show a red card.',
     'shape': 'A list of addresses or account names (up to 20), or "no limit".',
     'example': ['assistant@example.invalid'],
     'maps_to': ['checks.senders']},
    {'id': 'spend_tools',
     'ask': 'Does the agent have any tool that buys things or moves money, beyond the common '
            'payment tools Axiōma already knows? Give the tool names, or say "none".',
     'shape': 'A list of tool names (up to 20), or "none".',
     'example': ['buy_widgets'],
     'maps_to': ['policy.add']},
    {'id': 'scrub',
     'ask': 'Should the agent\'s file deletes and moves show a warning card? Say "keep" to keep the '
            'built-in warning, or "turn off" to remove it. Turning it off removes a built-in rule.',
     'shape': 'Exactly "keep" or "turn off".',
     'example': 'keep',
     'maps_to': ['policy.remove']},
    {'id': 'workspace',
     'ask': 'Which single folder does the agent do its work in? Give the full path, or say "none".',
     'shape': 'A full folder path (not your whole home folder), or "none".',
     'example': '/Users/example/projects/demo',
     'maps_to': ['policy.workspace']},
    {'id': 'output_dir',
     'ask': 'Which folder should the files it makes be saved in? Give the full path, or say "none".',
     'shape': 'A full folder path (not your whole home folder), or "none".',
     'example': '/Users/example/projects/demo/output',
     'maps_to': ['policy.output_dir']},
    {'id': 'skip_inside',
     'ask': 'Ask only if you named a folder above. Inside those folders, may deletes and moves skip '
            'the warning card? Anything outside them will still show one. Say "no" to keep a card '
            'on every delete and move.',
     'shape': '"yes" or "no".',
     'example': 'no',
     'ask_when': 'workspace or output_dir is a folder',
     'maps_to': ['policy.workspace', 'policy.output_dir']},
    {'id': 'spin_tools',
     'ask': 'Beyond the scheduled jobs and helper agents Axiōma already watches, does the agent have '
            'other tools that start scheduled jobs or other agents? Give the tool names, or say '
            '"none".',
     'shape': 'A list of tool names (up to 20), or "none".',
     'example': ['schedule_report'],
     'maps_to': ['policy.add']},
    {'id': 'deny_words',
     'ask': 'Are there words, provider names or targets (a website, a server, an account) that must '
            'always turn the card red when they appear in what the agent is about to do? The card '
            'looks for these exact words in the action, so give short words or names, not a '
            'description of a situation. List them, or say "none".',
     'shape': 'A list of short words or names (up to 20), or "none". An item over 6 words makes '
              'no rule unless it is exact text in double quotes.',
     'example': ['receive_only', 'prod-database'],
     'maps_to': ['checks.deny']},
    {'id': 'never_undo',
     'ask': 'Is there anything that could never be undone if the agent got it wrong, such as closing '
            'an account, transferring a domain or erasing a backup? The card looks for exact words '
            'in the action and cannot judge a situation (for example whether a backup exists or a '
            'spend was approved). List the short words that would show up in that action, or say '
            '"none".',
     'shape': 'A list of short words or names (up to 20), or "none". An item over 6 words makes '
              'no rule unless it is exact text in double quotes.',
     'example': ['transfer-domain', 'close-account'],
     'maps_to': ['checks.non_reversible']},
]
IDS = [q['id'] for q in QUESTIONS]

NONE_WORDS = {'none', 'nothing', 'nobody', 'no one', 'n/a', 'no'}
NO_LIMIT = {'no limit', 'no limits', 'any', 'anyone', 'unlimited'}
YES, NO = {'yes', 'y', 'true'}, {'no', 'n', 'false'}
TURN_OFF = {'turn off'}   # the one phrase that removes a default rule; no aliases
TOOL_NAME = re.compile(r'[A-Za-z0-9_.:*?-]{3,100}')


def questions():
    """The interview, in order, as plain data."""
    return [dict(q, ask_when=q.get('ask_when', 'always')) for q in QUESTIONS]


# -- parsing ------------------------------------------------------------------------------------
def _clean(text):
    """A stripped one-line string, or None when it holds control characters."""
    text = text.strip()
    return None if any(ord(c) < 32 or ord(c) == 127 for c in text) else text


def _word(value):
    """A short answer word: str lowercased and stripped; bool as yes/no; anything else None."""
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, str):
        text = _clean(value)
        return None if text is None else ' '.join(text.lower().split())
    return None


def _items(value, lower=False, allow_none=NONE_WORDS):
    """(items, problem). items == [] means the owner said "none"; None means no usable answer."""
    if isinstance(value, str):
        word = _word(value)
        if word is None:
            return None, 'the answer holds a line break or control character'
        if not word:
            return None, 'the answer is empty'
        if word in allow_none:
            return [], None
        parts = re.split(r'[\n,]', value)
    elif isinstance(value, (list, tuple)) and not value:
        return None, 'the answer is empty (say "none" if you mean none)'
    elif isinstance(value, (list, tuple)) and all(isinstance(p, str) for p in value):
        parts = list(value)
        if len(parts) == 1 and _word(parts[0]) in allow_none:
            return [], None
    else:
        return None, 'the answer is not a list of words or "none"'
    items = []
    for part in parts:
        text = _clean(part)
        if text is None:
            return None, 'an item holds a line break or control character'
        if not text:
            if isinstance(value, str):
                continue
            return None, 'an item is empty'
        text = text.lower() if lower else text
        if len(text) > MAX_LEN:
            return None, 'an item is longer than %d characters' % MAX_LEN
        if text not in items:
            items.append(text)
    if not items:
        return None, 'the answer is empty'
    if any(i.lower() in NONE_WORDS | NO_LIMIT for i in items):
        return None, 'the answer mixes "none" or "no limit" with names, or is unclear'
    if len(items) > MAX_ITEMS:
        return None, 'more than %d items; narrow the list' % MAX_ITEMS
    return items, None


def _folder(value):
    """(path | '' for none | None, problem)."""
    if not isinstance(value, str):
        return None, 'the answer is not a folder path or "none"'
    text = _clean(value)
    if text is None or not text:
        return None, 'the answer is empty or holds a control character'
    if text.lower() in NONE_WORDS:
        return '', None
    path = Path(text)
    if not path.is_absolute():
        return None, 'the folder must be a full path starting at the top of the disk'
    if '..' in path.parts:
        return None, 'the folder path may not contain ".."'
    if len(path.parts) < 3 or (path.parts[1] in ('Users', 'home') and len(path.parts) <= 3):
        return None, 'the folder is too broad; name a project folder, not a whole disk or home folder'
    return str(path), None


def _tool_names(value):
    items, problem = _items(value)
    if items:
        for name in items:
            if not TOOL_NAME.fullmatch(name) or len(re.sub(r'[*?]', '', name)) < 3:
                return None, 'tool name %s is not a plain tool name (letters, digits, _ . : - and * only)' % json.dumps(name)
    return items, problem


def _pattern(items):
    """Case-insensitive plain-text match of any item against the call's JSON arguments."""
    literal = [re.sub(r'([\\.^$*+?{}\[\]|()])', r'\\\1', json.dumps(item, ensure_ascii=False)[1:-1])
               for item in items]
    return '(?i)(?:' + '|'.join(literal) + ')'


# -- compile ------------------------------------------------------------------------------------
class _State:
    def __init__(self):
        self.policy, self.checks = {}, {}
        self.deny, self.irreversible, self.add = [], [], []
        self.lines, self.problems = {}, []

    def rule(self, qid, text):
        self.lines[qid] = 'RULE: ' + text

    def none(self, qid, text):
        self.lines[qid] = 'NONE: ' + text

    def problem(self, qid, text):
        text = text[0].upper() + text[1:]
        self.problems.append({'question': qid, 'problem': text})
        self.lines[qid] = 'OPEN: no rule made. ' + text


def _q(text):
    return '`' + str(text).replace('`', "'") + '`'


def _join(items):
    return ', '.join(_q(i) for i in items)


def _list_question(answers, qid, state, parser=_items, **kw):
    """The parsed items for a list question, or None (a problem is recorded) when unusable."""
    if qid not in answers:
        state.problem(qid, 'not answered.')
        return None
    items, problem = parser(answers[qid], **kw)
    if items is None:
        state.problem(qid, (problem or 'unclear') + '.')
    return items


def _triggers(value):
    """_items, but a long unquoted item is a problem, not a rule that never fires. Length guard only."""
    if isinstance(value, str) and '"' in value:
        # Split on commas and line breaks OUTSIDE double quotes, so "New York, New York" stays whole.
        if value.count('"') % 2:
            return None, 'the answer has an unmatched double quote'
        value = [p for p in (m.strip() for m in re.findall(r'(?:"[^"]*"|[^",\n])+', value)) if p]
    items, problem = _items(value)
    if not items:
        return items, problem
    out, long = [], []
    for item in items:
        quoted = len(item) >= 2 and item[0] == item[-1] == '"' and '"' not in item[1:-1]
        text = item[1:-1].strip() if quoted else item
        if not text:
            return None, 'an item is empty quotes'
        if not quoted and len(text.split()) > MAX_WORDS:
            long.append(text)
        elif text not in out:
            out.append(text)
    if long:
        return None, ('%s is longer than %d words, so it reads like a description, not text that would '
                      'appear in the action. The card matches exact text and cannot judge a situation; '
                      'give short words or names, put exact text in double quotes, or say "none"'
                      % (_join(long[:3]), MAX_WORDS))
    return out, None


def _reds(tools, items):
    return [{'tool': t, 'pattern': _pattern(items)} for t in tools]


def _red_question(answers, state, qid, tools, bucket, text, none_text):
    items = _list_question(answers, qid, state, _triggers)
    if items is None:
        return
    if items:
        bucket.extend(_reds(tools, items))
        state.rule(qid, text % _join(items))
    else:
        state.none(qid, none_text)


def _tool_question(answers, state, qid, category, words):
    items = _list_question(answers, qid, state, _tool_names)
    if items is None:
        return
    if items:
        for n, name in enumerate(items, 1):
            state.add.append({'id': 'charter-%s-%d' % (category, n), 'category': category, 'tool': name})
        state.rule(qid, 'a card for %s on calls to %s.' % (words, _join(items)))
    else:
        state.none(qid, 'you named no extra tools. The built-in rules for %s stay.' % words)


def _compile_all(answers, state):
    _red_question(answers, state, 'never_message', MESSAGE_TOOLS, state.deny,
                  'a red card on any send, post or publish call that names %s.',
                  'you named no one. Every send still shows a card.')
    items = _list_question(answers, 'senders', state, _items, lower=True, allow_none=NO_LIMIT)
    if items is not None:
        bad = [i for i in items if re.search(r'\s', i)]
        if bad:
            state.problem('senders', 'an address or account has a space in it: %s.' % _join(bad))
        elif items:
            state.checks['senders'] = dict((i, True) for i in items)
            state.rule('senders', 'sending is limited to %s. A send that names a different sender, or no '
                                  'sender at all, shows a RED card.' % _join(items))
        else:
            state.none('senders', 'you set no limit. Every send still shows a card.')
    _tool_question(answers, state, 'spend_tools', 'spend', 'spending')
    _scrub_and_folders(answers, state)
    _tool_question(answers, state, 'spin_tools', 'spin', 'starting jobs or agents')
    _red_question(answers, state, 'deny_words', ACTION_TOOLS, state.deny,
                  'a red card whenever %s appears in a send, post, payment, job, agent or terminal call.',
                  'you named no words.')
    _red_question(answers, state, 'never_undo', ACTION_TOOLS, state.irreversible,
                  'a red card, marked as non-reversible, whenever %s appears in a send, post, payment, job, '
                  'agent or terminal call.', 'you named nothing that cannot be undone.')


def _scrub_and_folders(answers, state):
    # scrub: the only way to remove a default rule is the exact words "turn off".
    if 'scrub' not in answers:
        state.problem('scrub', 'not answered. The built-in delete and move warning stays on.')
    else:
        word = _word(answers['scrub'])
        if word == 'keep':
            state.none('scrub', 'you kept the built-in delete and move warning.')
        elif word in TURN_OFF:
            state.policy['remove'] = ['scrub']
            state.rule('scrub', 'the built-in delete and move warning is removed (you said "turn off").')
        else:
            state.problem('scrub', 'the answer must be exactly "keep" or "turn off". The warning stays on.')
    # folders
    folders = {}
    for qid in ('workspace', 'output_dir'):
        if qid not in answers:
            state.problem(qid, 'not answered.')
            continue
        path, problem = _folder(answers[qid])
        if path is None:
            state.problem(qid, problem + '.')
        else:
            folders[qid] = path
    named = dict((k, v) for k, v in folders.items() if v)
    off = state.policy.get('remove') == ['scrub']
    OFF = 'The built-in delete and move warning is off by your earlier answer; other rules you set can still show a card.'
    every = OFF if off else 'Every delete and move still shows a card.'
    for qid in folders:
        if not folders[qid]:
            state.none(qid, 'you named no folder. ' + every)
    if not named:
        state.none('skip_inside', 'not needed: no folder was named.')
        return
    answer = _word(answers['skip_inside']) if 'skip_inside' in answers else None
    if 'skip_inside' not in answers:
        state.problem('skip_inside', 'not answered, so the folder%s you named are not used. %s'
                      % ('s' if len(named) > 1 else '', every))
    elif answer in YES:
        for qid, path in named.items():
            state.policy[qid] = path
            state.rule(qid, 'the folder is %s. %s' % (_q(path), (
                OFF + ' This folder changes nothing.'
                if off else 'Deletes and moves inside it skip the card; anything outside it still shows one.')))
        state.rule('skip_inside', 'you said yes: deletes and moves inside the named folder%s skip the warning card.%s'
                   % ('s' if len(named) > 1 else '', ' (' + OFF + ')' if off else ''))
    elif answer in NO:
        for qid, path in named.items():
            state.lines[qid] = 'NONE: you named %s but said no to skipping the card inside it, so no folder is set.' % _q(path)
        state.none('skip_inside', 'you said no. ' + every)
    else:
        state.problem('skip_inside', 'the answer must be "yes" or "no", so the folder%s you named are not used.'
                      % ('s' if len(named) > 1 else ''))


def _canonical(settings):
    return json.dumps(settings, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def fingerprint(settings):
    return 'AXC-' + hashlib.sha256(_canonical(settings).encode('ascii')).hexdigest()[:12]


def validate(settings):
    """Run the block through the plugin's own validators. Returns a list of error strings."""
    errors = []
    try:
        Policy(settings.get('policy', {}))
        if Policy.lenient(settings.get('policy', {}))[1]:
            errors.append('policy: lenient loader reported an error')
    except Exception as exc:
        errors.append('policy: %s' % exc)
    try:
        Checks(settings.get('checks', {}))
        if Checks.lenient(settings.get('checks', {}))[1]:
            errors.append('checks: lenient loader reported an error')
    except Exception as exc:
        errors.append('checks: %s' % exc)
    return errors


def _yaml_plain(ch):
    """True when YAML 1.1/1.2 readers accept this character raw inside a double-quoted scalar."""
    o = ord(ch)
    return (0x20 <= o <= 0x7E or 0xA0 <= o <= 0xD7FF or 0xE000 <= o <= 0xFFFD
            or 0x10000 <= o <= 0x10FFFF) and o not in (0x2028, 0x2029, 0xFEFF)


def _scalar(value):
    """A YAML double-quoted scalar. JSON's surrogate-pair escapes are NOT valid YAML (a loader reads
    them as two lone surrogates), so text is written raw, with only the quote and the backslash
    escaped. compile_charter refuses any character YAML will not take raw (see _unsafe)."""
    if not isinstance(value, str):
        return json.dumps(value)
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _unsafe(value):
    """True when any text in the block holds a character a YAML reader would reject or change."""
    if isinstance(value, str):
        return not all(_yaml_plain(c) for c in value)
    if isinstance(value, dict):
        return any(_unsafe(k) or _unsafe(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_unsafe(v) for v in value)
    return False


def _flow(rule):
    return '{' + ', '.join('%s: %s' % (k, _scalar(v)) for k, v in rule.items()) + '}'


def settings_yaml(settings, fp):
    """The settings block as YAML, in the nesting the README's Operator settings shows."""
    out = ['# Axiōma Charter settings, fingerprint %s' % fp,
           '# Nothing has applied this file. Add these rules by hand to the hermes-axioma settings.',
           '# ADD, do not replace: a block pasted over a policy or checks block you already have',
           '# erases the rules in it. Keep a copy of your config before you edit it.']
    base = '        '
    if not any(settings[block] for block in ('policy', 'checks')):
        return '\n'.join(out + ['# This charter makes no rule. There is nothing to copy.']) + '\n'
    out += ['plugins:', '  entries:', '    hermes-axioma:', '      settings:']
    for block in ('policy', 'checks'):
        body = settings[block]
        if not body:
            # Never written as an empty mapping: pasted in, "policy: {}" would erase a live policy.
            out.append('%s# %s: this charter makes no %s rule. Leave any %s block you have as it is.'
                       % (base, block, block, block))
            continue
        out.append('%s%s:' % (base, block))
        for key, value in body.items():
            if isinstance(value, dict):
                out.append('%s  %s:' % (base, key))
                out += ['%s    %s: %s' % (base, _scalar(k), 'true' if v else 'false') for k, v in value.items()]
            elif isinstance(value, list):
                out.append('%s  %s:' % (base, key))
                out += ['%s    - %s' % (base, _flow(v) if isinstance(v, dict) else _scalar(v)) for v in value]
            else:
                out.append('%s  %s: %s' % (base, key, _scalar(value)))
    return '\n'.join(out) + '\n'


def _defaults_line(removed):
    counts = {}
    for rule in DEFAULTS:
        counts[rule['category']] = counts.get(rule['category'], 0) + 1
    text = 'Built-in rules that stay on: %d for sending, %d for spending, %d for starting jobs or agents' % (
        counts.get('send', 0), counts.get('spend', 0), counts.get('spin', 0))
    if removed:
        return text + ' (listed in axioma/policy.py). The delete and move warning was turned off by your answer.'
    return text + ' (listed in axioma/policy.py), and the delete and move warning.'


def _terminal_rule(settings):
    return any(isinstance(rule, dict) and rule.get('tool') == 'terminal'
               for key in ('deny', 'non_reversible') for rule in settings['checks'].get(key, []))


def _use_lines(settings):
    """The "To use this" section. Names only the blocks this charter filled, says add-not-replace,
    and warns when a red-card word also covers terminal commands."""
    blocks = [block for block in ('policy', 'checks') if settings[block]]
    if not blocks:
        return ['This charter makes no rule, so there is nothing to copy. Your settings stay as they are. '
                'The Axiōma Charter tool does not edit any config.']
    names = ' and '.join('`%s`' % block for block in blocks)
    lines = ['- Keep a copy of your Hermes config first.',
             '- Add the rules under %s in charter-settings.yaml to the hermes-axioma settings by hand, then '
             'restart Hermes. The Axiōma Charter tool does not edit any config.' % names,
             '- Add, do not replace. If you already have a `policy` or `checks` block, put the new lines '
             'inside it. A block pasted over one you already have erases the rules in it.']
    if _terminal_rule(settings):
        lines.append('- Your red-card words also cover terminal commands (the lines with `tool: "terminal"`). '
                     'A terminal command that only mentions a word, such as a search or a commit message, '
                     'turns the card red too, and Hermes may stop to ask you. That includes scheduled jobs '
                     'and worker agents running with no one watching. Leave those lines out if you do not '
                     'want that.')
    return lines


def render_charter(state, settings, fp):
    removed = 'scrub' in settings['policy'].get('remove', [])
    lines = ['# Axiōma Charter', '',
             'Fingerprint: %s (the same code is on charter-settings.yaml)' % fp, '',
             'These are the rules the Axiōma card warns on. Axiōma advises: it does not block, approve '
             'or run anything. Hermes\'s own approval prompt and you decide. Nothing on this page has '
             'been applied to any setting.', '', '## Your answers']
    for number, qid in enumerate(IDS, 1):
        if qid in state.lines:
            lines.append('%d. (%s) %s' % (number, qid, state.lines[qid]))
    lines += ['', '## Still in force from the defaults', '- ' + _defaults_line(removed),
              '- Every card is advice. A red card does not stop the call; you answer it in the Hermes prompt.']
    if state.problems:
        lines += ['', '## Open questions',
                  'These answers were missing or unclear. They made no rule. Answer them and compile again.']
        lines += ['- (%s) %s' % (p['question'], p['problem']) for p in state.problems]
    lines += ['', '## Limits',
              '- Words are matched as plain text in the call\'s arguments, ignoring capital letters. A different '
              'spelling is not caught.',
              '- The card looks for the exact text of a rule; it does not understand it. A rule written as a '
              'description of a situation (for example "spending I did not approve") never fires. Items over '
              '%d words are refused for that reason; shorter ones are not checked.' % MAX_WORDS,
              '- Delete and move detection is best-effort shell reading. See the README.',
              '', '## To use this'] + _use_lines(settings)
    return '\n'.join(lines) + '\n'


def compile_charter(answers):
    """answers (dict: question id -> answer) -> dict with settings, charter, settings_yaml, problems,
    fingerprint. Deterministic: the same answers always give byte-identical text."""
    state = _State()
    if not isinstance(answers, dict):
        state.problems.append({'question': 'answers', 'problem': 'the answers must be an object keyed by question id.'})
        answers = {}
    for key in sorted(k for k in answers if k not in IDS):
        label = re.sub(r'[^A-Za-z0-9_-]', '', str(key))[:40] or 'unnamed'
        state.problems.append({'question': 'unknown key ' + label, 'problem': 'Not a question id; ignored.'})
    _compile_all(answers, state)
    policy = {}
    for key in ('workspace', 'output_dir', 'remove'):
        if key in state.policy:
            policy[key] = state.policy[key]
    if state.add:
        policy['add'] = state.add
    checks = {}
    if state.deny:
        checks['deny'] = state.deny
    if state.irreversible:
        checks['non_reversible'] = state.irreversible
    if 'senders' in state.checks:
        checks['senders'] = state.checks['senders']
    settings = {'policy': policy, 'checks': checks}
    errors = validate(settings)
    if not errors and _unsafe(settings):
        errors = ['an answer holds a character that cannot be written safely to the settings file']
    if errors:
        # Fail safe: an empty block is the plugin defaults, never a looser set.
        settings = {'policy': {}, 'checks': {}}
        for error in errors:
            state.problems.append({'question': 'validation', 'problem': error + '. No rules were produced.'})
        state.lines = dict((q, 'OPEN: no rule made. The compiled block failed the plugin\'s own validation.')
                           for q in state.lines)
    fp = fingerprint(settings)
    return {'settings': settings, 'charter': render_charter(state, settings, fp),
            'settings_yaml': settings_yaml(settings, fp), 'problems': state.problems,
            'fingerprint': fp, 'complete': not state.problems}


# -- files and tool -----------------------------------------------------------------------------
import stat as _stat


def _require_safe_io():
    """Fail closed, before anything is created, on a platform that cannot anchor file access on a
    directory descriptor without following links."""
    ok = (getattr(os, 'O_NOFOLLOW', 0) and getattr(os, 'O_DIRECTORY', 0)
          and {os.open, os.mkdir, os.stat, os.unlink} <= os.supports_dir_fd
          and os.stat in os.supports_follow_symlinks and hasattr(os, 'getuid'))
    if not ok:
        raise OSError('this platform cannot write the charter files safely; nothing was written')


def _step(parent_fd, name, create, final):
    """Open the directory `name` inside `parent_fd`, never through a link. The entry is looked at
    first (lstat), then opened, then the open descriptor is checked to be that same directory, so
    a link, a swap between the two steps, or a backend that follows links anyway is refused."""
    made = False
    try:
        seen = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        if not create:
            raise
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        made = True
        seen = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not _stat.S_ISDIR(seen.st_mode) or seen.st_uid != os.getuid():
        raise OSError('%s is not a folder owned by this user' % name)
    loose = 'the charter folder is open to other users; fix its permissions (owner only) first'
    if final and seen.st_mode & 0o077:     # also when this call made it: it may have been swapped
        raise OSError(loose)
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    opened = os.fstat(fd)                  # the descriptor is what gets used, so it is what is judged
    problem = None
    if (opened.st_dev, opened.st_ino) != (seen.st_dev, seen.st_ino) or not _stat.S_ISDIR(opened.st_mode):
        problem = '%s changed while it was being opened' % name
    elif opened.st_uid != os.getuid():
        problem = '%s is not a folder owned by this user' % name
    elif final and opened.st_mode & 0o077:
        problem = loose
    if problem:
        os.close(fd)
        raise OSError(problem)
    return fd


def _open_dir(directory, create):
    """A descriptor on the charter folder. Trust boundary: the folder two levels up (Hermes's own
    plugin-data area) is resolved once and trusted, as Hermes itself trusts it for config; the
    plugin's data folder and the charter folder below it must be real folders owned by this user,
    never links. Nothing is chmod-ed: a charter folder open to other users is refused."""
    _require_safe_io()
    directory = Path(directory)
    data, base = directory.parent, directory.parent.parent
    base_fd = os.open(os.path.realpath(str(base)), os.O_RDONLY | os.O_DIRECTORY)
    try:
        data_fd = _step(base_fd, data.name, create, final=False)
    finally:
        os.close(base_fd)
    try:
        return _step(data_fd, directory.name, create, final=True)
    finally:
        os.close(data_fd)


def _write(dirfd, name, text):
    """Exclusive, unpredictable 0600 temporary in the same folder, then an atomic rename. A symlink
    planted at the temporary or the final name is never written through: O_EXCL|O_NOFOLLOW refuses
    the first, and rename replaces the second instead of following it."""
    tmp = '.%s.%s.tmp' % (name, os.urandom(8).hex())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dirfd)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
        os.replace(tmp, name, src_dir_fd=dirfd, dst_dir_fd=dirfd)
    except Exception:
        try:
            os.unlink(tmp, dir_fd=dirfd)
        except OSError:
            pass
        raise


def _read(dirfd, name):
    """A regular file only: a link is refused, and a pipe or device cannot make the open hang."""
    seen = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
    if not _stat.S_ISREG(seen.st_mode):
        raise OSError('not a regular file')
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0), dir_fd=dirfd)
    with os.fdopen(fd, 'r', encoding='utf-8') as handle:
        opened = os.fstat(handle.fileno())
        if not _stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (seen.st_dev, seen.st_ino):
            raise OSError('not a regular file')
        return handle.read(1000000)


def write_charter(result, directory):
    """Write CHARTER.md and charter-settings.yaml into `directory` (created owner-only). Nothing else."""
    directory = Path(directory)
    dirfd = _open_dir(directory, create=True)
    try:
        _write(dirfd, CHARTER_FILE, result['charter'])
        _write(dirfd, SETTINGS_FILE, result['settings_yaml'])
    finally:
        os.close(dirfd)
    return [str(directory / CHARTER_FILE), str(directory / SETTINGS_FILE)]


def read_charter(directory):
    """(charter text, settings yaml) of the last compile, or None when there is none."""
    try:
        dirfd = _open_dir(directory, create=False)
    except OSError:
        return None
    try:
        return _read(dirfd, CHARTER_FILE), _read(dirfd, SETTINGS_FILE)
    except (OSError, UnicodeError):
        return None
    finally:
        os.close(dirfd)


NO_CHARTER = ('No charter has been compiled yet. Ask the agent to run the Axiōma Charter interview: it asks '
              'the questions one at a time, reads your answers back, then compiles the page. Nothing is '
              'applied to any setting.')

SCHEMA = {
    'name': 'axioma_charter',
    'description': 'Axiōma Charter: a plain-English permission interview that compiles into a one-page '
                   'charter and a matching settings block. Advice only: it applies nothing, edits no '
                   'config and no profile. Actions: questions (the interview), compile (answers -> '
                   'charter text, settings YAML and problems; writes CHARTER.md and '
                   'charter-settings.yaml in the plugin data folder), show (the last compiled charter). '
                   'Ask the questions ONE AT A TIME in plain English, no jargon, and pass the owner\'s own '
                   'answers; leave an unanswered question out rather than guessing. Before compile, read '
                   'all answers back in plain words and get the owner\'s yes (use preview: true to read '
                   'the charter itself back without writing a file), then read the compiled charter and '
                   'every problem back, including its "To use this" section. Tell the owner nothing was '
                   'applied and that they add the settings by hand, keeping the rules they already have.',
    'parameters': {'type': 'object', 'required': ['action'], 'additionalProperties': False, 'properties': {
        'action': {'type': 'string', 'enum': ['questions', 'compile', 'show']},
        'answers': {'type': 'object', 'description': 'Question id -> the owner\'s answer (compile only).'},
        'preview': {'type': 'boolean', 'description': 'compile only: return the charter without writing files.'},
    }},
}


def make_handler(directory_fn):
    """Tool handler. `directory_fn()` names the one charter folder; the caller cannot choose a path."""
    def handler(args, **kwargs):
        def reply(**fields):
            return json.dumps(dict(fields, applied=False, note=NOTHING_APPLIED), ensure_ascii=False)
        try:
            if not isinstance(args, dict) or set(args) - {'action', 'answers', 'preview'}:
                return reply(error='expected {action, answers?, preview?}')
            action = args.get('action')
            if action == 'questions':
                return reply(status='questions', intro=INTRO, questions=questions(), files=[])
            if action == 'compile':
                result = compile_charter(args.get('answers'))
                fields = dict(status='compiled', fingerprint=result['fingerprint'], complete=result['complete'],
                              problems=result['problems'], charter=result['charter'],
                              settings_yaml=result['settings_yaml'])
                if args.get('preview') is True:
                    return reply(files=[], **fields)
                return reply(files=write_charter(result, directory_fn()), **fields)
            if action == 'show':
                found = read_charter(directory_fn())
                if found is None:
                    return reply(status='none', message=NO_CHARTER, files=[])
                return reply(status='shown', files=[], charter=found[0], settings_yaml=found[1],
                             files_match=_fingerprints(found[0]) == _fingerprints(found[1]) != [])
            return reply(error='action must be questions, compile or show')
        except Exception as exc:
            return reply(error='charter failed: ' + str(exc)[:200])
    return handler


def _fingerprints(text):
    return sorted(set(re.findall(r'AXC-[0-9a-f]{12}', text)))


def command(directory_fn):
    """The /charter slash command: print the last charter, or say how to start."""
    def run(raw=''):
        found = read_charter(directory_fn())
        if found is None:
            return NO_CHARTER
        return found[0] + '\nNothing was applied. Settings: %s in the charter folder.' % SETTINGS_FILE
    return run
