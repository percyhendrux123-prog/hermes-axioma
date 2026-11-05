"""Advisory signal: show the agent's card and question before a send/spend/spin/scrub, and log it.

Axioma is an ADVISOR. It does not hold, block, authorize or execute anything. For a classified
call its only control-flow output is Hermes's documented `pre_tool_call` `approve` directive,
which hands the call to Hermes's own human-approval gate with the card as the description.
Hermes decides whether to ask (approval mode, YOLO, remembered approvals, cron policy, unattended
fail-closed) and the human answers there. Axioma records what it showed and what the host
reported back, as metadata only.
"""
import hashlib
import json
import re
import threading
import time
import uuid
from .card import NOTICE_QUESTION, render_card, render_notice, validate_card
from .policy import Policy
from .checks import Checks
from .fingerprint import CODE_LINE, Fingerprint, normalize_line, parse_code, stamp

CODE_ARG = re.compile(r'\s*(?:card\s+)?(?:code\s+)?#?([0-9A-Za-z]{4}[\s\-]?[0-9A-Za-z]{4})(?![0-9A-Za-z])')
LOCAL_SURFACES = ('cli', 'tui', 'desktop', 'acp', '')
PARSE_NOTE = 'could not parse (best-effort parser)'
CONFIG_SIGNAL = 'Part of the Axioma configuration is invalid and was skipped, so some standing rules may be missing; fix the plugin settings first.'
TTL = 300
CAPACITY = 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     default=str).encode()).hexdigest()


# Hermes canonicalizes legacy tool names before hooks; a card staged under the old name still matches.
ALIASES = {'cronjob': 'cronjob_manage'}


def card_key(session_id, tool, args):
    return (str(session_id), digest([ALIASES.get(tool, tool), args]))


class Advisor:
    def __init__(self, config, audit, checks_config=None, surface=lambda: '', clock=time.monotonic):
        self.audit, self.surface, self.clock = audit, surface, clock
        self.lock = threading.RLock()
        self.cards, self.shown = {}, {}
        # A bad setting keeps every rule that is valid on its own and turns every card RED.
        self.policy, policy_error = Policy.lenient(config)
        self.checks, checks_error = Checks.lenient({} if checks_config is None else checks_config)
        self.config_error = policy_error or checks_error
        self._fp = None

    @property
    def fp(self):
        """Keyed fingerprint (spec 5.6). If the log is unavailable the code still shows, under a
        throwaway key, and simply cannot be verified later."""
        if self._fp is None:
            try:
                self._fp, self.fp_durable = Fingerprint(self.audit.secret('fingerprint_key')), True
            except Exception:
                self._fp, self.fp_durable = Fingerprint.ephemeral(), False
        return self._fp

    # -- bookkeeping -------------------------------------------------------------------------
    def prune(self):
        now = self.clock()
        self.cards = {k: v for k, v in self.cards.items() if now - v['at'] < TTL}
        self.shown = {k: v for k, v in self.shown.items() if now - v['at'] < TTL}
        while len(self.cards) >= CAPACITY:
            self.cards.pop(min(self.cards, key=lambda k: self.cards[k]['at']))
        while len(self.shown) >= CAPACITY:
            self.shown.pop(min(self.shown, key=lambda k: self.shown[k]['at']))

    def record(self, **metadata):
        try:
            if metadata.get('event') in ('card', 'presented_to_host', 'answer'):
                metadata['seal'] = self.fp.seal(metadata)
            self.audit.record(**metadata)
        except Exception:
            pass  # logging failure never changes what the human sees

    # -- agent tool ----------------------------------------------------------------------------
    def submit(self, args, session_id='', **kwargs):
        """axioma_card handler: stage a card for one exact upcoming call. Never approves anything."""
        with self.lock:
            card_id = uuid.uuid4().hex
            try:
                self.prune()
                if not isinstance(args, dict) or set(args) != {'tool', 'arguments', 'card'}:
                    raise ValueError('envelope must be {tool, arguments, card}')
                tool, target = args['tool'], args['arguments']
                if not isinstance(tool, str) or not tool or not isinstance(target, dict):
                    raise ValueError('tool must be a name and arguments an object')
                key = card_key(session_id or '', tool, target)
                self.cards.pop(key, None)  # a replacement (even a bad one) retires the earlier card
                card = validate_card(args['card'])
                self.cards[key] = dict(card=card, card_id=card_id, at=self.clock())
                self.record(event='card', card_id=card_id, light=card['light'], valid=True,
                            categories=self.policy.classify(tool, target))
                return json.dumps({'status': 'staged', 'card_id': card_id,
                                   'note': 'Advice only. Hermes decides whether to ask the human.'})
            except Exception as exc:
                self.record(event='card', card_id=card_id, valid=False)
                return json.dumps({'error': 'card not staged: ' + str(exc)[:200],
                                   'note': 'Without a valid card the human sees a NO CARD notice.'})

    # -- hooks ---------------------------------------------------------------------------------
    def before(self, tool_name, args, session_id='', tool_call_id='', **kwargs):
        """pre_tool_call: return the documented approve directive with the card, or None."""
        with self.lock:
            try:
                args = args if isinstance(args, dict) else {}
                categories = self.policy.classify(tool_name, args)
                hard = self.checks.hard_red(tool_name, args)
                if not categories and not hard:
                    return None
                categories = categories or ('standing_rule',)
                self.prune()
                key = card_key(session_id or '', tool_name, args)
                staged = self.cards.pop(key, None)
                surface = self.safe_surface()
                messaging = surface not in LOCAL_SURFACES
                # SCRUB is best-effort parsing: a shape it could not read is said out loud and the
                # card is capped at CAUTION (never GO). Hard RED from rules or checks still wins.
                unparsed = 'scrub' in categories and self.policy.unparsed(tool_name, args)
                parse_note = [{'check': 'scrub_parse', 'pass': False, 'note': PARSE_NOTE}] if unparsed else []
                if staged:
                    card, results = self.checks.apply(tool_name, args, staged['card'], categories)
                    results = results + parse_note
                    if unparsed and card['light'] == 'green':
                        card = dict(card, light='yellow')
                    if self.config_error:
                        results = results + [{'check': 'axioma_config', 'pass': False}]
                        card = dict(card, light='red', signal=CONFIG_SIGNAL)
                    message = render_card(card, checks=results, messaging=messaging, kind=categories)
                    card_id, light, reason = staged['card_id'], card['light'], None
                else:
                    adjusted, results = self.checks.apply(tool_name, args, NO_CARD, categories)
                    results = [r for r in results if not r['check'].startswith('downstream_')]
                    results = results + parse_note
                    if self.config_error:
                        results = results + [{'check': 'axioma_config', 'pass': False}]
                        adjusted = dict(adjusted, light='red', signal=CONFIG_SIGNAL)
                    red = adjusted['light'] == 'red'
                    message = render_notice(tool_name, categories, checks=results, messaging=messaging,
                                            red_signal=adjusted['signal'] if red else None)
                    card_id, light, reason = uuid.uuid4().hex, ('red' if red else None), 'missing_card'
                # Shown equals staged (spec 5.6): fingerprint the exact text handed to the host plus
                # tool, exact args and card id; show the code under the question; log it sealed.
                parts = self.fp.digests(card_id, tool_name, args, message)
                code = self.fp.code_from(parts['card_id'], parts['text_digest'], parts['tool_digest'],
                                         parts['args_digest'])
                message = stamp(message, code, messaging=messaging)
                self.shown[(str(session_id or ''), str(tool_call_id))] = dict(
                    card_id=card_id, light=light, categories=categories, fingerprint=code, at=self.clock())
                self.record(event='presented_to_host', card_id=card_id, light=light,
                            categories=categories, reason=reason, surface=surface or 'unknown',
                            checks=[{'check': r['check'], 'pass': r['pass']} for r in results],
                            fingerprint=code, **{k: v for k, v in parts.items() if k != 'card_id'})
                # Every card gets a fresh rule key. Hermes uses the first approve's key for the
                # whole call (even when another plugin also asked), so a reusable key could let a
                # remembered Session/Always cover a different call or another plugin's request.
                rule_key = 'axioma:%s:%s:%s:%s' % ('+'.join(categories), tool_name, light or 'nocard',
                                                   uuid.uuid4().hex)
                return {'action': 'approve', 'message': message, 'rule_key': rule_key}
            except Exception:
                # An advisory failure still shows the human something; it never silently drops.
                notice = 'AXIOMA: advisory unavailable for this call. Hermes approval decides.'
                messaging = self.safe_surface() not in LOCAL_SURFACES
                text = (NOTICE_QUESTION + '\n' + notice) if messaging else (notice + '\n' + NOTICE_QUESTION)
                try:
                    card_id = uuid.uuid4().hex
                    parts = self.fp.digests(card_id, tool_name, args, text)
                    code = self.fp.code_from(parts['card_id'], parts['text_digest'], parts['tool_digest'],
                                             parts['args_digest'])
                    text = stamp(text, code, messaging=messaging)
                    self.shown[(str(session_id or ''), str(tool_call_id))] = dict(
                        card_id=card_id, light=None, categories=('unknown',), fingerprint=code, at=self.clock())
                    self.record(event='presented_to_host', card_id=card_id, light=None,
                                categories=['unknown'], reason='advisory_unavailable',
                                surface=self.safe_surface() or 'unknown', fingerprint=code,
                                **{k: v for k, v in parts.items() if k != 'card_id'})
                except Exception:
                    pass  # the notice itself must still reach the human
                return {'action': 'approve', 'rule_key': 'axioma:' + uuid.uuid4().hex, 'message': text}

    def safe_surface(self):
        try:
            value = self.surface()
            return value.strip().lower() if isinstance(value, str) else ''
        except Exception:
            return ''

    def respond(self, pattern_key='', choice='', surface='', session_id='', tool_call_id='', **kwargs):
        """post_approval_response observer: log the host-reported answer. Never authorizes."""
        with self.lock:
            if not str(pattern_key).startswith('plugin_rule:axioma:'):
                return
            item = self.shown.pop((str(session_id or ''), str(tool_call_id)), None)
            if item is None:
                return
            choice = str(choice)
            known = choice if choice in ('once', 'session', 'always', 'deny', 'timeout', 'cancelled',
                                         'notify_failed') or choice.startswith('smart_') else 'unknown'
            answer = ('yes' if known in ('once', 'session', 'always') else
                      'no' if known == 'deny' else
                      'auto' if known.startswith('smart_') else 'unanswered')
            self.record(event='answer', card_id=item['card_id'], light=item['light'],
                        categories=list(item['categories']), choice=known, answer=answer,
                        surface=str(surface or '') or 'unknown', fingerprint=item.get('fingerprint'))

    def finalize(self, session_id='', **kwargs):
        with self.lock:
            sid = str(session_id or '')
            self.cards = {k: v for k, v in self.cards.items() if k[0] != sid}
            self.shown = {k: v for k, v in self.shown.items() if k[0] != sid}


    # -- /signals verify <code> and /signals cards (spec 5.6) ------------------------------------
    def command(self, raw=''):
        """Plain-words check of one card code: staged -> shown -> answered, mismatches named."""
        try:
            words = str(raw or '').strip().split(None, 1)
            verb = words[0].lower() if words else ''
            rest = words[1] if len(words) > 1 else ''
            if verb == 'cards':
                return self.cards_listing()
            match = CODE_ARG.match(rest)
            code = parse_code(match.group(1)) if match else None
            if code is None:
                return ('Usage: /signals verify <card code>, for example /signals verify 7Q4K-2MPD. '
                        'To check the words too, paste the card text on the lines after the code.')
            pasted = rest[match.end():]
            return '\n'.join(self.verify(code, pasted.strip('\n')))
        except Exception:
            return 'Card records are unavailable right now; nothing was changed.'

    def cards_listing(self, limit=20):
        rows = [r for r in self.audit.card_rows() if r['event'] == 'presented_to_host'][:limit]
        if not rows:
            return 'No cards shown yet.'
        lines = []
        for r in rows:
            answers = [a for a in self.audit.card_rows(card_id=r['card_id']) if a['event'] == 'answer']
            lines.append('card code %s: %s on %s, %s' % (
                r.get('fingerprint') or 'none', self.light_word(r), r.get('surface') or 'unknown surface',
                ('answered ' + answers[0].get('answer', 'unknown')) if answers else 'no answer recorded'))
        return '\n'.join(lines)

    @staticmethod
    def light_word(row):
        if row.get('reason') == 'missing_card':
            return 'STOP (no card)' if row.get('light') == 'red' else 'NO CARD'
        if row.get('reason') == 'advisory_unavailable':
            return 'advisory unavailable'
        return {'red': 'STOP', 'yellow': 'CAUTION', 'green': 'GO'}.get(row.get('light'), 'unknown')

    def sealed(self, row):
        return self.fp.sealed({k: v for k, v in row.items() if k not in ('id', 'at')})

    def verify(self, code, pasted=''):
        """Returns plain-words lines. Every check that fails says so; the last line is the verdict."""
        fp = self.fp
        stamp_ = lambda t: time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t))
        out, problems = ['card code ' + code], []
        if not getattr(self, 'fp_durable', False):
            return out + ['MISMATCH: the card log is unavailable, so this code cannot be checked.']
        shown = [r for r in self.audit.card_rows(fingerprint=code) if r['event'] == 'presented_to_host']
        if not shown:
            answered = [r for r in self.audit.card_rows(fingerprint=code) if r['event'] == 'answer']
            if answered:
                return out + ['MISMATCH: an answer is recorded under this code but no card with this code '
                              'was ever shown. The log was changed, or the answer belongs to another card.']
            return out + ['MISMATCH: no card with this code was shown from this log. If you saw this code '
                          'on a card, that card did not come from this Axioma install, the log was cleared, '
                          'or the code was misread.']
        if len(shown) > 1:
            problems.append('more than one shown record carries this code; the log was changed.')
        row = shown[-1]
        history = self.audit.card_rows(card_id=row['card_id'])
        staged = [r for r in history if r['event'] == 'card']
        if row.get('reason') == 'missing_card':
            out.append('staged: no card from the agent (NO CARD notice).')
        elif row.get('reason') == 'advisory_unavailable':
            out.append('staged: not known (the advisor failed and showed a fallback notice).')
        elif staged:
            s = staged[-1]
            out.append('staged: card from the agent, light %s, at %s.' % (s.get('light'), stamp_(s['at'])))
            if not self.sealed(s):
                problems.append('the staged record was changed after it was written.')
            if s.get('light') != row.get('light'):
                out.append('note: the checks changed the light from %s to %s before it was shown.'
                           % (s.get('light'), row.get('light')))
        else:
            problems.append('the card was shown as staged by the agent, but no staged record exists.')
        out.append('shown: %s, handed to Hermes on %s at %s.' % (
            self.light_word(row), row.get('surface') or 'unknown surface', stamp_(row['at'])))
        if not self.sealed(row):
            problems.append('the shown record was changed after it was written.')
        recomputed = fp.code_from(row['card_id'], row.get('text_digest'), row.get('tool_digest'),
                                  row.get('args_digest'))
        if recomputed != code:
            problems.append('the shown record does not produce this code from its own contents; it was changed.')
        answers = [r for r in history if r['event'] == 'answer']
        if not answers:
            out.append('answered: no answer recorded (still waiting, or the prompt closed without one).')
        for a in answers:
            out.append('answered: %s (%s) on %s at %s.' % (a.get('answer'), a.get('choice'),
                                                           a.get('surface') or 'unknown surface', stamp_(a['at'])))
            if a.get('fingerprint') != code:
                problems.append('the answer was recorded against code %s, not the code that was shown.'
                                % (a.get('fingerprint') or 'none'))
            if not self.sealed(a):
                problems.append('the answer record was changed after it was written.')
        if len(answers) > 1:
            problems.append('more than one answer is recorded for this card.')
        if pasted.strip():
            out += self.compare_text(row, pasted, problems)
        else:
            out.append('words: not checked. Paste the card text after the code to check them too.')
        if problems:
            return out + ['MISMATCH: ' + p for p in problems]
        return out + ['OK: staged, shown and answered records agree, and none were changed after writing. '
                      'This confirms the log, not the screen: compare this code with the one on the card you saw.']

    def compare_text(self, row, pasted, problems):
        """Line-by-line check of a pasted card against the keyed line digests (no bodies stored).
        Lines before the first and after the last card line (the Hermes header, the command, the
        deadline, buttons) are ignored; a label the surface put in front of a line (such as
        'Reason: ') is tolerated. Inside the card, an added, changed, missing or reordered line is
        reported."""
        fp, expected = self.fp, list(row.get('line_digests') or [])
        if not expected:
            return ['words: this record has no line digests to compare.']
        where = {}
        for i, d in enumerate(expected):
            where.setdefault(d, i)
        hits = []  # (pasted line number, expected index or None) for each non-empty pasted line
        for n, line in enumerate(pasted.split('\n'), 1):
            norm = normalize_line(line)
            if not norm or CODE_LINE.match(norm):
                continue
            words = norm.split(' ')
            found = next((where[d] for d in (fp.line_digest(' '.join(words[i:])) for i in range(len(words)))
                          if d in where), None)
            hits.append((n, found))
        matched = [k for k, (_, i) in enumerate(hits) if i is not None]
        lines = []
        if matched:
            inside = hits[matched[0]:matched[-1] + 1]
            added = [n for n, i in inside if i is None]
            got = [i for _, i in inside if i is not None]
            if added:
                lines.append('pasted line%s %s %s not on the staged card (added or changed).' % (
                    's' if len(added) > 1 else '', ', '.join(map(str, added)), 'are' if len(added) > 1 else 'is'))
            if got != sorted(got):
                lines.append('the card lines are in a different order than staged.')
            found = set(got)
        else:
            found = set()
        missing = [i + 1 for i in range(len(expected)) if i not in found]
        if missing:
            lines.append('staged line%s %s of %d %s missing or changed (or cut by the surface).' % (
                's' if len(missing) > 1 else '', ', '.join(map(str, missing)), len(expected),
                'are' if len(missing) > 1 else 'is'))
        if lines:
            problems.extend('the pasted card differs from what was staged: ' + x for x in lines)
            return []
        return ['words: all %d lines of the pasted card match what was staged, in order.' % len(expected)]

NO_CARD = {'intent': 'not supplied', 'light': 'yellow', 'signal': 'No card.', 'question': 'None?',
           'affects': ['self'], 'told': True}
