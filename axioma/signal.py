"""Inline signal color inside the agent's NORMAL reply. No cards.

The agent marks the few spans of its own prose that deserve the human's curiosity, using the
Axiōma Signal Spec v0.1 markup (section 3.1):

    [signal:stop;why=no_eval]without an eval or a test[/signal]
    [signal:caution]merge into Hermes[/signal]
    [signal:go;check=terminal]passed 41 of 41[/signal]
    [whisper:unverified_figure]about 4,200 users[/whisper]

`transform_llm_output` renders them per surface, never color alone (spec 4.1):
  cli / tui   ANSI 24-bit color + a style cue (bold+underline, underline, italic) + the word
  desktop     KaTeX \\color{} (what Hermes Desktop's sanitizer keeps) + the word outside the math
  markdown    **bold** + the word (Telegram, Discord, ...)
  plain       the word only (SMS, iMessage, unknown surfaces)

It advises. It never blocks, approves or executes anything. Green renders only when a tool call
the host reported as passing backs it. Every complete stop, caution, whisper and go tag is logged as metadata
(salted hash, no bodies). In a reply that holds a tag, tags never leak, including malformed ones; a
reply with no exact or cut-off tag is returned unchanged, and code is never stripped (README).
"""
import hashlib
import json
import re
import threading
import uuid

LEVELS = ('stop', 'caution', 'go', 'intent')
ALIASES = {'red': 'stop', 'yellow': 'caution', 'green': 'go', 'white': 'intent'}
REASONS = ('low_confidence', 'unverified_figure', 'voice_drift', 'assumption')
WORDS = {'stop': 'stop', 'caution': 'caution', 'go': 'go', 'whisper': 'second look'}
SEVERITY = {'stop': 0, 'caution': 1, 'go': 2}
EMPTY = '(empty reply)'

# Spec 4.6. Night = axioma.yaml, day = axioma-day.yaml. 'cvd' = color-vision-safe: night is the
# Okabe-Ito set from the spec; day was found by search with the spec's own method (Machado 2009 +
# CIEDE2000): every gate pair >= 12 under protan/deutan/tritan simulation, contrast >= 5.2:1 on
# #F6F5F1 (docs/evidence/cvd/). Simulation only; not yet tested with CVD readers.
PALETTES = {
    ('dark', 'default'): {'intent': 'F0F0EE', 'stop': 'FF453A', 'caution': 'FFCC00', 'go': '30D158', 'whisper': 'EADFB8'},
    ('light', 'default'): {'intent': '1A1B1E', 'stop': 'D70015', 'caution': 'A66B00', 'go': '248A3D', 'whisper': '8A6A1F'},
    ('dark', 'cvd'): {'intent': 'F0F0EE', 'stop': 'E8603C', 'caution': 'F0E442', 'go': '56B4E9', 'whisper': 'EADFB8'},
    ('light', 'cvd'): {'intent': '1A1B1E', 'stop': 'CA163A', 'caution': '684B08', 'go': '156079', 'whisper': '8A6A1F'},
}
# Terminal style cues: standard SGR only (no extended-underline guessing, spec 4.2).
STYLE = {'stop': '1;4', 'caution': '4', 'go': '3', 'intent': '1', 'whisper': ''}
# Each style is turned off with exactly the codes that undo what it set.
STYLE_OFF = {'stop': '\x1b[22;24m', 'caution': '\x1b[24m', 'go': '\x1b[23m', 'intent': '\x1b[22m', 'whisper': ''}
FG_OFF = '\x1b[39m'

TERMINAL = {'cli', 'tui'}
DESKTOP = {'desktop'}
MARKDOWN = {'telegram', 'discord', 'slack', 'matrix', 'mattermost', 'api_server', 'dashboard',
            'hermes_browser', 'browser', 'acp', 'webui', 'feishu', 'dingtalk', 'wecom'}

DEFAULT_BUDGET = {'max_spans': 3, 'max_whispers': 2, 'max_span_words': 16}
TOKEN = re.compile(r'^[A-Za-z0-9_.\-]{1,64}$')
# A tag: an opening [kind:value...], or a closing [/kind]. A valueless opener ([signal],
# [signal:]) is a tag only when a closer of the same kind follows on its line; otherwise it is a
# lookalike (array[signal]) and is left alone. A tag cut off at the end of a line or before inline
# code (a truncated stream) is removed, so it can never leak. Values have no length cap, and
# zero-width characters inside a tag do not hide it.
_W = r'[\s\u200b-\u200d\u2060\ufeff]*'
# Loose forms ([signal stop], [signal_stop], [signal\:stop], [signal：stop], [whisper(x)]): any
# character after the keyword that is not a letter, digit, ':' or ']' makes a weak tag, which is
# removed only when a closer of its kind follows (else left as text: array[signal_1]). A closer may
# carry a markdown escape ([\/signal]) or trailing junk ([/signal and more]).
# No tag part may contain '[', so a broken opener can never swallow the tags after it. Loose forms
# that read as a tag ([signal stop], [signal=stop], [signal\:stop], [signal：stop]) are always tags
# (marked strong, rendered plain); other punctuation ([signal_1], [whisper.level]) stays weak.
# A BROKEN tag (its ']' never comes before the next '[' or the end of the line) loses only its
# keyword and value ([signal:stop;why=x, [/signal, [signal ) and the rest of the line stays; a broken
# closer still closes.
TAG = re.compile(r'\[' + _W + r'(?:(?P<close>\\*/)' + _W + r'(?P<ckind>signal|whisper)' + _W + r'(?:[^A-Za-z0-9\]\[\n][^\]\[\n]*)?'
                 r'|(?P<okind>signal|whisper)' + _W + ':' + _W + r'(?P<value>[^\]\[\n\s][^\]\[\n]*?)'
                 r'|(?P<wkind>signal|whisper)' + _W + r':?'
                 r'|(?P<skind>signal|whisper)(?:[\s=\\\uff1a\ufe55\ufe13][^\]\[\n]*)'
                 r'|(?P<lkind>signal|whisper)[^A-Za-z0-9:\]\[\n][^\]\[\n]*)' + _W + r'\]'
                 r'|\[' + _W + r'(?:(?P<bclose>\\*/)' + _W + r')?(?P<bkind>signal|whisper)(?![A-Za-z0-9])'
                 r'(?:[ \t]*[:=\\\uff1a][ \t]*[^\s\[\]]*)?(?=[^\]\[\n]*(?:\[|$))',
                 re.IGNORECASE | re.MULTILINE)
# Fences, including inside list items and blockquotes (any indent, '>', '-', '*', '+', '1.' first).
# A backtick fence's info string has no backtick; the closer uses the same character, is at least as
# long, and has nothing after it. Code detection only decides styling (see Signal.parse): a wrong
# guess can cost color, never leak a tag or hide a stop.
# Invisible characters a tag could hide behind ([sig<ZWSP>nal:stop]): removed inside a bracket
# only when what remains is a tag. A keyword cut off at the very end of a reply is removed too.
INVISIBLE = re.compile('[\x00-\x08\x0e-\x1f\x7f\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u2060-\u206f'
                       '\u3164\ufe00-\ufe0f\ufeff\uffa0]')
# Starts at the LAST '[' before a ']', so an earlier unclosed '[' can't hide the tag behind it.
BRACKET = re.compile(r'\[[^\[\]\n]*\]?')
# CommonMark HTML block starts (types 1-7): '<' at the start of a line, also behind blockquote and
# list markers ('> <div>', '- <div>', '1. <div>'), which open an HTML block inside the container.
HTML_BLOCK = re.compile(r'^[ \t]*(?:(?:>|[-+*]|\d{1,9}[.)])[ \t]*)*<(?:[A-Za-z][A-Za-z0-9-]*(?:[\s/>]|$)|/[A-Za-z]|!--|\?|![A-Za-z]|!\[CDATA\[)',
                        re.MULTILINE)
# A link Desktop's GFM autolinks would extend over the math: www., a scheme, or an email address.
LINKISH = re.compile(r'(?:www\.|[A-Za-z][A-Za-z0-9+.\-]*://|[^\s@]@[^\s@]+\.)\S*$', re.IGNORECASE)
_WL = r'[ \t\u200b-\u200d\u2060\ufeff]*'
TRUNCATED = re.compile(r'\[' + _WL + r'/?' + _WL + r'(?:sig(?:n(?:a(?:l)?)?)?|whi(?:s(?:p(?:e(?:r)?)?)?)?)' + _WL
                       + r'(?:$|(?=\[))', re.IGNORECASE | re.MULTILINE)
# Tag-shaped strings: any opener or closer with a ']', and a cut-off keyword before '[' or line end.
SPLICED = re.compile(r'\[\s*\\?/?\s*(?:signal|whisper)\b[^\]\[\n]*\]'
                     r'|\[\s*\\?/?\s*(?:sig(?:n(?:a(?:l)?)?)?|whi(?:s(?:p(?:e(?:r)?)?)?)?)\s*(?=\[|$)',
                     re.IGNORECASE | re.MULTILINE)
FENCE = re.compile(r'^[ \t]*(?:(?:>|[-+*]|\d{1,9}[.)])[ \t]*)*(`{3,}|~{3,})(.*)$')
# Exact Axiōma tag forms. A reply holds tags only if it has one of these: an opener with a
# known value and its ']' ([signal:stop;why=x], [whisper:assumption]) or an exact closer
# ([/signal], [\/whisper]). A reply without one is returned unchanged, so loose, broken or cut-off
# lookalikes in ordinary text and code (df[signal > 0], mask[sig[0]]) are never touched.
STRICT_OPEN = re.compile(r'\[' + _W + r'(signal|whisper)' + _W + ':' + _W + r'([^\]\[\n]+?)' + _W + r'\]', re.IGNORECASE)
STRICT_CLOSE = re.compile(r'\[' + _W + r'\\*/' + _W + r'(?:signal|whisper)' + _W + r'\]', re.IGNORECASE)
# A tag cut off by a truncated stream also counts, in prose only (never in code): an opener with a
# ':' or a closer whose ']' never comes ([signal:stop;why=x, [/signal), or a keyword or prefix cut
# off at the very end of the reply (ok [signal, ok [/sig). Code-shaped forms (df[signal > 0],
# mask[sig[0]], arr[whisper = 3]) match none of these.
CUT_TAG = re.compile(r'\[' + _W + r'(?:\\*/' + _W + r'(?:signal|whisper)(?![A-Za-z0-9])|(?:signal|whisper)' + _W + ':)'
                     r'[^\]\[\n]*(?=\[|$)', re.IGNORECASE | re.MULTILINE)
CUT_END = re.compile(r'\[' + _WL + r'/?' + _WL + r'(?:sig(?:n(?:a(?:l)?)?)?|whi(?:s(?:p(?:e(?:r)?)?)?)?)' + _WL + r'\s*\Z',
                     re.IGNORECASE)
INDENTED = re.compile(r'^(?: {4}|\t)')
# Hermes Desktop's own East Asian rule (apps/desktop/src/lib/markdown-preprocess.ts CJK_RE): a math
# body containing these is escaped back to prose, so such spans never use the math path.
CJK = re.compile('[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af\uff00-\uffef]')
ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)?|[@-_])')
SAFE_AFTER_MATH = set(' \t.,;:!?)]}\'"')
# Control, line/paragraph separators and bidirectional overrides/isolates: never inside a span.
CONTROL = re.compile('[\x00-\x08\x0b-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069]')
# Math the agent itself may be writing: $$...$$, \(...\), \[...\], or a '$' that is not currency.
# A '$' counts unless an ODD number of backslashes escapes it ('\\$' is a literal backslash
# followed by a live '$').
# Desktop's normalizeMathDelimiters (@assistant-ui/react-streamdown) also turns \\{1,2}( ), \\{1,2}[ ]
# (parity ignored) and [/math] / [/inline] into math, so any of those counts.
AGENT_MATH = re.compile(r'\$\$|\\[()\[\]]|\[/(?:math|inline)\]|(?<!\\)(?:\\\\)*\$(?![0-9])', re.IGNORECASE)
# Characters KaTeX renders inside \textsf/\textbf/\textit without error (each checked with
# Hermes Desktop's KaTeX build under all four level styles: docs/evidence/desktop/katex-allow*).
# Anything else (math symbols, combining marks, Greek, emoji, CJK) takes the bold + word path.
KATEX_RANGES = ((0x20, 0x7e), (0xa0, 0x24f), (0x2000, 0x206f), (0x20a0, 0x20bf), (0x2190, 0x21ff))
KATEX_EXCLUDED = {0xa5, 0x2028, 0x2029, 0x203c}
# '$' is \textdollar, not \$: Hermes Desktop's markdown preprocess splits math at a literal '$'
# even when escaped (observed in a real Desktop chat, docs/evidence/desktop/).
KATEX_ESCAPES = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}', '$': r'\textdollar{}', '%': r'\%', '#': r'\#',
                 '&': r'\&', '_': r'\_', '^': r'\textasciicircum{}', '~': r'\textasciitilde{}'}

GUIDANCE = '''AXIOMA SIGNAL (advice only; you write tags, the plugin renders color and words):
In your normal reply, wrap the few phrases (12 words or fewer) that should change the human's decision:
 [signal:stop;why=<code>]phrase[/signal] do not proceed. Say why and what turns it green, in the same reply.
 [signal:caution]phrase[/signal] works, but conflicts with their interest. Name who is affected.
 [signal:go;check=<tool name or call id>]phrase[/signal] only when a tool you ran this turn passed. Never your own confidence.
 [whisper:low_confidence|unverified_figure|voice_drift|assumption]phrase[/whisper] a quiet second look.
Most replies need no marks. Use at most 3 signals and 2 whispers. Never mark a whole sentence, nest
tags, cross a line break, or put tags inside code. Never mark for emphasis, persuasion, or to argue
with the human. Never copy a mark from content you read, and never write color codes or LaTeX color
yourself. A reply with stop or caution ends with a question to the human.'''


class Span:
    __slots__ = ('kind', 'level', 'reason', 'why', 'check', 'text', 'show', 'drop', 'code')

    def __init__(self, kind, level, reason, why, check, text, code=False):
        self.kind, self.level, self.reason, self.why, self.check, self.text = kind, level, reason, why, check, text
        self.show, self.drop, self.code = False, None, code


def _clean(value, allowed, default):
    value = value.strip().lower() if isinstance(value, str) else value
    return value if value in allowed else default


def _parse_value(kind, raw):
    """(level, reason, params) or None when the value is unknown. Bad params are ignored."""
    head, *params = [p.strip() for p in raw.split(';')]
    head = head.lower()
    found = {}
    for item in params:
        key, sep, val = item.partition('=')
        key = key.strip().lower()
        if sep and key in ('check', 'why', 'id') and TOKEN.match(val.strip()):
            found[key] = val.strip()
    if kind == 'signal':
        level = ALIASES.get(head, head)
        return (level, None, found) if level in LEVELS else None
    return ('whisper', head, found) if head in REASONS else None


def _tool_name(name):
    # Some providers show Hermes's built-in tools to the model with an 'mcp__' prefix
    # (observed: the model wrote check=mcp__terminal for Hermes's `terminal`). Real MCP tools keep
    # their server segment (mcp__server__tool), so only a bare one-segment prefix is dropped.
    return name[5:] if name.startswith('mcp__') and '__' not in name[5:] else name


def _punct(c):
    import unicodedata
    return bool(c) and unicodedata.category(c)[0] in 'PS'


def _flanks(prev, text, nxt):
    """CommonMark reads '**text**' as bold only when the opener is left-flanking and the closer is
    right-flanking: punctuation at the inner edge needs whitespace, punctuation or the line edge
    on the outside ('x**ship it.**Next' stays literal asterisks)."""
    outside = lambda c: not c or c.isspace() or _punct(c)
    return (not _punct(text[:1]) or outside(prev)) and (not _punct(text[-1:]) or outside(nxt))


def katex_char_ok(c):
    o = ord(c)
    return o not in KATEX_EXCLUDED and any(a <= o <= b for a, b in KATEX_RANGES)


def katex_text(text):
    return ''.join(KATEX_ESCAPES.get(c, c) for c in text)


class Signal:
    def __init__(self, audit, theme='dark', palette='default', words='always', budget=None,
                 messaging_marker=True, env=None):
        import os
        self.audit = audit
        self.env = os.environ if env is None else env
        # A cosmetic setting never breaks registration: normalize, else fall back to the default.
        self.theme = _clean(theme, ('dark', 'light'), 'dark')
        self.palette = _clean(palette, ('default', 'cvd', 'none'), 'default')
        self.words = _clean(words, ('always', 'plain_only'), 'always')
        if isinstance(messaging_marker, str):
            messaging_marker = messaging_marker.strip().lower() in ('true', 'yes', '1', 'on')
        self.messaging_marker = messaging_marker is not False
        self.budget = dict(DEFAULT_BUDGET)
        if isinstance(budget, dict):
            for key, value in budget.items():
                if key in DEFAULT_BUDGET and isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    self.budget[key] = value
        self.lock = threading.Lock()
        self.checks = {}  # session_id -> [(turn_id, tool_call_id, tool_name)] that the host reported ok

    # -- observed checks (spec 5.1: green only from real checks) -------------------------------
    def observe(self, tool_name='', tool_call_id='', session_id='', turn_id='', status=None, **kwargs):
        """post_tool_call observer: remember calls the HOST reported as passing. Never acts."""
        if status != 'ok' or not tool_name or tool_name == 'axioma_card':
            return
        with self.lock:
            items = self.checks.setdefault(str(session_id or ''), [])
            items.append((str(turn_id or ''), str(tool_call_id or ''), str(tool_name)))
            del items[:-200]
            while len(self.checks) > 256:
                self.checks.pop(next(iter(self.checks)))

    def check_passed(self, check, session_id, turn_id):
        if not check:
            return False
        check = _tool_name(check)
        if not check:
            return False  # 'mcp__' alone names no call
        with self.lock:
            for turn, call_id, name in self.checks.get(str(session_id or ''), []):
                if (call_id and check == call_id) or (check == _tool_name(name) and turn and turn == str(turn_id or '')):
                    return True
        return False

    def finalize(self, session_id='', **kwargs):
        with self.lock:
            self.checks.pop(str(session_id or ''), None)

    # -- parsing ------------------------------------------------------------------------------
    def parse(self, text, kept=None):
        """List of str and Span pieces. Spans never cross lines. `kept`, if given, collects every
        piece of the reply left as written (text between tags, lookalikes) as (offset, text).

        Exact tags are read everywhere; inside code (fenced blocks, indented lines, inline code) only
        exact tags are read, a complete span renders as plain text plus its word with no markup, and
        everything else in code stays as written. Code detection is a best-effort guess; a miss reads
        that code as prose."""
        pieces, fence, base = [], None, 0
        for n, line in enumerate(text.split('\n')):
            if n:
                pieces.append('\n')
                base += 1
            at, base = base, base + len(line)
            m = FENCE.match(line)
            if fence is None and m and not (m.group(1)[0] == '`' and '`' in m.group(2)):
                fence = (m.group(1)[0], len(m.group(1)))
                pieces.extend(self.parse_line(line, code=True, kept=kept, base=at))
                continue
            if fence is not None:
                if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1] and not m.group(2).strip():
                    fence = None
                pieces.extend(self.parse_line(line, code=True, kept=kept, base=at))
                continue
            pieces.extend(self.parse_line(line, code=bool(INDENTED.match(line)), kept=kept, base=at))
        return pieces

    @staticmethod
    def code_spans(line):
        """[(is_code, text)]: a run of N backticks opens a code span only if a run of exactly N
        backticks closes it later on the line (CommonMark); otherwise the backticks are text."""
        out, start, i, n = [], 0, 0, len(line)
        while i < n:
            if line[i] != '`':
                i += 1
                continue
            j = i
            while j < n and line[j] == '`':
                j += 1
            run, k, close = j - i, j, -1
            while k < n:
                if line[k] != '`':
                    k += 1
                    continue
                e = k
                while e < n and line[e] == '`':
                    e += 1
                if e - k == run:
                    close = k
                    break
                k = e
            if close < 0:
                i = j
                continue
            out.append((False, line[start:i]))
            out.append((True, line[i:close + run]))
            i = start = close + run
        out.append((False, line[start:]))
        return out

    def parse_line(self, line, code=False, kept=None, base=0):
        out, open_tag, buf = [], None, []
        tokens, at = [], base
        for is_code, chunk in self.code_spans(line):
            tokens += self.split_tags(chunk, code or is_code, at)
            at += len(chunk)
        # A valueless opener is a tag only if a closer of its kind follows; else it is plain text.
        # Inside code, an opener whose value is not a tag value and has no closer is code
        # (samples[signal:end]) and is kept as written. An opener with an unknown value outside
        # code that has no closer opens nothing and is removed.
        # closer_after[i]: kinds of closers after i and before the next VALID opener (one backward
        # pass, linear time), so a lookalike or unknown opener never takes the closer that belongs
        # to a real span after it ('arr[signal] and [signal:stop]x[/signal]' keeps the stop).
        valid = [kind == 'open' and _parse_value(value[0], value[1]) is not None for kind, value, _ in tokens]
        closer_after, seen = [None] * len(tokens), frozenset()
        for i in range(len(tokens) - 1, -1, -1):
            closer_after[i] = seen
            if tokens[i][0] == 'close':
                seen = seen | {tokens[i][1]}
            elif tokens[i][0] == 'cclose':
                seen = seen | {tokens[i][1][0]}
            elif valid[i] and not tokens[i][1][2]:
                seen = frozenset()  # a valid opener in code does not take its outer span's closers
        for i, (kind, value, pos) in enumerate(tokens):
            if kind == 'open' and value[2] and value[0] not in closer_after[i]:
                tokens[i] = ('text', value[3], pos)  # an opener in code with no closer stays as written
            elif kind == 'open' and not valid[i] and value[0] not in closer_after[i]:
                if len(value) == 4 and value[2]:
                    tokens[i] = ('text', value[3], pos)  # code: kept as written
                else:
                    tokens[i] = ('text', '', pos)  # a malformed opener with nothing to close: removed
            elif kind == 'weak':
                closes = value[0] in closer_after[i]
                tokens[i] = ('open', (value[0], '', value[2]), pos) if closes else ('text', value[1], pos)
        open_raw, open_pos, nested = '', 0, {}
        for kind, value, pos in tokens:
            close_raw = None
            if kind == 'cclose':
                if open_tag is None or open_tag[0] != value[0] or nested.get(value[0]):
                    # a closer in code that closes nothing, a span of another kind, or a
                    # nested opener kept as code text, stays as written.
                    if open_tag is not None and nested.get(value[0]):
                        nested[value[0]] -= 1
                    kind, value = 'text', value[1]
                else:
                    kind, value, close_raw = 'close', value[0], value[1]
            if kind == 'text':
                if kept is not None and value:
                    kept.append((pos, value))
                (buf if open_tag else out).append(value)
            elif kind == 'open':
                if open_tag is None:
                    open_tag = value[:3]  # a nested opener inside a span is dropped
                    open_raw, open_pos = (value[3] if len(value) > 3 else ''), pos
                elif len(value) > 3 and value[2]:
                    buf.append(value[3])  # a nested opener in code stays as written
                    nested[value[0]] = nested.get(value[0], 0) + 1  # and so does its closer in code
                    if kept is not None:
                        kept.append((pos, value[3]))
            elif kind == 'close' and open_tag is not None:
                tag_kind, raw, in_code = open_tag
                parsed = _parse_value(tag_kind, raw) if tag_kind == value else None
                body = ''.join(buf)
                if parsed and body.strip():
                    level, reason, params = parsed
                    out.append(Span(tag_kind, level, reason, params.get('why'), params.get('check'), body,
                                    code=in_code))
                else:
                    # a tag written in code that forms no span (empty or mismatched) stays as
                    # written; a tag in prose goes, and the body stays plain text.
                    head = open_raw if in_code else ''
                    tail = close_raw or ''
                    if kept is not None:
                        if head:
                            kept.append((open_pos, head))
                        if tail:
                            kept.append((pos, tail))
                    out.append(head + body + tail)
                open_tag, buf, nested = None, [], {}
        if open_tag is not None and open_tag[2] and open_raw:
            # an opener in code left open (its closer went to a nested pair) stays as written.
            if kept is not None:
                kept.append((open_pos, open_raw))
            out.append(open_raw)
        out.extend(buf)  # unclosed span: plain text
        return out

    @staticmethod
    def split_tags(segment, code=False, base=0):
        """Tokens (kind, value, offset); offset is `base` plus the position in `segment`."""
        tokens, pos = [], 0
        for m in TAG.finditer(segment):
            if code and not ((m.group('okind') and _parse_value(m.group('okind').lower(), m.group('value')) is not None)
                             or (m.group('close') and STRICT_CLOSE.fullmatch(m.group(0)))):
                continue  # inside code, anything but an exact tag (known value) stays as written
            tokens.append(('text', segment[pos:m.start()], base + pos))
            at = base + m.start()
            if m.group('close') and code:
                tokens.append(('cclose', (m.group('ckind').lower(), m.group(0)), at))
            elif m.group('close'):
                tokens.append(('close', m.group('ckind').lower(), at))
            elif m.group('okind'):
                tokens.append(('open', (m.group('okind').lower(), m.group('value'), code, m.group(0)), at))
            elif m.group('skind'):
                # Reads as a tag but is not the grammar: always removed, the phrase stays plain.
                tokens.append(('open', (m.group('skind').lower(), '', code, m.group(0), 'strong'), at))
            elif m.group('bkind'):
                # Broken (no ']' before the next '[' or the line end): the keyword is removed; a
                # broken closer still closes, a broken opener opens nothing.
                if m.group('bclose') is not None:
                    tokens.append(('close', m.group('bkind').lower(), at))
            elif m.group('wkind') or m.group('lkind'):
                # Valueless ([signal]) or loose ([signal stop], [signal=stop], [signal-1]): a tag
                # only when a closer of its kind follows, and then always plain (malformed).
                tokens.append(('weak', ((m.group('wkind') or m.group('lkind')).lower(), m.group(0), code), at))
            pos = m.end()
        tokens.append(('text', segment[pos:], base + pos))
        return tokens

    # -- decisions: integrity, rarity budget, whisper once ----------------------------------------
    def decide(self, spans, session_id, turn_id):
        gates = [s for s in spans if s.level in SEVERITY]
        for s in spans:
            # Words, or characters for text written without spaces (Chinese, Japanese, a long token).
            if len(s.text.split()) > self.budget['max_span_words'] or len(s.text) > 8 * self.budget['max_span_words']:
                s.drop = 'too_long'
            elif s.level == 'go' and not self.check_passed(s.check, session_id, turn_id):
                s.drop = 'no_check' if not s.check else 'check_not_observed'
        ranked = sorted([s for s in gates if not s.drop], key=lambda s: SEVERITY[s.level])
        for s in ranked[self.budget['max_spans']:]:
            s.drop = 'over_budget'
        for s in [s for s in spans if s.level == 'intent'][1:]:
            s.drop = 'over_budget'
        for s in spans:
            s.show = s.drop is None

    def log(self, span, scope, surface, salt, whispers_left=1):
        span_hash = hashlib.sha256(salt + span.text.encode()).hexdigest() if salt else None
        if span.level == 'whisper' and span.show:
            if self.audit.whisper_seen(scope, span_hash):
                span.show, span.drop = False, 'repeat'  # plain, logged, spends no budget
            if whispers_left <= 0:
                span.show, span.drop = False, 'over_budget'
            elif not self.audit.whisper_once(scope, span_hash, span.reason):
                span.show, span.drop = False, 'repeat'
        reason = span.drop or span.reason or span.why
        if span.level == 'intent' and span.show:
            return  # intent is not a risk signal; nothing to audit
        self.audit.record(event='signal', span_id=uuid.uuid4().hex, level=span.level, reason=reason,
                          scope_hash=scope, surface=surface, shown=span.show, span_hash=span_hash,
                          check_ok=(span.show if span.level == 'go' else None))

    # -- rendering ----------------------------------------------------------------------------
    def word(self, span, rich):
        if span.level == 'intent' or (rich and self.words == 'plain_only'):
            return ''
        if span.level == 'whisper' and not rich and not self.messaging_marker:
            return ''
        return ' (' + WORDS[span.level] + ')'

    def colors(self):
        return None if self.palette == 'none' else PALETTES[(self.theme, self.palette)]

    def render(self, span, surface, before='', after='', math_ok=True):
        """`before`: this line's text so far; `after`: the next character of the reply."""
        text = span.text
        if not span.show:
            return text
        # A span can't carry escape, control, separator or bidi characters into its styling, and
        # they can't reorder or hide the word after it.
        text = CONTROL.sub('', ANSI.sub('', text))
        if span.code:
            return text + self.word(span, rich=False)  # inside code: the word, never markup
        if surface in TERMINAL:
            colors = None if self.env.get('NO_COLOR') else self.colors()
            color = '\x1b[38;2;%d;%d;%dm' % tuple(int(colors[span.level][i:i + 2], 16) for i in (0, 2, 4)) \
                if colors else ''
            style = '\x1b[' + STYLE[span.level] + 'm' if STYLE[span.level] else ''
            word = self.word(span, rich=bool(color))  # no color applied: the word is the cue
            if not color and not style:
                return text + word
            return color + style + text + STYLE_OFF[span.level] + word + (FG_OFF if color else '')
        if surface in DESKTOP:
            colors = self.colors()
            if span.level != 'intent' and colors and math_ok and self.katex_safe(text) and \
                    self.math_context_safe(span, before, after):
                body = r'\textsf{' + katex_text(text) + '}'
                if span.level == 'stop':
                    body = r'\underline{\textsf{\textbf{' + katex_text(text) + '}}}'
                elif span.level == 'caution':
                    body = r'\underline{' + body + '}'
                elif span.level == 'go':
                    body = r'\textsf{\textit{' + katex_text(text) + '}}'
                return '$\\color{#' + colors[span.level] + '}{' + body + '}$' + self.word(span, rich=True)
            # When the agent wrote math of its own, the span may sit inside it: no '**' either.
            return self.markdown(span, text, rich=span.level == 'intent', before=before, after=after,
                                 bold=math_ok)
        if surface in MARKDOWN:
            return self.markdown(span, text, rich=False, before=before, after=after)
        return text + self.word(span, rich=False)

    def markdown(self, span, text, rich, before='', after='', bold=True):
        word = self.word(span, rich=rich) if span.level != 'intent' else ''
        # Bold only where '**' cannot merge with neighbouring asterisks or be escaped.
        if (not bold or span.level == 'whisper' or LINKISH.search(before) or '*' in text or '|' in text or text != text.strip() or text.endswith('\\')
                or before[-1:] in ('\\', '*') or after == '*' or not _flanks(before[-1:], text, (word or after)[:1])):
            return text + word
        return '**' + text + '**' + word

    def math_context_safe(self, span, before, after):
        """Hermes Desktop's preprocess decides what is math from the text around a `$`. Use the math
        path only where it cannot be re-read as currency, escaped, or paired with a stray `$`."""
        if before[-1:] in ('$', '\\') or before[-1:].isdigit():
            return False  # '$$' display math, an escaped opener, or a currency-looking '5$'
        if LINKISH.search(before):
            return False  # a www./scheme/email autolink touching the span would swallow the math
        if not self.word(span, rich=True) and after and after not in SAFE_AFTER_MATH:
            return False  # without the word, the closing '$' would touch a digit, letter or '$'
        return True

    @classmethod
    def stray_backtick(cls, text):
        """True when a line outside fenced code has a backtick run with no matching closer.
        Desktop's tail repair (remend) closes it at the end of the paragraph, which would turn the
        plugin's math after it into inline code."""
        fence = None
        for line in text.split('\n'):
            m = FENCE.match(line)
            if fence is None and m and not (m.group(1)[0] == '`' and '`' in m.group(2)):
                fence = (m.group(1)[0], len(m.group(1)))
                continue
            if fence is not None:
                if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1] and not m.group(2).strip():
                    fence = None
                continue
            if any('`' in chunk for is_code, chunk in cls.code_spans(line) if not is_code):
                return True
        return False

    @staticmethod
    def katex_safe(text):
        # Markdown inside the span (code, links, emphasis) would print literally inside math.
        # '|' would split a GFM table cell in the middle of the math. '[', ']' and '!' are read by
        # Desktop's tail repair (remend) as an unfinished link or image, even inside math.
        # '--', "''" are KaTeX text-mode ligatures (en/em dash, closing quote): they'd alter a command.
        return (not re.search(r"[`*|\n\[\]!]|<|--|''", text) and not CJK.search(text) and len(text) <= 200
                and all(katex_char_ok(c) for c in text))

    # -- hook ---------------------------------------------------------------------------------
    def transform(self, response_text, session_id='', platform='', turn_id='', **kwargs):
        if not isinstance(response_text, str):
            return None
        # Bring tags hidden by invisible characters into view, and drop a keyword cut off at the end.
        text = self.prepare(response_text)
        if not (self.prose_has_tags(text) or self.cut_off(response_text)
                or any(isinstance(p, Span) for p in self.parse(text))):
            return None  # no exact tag: the host keeps the original and other transforms still run
        surface = platform.strip().lower() if isinstance(platform, str) else ''
        pieces = self.unsplice_pieces(self.parse(text))
        if self.joined(''.join(p.text if isinstance(p, Span) else p for p in pieces)):
            # removal joined text into a live tag inside code (adversarial): clean code too.
            skip_code = False
            pieces = self.unsplice_pieces(self.parse(text), skip_code=False)
        else:
            skip_code = True
        spans = [p for p in pieces if isinstance(p, Span)]
        self.decide(spans, session_id, turn_id)
        scope = hashlib.sha256(str(session_id).encode()).hexdigest()
        try:
            salt = self.audit.salt()
        except Exception:
            salt = None
        whispers_left = self.budget['max_whispers']
        for span in spans:
            try:
                self.log(span, scope, surface, salt, whispers_left)
            except Exception:
                # A failed log never hides a stop or caution from the human; a whisper or go that
                # cannot be logged (or verified) stays plain.
                if span.level in ('whisper', 'go'):
                    span.show = False
            if span.level == 'whisper' and span.show:
                whispers_left -= 1
        # Desktop: if the agent writes any math of its own ($$, \(, \[, or a '$' that is not a
        # currency amount), the math path could interleave with it, so this reply uses bold + word.
        # Span text counts too: a span drawn without math (fallback, over budget, unverified go)
        # still prints its own '$'.
        prose = ''.join(p if isinstance(p, str) else p.text for p in pieces)
        # Desktop's escapeCjkProseDollars pairs '$' signs (currency included) across the reply and
        # can escape the plugin's closing '$' when CJK text follows: any '$' plus CJK means no math.
        # A raw HTML block (a line starting with <tag, </tag, <!--) passes its text through unparsed:
        # math inside it would show as LaTeX source.
        math_ok = not AGENT_MATH.search(prose) and not ('$' in prose and CJK.search(prose)) \
            and not self.stray_backtick(prose) and not HTML_BLOCK.search(prose)
        out, line = [], ''
        for i, piece in enumerate(pieces):
            if isinstance(piece, Span):
                after = next(((p.text if isinstance(p, Span) else p)[:1] for p in pieces[i + 1:]
                              if (p.text if isinstance(p, Span) else p)), '')
                piece = self.render(piece, surface, before=line, after=after, math_ok=math_ok)
                line = '' if piece.endswith('\n') else line + piece
            elif piece == '\n':
                line = ''
            else:
                line += piece
            out.append(piece)
        kept = [''.join(p.text if isinstance(p, Span) else p for p in pieces)]
        out = self.unsplice(''.join(out), kept, skip_code=skip_code)
        if skip_code and self.joined(out):
            out = self.unsplice(out, kept, skip_code=False)
        if out == response_text:
            return None  # only lookalikes: the host keeps the original
        # Hermes treats an empty replacement as "no change" and would deliver the raw tags.
        return out if out.strip() else EMPTY

    @staticmethod
    def shapes(text):
        """Tag-shaped strings in `text` as (start, end, key, rest): an opener, closer, broken or
        cut-off keyword, read the way the parser reads them (invisible characters inside a bracket
        ignored, any number of backslashes). `rest` is what stays of the bracket once the shape goes."""
        found = []
        for m in BRACKET.finditer(text):
            seg = m.group(0)
            # Read raw (as the parser does: '[whisper<ZWSP>now' is a broken tag) and with
            # invisible characters removed (as _unhide does: '[<ZWSP>signal:stop]' is a tag).
            for form in (seg, INVISIBLE.sub('', seg)):
                t = TAG.match(form) or TRUNCATED.match(form) or SPLICED.match(form)
                if t and t.end():
                    found.append((m.start(), m.end(), t.group(0), form[t.end():]))
                    break
        return found

    @staticmethod
    def shape_ends(text):
        """Tag shapes as (start, raw end, key): the exact characters of `text` a shape occupies
        (invisible characters inside it included), for deletion in place."""
        found = []
        for m in BRACKET.finditer(text):
            seg = m.group(0)
            t = TAG.match(seg) or TRUNCATED.match(seg) or SPLICED.match(seg)
            if t and t.end():
                found.append((m.start(), m.start() + t.end(), t.group(0)))
                continue
            clean = INVISIBLE.sub('', seg)
            t = TAG.match(clean) or TRUNCATED.match(clean) or SPLICED.match(clean)
            if t and t.end():
                need, i = t.end(), 0
                while need and i < len(seg):
                    need -= not INVISIBLE.match(seg[i])
                    i += 1
                found.append((m.start(), m.start() + i, t.group(0)))
        return found

    def unsplice_pieces(self, pieces, skip_code=True):
        """Make the reply idempotent before decisions, logging and styling: what the human reads
        (span text plain) must hold no tag the parser would consume. Removing a tag can join the text
        around it into a new one ([[/signal]/signal]), change what is code (a fence or backtick run
        that only closes once a tag is gone), or copy a lookalike that sits in code into prose. So the
        reply as it stands is parsed again, and every tag shape that is not inside text that parse
        keeps as written is removed (repeat until stable; past the bound, every remaining shape loses
        its '[', and a '(' never starts a tag). Each span is read twice: followed by a boundary (its
        word, ' (stop)', splits '[' + 'signal' + ' (stop)' into '[signal') and followed directly by
        the next piece (no word: intent, plain_only, over budget). A span keeps its level and word;
        only joined tag text goes."""
        joined = ''.join(p.text if isinstance(p, Span) else p for p in pieces)
        if '[' not in joined:
            return pieces
        for attempt in range(17):
            changed = False
            for boundary in (' (', ''):  # every word starts ' (': ' (stop)', ' (second look)'
                pieces, edited = self._unsplice_once(pieces, boundary, last=attempt == 16, skip_code=skip_code)
                changed |= edited
            if not changed:
                break
        return pieces

    def _unsplice_once(self, pieces, boundary, last=False, skip_code=True):
        import bisect
        texts = [p.text + boundary if isinstance(p, Span) else p for p in pieces]
        plain = ''.join(texts)
        if '[' not in plain:
            return pieces, False
        # What this reply would look like to the parser on a second pass (the same preprocessing).
        kept = []
        if self.prepare(plain) == plain:
            self.parse(plain, kept)  # else a hidden or cut-off tag: nothing tag-shaped counts as text
        kept.sort()
        starts = [k for k, _ in kept]
        cut = []  # (start, end): characters to delete; with `last`, only the '[' becomes '('
        code = self.in_code(plain) if skip_code else (lambda i: False)
        for start, end, key in self.shape_ends(plain):
            if code(start):
                continue  # nothing inside code is removed here
            i = bisect.bisect_right(starts, start) - 1
            if i >= 0 and end <= starts[i] + len(kept[i][1]) and plain[start:end] == key:
                continue  # a lookalike the parser keeps as written
            cut.append((start, end))
        if not cut:
            return pieces, False
        keep = bytearray(b'\x01') * len(plain)
        swap = set()
        for start, end in cut:
            if last:
                swap.add(start)
            else:
                keep[start:end] = b'\x00' * (end - start)
        out, pos = [], 0
        for piece, t in zip(pieces, texts):
            body = len(t) - (len(boundary) if isinstance(piece, Span) else 0)  # the boundary is not text
            text = ''.join('(' if j in swap else plain[j] for j in range(pos, pos + body) if keep[j])
            if isinstance(piece, Span):
                piece.text = text
                out.append(piece)
            else:
                out.append(text)
            pos += len(t)
        return out, True

    @classmethod
    def unsplice(cls, out, kept, skip_code=True):
        """Removing one tag can join the text around it into a new one ([[/signal]/signal],
        [sig[/signal]nal:go]...). The only tag-shaped strings the output may hold are lookalikes the
        reply wrote as text (`kept`: the parser's text tokens, so a tag it consumed never counts).
        Any other is removed, repeating until stable; past the bound, every remaining shape loses its
        '[' (a '(' can never start a tag), so nothing tag-shaped is ever made by removal."""
        from collections import Counter
        allowed = Counter(key for piece in kept if '[' in piece for _, _, key, _ in cls.shapes(piece))
        for _ in range(32):
            code = cls.in_code(out) if skip_code else (lambda i: False)  # once per round (speed)
            found = [s for s in cls.shapes(out) if not code(s[0])]  # code stays
            have = Counter(key for _, _, key, _ in found)
            extra = {k: n - allowed.get(k, 0) for k, n in have.items() if n > allowed.get(k, 0)}
            if not extra:
                return out
            parts, pos = [], 0
            for start, end, key, rest in found:  # drop the LAST surplus copies (removal joins late text)
                if extra.get(key, 0) > 0 and have[key] <= extra[key]:
                    parts.append(out[pos:start])
                    parts.append(rest)
                    pos = end
                    extra[key] -= 1
                have[key] -= 1
            parts.append(out[pos:])
            out = ''.join(parts)
        parts, pos = [], 0
        code = cls.in_code(out) if skip_code else (lambda i: False)
        for start, end, key, rest in cls.shapes(out):
            if code(start):
                continue
            parts.append(out[pos:start])
            parts.append('(' + out[start + 1:end])
            pos = end
        parts.append(out[pos:])
        return ''.join(parts)

    @staticmethod
    def has_tags(text):
        """True when `text` holds at least one exact Axiōma tag (known-value opener or exact closer)."""
        if STRICT_CLOSE.search(text):
            return True
        return any(_parse_value(m.group(1).lower(), m.group(2)) is not None for m in STRICT_OPEN.finditer(text))

    def joined(self, text):
        """True when `text` (a reply after tag removal) would still be read as holding a tag: an
        exact tag in prose, or a complete exact span anywhere (code included)."""
        return self.prose_has_tags(text) or any(isinstance(p, Span) for p in self.parse(text))

    def prose_has_tags(self, text):
        """An exact tag in prose, read the way the parser reads it: one line and one prose chunk
        (between inline code spans) at a time, so text on both sides of code never joins into one."""
        return any(not code and self.has_tags(piece) for code, piece in self.segments(text))

    def cut_off(self, text):
        """True when prose (not code) holds a tag a truncated stream cut off (CUT_TAG, CUT_END)."""
        segs = self.segments(text)
        if segs and not segs[-1][0] and CUT_END.search(segs[-1][1]):
            return True
        return any(not code and CUT_TAG.search(piece) for code, piece in segs)

    @classmethod
    def segments(cls, text):
        """(is_code, piece) covering `text` exactly, with the code detection parse() uses."""
        out, fence = [], None
        for n, line in enumerate(text.split('\n')):
            if n:
                out.append((False, '\n'))
            m = FENCE.match(line)
            if fence is None and m and not (m.group(1)[0] == '`' and '`' in m.group(2)):
                fence = (m.group(1)[0], len(m.group(1)))
                out.append((True, line))
                continue
            if fence is not None:
                if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1] and not m.group(2).strip():
                    fence = None
                out.append((True, line))
                continue
            if INDENTED.match(line):
                out.append((True, line))
                continue
            out.extend(cls.code_spans(line))
        return out

    @classmethod
    def in_code(cls, text):
        """A test `f(i)`: True when position i of `text` is inside detected code."""
        import bisect
        starts, ends, at = [], [], 0
        for code, piece in cls.segments(text):
            if code:
                starts.append(at)
                ends.append(at + len(piece))
            at += len(piece)

        def f(i):
            k = bisect.bisect_right(starts, i) - 1
            return k >= 0 and i < ends[k]
        return f

    def prepare(self, text):
        """Unhide tags behind invisible characters and drop cut-off keywords, outside code only."""
        return ''.join(piece if code else TRUNCATED.sub('', BRACKET.sub(self._unhide, piece))
                       for code, piece in self.segments(text))

    @staticmethod
    def _unhide(match):
        cleaned = INVISIBLE.sub('', match.group(0))
        return cleaned if cleaned != match.group(0) and TAG.match(cleaned) else match.group(0)

    def listing(self, raw=''):
        try:
            rows = [r for r in self.audit.rows(1000) if r['event'] in ('signal', 'whisper')][:100]
            lines = []
            for r in rows:
                level = r.get('level') or 'whisper'
                lines.append('%s %s%s on %s, %s (span %s)' % (
                    level, 'shown' if r.get('shown', True) else 'not shown',
                    ' (' + r['reason'] + ')' if r.get('reason') else '', r.get('surface') or 'unknown surface',
                    'id ' + (r.get('span_id') or r['id'])[:8], (r.get('span_hash') or '')[:12]))
            return '\n'.join(lines) or 'No signals logged yet. Text bodies are never stored.'
        except Exception:
            return 'Signal metadata is unavailable; no text bodies are stored.'
