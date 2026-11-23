// Axioma for Claude Code: inline signal marks, and an advisory card before send/spend/spin/scrub.
//
// ADVISOR. The agent marks the few phrases of its reply that deserve a second look; this mod draws
// them (color + a style cue + a word, never color alone). Before a call that sends, spends, spins
// up or scrubs, the card is shown in Claude Code's own question dialog and the call waits for the
// person to pick Hold or Go ahead. Go ahead only lets the call continue to Claude Code's own
// permission check: nothing here approves, allows or runs a call. Nothing is written to disk.
import { Axioma, CARD_DESCRIPTION, CARD_SCHEMA, argsOf } from './lib/engine.mjs'

const CARD_TOOL = 'axioma_card'
const CARD_FULL = 'mcp__axiom-axioma__axioma_card'
const GO = ['Go ahead', 'Go ahead anyway']
const LIGHT_WORD = { red: 'STOP', yellow: 'CAUTION', green: 'GO' }

function listing(ax) {
  if (!ax.entries.length) return 'No signals or cards yet this session. Nothing is written to disk, and no text bodies are kept.'
  return ax.entries.slice(-40).map((r) => {
    const t = new Date(r.at).toISOString().slice(11, 19)
    if (r.event === 'signal') return t + ' ' + r.level + ' ' + (r.shown ? 'shown' : 'not shown') + (r.reason ? ' (' + r.reason + ')' : '')
    if (r.event === 'card') return t + ' card ' + (r.valid ? 'staged (' + r.light + ')' : 'rejected') + ' id ' + (r.id || '')
    if (r.event === 'review') return t + ' card ' + (r.light ? LIGHT_WORD[r.light] : 'NO CARD') + ' for ' + r.kind.join('+') + ': ' + r.answer
    return t + ' ' + r.event
  }).join('\n') + '\n(this session only; no text bodies)'
}

// Show the card for a send/spend/spin/scrub call and wait for Hold or Go ahead.
// Returns { deny } to hold the call, or null to let it go on to Claude Code's own permission check.
async function hold(ax, $, e) {
  let review
  try {
    let cwd = null
    if (ax.options.workspace) {
      try { cwd = await $.session.cwd() } catch { cwd = null }
    }
    review = ax.review(e.tool, argsOf(e), { cwd })
  } catch {
    return null // the advisor failing never blocks a call
  }
  if (!review) return null
  let surfaces = []
  try { surfaces = await $.session.surfaces() } catch { surfaces = [] }
  if (!surfaces.length) {
    // claude -p and the Agent SDK: nobody to ask. Claude Code's own permission decides.
    ax.log({ event: 'review', light: review.light, kind: review.kind, answer: 'not shown (nobody to ask)' })
    return null
  }
  let answer = null
  try {
    answer = await $.ui.ask(review.text, { options: review.options, header: 'Axioma card' })
  } catch { answer = null } // dismissed, or "Chat about this": not Go ahead, so the call is held
  const go = GO.includes(answer)
  ax.log({ event: 'review', light: review.light, kind: review.kind, answer: go ? 'go ahead' : 'hold' })
  try {
    $.ui.log('Axioma card (' + (review.light ? LIGHT_WORD[review.light] : 'NO CARD') + ', ' + review.kind.join('+') + '): '
      + (go ? 'you chose Go ahead. Advice only; Claude Code\'s own permission check follows.' : 'you chose Hold. The call did not run.'))
  } catch { /* a log line is a courtesy */ }
  if (go) return null
  return { deny: 'The person saw the Axioma card for this call and did not pick Go ahead, so it did not run. Do not retry the same call; ask them what they want instead.' }
}

export function register(on, options = {}) {
  const ax = new Axioma(options)

  on('session.start', async ($, e, next) => {
    try {
      await $.tool.register({
        name: CARD_TOOL,
        description: CARD_DESCRIPTION,
        inputSchema: CARD_SCHEMA,
        isDeferred: false,
      })
    } catch { /* an older Claude Code may refuse the field; the signals still work */ }
    try {
      await $.command.register({ name: 'signals', description: 'List this session\'s Axioma signals and cards (no text bodies)' })
    } catch { /* the name may be taken */ }
    return next(e)
  })

  // Teach Claude the tag grammar and the card protocol, once per conversation.
  on('prompt.context', async ($, e, next) => {
    const blocks = [...(e.blocks || []).filter((b) => b.name !== 'axioma'), { name: 'axioma', text: ax.guidance(CARD_FULL) }]
    return next({ ...e, blocks })
  })

  on('turn.start', async ($, e, next) => {
    ax.startTurn(e.turnId)
    return next(e)
  })

  on('command.run', { command: 'signals' }, async () => ({ text: listing(ax), isTextDisplayOnly: true }))

  // The card tool, and the hold before a send/spend/spin/scrub call.
  on('tool.call', async ($, e, next) => {
    if (e.tool === CARD_FULL) {
      const call = e.call && typeof e.call === 'object' ? e.call : {}
      return { result: ax.stageCard({ tool: call.tool, arguments: call.arguments, card: e.card }) }
    }
    const held = await hold(ax, $, e)
    if (held) return held
    const result = await next(e)
    // A call Claude Code reports as having succeeded can back a green signal.
    if (result && !result.deny && !result.isError && e.tool !== 'AskUserQuestion') ax.noteOk(e.tool, e.tool_use_id)
    return result
  })

  // Draw the marks in Claude Code's own transcript. The stored message is never changed.
  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    const text = e.props && e.props.text
    if (typeof text !== 'string' || !text.includes('[')) return next(e)
    let noColor = false
    try { noColor = Boolean(await $.env.get('NO_COLOR')) } catch { noColor = false }
    const out = ax.renderMessage(e.requestId, text, { noColor })
    if (!out) return next(e)
    // Nothing to colour (everything plain, over budget, or in code): keep Claude Code's own
    // markdown drawing and only swap the text.
    if (!out.styled) return next({ ...e, props: { ...e.props, text: out.plainText } })
    const { Box, Text, Markdown } = $.ui.resolve(e)
    const children = []
    let run = []
    const flush = () => {
      if (run.length) children.push(Markdown({ text: run.join('\n') }))
      run = []
    }
    out.lines.forEach((line, i) => {
      if (!line.styled) { run.push(plainLineText(line)); return }
      flush()
      const parts = []
      for (const p of line.pieces) {
        if (typeof p === 'string') { if (p) parts.push(p); continue }
        const props = { children: [p.text] }
        if (p.color) props.color = p.color
        if (p.bold) props.bold = true
        if (p.underline) props.underline = true
        if (p.italic) props.italic = true
        parts.push(Text(props))
        if (p.word) parts.push(p.word)
      }
      children.push(Text({ key: 'axioma-line-' + i, children: parts }))
    })
    flush()
    const body = Box({ key: 'axioma-body', flexDirection: 'column', flexGrow: 1, children })
    // The terminal draws a bullet and a two-column margin beside a reply; keep them where we
    // replace the drawing, so a marked reply sits where an unmarked one would.
    if (e.surface !== 'terminal') return body
    const gutter = Text({ key: 'axioma-gutter', children: [e.props.isFirstOfReply ? '\u23fa ' : '  '] })
    return Box({ key: 'axioma-message', flexDirection: 'row', children: [gutter, body] })
  })
}

function plainLineText(line) {
  return line.pieces.map((p) => (typeof p === 'string' ? p : p.text + p.word)).join('')
}
