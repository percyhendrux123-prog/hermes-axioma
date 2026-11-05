"""Card fingerprint: "shown equals staged" (spec 5.6).

A short code, read aloud, that ties what the human saw to what the agent staged and to what the
host reported back. It is a keyed hash (HMAC-SHA-256 under a random per-database key that is never
logged), truncated to 40 bits and written as 8 Crockford base32 characters: 7Q4K-2MPD.

Covered: the exact card text handed to the host (without its own code line), the tool name, the
canonical JSON of the exact arguments, and the card id. The log keeps only keyed digests of those
parts, never the bodies, so the code can be recomputed from the log and each record carries a seal.

Not proven: a compromised host, or anyone holding the key file, can forge both ends. It detects a
card changed in transit (when the human compares the words or the code) and a log record edited
after it was written.
"""
import hashlib
import hmac
import json
import os
import re
import unicodedata

VERSION = 'axioma-fp-v1'
ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'  # Crockford base32: no I, L, O, U
LABEL = 'card code'
LONG_QUESTION = 120  # longer questions get the code above them, so truncation cannot cut it
_DECODE = str.maketrans({'O': '0', 'I': '1', 'L': '1'})
CODE_LINE = re.compile(r'^card code [0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$')


def canonical(value):
    """Canonical JSON: sorted keys, no spaces, UTF-8; non-JSON values fall back to str()."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)


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


def normalize_line(line):
    """For comparing a pasted card with the staged one: NFKC, collapsed spaces, trimmed."""
    return ' '.join(unicodedata.normalize('NFKC', str(line)).split())


class Fingerprint:
    def __init__(self, key):
        if not isinstance(key, (bytes, bytearray)) or len(key) < 16:
            raise ValueError('fingerprint key must be at least 16 random bytes')
        self.key = bytes(key)

    @classmethod
    def ephemeral(cls):
        """Used only when the log is unavailable: the code still shows, but cannot be verified later."""
        return cls(os.urandom(32))

    def mac(self, *parts):
        return hmac.new(self.key, canonical([VERSION] + list(parts)).encode('utf-8'), hashlib.sha256).digest()

    def digests(self, card_id, tool, args, text):
        lines = [normalize_line(x) for x in str(text).split('\n')]
        return {
            'card_id': str(card_id),
            'text_digest': self.mac('text', str(text)).hex()[:32],
            'tool_digest': self.mac('tool', str(tool)).hex()[:32],
            'args_digest': self.mac('args', canonical(args)).hex()[:32],
            'line_digests': [self.mac('line', x).hex()[:16] for x in lines if x],
        }

    def code_from(self, card_id, text_digest, tool_digest, args_digest):
        return pretty(crockford(self.mac('code', str(card_id), text_digest, tool_digest, args_digest)[:5]))

    def code(self, card_id, tool, args, text):
        d = self.digests(card_id, tool, args, text)
        return self.code_from(d['card_id'], d['text_digest'], d['tool_digest'], d['args_digest'])

    def seal(self, metadata):
        body = {k: v for k, v in metadata.items() if k != 'seal'}
        return self.mac('seal', canonical(body)).hex()[:32]

    def sealed(self, metadata):
        return hmac.compare_digest(str(metadata.get('seal') or ''), self.seal(metadata))

    def line_digest(self, line):
        return self.mac('line', normalize_line(line)).hex()[:16]


def stamp(text, code, messaging=False):
    """Put the code on its own line right under the question, so it survives the truncation the
    CLI panel and messaging adapters apply to the end of an approval description."""
    lines = text.split('\n')
    q = 0 if messaging else 1  # the question line: first on messaging, right after the light locally
    at = q + 1
    if len(lines[q]) > LONG_QUESTION:
        at = q  # a long question could push the code past the CLI panel rows or a short adapter
        #         budget (Discord keeps 300 characters), so the code goes directly above it instead
    return '\n'.join(lines[:at] + [LABEL + ' ' + code] + lines[at:])


def unstamp(text):
    """The card text the fingerprint covers: the shown text without its own code line."""
    return '\n'.join(x for x in text.split('\n') if not CODE_LINE.match(x.strip()))
