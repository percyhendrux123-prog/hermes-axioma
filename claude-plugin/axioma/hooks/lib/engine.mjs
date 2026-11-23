// Session state for the Axioma mod: what has been seen, staged and shown. Memory only: nothing
// here is written to disk, and no message text, tool argument or card text is kept in the ledger.
import { classify } from './classify.mjs'
import {
  CardStore, applyChecks, argsOf, callSummary, renderCard, renderNotice, validateCard,
} from './card.mjs'
import {
  GUIDANCE as SIGNAL_GUIDANCE, decide, parse, plan, plainLine, replyHasTags, scrubJoined,
} from './signal.mjs'

export const CARD_GUIDANCE = (cardTool) => `AXIOMA CARD (advice only): before a call that sends, spends, spins up or scrubs (a message, post or email; a payment;
a deploy, push, scheduled job; a remove or move of files), first call ${cardTool} with
{call: {tool, arguments}, card} where call is exactly the call you are about to make, and
card is {intent, light: red|yellow|green, signal: one sentence, question: one question ending in ?,
affects: [who else sees or feels it], told: boolean}. Then make the original call. Claude Code shows
the card to the person and holds the call until they pick Hold or Go ahead. A card is advice, never
consent: GREEN is not permission, and Claude Code's own permission check still runs after Go ahead.
If the person picks Hold, do not retry the same call; ask what they want instead. Remove and move
detection is best-effort shell parsing: removes inside bash -c, eval, ssh, docker exec or scripts are not seen.`

export const CARD_SCHEMA = {
  type: 'object',
  required: ['call', 'card'],
  additionalProperties: false,
  properties: {
    // Not named `tool`: Claude Code reserves that key for the name of the tool being called.
    call: {
      type: 'object',
      additionalProperties: false,
      required: ['tool', 'arguments'],
      properties: {
        tool: { type: 'string', description: 'The exact tool name of the upcoming call, for example Bash.' },
        arguments: { type: 'object', description: 'The exact arguments of the upcoming call.' },
      },
    },
    card: {
      type: 'object',
      additionalProperties: false,
      required: ['intent', 'light', 'signal', 'question'],
      properties: {
        intent: { type: 'string', maxLength: 400 },
        light: { type: 'string', enum: ['red', 'yellow', 'green'] },
        signal: { type: 'string', maxLength: 400 },
        question: { type: 'string', maxLength: 400 },
        affects: { type: 'array', items: { type: 'string' } },
        told: { type: 'boolean' },
      },
    },
  },
}

export const CARD_DESCRIPTION = 'Stage an advisory card for one exact upcoming tool call. Advice only: it does not approve, '
  + 'block or run anything. Claude Code shows the card and asks the person to Hold or Go ahead. Remove/move '
  + '(SCRUB) detection is best-effort shell parsing; a shape it cannot read is shown as CAUTION, never GO.'

const LEDGER_MAX = 200
const CACHE_MAX = 400
const CHECKS_MAX = 200

let counter = 0
function newId() {
  counter += 1
  const r = globalThis.crypto?.randomUUID?.()
  return r ? r.replace(/-/g, '').slice(0, 12) : Date.now().toString(36) + counter.toString(36)
}

export class Axioma {
  constructor(options = {}, { now = () => Date.now() } = {}) {
    this.options = {
      theme: options.theme === 'light' ? 'light' : 'dark',
      palette: ['default', 'cvd', 'none'].includes(options.palette) ? options.palette : 'default',
      words: options.words === 'plain_only' ? 'plain_only' : 'always',
      workspace: typeof options.workspace === 'string' && options.workspace.startsWith('/') ? options.workspace.replace(/\/+$/, '') : '',
    }
    this.now = now
    this.cards = new CardStore(now)
    this.turn = ''
    this.checks = [] // { id, tool, turn } for calls Claude Code reported as successful
    this.whispered = new Map() // phrase -> requestId that first showed it
    this.cache = new Map() // requestId + text -> render plan, so a redraw never changes a decision
    this.entries = [] // ledger: metadata only
  }

  // -- instructions -----------------------------------------------------------------------------
  guidance(cardTool) {
    return SIGNAL_GUIDANCE + '\n' + CARD_GUIDANCE(cardTool)
  }

  // -- ledger -----------------------------------------------------------------------------------
  log(entry) {
    this.entries.push({ at: this.now(), ...entry })
    if (this.entries.length > LEDGER_MAX) this.entries.shift()
  }

  // -- observed checks (green only from real checks) -----------------------------------------------
  startTurn(turnId) {
    this.turn = String(turnId ?? '')
  }

  noteOk(tool, id) {
    if (!tool) return
    this.checks.push({ id: String(id || ''), tool: String(tool), turn: this.turn })
    if (this.checks.length > CHECKS_MAX) this.checks.shift()
  }

  checkPassed(check) {
    if (!check) return false
    return this.checks.some((c) => (c.id && c.id === check) || (c.tool === check && c.turn === this.turn))
  }

  // -- inline signals ---------------------------------------------------------------------------
  /**
   * Plan how to draw one assistant text block, or null to leave it as Claude Code draws it.
   * Same (requestId, text) always gives the same plan. Returns { lines, styled, plainText }.
   */
  renderMessage(requestId, text, { noColor = false } = {}) {
    if (typeof text !== 'string' || !text.includes('[') || !replyHasTags(text)) return null
    const key = String(requestId ?? '') + '\u0000' + text + '\u0000' + (noColor ? '1' : '0')
    const hit = this.cache.get(key)
    if (hit) return hit
    const lines = parse(text)
    const spans = lines.flat().filter((p) => typeof p !== 'string')
    decide(spans, {
      checkPassed: (c) => this.checkPassed(c),
      // A phrase already whispered in another block is plain. A redraw of the same block, or a
      // longer stream of it, keeps its whisper.
      whisperSeen: (phrase) => {
        const k = phrase.trim().toLowerCase()
        const owner = this.whispered.get(k)
        const mine = String(requestId ?? '')
        if (owner === undefined || owner === mine) { this.whispered.set(k, mine); return false }
        return true
      },
    })
    for (const s of spans) {
      if (s.level === 'intent' && s.show) continue // intent is not a risk signal
      this.log({ event: 'signal', level: s.level, reason: s.drop || s.reason || s.why || null, shown: s.show })
    }
    const rendered = plan(lines, { ...this.options, noColor })
    const styled = rendered.some((l) => l.styled)
    const plain = scrubJoined(rendered.map(plainLine).join('\n'))
    const result = { lines: rendered, styled, plainText: plain.trim() ? plain : '(empty reply)' }
    this.cache.set(key, result)
    if (this.cache.size > CACHE_MAX) this.cache.delete(this.cache.keys().next().value)
    return result
  }

  // -- cards ------------------------------------------------------------------------------------
  /** axioma_card handler. Never approves anything. Returns the text Claude reads back. */
  stageCard(envelope) {
    const id = newId()
    try {
      const card = this.cards.stage(envelope, id)
      this.log({ event: 'card', id, light: card.light, valid: true })
      return JSON.stringify({ status: 'staged', card_id: id, note: 'Advice only. The person is asked to Hold or Go ahead; Claude Code\'s own permission check still applies.' })
    } catch (err) {
      this.log({ event: 'card', id, valid: false })
      return JSON.stringify({ error: 'card not staged: ' + String(err.message || err).slice(0, 200), note: 'Without a valid card the person sees a NO CARD notice.' })
    }
  }

  /**
   * For a call that is about to run: null when it is none of send/spend/spin/scrub, else what to
   * show { text, options, light, kind, id, reason, summary }.
   */
  review(tool, args, { cwd = null } = {}) {
    const roots = this.options.workspace ? [this.options.workspace] : []
    const { categories, unparsed } = classify(tool, args, { roots, cwd })
    if (!categories.length) return null
    const call = callSummary(tool, args)
    const staged = this.cards.take(tool, args)
    let text
    let light
    let id
    let reason = null
    if (staged) {
      const { card, results } = applyChecks(staged.card, { unparsed })
      const final = unparsed && card.light === 'green' ? { ...card, light: 'yellow' } : card
      text = renderCard({ card: final, results, kind: categories, call })
      light = final.light
      id = staged.id
    } else {
      // No card: the notice is a caution at most. An unreadable remove or move is named.
      const results = unparsed ? [{ check: 'scrub_parse', pass: false, note: 'could not parse (best-effort parser)' }] : []
      text = renderNotice({ tool, kind: categories, results, call })
      light = null
      id = newId()
      reason = 'missing_card'
    }
    const options = light === 'red' ? ['Hold', 'Go ahead anyway'] : ['Hold', 'Go ahead']
    return { text, options, light, kind: categories, id, reason, call }
  }
}

export { argsOf, validateCard }
