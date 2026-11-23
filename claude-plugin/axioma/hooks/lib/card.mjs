// The advisory card: validate what the agent staged, adjust the light, write the text.
//
// Port of axioma/card.py and the card parts of axioma/checks.py and axioma/advisor.py.
// A card is advice. It is never consent: nothing here approves, allows or runs a call.

export const LIGHTS = ['red', 'yellow', 'green']
export const LIGHT_WORDS = { red: 'STOP', yellow: 'CAUTION', green: 'GO' }
export const ADVICE = '(advice only; you decide here, and Claude Code\u2019s own permission check still applies)'
export const NOTICE_QUESTION = 'What do you need to know before this runs?'
export const PARSE_NOTE = 'could not parse (best-effort parser)'
export const TTL_MS = 300000
export const CAPACITY = 256

// eslint-disable-next-line no-control-regex
const CONTROLISH = /[\p{C}\u2028\u2029]/u

/** Throws on a card that is not exactly the documented shape. Returns a copy. */
export function validateCard(value) {
  const required = ['intent', 'light', 'signal', 'question']
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('card must be an object')
  const keys = Object.keys(value)
  if (!required.every((k) => keys.includes(k)) || keys.some((k) => ![...required, 'affects', 'told'].includes(k))) {
    throw new Error('required intent/light/signal/question; optional affects/told only')
  }
  if ('told' in value && typeof value.told !== 'boolean') throw new Error('told must be boolean')
  if ('affects' in value) {
    const items = typeof value.affects === 'string' ? [value.affects] : value.affects
    if (!Array.isArray(items) || items.length > 12 || !items.every((x) => typeof x === 'string' && x.length > 0 && x.length <= 100)) {
      throw new Error('affects must be a short string or list')
    }
    if (items.some((x) => CONTROLISH.test(x))) throw new Error('affects controls are forbidden')
  }
  if (typeof value.light !== 'string' || !LIGHTS.includes(value.light)) throw new Error('light must be red, yellow or green')
  for (const key of ['intent', 'signal', 'question']) {
    const text = value[key]
    if (typeof text !== 'string' || !text.trim() || text.length > 400) throw new Error('card text must be 1..400 characters')
    if (CONTROLISH.test(text)) throw new Error('control characters are not allowed')
  }
  if (!value.question.endsWith('?') || (value.question.match(/\?/g) || []).length !== 1) throw new Error('one question ending in ? required')
  if (value.signal.trim().replace(/[.!?]+$/, '').split(/[.!?]+\s+/).length !== 1) throw new Error('signal must be one sentence')
  return { ...value }
}

const DOWNSTREAM = /(?<![a-z])(?:end[ _-]?users?|public|clients?|customers?|users?|subscribers?|followers?|everyone|patients?|members?|audiences?|students?|buyers?|leads?)(?![a-z])/i

/**
 * Checks that can only make a card more careful (green to yellow), never less.
 * Returns { card, results }; results are { check, pass, note? }.
 */
export function applyChecks(card, { unparsed = false } = {}) {
  const out = { ...card }
  const results = []
  const raw = out.affects ?? []
  const affects = typeof raw === 'string' ? [raw] : raw
  if (!affects.length) results.push({ check: 'downstream_declared', pass: false })
  if (affects.some((x) => DOWNSTREAM.test(x)) && !out.told) results.push({ check: 'downstream_informed', pass: false })
  if (unparsed) results.push({ check: 'scrub_parse', pass: false, note: PARSE_NOTE })
  if (out.light === 'green' && results.some((r) => !r.pass)) out.light = 'yellow'
  return { card: out, results }
}

function resultLine(r) {
  return r.check + ': ' + (r.note || (r.pass ? 'pass' : 'fail'))
}

/** One line naming the call, for the person to recognise it. Truncated, single line. */
export function callSummary(tool, args) {
  const first = typeof args?.command === 'string' ? args.command
    : typeof args?.file_path === 'string' ? args.file_path
      : Object.keys(args || {}).length ? JSON.stringify(args) : ''
  const flat = String(first).replace(/\s+/g, ' ').replace(CONTROLISH, '').trim()
  const cut = flat.length > 160 ? flat.slice(0, 157) + '...' : flat
  return cut ? tool + ': ' + cut : tool
}

/**
 * The text shown in Claude Code's question dialog. The last line is the question (the dialog asks
 * for one that ends in a question mark). RED never says "yes".
 */
export function renderCard({ card, results = [], kind = [], call = '' }) {
  const word = LIGHT_WORDS[card.light]
  const head = word + ' \u00b7 ' + (card.light === 'red' ? 'proceed: no' : 'proceed: yes / no')
  const lines = [head]
  if (call) lines.push('call: ' + call)
  lines.push('intent: ' + card.intent, 'signal: ' + card.signal)
  if (kind.length) lines.push('kind: ' + kind.join('+'))
  for (const r of results) lines.push(resultLine(r))
  lines.push(ADVICE, card.question)
  return lines.join('\n')
}

/** Shown when the agent staged no valid card for this exact call. Plain words. */
export function renderNotice({ tool, kind, results = [], call = '' }) {
  const lines = ['NO CARD \u00b7 proceed: yes / no']
  if (call) lines.push('call: ' + call)
  lines.push('signal: Unreviewed ' + kind.join('+') + ' via ' + tool + '.', 'kind: ' + kind.join('+'))
  for (const r of results) lines.push(resultLine(r))
  lines.push('intent: not stated (the agent supplied no card for this exact call)', ADVICE, NOTICE_QUESTION)
  return lines.join('\n')
}

// -- matching a staged card to the call it describes ---------------------------------------------
function canon(value) {
  if (Array.isArray(value)) return '[' + value.map(canon).join(',') + ']'
  if (value && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map((k) => JSON.stringify(k) + ':' + canon(value[k])).join(',') + '}'
  }
  return JSON.stringify(value) ?? 'null'
}

const ENVELOPE = ['tool', 'tool_use_id', 'agentId', 'consent', 'requestMeta']

/** The tool's own arguments out of a tool.call event. */
export function argsOf(e) {
  const out = {}
  for (const k of Object.keys(e)) if (!ENVELOPE.includes(k)) out[k] = e[k]
  return out
}

/** Key a card by tool and exact arguments. A Bash `description` is prose, not part of the call. */
export function cardKey(tool, args) {
  const a = { ...(args || {}) }
  if (tool === 'Bash') delete a.description
  return tool + '\u0000' + canon(a)
}

export class CardStore {
  constructor(now = () => Date.now()) {
    this.now = now
    this.cards = new Map()
  }

  prune() {
    const t = this.now()
    for (const [k, v] of this.cards) if (t - v.at >= TTL_MS) this.cards.delete(k)
    while (this.cards.size >= CAPACITY) this.cards.delete(this.cards.keys().next().value)
  }

  /** Stage a card for one exact call. A replacement (even a bad one) retires the earlier card. */
  stage(envelope, id) {
    this.prune()
    if (envelope === null || typeof envelope !== 'object' || Array.isArray(envelope)
      || Object.keys(envelope).sort().join() !== 'arguments,card,tool') {
      throw new Error('envelope must be {tool, arguments, card}')
    }
    const { tool, arguments: target } = envelope
    if (typeof tool !== 'string' || !tool || target === null || typeof target !== 'object' || Array.isArray(target)) {
      throw new Error('tool must be a name and arguments an object')
    }
    const key = cardKey(tool, target)
    this.cards.delete(key)
    const card = validateCard(envelope.card)
    this.cards.set(key, { card, id, at: this.now() })
    return card
  }

  /** Take the card staged for this exact call, once. */
  take(tool, args) {
    this.prune()
    const key = cardKey(tool, args)
    const item = this.cards.get(key)
    this.cards.delete(key)
    return item || null
  }
}
