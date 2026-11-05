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
    compare_lines(fp, expected, pasted, labels)   pasted card vs staged line digests
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
    try:
        if stat.S_IMODE(os.stat(path).st_mode) & ~mode:
            os.chmod(path, mode)
    except OSError:
        pass


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
def _label_forms(labels):
    forms = []
    for label in labels:
        label = clean_line(label)
        if label:
            forms += [label + ': ', '**' + label + ':** ', label + '\uff1a', '<b>' + label + ':</b> ']
    return forms


def compare_lines(fp, expected, pasted, labels=LABELS):
    """Compare a pasted card with the staged line digests. Returns (problems, notes, summary):
    problems are mismatches in plain words, notes are honest limits (such as a surface cut).

    A pasted line matches only if it equals a staged line exactly (after whitespace cleanup), or
    equals one after removing one allowlisted host label at its start. Lines before the first
    and after the last matching line are treated as host framing. A line that ends in '...' marks
    where the surface cut the card: staged lines after it are reported as cut, not as changed."""
    expected = list(expected or [])
    forms = _label_forms(labels)
    want = set(expected)
    seq, cut_at, partial = [], None, None  # seq: (pasted line number, digest or None, cleaned)
    for n, raw in enumerate(str(pasted).split('\n'), 1):
        line = clean_line(CODE_SUFFIX.sub('', raw))
        if not line or CODE_LINE.match(line):
            continue
        d = fp.line_digest(line)
        if d not in want:
            d = next((fp.line_digest(line[len(f):]) for f in forms if line.startswith(f)
                      and fp.line_digest(line[len(f):]) in want), None)
        if d is None and (CUT_LINE.match(line) or line.endswith(CUT_MARKS)):
            if seq and any(x[1] for x in seq):
                cut_at, partial = n, line
                break
        seq.append((n, d, line))
    hits = [i for i, x in enumerate(seq) if x[1]]
    if not hits:
        return (['none of the pasted lines is a line of the staged card.'], [], None)
    lo, hi = hits[0], hits[-1]
    # A changed first or last card line looks like host framing; when that staged line is
    # missing, the unmatched pasted line right next to the card is read as its changed copy.
    if lo > 0 and seq[lo][1] != expected[0] and expected[0] not in [x[1] for x in seq]:
        lo -= 1
    if hi < len(seq) - 1 and cut_at is None and seq[hi][1] != expected[-1] \
            and expected[-1] not in [x[1] for x in seq]:
        hi += 1
    inside = seq[lo:hi + 1]
    got = [x[1] for x in inside]
    problems, notes = [], []
    added, moved, missing = [], [], []
    matcher = difflib.SequenceMatcher(None, expected, got, autojunk=False)
    last_matched = -1
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == 'equal':
            last_matched = i2 - 1
            continue
        for j in range(j1, j2):
            n, d, line = inside[j]
            if d is None:
                look = unicodedata.normalize('NFKC', line) != line
                added.append('%d%s' % (n, ' (look-alike characters)' if look else ''))
            else:
                moved.append(str(n))
        missing += list(range(i1, i2))
    cut = []
    if cut_at is not None:
        cut = [i for i in missing if i > last_matched]
        missing = [i for i in missing if i <= last_matched]
    if added:
        problems.append('pasted line%s %s %s not on the staged card (added or changed).' % (
            's' if len(added) > 1 else '', ', '.join(added), 'are' if len(added) > 1 else 'is'))
    if moved:
        problems.append('pasted line%s %s %s out of order or repeated.' % (
            's' if len(moved) > 1 else '', ', '.join(moved), 'are' if len(moved) > 1 else 'is'))
    if missing:
        problems.append('staged line%s %s of %d %s missing or changed.' % (
            's' if len(missing) > 1 else '', ', '.join(str(i + 1) for i in missing), len(expected),
            'are' if len(missing) > 1 else 'is'))
    if cut and partial is not None:
        notes.append('cut by the surface at pasted line %d (%r): staged line%s %s of %d could not be '
                     'checked.' % (cut_at, partial[:40], 's' if len(cut) > 1 else '',
                                   ', '.join(str(i + 1) for i in cut), len(expected)))
    summary = None
    if not problems:
        checked = len(expected) - len(cut)
        summary = ('all %d lines of the pasted card match what was staged, in order.' % len(expected)
                   if not cut else
                   'the first %d of %d staged lines match, in order; the rest was cut by the surface.'
                   % (checked, len(expected)))
    return problems, notes, summary
