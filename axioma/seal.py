"""Card code: "shown equals staged" (Axioma Signal spec 5.6). Self-contained: stdlib only.

A short code, read aloud, that ties what the human saw to what the agent staged and to what the
host reported back. It is a keyed hash (HMAC-SHA-256 under a random key kept in its own
owner-only file and never logged), truncated to 40 bits and written as 8 Crockford base32
characters: 7Q4K-2MPD.

Covered: the exact card text handed to the host (without its own code line), the tool name, the
canonical JSON of the exact arguments, and the card id. The log keeps only keyed digests of those
parts, never the bodies, so the code can be recomputed from the log and each record carries a seal.

Not proven: a compromised host, or anyone who can read the key file, can forge both ends. It
detects a card changed in transit (when the human compares the code or pastes the words) and a log
record edited afterwards by someone who cannot read the key file.

Interface used by the host plugin (nothing else here knows about it):
    load_key(path) -> bytes            create once (0600, parent 0700), then read
    Fingerprint(key)                   .digests() .code_from() .code() .seal() .sealed()
    stamp(text, code, messaging)       put the code line on the card; unstamp() removes it
    parse_code(text)                   what a human types back -> 'XXXX-XXXX' or None
    compare_lines(fp, expected, pasted, labels, prefixes, chrome, tool_digest, code)
                                       pasted card vs staged line digests and prefix tags
"""
import difflib
import hashlib
import hmac
import json
import os
import re
import stat
import unicodedata

VERSION = 'axioma-fp-v1'
ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'  # Crockford base32: no I, L, O, U
LABEL = 'card code'
LONG_QUESTION = 120  # on messaging, a longer question gets the code above it (Discord keeps 300 chars)
_DECODE = str.maketrans({'O': '0', 'I': '1', 'L': '1'})
_C = '[0-9A-HJKMNP-TV-Z]'
CODE_LINE = re.compile(r'^card code %s{4}-%s{4}$' % (_C, _C))
SEP = ' \u00b7 '  # the separator the card already uses on its light line
CODE_SUFFIX = re.compile(r'\s*\u00b7\s*card code %s{4}-%s{4}\s*$' % (_C, _C))
CODE_ANY = re.compile(r'(?:^|\u00b7 )card code (%s{4}-%s{4})$' % (_C, _C), re.M)
CODE_ARG = re.compile(r'\s*(?:card\s+)?(?:code\s+)?#?([0-9A-Za-z]{4}[\s\-]?[0-9A-Za-z]{4})(?![0-9A-Za-z])')
# Labels a host may put in front of the first description line (exact prefixes only, never a
# suffix match: "anything + staged line" must not count as the staged line).
LABELS = ('Why it was flagged', 'Reason', 'Description')
# The host's own prompt text in English (the host plugin adds the localized forms at run time).
CHROME = ('Hermes wants to run a command that needs your OK',
          'Do you want Hermes to run this command?', 'Requested command:',
          "If you don't answer within 5 minutes it will NOT run.",
          'Smart DENY: owner override applies to this one operation only.',
          'Allow Once', 'Allow Session', 'Always Allow', 'Deny')
TAG = 8  # hex characters per keyed prefix tag (32 bits; useless without the key)
CUT_MARKS = ('...', '\u2026')
CUT_LINE = re.compile(r'^\W*\(?description truncated\)?\W*$', re.I)


# -- canonical encoding ---------------------------------------------------------------------------
def _plain(value, depth=0):
    """JSON-safe copy: non-string keys are type-tagged (so {1: x} and {'1': x} differ and mixed
    keys can still be sorted), tuples become lists, unknown objects become their str()."""
    if depth > 100:
        return '<too deep>'
    if isinstance(value, dict):
        return {(k if isinstance(k, str) else '<%s>%r' % (type(k).__name__, k)): _plain(v, depth + 1)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v, depth + 1) for v in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def canonical(value):
    """Canonical JSON: sorted keys, no spaces, ASCII-escaped (a lone surrogate cannot break it).
    Never raises: anything json cannot take is encoded through repr()."""
    try:
        return json.dumps(_plain(value), sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    except Exception:
        return json.dumps('<repr>' + repr(value), ensure_ascii=True)


def crockford(data):
    bits = int.from_bytes(data, 'big')
    width = len(data) * 8
    return ''.join(ALPHABET[(bits >> (width - 5 * (i + 1))) & 31] for i in range(width // 5))


def pretty(raw):
    return raw[:4] + '-' + raw[4:]


def parse_code(text):
    """Accept what a human types back: any case, with or without the dash, spaces or label.
    O reads as 0 and I/L as 1 (Crockford). Returns 'XXXX-XXXX' or None."""
    if not isinstance(text, str):
        return None
    raw = re.sub(r'(?i)^\s*(card\s*)?(code\s*)?#?', '', text)
    raw = re.sub(r'[\s\-_.]', '', raw).upper().translate(_DECODE)
    if len(raw) != 8 or any(c not in ALPHABET for c in raw):
        return None
    return pretty(raw)


def clean_line(line):
    """Exact comparison form of one card line: outer whitespace trimmed and inner runs of
    whitespace collapsed (surfaces reflow spaces). No Unicode normalization: a look-alike
    character is a different line."""
    return ' '.join(str(line).split())


# -- the key --------------------------------------------------------------------------------------
def load_key(path):
    """The per-install key: 32 random bytes in their own file, owner read/write only (0600) in an
    owner-only directory (0700). Created once; an existing file with looser modes is tightened.
    Raises if the key cannot be created or read; the caller must not invent a durable substitute."""
    path = os.fspath(path)
    parent = os.path.dirname(path) or '.'
    os.makedirs(parent, mode=0o700, exist_ok=True)
    _tighten(parent, 0o700)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        try:
            os.write(fd, os.urandom(32))
            os.fsync(fd)
        finally:
            os.close(fd)
    _tighten(path, 0o600)
    with open(path, 'rb') as f:
        key = f.read()
    if len(key) != 32:
        raise ValueError('card code key file is damaged')
    return key


def _tighten(path, mode):
    """Tighten, then verify; a refused or ineffective chmod must not certify a key."""
    try:
        info = os.stat(path, follow_symlinks=False)
        right_type = stat.S_ISDIR(info.st_mode) if mode == 0o700 else stat.S_ISREG(info.st_mode)
        if not right_type or info.st_uid != os.getuid():
            raise PermissionError('card code key and parent must be owner-only; durable verification refused')
        if stat.S_IMODE(info.st_mode) & ~mode:
            os.chmod(path, mode)
    except OSError:
        pass  # The independent check below decides whether the path is safe.
    try:
        info = os.stat(path, follow_symlinks=False)
        right_type = stat.S_ISDIR(info.st_mode) if mode == 0o700 else stat.S_ISREG(info.st_mode)
        if (not right_type or info.st_uid != os.getuid() or
                stat.S_IMODE(info.st_mode) & ~mode):
            raise PermissionError('unsafe key path')
    except OSError as exc:
        raise PermissionError('card code key and parent must be owner-only; durable verification refused') from exc


# -- the code -------------------------------------------------------------------------------------
class Fingerprint:
    def __init__(self, key):
        if not isinstance(key, (bytes, bytearray)) or len(key) < 16:
            raise ValueError('fingerprint key must be at least 16 random bytes')
        self.key = bytes(key)

    @classmethod
    def ephemeral(cls):
        """Only when the key file is unavailable: the code still shows but cannot be verified."""
        return cls(os.urandom(32))

    def mac(self, *parts):
        return hmac.new(self.key, canonical([VERSION] + list(parts)).encode('ascii'), hashlib.sha256).digest()

    @staticmethod
    def card_lines(text):
        """The lines a pasted card is compared against: non-empty, without the code line."""
        lines = (clean_line(CODE_SUFFIX.sub('', x)) for x in str(text).split('\n'))
        return [x for x in lines if x and not CODE_LINE.match(x)]

    def digests(self, card_id, tool, args, text):
        return {
            'card_id': str(card_id),
            'text_digest': self.mac('text', str(text)).hex()[:32],
            'tool_digest': self.mac('tool', str(tool)).hex()[:32],
            'args_digest': self.mac('args', canonical(args)).hex()[:32],
            'line_digests': [self.line_digest(x) for x in self.card_lines(text)],
            'prefix_tags': [self.prefix_tags(x) for x in self.card_lines(text)],
        }

    def code_from(self, card_id, text_digest, tool_digest, args_digest):
        return pretty(crockford(self.mac('code', str(card_id), text_digest, tool_digest, args_digest)[:5]))

    def code(self, card_id, tool, args, text):
        d = self.digests(card_id, tool, args, text)
        return self.code_from(d['card_id'], d['text_digest'], d['tool_digest'], d['args_digest'])

    def seal(self, record):
        """Keyed seal over every field of a log record (its timestamp included) except the seal."""
        return self.mac('seal', canonical({k: v for k, v in record.items() if k != 'seal'})).hex()[:32]

    def sealed(self, record):
        return hmac.compare_digest(str(record.get('seal') or ''), self.seal(record))

    def line_digest(self, line):
        return self.mac('line', clean_line(line)).hex()[:16]

    def prefix_tag(self, text):
        return self.mac('prefix', clean_line(text)).hex()[:TAG]

    def prefix_tags(self, line):
        """Keyed tags of every strict prefix of one card line, so a line the surface cut ('...')
        can be checked as a true start of that line. Without the key they say nothing about the
        words; their count does show roughly how long the line is."""
        line, seen, out = clean_line(line), set(), []
        for k in range(1, len(line)):
            if not line[:k].strip():
                continue
            tag = self.prefix_tag(line[:k])
            if tag not in seen:
                seen.add(tag)
                out.append(tag)
        return ''.join(out)


def stamp(text, code, messaging=False):
    """Put the code where hosts truncate last. Locally (the CLI panel keeps the first rows of a
    description and may show only one or two of them) it ends the first line, the light line,
    which sits directly above the question. On messaging (adapters keep a prefix of the
    description) it is its own line right under the question, or right above a long question."""
    lines = text.split('\n')
    line = LABEL + ' ' + code
    if not messaging:
        return '\n'.join([lines[0] + SEP + line] + lines[1:])
    at = 0 if len(lines[0]) > LONG_QUESTION else 1
    return '\n'.join(lines[:at] + [line] + lines[at:])


def unstamp(text):
    """The card text the code covers: the shown text without its own code (line or suffix)."""
    return '\n'.join(CODE_SUFFIX.sub('', x) for x in text.split('\n') if not CODE_LINE.match(x.strip()))


# -- pasted card vs staged lines ------------------------------------------------------------------
# Markup a surface may wrap around its own prompt text (bold, code fences, HTML tags, a warning
# sign, the CLI panel border). Stripped only when comparing a line with the host's prompt text,
# never when comparing a line with the card.
_MARKUP = re.compile(r'</?(?:b|i|u|s|pre|code|strong|em)>|\*\*|__|`|[\u2502\u2500\u256d\u256e\u2570\u256f\u250c\u2510\u2514\u2518|]')
_WARN = re.compile(r'^(?:\u26a0\ufe0f?|\u231b)\s*')
_FENCE = re.compile(r'^\s*```[A-Za-z0-9_+-]*\s*$')  # a code fence, with or without its language
CODE_SEEN = re.compile(r'card code ([0-9A-Za-z]{4}-[0-9A-Za-z]{4})')


def _unmark(line):
    line = _FENCE.sub('', str(line))
    return clean_line(_WARN.sub('', clean_line(_MARKUP.sub(' ', line))))


def _label_forms(labels):
    forms = []
    for label in labels:
        label = clean_line(label)
        if label:
            forms += [label + ': ', '**' + label + ':** ', label + '\uff1a', '<b>' + label + ':</b> ']
    return forms


def _plural(items, one, many):
    return '%s %s %s' % (many if len(items) > 1 else one, ', '.join(items), 'are' if len(items) > 1 else 'is')


def compare_lines(fp, expected, pasted, labels=LABELS, prefixes=None, chrome=CHROME, tool_digest=None,
                  code=None):
    """Compare a pasted card with the staged line digests. Returns (problems, notes, summary):
    problems are mismatches in plain words, notes are honest limits (such as a surface cut).

    Every non-empty pasted line must be one of these, or it is reported as added or changed:
      - a staged card line, exactly (after whitespace cleanup), or exactly after removing one
        allowlisted host label at its start;
      - the host's own prompt text, exactly (header, deadline, buttons: `chrome`), or the tool
        name the card was staged for (checked against `tool_digest`), ignoring only markup;
      - the one line where the surface cut the card: after the last card line, it ends in '...'
        and the text before the marker is a strict prefix of the next staged line (checked
        against that line's keyed `prefixes`), or it is a '(description truncated)' line.
    Staged lines after a valid cut are reported as cut, not as changed. A pasted card that
    shows a card code other than `code` is a mismatch."""
    expected = list(expected or [])
    forms = _label_forms(labels)
    want = set(expected)
    host = {_unmark(c) for c in (chrome or ())} - {''}
    problems, notes = [], []
    if code:
        seen = {parse_code(m) or m.upper() for m in CODE_SEEN.findall(str(pasted))}
        others = sorted(seen - {code})
        if others:
            problems.append('the pasted card shows card code %s, but the code being checked is %s.'
                            % (' and '.join(others), code))
    entries = []  # (pasted line number, kind, digest or None, cleaned line)
    for n, raw in enumerate(str(pasted).split('\n'), 1):
        line = clean_line(CODE_SUFFIX.sub('', raw))
        if not line or CODE_LINE.match(line):
            continue
        d = fp.line_digest(line)
        if d not in want:
            d = next((fp.line_digest(line[len(f):]) for f in forms if line.startswith(f)
                      and fp.line_digest(line[len(f):]) in want), None)
        if d is not None:
            entries.append((n, 'card', d, line))
            continue
        bare = _unmark(line)
        unlabelled = next((line[len(f):] for f in forms if line.startswith(f)), line)
        if not bare or CODE_LINE.match(bare) or CODE_LINE.match(_unmark(unlabelled)):
            continue  # markup only (a code fence, a border), or the code line inside markup
        if bare in host or (tool_digest and hmac.compare_digest(
                fp.mac('tool', bare).hex()[:32], str(tool_digest))):
            entries.append((n, 'host', None, line))
        elif CUT_LINE.match(line):
            entries.append((n, 'cutline', None, line))
        elif line.endswith(CUT_MARKS):
            entries.append((n, 'cut', None, line))
        else:
            entries.append((n, 'other', None, line))
    cards = [e for e in entries if e[1] == 'card']
    if not cards and not any(e[1] == 'cut' for e in entries):
        return (problems + ['none of the pasted lines is a line of the staged card.'], [], None)
    # The cut, if any: the first cut line with no card line after it.
    last_card = max((i for i, e in enumerate(entries) if e[1] == 'card'), default=-1)
    cut_i = next((i for i, e in enumerate(entries) if e[1] in ('cut', 'cutline') and i > last_card), None)
    got = [e[2] for e in cards]
    moved, missing, last_matched = [], [], -1
    matcher = difflib.SequenceMatcher(None, expected, got, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == 'equal':
            last_matched = i2 - 1
            continue
        moved += [str(cards[j][0]) for j in range(j1, j2)]
        missing += list(range(i1, i2))
    cut, cut_note = [], None
    if cut_i is not None:
        n, kind, _, line = entries[cut_i]
        nxt = last_matched + 1
        ok = False
        if kind == 'cutline':
            ok = last_matched >= 0
        elif nxt < len(expected) and prefixes and nxt < len(prefixes):
            text = clean_line(line[:-(3 if line.endswith('...') else 1)])
            tags = str(prefixes[nxt] or '')
            tags = {tags[i:i + TAG] for i in range(0, len(tags), TAG)}
            ok = any(c and fp.prefix_tag(c) in tags
                     for c in [text] + [clean_line(text[len(f):]) for f in forms if text.startswith(f)])
        if ok:
            cut = [i for i in missing if i >= nxt]
            missing = [i for i in missing if i < nxt]
            cut_note = (n, line, kind, nxt)
    added = []
    for i, (n, kind, _, line) in enumerate(entries):
        if i == cut_i and cut_note:
            continue
        if kind == 'cutline' and cut_note and i > cut_i:
            continue  # a second truncation marker after an honest cut
        if kind in ('other', 'cut', 'cutline'):
            look = unicodedata.normalize('NFKC', line) != line
            added.append('%d%s' % (n, ' (look-alike characters)' if look else ''))
    if added:
        problems.append(_plural(added, 'pasted line', 'pasted lines') +
                        " not on the staged card and not the host's own prompt text (added or changed;"
                        " a line ending in '...' counts as a cut only when it is the start of the next"
                        ' staged line).')
    if moved:
        problems.append(_plural(moved, 'pasted line', 'pasted lines') + ' out of order or repeated.')
    if missing:
        problems.append('staged line%s %s of %d %s missing or changed.' % (
            's' if len(missing) > 1 else '', ', '.join(str(i + 1) for i in missing), len(expected),
            'are' if len(missing) > 1 else 'is'))
    host_lines = [str(e[0]) for e in entries if e[1] == 'host']
    if host_lines:
        notes.append("%s the host's own prompt text (header, tool name, deadline or buttons), "
                     'checked against that text.' % _plural(host_lines, 'pasted line', 'pasted lines'))
    if cut and cut_note:
        n, line, kind, nxt = cut_note
        where = '' if kind == 'cutline' else ', the true start of staged line %d' % (nxt + 1)
        notes.append('cut by the surface at pasted line %d (%r)%s: staged line%s %s of %d could not '
                     'be checked.' % (n, line[:40], where, 's' if len(cut) > 1 else '',
                                      ', '.join(str(i + 1) for i in cut), len(expected)))
    summary = None
    if not problems:
        summary = ('all %d lines of the pasted card match what was staged, in order.' % len(expected)
                   if not cut else
                   'the first %d of %d staged lines match, in order; the rest was cut by the surface.'
                   % (len(expected) - len(cut), len(expected)))
    return problems, notes, summary
