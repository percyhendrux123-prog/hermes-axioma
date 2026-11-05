"""Explicit matching, not semantic shell analysis or a security sandbox.

SCRUB is BEST-EFFORT shell-command parsing. It reads the common shapes of rm/mv/unlink/rmdir and
flags what it cannot prove contained. When a remove or move has a shape the token walk cannot read
(a quoted or escaped separator among its words, or a command word that is itself an expansion,
including behind sudo/time/if/!/{ or inside quotes), `unparsed()` says so; the advisor then labels
the card "could not parse" and caps it at CAUTION, never GO. It is not a shell interpreter.
"""
from fnmatch import fnmatchcase
import re
import shlex
from pathlib import Path

# Host tools/cronjob_tools.py: run, run_now and trigger all fire a job immediately.
CRON_ACTIONS = ['create', 'add', 'update', 'resume', 'run', 'run_now', 'trigger']
REMOVERS = ('rm', 'mv', 'unlink', 'rmdir')
# Always SCRUB: deletion whose targets are computed elsewhere (not provable from the command line).
ALWAYS_SCRUB = re.compile(
    r'\bfind\b[^\n;&|]*\s-(?:delete|exec(?:dir)?\s+(?:\S*/)?(?:rm|unlink|rmdir)\b)'
    r'|\brsync\b[^\n;&|]*\s--(?:del\b|delete|remove-source-files)'
    r'|\bgit\s+(?:-\S+\s+(?:\S+\s+)?)*clean\b', re.IGNORECASE)


# Words after which the next word is still in command position (with their options skipped).
PREFIXES = {'sudo', 'doas', 'time', 'nohup', 'exec', 'command', 'builtin', 'env', 'nice', 'ionice',
            'timeout', 'stdbuf', 'xargs', 'then', 'do', 'else', 'elif', 'if', 'while', 'until', '!', '{'}
# Prefix options that consume the following word (sudo -u USER, env -u NAME, nice -n N, ...).
ARG_OPTS = {'sudo': set('ugCDhprtUT'), 'doas': set('uC'), 'env': set('uCS'), 'nice': set('n'),
            'ionice': set('cnp'), 'timeout': set('sk'), 'stdbuf': set('ioe'), 'xargs': set('IdEeLnPs')}
SEPARATORS = ';&|()\n'
OPAQUE = ';&|#()'


class Word:
    __slots__ = ('text', 'opaque', 'expands', 'bare', 'glob')

    def __init__(self):
        # opaque: a separator character was quoted/escaped in it; expands: holds $ or a backtick;
        # bare: an UNQUOTED $ or backtick, which the shell word-splits after expanding.
        # glob: an UNQUOTED '*', '?', '[' or '{', which bash may expand (pathname or brace expansion).
        self.text, self.opaque, self.expands, self.bare, self.glob = '', False, False, False, False


def lex(command):
    """Quote-aware split into segments of words. A word is `opaque` when a separator character
    (; & | # ( )) appears in it quoted or escaped, and `expands` when it holds an unquoted or
    double-quoted $ or backtick. Raises ValueError on an unterminated quote."""
    segments, words, word, i, n = [], [], None, 0, len(command)
    while i < n:
        c = command[i]
        if c in ' \t' or c in SEPARATORS:
            if word is not None:
                words.append(word)
                word = None
            if c in SEPARATORS and words:
                segments.append(words)
                words = []
        elif c == '#' and word is None:
            while i < n and command[i] != '\n':
                i += 1
            continue
        else:
            word = word or Word()
            if c == '\\':
                i += 1
                if i < n:
                    word.opaque |= command[i] in OPAQUE
                    word.text += command[i]
            elif c == "'":
                close = command.find("'", i + 1)
                if close < 0:
                    raise ValueError('unterminated quote')
                body = command[i + 1:close]
                word.opaque |= any(x in body for x in OPAQUE)
                word.text += body
                i = close
            elif c == '"':
                i += 1
                while i < n and command[i] != '"':
                    if command[i] == '\\' and i + 1 < n and command[i + 1] in '$`"\\\n':
                        i += 1
                    elif command[i] in '$`':
                        word.expands = True
                    word.opaque |= command[i] in OPAQUE
                    word.text += command[i]
                    i += 1
                if i >= n:
                    raise ValueError('unterminated quote')
            else:
                word.expands |= c in '$`'
                word.bare |= c in '$`'
                word.glob |= c in '*?[{'
                word.text += c
        i += 1
    if word is not None:
        words.append(word)
    if words:
        segments.append(words)
    return segments


def command_index(words):
    """Index of the command word of a segment, skipping assignments, prefixes and their options."""
    i, prefix = 0, None
    while i < len(words):
        text = words[i].text
        if prefix is None and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', text):
            # An assignment (even X=$(...) or X="$PWD") names no command; its value is not run here.
            i += 1
            continue
        if text in PREFIXES and not words[i].expands:
            prefix = text
            i += 1
            if prefix == 'timeout':  # timeout [options] DURATION COMMAND
                while i < len(words) and words[i].text.startswith('-'):
                    i += 1
                i += 1
            continue
        if prefix and text.startswith('-') and len(text) > 1:
            letter = text[1] if not text.startswith('--') else ''
            i += 2 if (letter in ARG_OPTS.get(prefix, ()) and len(text) == 2) else 1
            continue
        if prefix == 'env' and '=' in text:
            i += 1
            continue
        return i
    return None


# The delimiter word after '<<' / '<<-': read up to whitespace or a separator, then unquoted the way
# bash does ('E""OF' is EOF, 'EOF-1' is EOF-1). A quoted delimiter means the body is not expanded.
HEREDOC = re.compile(r'<<(-?)[ \t]*((?:[^\s;&|()<>\'"]|\'[^\'\n]*\'|"[^"\n]*")+)')
# Heredoc bodies fed to these are data, not shell commands. A body fed to a shell (bash, sh, ssh,
# ...) or to anything not listed is still read line by line.
DATA_SINKS = {'cat', 'tee'}
NON_SHELL = DATA_SINKS | {'python', 'python3', 'node', 'ruby', 'perl', 'jq', 'psql', 'mysql', 'sqlite3'}


def _live_heredocs(line):
    """HEREDOC matches on one line that bash would treat as heredocs: outside quotes, not escaped,
    and not inside a comment (a '#' that starts a word)."""
    live, i, n, quote = [], 0, len(line), None
    while i < n:
        c = line[i]
        if quote:
            if c == '\\' and quote == '"':
                i += 2
                continue
            if c == quote:
                quote = None
        elif c == '\\':
            i += 2
            continue
        elif c in '\'"':
            quote = c
        elif c == '#' and (i == 0 or line[i - 1] in ' \t;&|()'):
            break
        elif line.startswith('<<', i) and not line.startswith('<<<', i):
            m = HEREDOC.match(line, i)
            if m:
                live.append(m)
                i = m.end()
                continue
        i += 1
    return live


def strip_heredocs(command, consumers):
    """Drop a heredoc body only in ONE shape; otherwise return the command unchanged (every body is
    read as commands, which can only add notices, never remove them).

    The one shape (AXIOM decision after review pass 14): the whole command is a single simple
    command on its first line, whose command word is in `consumers`, with exactly one heredoc
    (outside quotes and comments), no pipe, list, group, fd duplication or process substitution on
    that line (only plain words and `>`/`>>` file redirects), a closing delimiter that appears, an
    unexpanded body (quoted delimiter) or one with no `$(`/backtick, and nothing but blank or comment
    lines after the delimiter."""
    if re.search(r'\\\r?\n', command):
        return command  # backslash-newline: bash joins it outside quoted bodies only; don't guess
    lines = command.split('\n')
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return command
    line = lines[0]
    found = _live_heredocs(line)
    if len(found) != 1:
        return command
    m = found[0]
    rest = line[:m.start()] + ' ' + line[m.end():]
    if re.search(r'[;&|(){}<`]|\$\(|>&|>\s*>?\s*\(', rest):
        return command
    words = rest.replace('>>', ' ').replace('>', ' ').split()
    name = next((w.lower() for w in words if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', w)), '')
    if name not in consumers or name in PREFIXES:
        return command
    raw = m.group(2)
    quoted = any(q in raw for q in '\'"\\')
    delim = re.sub(r'[\'"\\]', '', raw)
    dash = m.group(1)
    end = next((j for j in range(1, len(lines))
                if (lines[j].lstrip('\t') if dash else lines[j]) == delim), None)
    if end is None:
        return command
    if not quoted and re.search(r'\$\(|`', '\n'.join(lines[1:end])):
        return command
    if any(x.strip() and not x.strip().startswith('#') for x in lines[end + 1:]):
        return command
    return '\n'.join([line, lines[end]])


def _misread(word):
    """The token walk drops quoting, so a quoted/escaped word that is only separator characters
    (';', '|', '&&', '()') reads as a separator, and one starting with '#' reads as a comment.
    Quoted separators inside a longer word ("b (copy).txt", "/w/#notes") are read correctly."""
    return word.opaque and bool(word.text) and (set(word.text) <= set(';&|()') or word.text.startswith('#'))


def _named_by_expansion(words):
    """True when a segment's command name is not visible: its last path component comes from an
    expansion, or any part is an unquoted expansion (word-split: $V/tool can run "/bin/rm -rf ...")."""
    at = command_index(words)
    if at is None:
        return False
    if _globbed(words[at]):
        return True
    if not words[at].expands:
        return False
    return words[at].bare or any(c in words[at].text.rsplit('/', 1)[-1] for c in '$`')


# Commands a brace or glob pattern in the command word could turn into, and that SCRUB reads.
GLOB_TARGETS = REMOVERS + ('find', 'rsync', 'git', 'xargs', 'sudo', 'doas', 'env', 'command', 'exec', 'eval',
                           'sh', 'bash', 'zsh', 'dash', 'ksh', 'fish', 'shred', 'srm', 'trash')


def _brace_words(text, limit=64):
    """Brace expansion of one word ({a,b}, x{,y}, {1..3} kept literal), bounded; the shell would
    run the FIRST resulting word as the command."""
    m = re.search(r'\{([^{}]*)\}', text)
    if not m or ',' not in m.group(1):
        return [text]
    out = []
    for alt in m.group(1).split(','):
        out += _brace_words(text[:m.start()] + alt + text[m.end():], limit)
        if len(out) >= limit:
            break
    return out[:limit]


def _globbed(word):
    """True when bash would expand the command word itself into a command SCRUB reads: brace
    expansion ({rm,-rf,x}, r{m,}) or a pathname pattern (/bin/r?, /bin/r[m], /bin/r*). Patterns
    that cannot name one of GLOB_TARGETS stay quiet ('*.py)' case patterns, '[Unit]' or '* item' in a
    heredoc body), as do '[', '[[' and group braces. A bare wildcard-only word ('*', '?') is a case
    pattern or list bullet far more often than a command, and stays quiet (documented limit)."""
    import fnmatch
    text = word.text
    if not word.glob or text in ('[', '[[', '{', '}', ']]'):
        return False
    if re.search(r'\{[^{}]*,[^{}]*\}', text):
        if text.count('{') > 16:
            return True  # too many brace groups to expand here: could not parse
        cands = [c for c in _brace_words(text) if c]  # bash drops empty words; the first one runs
        text = cands[0] if cands else ''
        if Path(text).name.lower() in GLOB_TARGETS:
            return True
    name = Path(text).name
    if not any(c in name for c in '*?['):
        return False
    if '/' not in text and not re.sub(r'[*?]', '', name):
        return False  # a bare wildcard-only word: case pattern or list bullet
    return any(fnmatch.fnmatchcase(t, name.lower()) for t in GLOB_TARGETS)


def _try(fn):
    try:
        fn()
        return True
    except Exception:
        return False

DEFAULTS = [
    {'id': 'message-send', 'category': 'send', 'tool': 'send_message'},
    {'id': 'email-send', 'category': 'send', 'tool': '*send_email*'},
    {'id': 'message-connectors', 'category': 'send', 'tool': '*__send_message*'},
    {'id': 'post', 'category': 'send', 'tool': '*create_post*'},
    {'id': 'post-message', 'category': 'send', 'tool': '*post_message*'},
    {'id': 'tweet', 'category': 'send', 'tool': '*post_tweet*'},
    {'id': 'publish', 'category': 'send', 'tool': '*publish*'},
    {'id': 'payment', 'category': 'spend', 'tool': '*create_payment*'},
    {'id': 'payment-confirm', 'category': 'spend', 'tool': '*confirm_payment*'},
    {'id': 'payment-capture', 'category': 'spend', 'tool': '*capture_payment*'},
    {'id': 'checkout', 'category': 'spend', 'tool': '*create_checkout*'},
    {'id': 'purchase', 'category': 'spend', 'tool': '*create_purchase*'},
    {'id': 'charge', 'category': 'spend', 'tool': '*create_charge*'},
    {'id': 'refund', 'category': 'spend', 'tool': '*create_refund*'},
    {'id': 'cron', 'category': 'spin', 'tool': 'cronjob', 'actions': CRON_ACTIONS},
    # Native dispatch canonicalizes the legacy `cronjob` alias to `cronjob_manage` before hooks run.
    {'id': 'cron-manage', 'category': 'spin', 'tool': 'cronjob_manage', 'actions': CRON_ACTIONS},
    {'id': 'cron-create', 'category': 'spin', 'tool': '*cron*create*'},
    {'id': 'jobs', 'category': 'spin', 'tool': '*job*create*'},
    {'id': 'agent', 'category': 'spin', 'tool': 'delegate_task', 'actions': ['spawn']},
    {'id': 'kanban', 'category': 'spin', 'tool': 'kanban_create'},
    {'id': 'deploy', 'category': 'spin', 'tool': 'terminal',
     'command': r'\b(?:netlify|vercel|fly(?:ctl)?|firebase|wrangler|railway)\s+(?:[^\n;&|]*\s)?(?:deploy|publish)\b|\b(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:deploy|publish)\b|\bkubectl\s+(?:apply|create|rollout)\b|\bterraform\s+apply\b|\bdocker\s+(?:push|stack\s+deploy)\b'},
    {'id': 'push', 'category': 'send', 'tool': 'terminal',
     'command': r'\bgit\s+(?:-[^\n;&|]*\s)?push\b|\bgh\s+(?:pr\s+(?:create|merge)|release\s+create)\b'},
    {'id': 'terminal-jobs', 'category': 'spin', 'tool': 'terminal',
     'command': r'\bhermes\s+(?:cron|kanban)\s+(?:create|add)\b|\bcrontab\b|\bhermes\s+.*(?:chat|delegate)\b'},
]


class Policy:
    def __init__(self, config=None):
        config = {} if config is None else config
        if not isinstance(config, dict) or set(config) - {'add', 'remove', 'workspace', 'output_dir'}:
            raise ValueError('policy requires add/remove and optional workspace/output_dir')
        self.roots = []
        for key in ('workspace', 'output_dir'):
            if key in config:
                if not isinstance(config[key], str) or not Path(config[key]).is_absolute():
                    raise ValueError('workspace/output_dir must be absolute')
                self.roots.append(Path(config[key]).resolve())
        remove, add = config.get('remove', []), config.get('add', [])
        if not isinstance(remove, list) or not all(isinstance(x, str) for x in remove) or not isinstance(add, list):
            raise ValueError('policy add/remove must be lists')
        if set(remove) - ({r['id'] for r in DEFAULTS} | {'scrub'}):
            raise ValueError('unknown default rule id')
        self.scrub_enabled = 'scrub' not in remove
        rules = [dict(r) for r in DEFAULTS if r['id'] not in remove] + add
        self.rules = []
        ids = set()
        for r in rules:
            if not isinstance(r, dict) or set(r) - {'id', 'category', 'tool', 'actions', 'command'}:
                raise ValueError('invalid rule fields')
            if not all(isinstance(r.get(k), str) and r[k].strip() for k in ('id', 'category', 'tool')):
                raise ValueError('rule id/category/tool required')
            if r['id'] in ids or r['category'] not in ('send', 'spend', 'spin', 'scrub'):
                raise ValueError('duplicate id or invalid category')
            ids.add(r['id'])
            actions = r.get('actions')
            if actions is not None and (not isinstance(actions, list) or not actions or
                                        not all(isinstance(x, str) and x for x in actions)):
                raise ValueError('actions must be nonempty strings')
            try:
                regex = re.compile(r['command'], re.IGNORECASE) if 'command' in r else None
            except (TypeError, re.error) as exc:
                raise ValueError('invalid command regex') from exc
            self.rules.append((dict(r), regex))

    @classmethod
    def lenient(cls, config):
        """(policy, had_error). On a bad config keep every part that is valid on its own.

        Dropping a bad workspace leaves no roots, so SCRUB flags every rm/mv (conservative).
        """
        try:
            return cls(config), False
        except Exception:
            pass
        clean = {}
        if isinstance(config, dict):
            for key in ('workspace', 'output_dir'):
                if key in config and _try(lambda: cls({key: config[key]})):
                    clean[key] = config[key]
            if isinstance(config.get('remove'), list):
                clean['remove'] = [x for x in config['remove'] if _try(lambda: cls({'remove': [x]}))]
            if isinstance(config.get('add'), list):
                good = []
                for rule in config['add']:
                    if _try(lambda: cls({'add': good + [rule]})):
                        good.append(rule)
                clean['add'] = good
        try:
            return cls(clean), True
        except Exception:
            return cls(), True

    def classify(self, tool, args):
        found = set()
        for rule, regex in self.rules:
            if not fnmatchcase(tool, rule['tool']):
                continue
            if 'actions' in rule:
                # Hermes trims + lowercases `action` before acting; delegate_task with no action spawns.
                action = args.get('action')
                action = action.strip().lower() if isinstance(action, str) else ''
                if not action and tool == 'delegate_task':
                    action = 'spawn'
                if action not in [a.strip().lower() for a in rule['actions']]:
                    continue
            if regex is not None and not regex.search(str(args.get('command', ''))):
                continue
            found.add(rule['category'])
        if self.scrub_enabled and tool == 'terminal' and (self.scrubs(args) or self.unparsed(tool, args)):
            found.add('scrub')
        return tuple(x for x in ('send', 'spend', 'spin', 'scrub') if x in found)

    @staticmethod
    def _command(args):
        # Bash removes backslash-newline (line continuation) before parsing; do the same.
        return str(args.get('command', '')).replace('\\\r\n', '').replace('\\\n', '')

    def _stripped(self, args, consumers):
        """The command with a heredoc body dropped only in strip_heredocs' one shape. The check
        runs on the RAW command: bash keeps backslash-newline inside a quoted body, so a joined
        command could move the closing delimiter."""
        raw = str(args.get('command', ''))
        if strip_heredocs(raw, consumers) == raw:
            return self._command(args)
        return self._command({'command': strip_heredocs(raw, consumers)})

    def unparsed(self, tool, args):
        """True when SCRUB could not parse a remove/move (or an expansion-named command). Best effort:
        the card then says "could not parse" and is capped at CAUTION. Plain commands are untouched."""
        if not self.scrub_enabled or tool != 'terminal' or not isinstance(args, dict):
            return False
        command = self._stripped(args, NON_SHELL)
        if not re.search(r'[\'"\\$`*?\[{]', command):
            return False  # nothing quoted, escaped or expanded: the token walk reads it as written
        try:
            segments = lex(command)
        except ValueError:
            return bool(re.search(r'\b(?:rm|mv|unlink|rmdir)\b', re.sub(r'[\'"\\]', '', command), re.I))
        for words in segments:
            at = command_index(words)
            if at is None:
                continue
            if _named_by_expansion(words):
                return True  # the command itself is an expansion: what runs is not visible here
            name = Path(words[at].text).name.lower()
            if name in REMOVERS and any(_misread(w) for w in words[at + 1:]):
                return True  # a quoted/escaped separator the walk reads as a real one: can't trust it
        return False

    def scrubs(self, args):
        command = self._stripped(args, DATA_SINKS)
        # Pre-check on the command with quotes/backslashes removed, so m""v and 'rm' still match.
        # Case-insensitive: macOS file systems run RM and MV as rm and mv.
        unquoted = re.sub(r'[\'"\\]', '', command)
        if ALWAYS_SCRUB.search(unquoted):
            return True
        # A command word that is itself an expansion ($DEL, ${a}m, $(...), `...`) can't be named.
        # A literal last path component ("$HOME/bin/tool", $VENV/bin/rm) still names the command,
        # and the walk below reads it. Unparseable quoting falls back to the coarse pattern.
        try:
            # Bodies fed to python/node/... are not shell commands; their words name nothing.
            hidden = any(_named_by_expansion(words) for words in lex(self._stripped(args, NON_SHELL)))
        except ValueError:
            hidden = bool(re.search(r'(?:^|[;&|(\n]|\$\()\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*[$`]', command))
        if hidden:
            return True
        if not re.search(r'\b(?:rm|mv|unlink|rmdir)\b', unquoted, re.IGNORECASE):
            return False
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|()')
            lexer.whitespace_split = True
            lexer.commenters = ''  # bash: '#' starts a comment only at the start of a word
            tokens = list(lexer)
        except ValueError:
            return True
        # Unknown is flagged, never assumed contained. The host's persistent terminal cwd is
        # not visible to plugins, so a relative operand needs an explicit absolute `workdir`.
        workdir = args.get('workdir')
        cwd = Path(workdir) if isinstance(workdir, str) and Path(workdir).is_absolute() else None

        def is_separator(t):
            return bool(t) and all(c in ';&|()' for c in t)

        def command_name(t):
            # Subshells and substitutions: (cd, $(rm, `rm, {rm. Lowercased for case-insensitive FS.
            return Path(t.lstrip('`$({')).name.lower()
        seen_command = False
        for i, token in enumerate(tokens):
            name = command_name(token)
            if name not in REMOVERS:
                continue
            seen_command = True
            if any(command_name(t) == 'xargs' for t in tokens[:i]):
                return True  # xargs appends targets from stdin: never provable from the command line
            operands, rest, j = [], tokens[i + 1:], 0
            while j < len(rest):
                t = rest[j]
                j += 1
                if is_separator(t) or t.startswith('#'):
                    break  # separator, or a word-initial '#' comment
                if t == '--':
                    for x in rest[j:]:
                        if is_separator(x):
                            break
                        operands.append(x)
                    break
                if name == 'rm' and t.startswith('--') and len(t) > 2 and '--recursive'.startswith(t):
                    return True  # GNU accepts unique abbreviations: --r, --recur, ...
                if name == 'rm' and (t.startswith('-') and not t.startswith('--') and 'r' in t[1:].lower()):
                    return True
                if name == 'rmdir' and (t == '--parents' or (t.startswith('-') and not t.startswith('--') and 'p' in t[1:])):
                    return True  # -p also removes parent directories, up to and past the workspace
                opt = t.split('=', 1)[0]
                if name == 'mv' and t.startswith('--') and len(opt) > 2 and '--target-directory'.startswith(opt):
                    if '=' in t:
                        operands.append(t.split('=', 1)[1])
                    elif j < len(rest):
                        operands.append(rest[j])
                        j += 1
                    continue
                if name == 'mv' and t.startswith('-') and not t.startswith('--') and 't' in t[1:]:
                    # GNU short-flag cluster (-t DIR, -tDIR, -ftDIR): after `t` comes the target.
                    attached = t[t.index('t', 1) + 1:]
                    if attached:
                        operands.append(attached)
                    elif j < len(rest):
                        operands.append(rest[j])
                        j += 1
                    continue
                if not t.startswith('-'):
                    operands.append(t)
            if not self.roots:
                return True  # workspace unknown is not evidence of containment
            if not operands:
                return True  # targets come from elsewhere (xargs, stdin): not proven contained
            if any(command_name(x) in ('cd', 'pushd', 'popd') for x in tokens):
                return True  # any directory change in the command makes the effective cwd unknown
            for operand in operands:
                if any(c in operand for c in '$*?~`{}[]'):
                    return True  # shell expansion (incl. brace/bracket): containment unknown
                if not Path(operand).is_absolute() and cwd is None:
                    return True  # relative operand, cwd unknown: not proven contained
                path = ((cwd or Path('/')) / operand).resolve()
                if not any(path == root or root in path.parents for root in self.roots):
                    return True
        if not seen_command and ('$' in command or '`' in command):
            return True  # rm/mv named only through a variable or substitution: not provable
        return False
