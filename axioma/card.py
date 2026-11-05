"""Bounded single-line advisories; model text is never a decision."""
import re
import unicodedata

COLORS = {'red': '255;69;58', 'yellow': '255;204;0', 'green': '48;209;88'}
WORDS = {'red': 'STOP', 'yellow': 'CAUTION', 'green': 'GO'}


def validate_card(value):
    required = {'intent', 'light', 'signal', 'question'}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {'affects', 'told'}:
        raise ValueError('required intent/light/signal/question; optional affects/told only')
    if 'told' in value and not isinstance(value['told'], bool):
        raise ValueError('told must be boolean')
    if 'affects' in value:
        affects = value['affects']
        items = [affects] if isinstance(affects, str) else affects
        if not isinstance(items, list) or len(items) > 12 or not all(isinstance(x, str) and 0 < len(x) <= 100 for x in items):
            raise ValueError('affects must be a short string or list')
        if any(any(unicodedata.category(c).startswith('C') for c in text) for text in items):
            raise ValueError('affects controls are forbidden')
    if not isinstance(value['light'], str) or value['light'] not in COLORS:
        raise ValueError('light must be red, yellow or green')
    for key in ('intent', 'signal', 'question'):
        text = value[key]
        if not isinstance(text, str) or not text.strip() or len(text) > 400:
            raise ValueError('card text must be 1..400 characters')
        if any(unicodedata.category(c).startswith('C') or c in '\u2028\u2029' for c in text):
            raise ValueError('control characters are not allowed')
    if not value['question'].endswith('?') or value['question'].count('?') != 1:
        raise ValueError('one question ending in ? required')
    if len(re.split(r'[.!?]+\s+', value['signal'].strip().rstrip('.!?'))) != 1:
        raise ValueError('signal must be one sentence')
    return dict(value)


def _layout(head, question, details, advice, messaging):
    """Most important first, because Hermes's CLI approval panel shows the description last and
    truncates it to a few rows: light + proceed, then the question, then the reasons.
    Messaging surfaces lead with the question."""
    top = [question, head] if messaging else [head, question]
    return '\n'.join(top + details + [advice])


def render_card(card, color=False, messaging=False, checks=(), kind=()):
    card = validate_card(card)
    def paint(text, rgb):
        return '\x1b[38;2;' + rgb + 'm' + text + '\x1b[0m' if color and not messaging else text
    light = card['light']
    head = paint(WORDS[light], COLORS[light]) + ' · ' + ('proceed: no' if light == 'red' else 'proceed: yes / no')
    details = [paint('intent: ' + card['intent'], '255;255;255'),
               paint('signal: ' + card['signal'], COLORS[light])]
    if kind:
        details.append('kind: ' + '+'.join(kind))
    details += [r['check'] + ': ' + (r.get('note') or ('pass' if r['pass'] else 'fail')) for r in checks]
    return _layout(head, card['question'], details, ADVICE, messaging)


ADVICE = '(advice only; you decide in the Hermes prompt)'
NOTICE_QUESTION = 'What do you need to know before this runs?'


def render_notice(tool, categories, checks=(), messaging=False, red_signal=None):
    """Shown when the agent supplied no valid card for this exact call. Plain words, no color."""
    head = ('STOP' if red_signal else 'NO CARD') + ' · ' + ('proceed: no' if red_signal else 'proceed: yes / no')
    details = ['signal: ' + (red_signal or 'Unreviewed %s via %s.' % ('+'.join(categories), tool)),
               'kind: ' + '+'.join(categories)]
    details += [r['check'] + ': ' + (r.get('note') or ('pass' if r['pass'] else 'fail')) for r in checks]
    details += ['intent: not stated (the agent supplied no card for this exact call)']
    return _layout(head, NOTICE_QUESTION, details, ADVICE, messaging)
