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
import threading
import time
import uuid
from .card import NOTICE_QUESTION, render_card, render_notice, validate_card
from .policy import Policy
from .checks import Checks

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
                self.shown[(str(session_id or ''), str(tool_call_id))] = dict(
                    card_id=card_id, light=light, categories=categories, at=self.clock())
                self.record(event='presented_to_host', card_id=card_id, light=light,
                            categories=categories, reason=reason,
                            checks=[{'check': r['check'], 'pass': r['pass']} for r in results])
                # Every card gets a fresh rule key. Hermes uses the first approve's key for the
                # whole call (even when another plugin also asked), so a reusable key could let a
                # remembered Session/Always cover a different call or another plugin's request.
                rule_key = 'axioma:%s:%s:%s:%s' % ('+'.join(categories), tool_name, light or 'nocard',
                                                   uuid.uuid4().hex)
                return {'action': 'approve', 'message': message, 'rule_key': rule_key}
            except Exception:
                # An advisory failure still shows the human something; it never silently drops.
                notice = 'AXIOMA: advisory unavailable for this call. Hermes approval decides.'
                text = (NOTICE_QUESTION + '\n' + notice) if self.safe_surface() not in LOCAL_SURFACES \
                    else (notice + '\n' + NOTICE_QUESTION)
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
                        categories=item['categories'], choice=known, answer=answer)

    def finalize(self, session_id='', **kwargs):
        with self.lock:
            sid = str(session_id or '')
            self.cards = {k: v for k, v in self.cards.items() if k[0] != sid}
            self.shown = {k: v for k, v in self.shown.items() if k[0] != sid}


NO_CARD = {'intent': 'not supplied', 'light': 'yellow', 'signal': 'No card.', 'question': 'None?',
           'affects': ['self'], 'told': True}
