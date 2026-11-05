"""hermes-axioma: inline signal color in the agent's normal reply, plus an advisory card before
send/spend/spin/scrub.

ADVISOR ONLY. The agent marks the few spans of its reply that deserve a second look; the plugin
renders them per surface (color + a style cue + a word; never color alone) and logs metadata. The
card path shows a card and a question inside Hermes's own approval prompt. Nothing here holds,
blocks, authorizes or executes a call; Hermes's own approval gate decides (see docs/HOST-GAPS.md).
Public plugin surfaces only: ctx.register_tool/hook/command, ctx.get_config,
ctx.session_surface, plugins.plugin_storage.plugin_data_dir.
"""
from .axioma.advisor import Advisor
from .axioma.audit import Audit
from .axioma.signal import GUIDANCE as SIGNAL_GUIDANCE, Signal

CARD_GUIDANCE = '''AXIOMA CARD (advisory): before a send/spend/spin/scrub call, call axioma_card with the target
 tool, its exact arguments, and card {intent, light: red|yellow|green, signal: one sentence,
 question: one question ending in ?, affects: [who else sees or feels it], told: boolean}, then make
 the original call. Hermes shows the card in its own approval prompt; the human decides there. A
 card is advice, never consent; GREEN is not permission. SCRUB (deletes/moves) is best-effort shell
 parsing: a remove/move whose shape it could not parse is capped at CAUTION; removes inside bash -c,
 eval, ssh, docker exec or scripts are not seen at all.'''

GUIDANCE = SIGNAL_GUIDANCE + '\n' + CARD_GUIDANCE

SCHEMA = {
    'name': 'axioma_card',
    'description': 'Stage an advisory card for one exact upcoming tool call. Advice only: it does not '
                   'approve, block or execute anything. SCRUB (rm/mv/unlink/rmdir) detection is '
                   'best-effort shell parsing: a remove/move whose shape it could not parse is shown as '
                   'CAUTION, never GO; removes inside bash -c, eval, ssh, docker exec or scripts are not seen.',
    'parameters': {'type': 'object', 'required': ['tool', 'arguments', 'card'],
                   'additionalProperties': False, 'properties': {
                       'tool': {'type': 'string'}, 'arguments': {'type': 'object'},
                       'card': {'type': 'object', 'additionalProperties': False,
                                'required': ['intent', 'light', 'signal', 'question'], 'properties': {
                                    'intent': {'type': 'string', 'maxLength': 400},
                                    'light': {'type': 'string', 'enum': ['red', 'yellow', 'green']},
                                    'signal': {'type': 'string', 'maxLength': 400},
                                    'question': {'type': 'string', 'maxLength': 400},
                                    'affects': {'type': 'array', 'items': {'type': 'string'}},
                                    'told': {'type': 'boolean'},
                                }}}},
}


def data_root():
    from plugins.plugin_storage import plugin_data_dir
    return plugin_data_dir('hermes-axioma')


def register(ctx):
    audit = Audit(data_root() / 'audit.sqlite3')
    surface = getattr(ctx, 'session_surface', None)
    advisor = Advisor(ctx.get_config('policy', default={}), audit,
                      checks_config=ctx.get_config('checks', default={}),
                      surface=surface if callable(surface) else (lambda: ''))
    signal = Signal(audit, theme=ctx.get_config('theme', default='dark'),
                    palette=ctx.get_config('palette', default='default'),
                    words=ctx.get_config('words', default='always'),
                    budget=ctx.get_config('budget', default={}),
                    messaging_marker=ctx.get_config('messaging_marker', default=True))

    def finalize(**kwargs):
        advisor.finalize(**kwargs)
        signal.finalize(**kwargs)
    ctx.register_tool(name='axioma_card', toolset='axioma', schema=SCHEMA, handler=advisor.submit)
    ctx.register_hook('pre_tool_call', advisor.before)
    ctx.register_hook('post_tool_call', signal.observe)
    ctx.register_hook('post_approval_response', advisor.respond)
    ctx.register_hook('pre_llm_call', lambda **kw: {'context': GUIDANCE})
    ctx.register_hook('on_session_finalize', finalize)
    ctx.register_hook('transform_llm_output', signal.transform)

    def signals(raw=''):
        verb = str(raw or '').strip().split(None, 1)
        if verb and verb[0].lower() in ('verify', 'cards'):
            return advisor.command(raw)
        return signal.listing(raw)
    ctx.register_command('signals', signals, args_hint='[verify <card code> | cards]',
                         description='List recent signals and whispers (no text bodies). '
                                     '/signals cards lists card codes; /signals verify <code> checks '
                                     'staged -> shown -> answered.')
    ctx.register_command('whispers', signal.listing, description='Same list as /signals (kept for older notes).')
