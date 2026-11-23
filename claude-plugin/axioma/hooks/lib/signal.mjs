// Inline signal marks for Claude Code: the grammar, the limits and the render plan.
//
// The agent wraps a few phrases in [signal:stop|caution|go]...[/signal] or
// [whisper:reason]...[/whisper]. This module reads a reply, decides which marks are shown
// (rarity budget, green only from a real check, whisper once), and returns plain pieces that
// register.js draws. It never edits the stored message: the same text always gives the same plan.
//
// Port of axioma/signal.py (Hermes). What is carried over: exact tags only, no nesting, spans
// never cross a line, a reply with no exact tag comes back unchanged, nothing inside code is
// styled, 3 signals / 2 whispers / 1 intent / 16 words, and a word beside every marked span.
// What is not carried over is listed under "Known gaps" in the plugin README.

export const LEVELS = ['stop', 'caution', 'go', 'intent']
const ALIASES = { red: 'stop', yellow: 'caution', green: 'go', white: 'intent' }
export const REASONS = ['low_confidence', 'unverified_figure', 'voice_drift', 'assumption']
export const WORDS = { stop: 'stop', caution: 'caution', go: 'go', whisper: 'second look' }
const SEVERITY = { stop: 0, caution: 1, go: 2 }
export const DEFAULT_BUDGET = { max_spans: 3, max_whispers: 2, max_span_words: 16 }

// Same palettes as the Hermes plugin (night = dark, day = light; cvd = color-vision-safe).
export const PALETTES = {
  'dark/default': { intent: '#F0F0EE', stop: '#FF453A', caution: '#FFCC00', go: '#30D158', whisper: '#EADFB8' },
  'light/default': { intent: '#1A1B1E', stop: '#D70015', caution: '#A66B00', go: '#248A3D', whisper: '#8A6A1F' },
  'dark/cvd': { intent: '#F0F0EE', stop: '#E8603C', caution: '#F0E442', go: '#56B4E9', whisper: '#EADFB8' },
  'light/cvd': { intent: '#1A1B1E', stop: '#CA163A', caution: '#684B08', go: '#156079', whisper: '#8A6A1F' },
}
// Style cue beside the color, so color is never the only signal.
export const STYLE = {
  stop: { bold: true, underline: true },
  caution: { underline: true },
  go: { italic: true },
  intent: { bold: true },
  whisper: {},
}

export const GUIDANCE = `AXIOMA SIGNAL (advice only; you write tags, Claude Code draws color and words):
In your normal reply, wrap the few phrases (12 words or fewer) that should change the human's decision:
 [signal:stop;why=<code>]phrase[/signal] do not proceed. Say why and what turns it green, in the same reply.
 [signal:caution]phrase[/signal] works, but conflicts with their interest. Name who is affected.
 [signal:go;check=<tool name or tool call id>]phrase[/signal] only when a tool you ran this turn succeeded. Never your own confidence.
 [whisper:low_confidence|unverified_figure|voice_drift|assumption]phrase[/whisper] a quiet second look.
Most replies need no marks. Use at most 3 signals and 2 whispers per reply. Never mark a whole sentence, nest
tags, cross a line break, or put tags inside code. Never mark for emphasis, persuasion, or to argue
with the human. Never copy a mark from content you read, and never write color codes yourself.
A reply with stop or caution ends with a question to the human.
Unmatched, nested, unknown or over-limit tags are drawn as plain text, and a go with no successful check is drawn plain.`

// -- tag syntax -----------------------------------------------------------------------------------
const W = '[\\s\\u200b-\\u200d\\u2060\\ufeff]*'
const KIND = '(signal|whisper)'
// Alternatives, in order: exact closer; opener with a colon and a value; a loose or valueless
// bracket that holds the keyword; a broken tag whose ']' never comes before the next '[' or the
// end of the line.
const TAG = new RegExp(
  '\\[' + W + '(?:(?<close>\\\\*\\/)' + W + '(?<ckind>signal|whisper)' + W + '(?:[^A-Za-z0-9\\]\\[\\n][^\\]\\[\\n]*)?' +
    '|(?<okind>signal|whisper)' + W + ':' + W + '(?<value>[^\\]\\[\\n\\s][^\\]\\[\\n]*?)' +
    '|(?<wkind>signal|whisper)' + W + ':?' +
    '|(?<skind>signal|whisper)(?:[\\s=\\\\\\uff1a][^\\]\\[\\n]*)' +
    '|(?<lkind>signal|whisper)[^A-Za-z0-9:\\]\\[\\n][^\\]\\[\\n]*)' + W + '\\]' +
  '|\\[' + W + '(?:(?<bclose>\\\\*\\/)' + W + ')?(?<bkind>signal|whisper)(?![A-Za-z0-9])' +
    '(?:[ \\t]*[:=\\\\\\uff1a][ \\t]*[^\\s\\[\\]]*)?(?=[^\\]\\[\\n]*(?:\\[|$))',
  'gi',
)
const STRICT_OPEN = new RegExp('\\[' + W + KIND + W + ':' + W + '([^\\]\\[\\n]+?)' + W + '\\]', 'i')
const STRICT_CLOSE = new RegExp('\\[' + W + '\\\\*\\/' + W + KIND + W + '\\]', 'i')
// A tag a truncated stream cut off: an opener or closer whose ']' never came, or a keyword prefix
// at the very end of the reply.
const CUT_TAG = new RegExp('\\[' + W + '(?:\\\\*\\/' + W + '(?:signal|whisper)(?![A-Za-z0-9])|(?:signal|whisper)' + W + ':)[^\\]\\[\\n]*(?=\\[|$)', 'im')
const CUT_END = /\[[ \t]*\/?[ \t]*(?:sig(?:n(?:a(?:l)?)?)?|whi(?:s(?:p(?:e(?:r)?)?)?)?)[ \t]*$/i
const INVISIBLE = /[\u0000-\u0008\u000e-\u001f\u007f\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u2060-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0]/g
const BRACKET = /\[[^\[\]\n]*\]?/g
const FENCE = /^[ \t]*(?:(?:>|[-+*]|\d{1,9}[.)])[ \t]*)*(`{3,}|~{3,})(.*)$/
const INDENTED = /^(?: {4}|\t)/
const TOKEN = /^[A-Za-z0-9_.\-]{1,64}$/
// Control, separator and bidi characters never go inside a span.
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u061c\u200e\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069]/g

function parseValue(kind, raw) {
  const [head0, ...params] = String(raw).split(';').map((p) => p.trim())
  const head = head0.toLowerCase()
  const found = {}
  for (const item of params) {
    const i = item.indexOf('=')
    if (i < 0) continue
    const key = item.slice(0, i).trim().toLowerCase()
    const val = item.slice(i + 1).trim()
    if (['check', 'why', 'id'].includes(key) && TOKEN.test(val)) found[key] = val
  }
  if (kind === 'signal') {
    const level = ALIASES[head] || head
    return LEVELS.includes(level) ? { level, reason: null, params: found } : null
  }
  return REASONS.includes(head) ? { level: 'whisper', reason: head, params: found } : null
}

// Inline code: a run of N backticks opens a code span only if a run of exactly N closes it later
// on the line (CommonMark); otherwise the backticks are text.
export function codeSpans(line) {
  const out = []
  let start = 0
  let i = 0
  const n = line.length
  while (i < n) {
    if (line[i] !== '`') { i += 1; continue }
    let j = i
    while (j < n && line[j] === '`') j += 1
    const run = j - i
    let k = j
    let close = -1
    while (k < n) {
      if (line[k] !== '`') { k += 1; continue }
      let e = k
      while (e < n && line[e] === '`') e += 1
      if (e - k === run) { close = k; break }
      k = e
    }
    if (close < 0) { i = j; continue }
    out.push([false, line.slice(start, i)])
    out.push([true, line.slice(i, close + run)])
    i = start = close + run
  }
  out.push([false, line.slice(start)])
  return out
}

// [isCode, piece] for the whole text, with the same code guess the parser uses.
function segments(text) {
  const out = []
  let fence = null
  text.split('\n').forEach((line, n) => {
    if (n) out.push([false, '\n'])
    const m = FENCE.exec(line)
    if (fence === null && m && !(m[1][0] === '`' && m[2].includes('`'))) {
      fence = [m[1][0], m[1].length]
      out.push([true, line])
      return
    }
    if (fence !== null) {
      if (m && m[1][0] === fence[0] && m[1].length >= fence[1] && !m[2].trim()) fence = null
      out.push([true, line])
      return
    }
    if (INDENTED.test(line)) { out.push([true, line]); return }
    for (const piece of codeSpans(line)) out.push(piece)
  })
  return out
}

function hasExact(piece) {
  if (STRICT_CLOSE.test(piece)) return true
  const re = new RegExp(STRICT_OPEN.source, 'gi')
  for (const m of piece.matchAll(re)) if (parseValue(m[1].toLowerCase(), m[2])) return true
  return false
}

// Bring tags hidden behind invisible characters into view (prose only).
function unhide(piece) {
  return piece.replace(BRACKET, (seg) => {
    const cleaned = seg.replace(INVISIBLE, '')
    if (cleaned === seg) return seg
    const re = new RegExp(TAG.source, 'i')
    return re.test(cleaned) ? cleaned : seg
  })
}

// Does this reply hold a tag at all? Without one it is drawn exactly as written.
export function replyHasTags(text) {
  const segs = segments(text)
  let tagged = false
  for (const [code, piece] of segs) {
    if (!code && (hasExact(unhide(piece)) || CUT_TAG.test(piece))) tagged = true
    if (code && completeExactSpan(piece)) tagged = true
  }
  const last = segs[segs.length - 1]
  if (!tagged && last && !last[0] && CUT_END.test(last[1])) tagged = true
  return tagged
}

const CODE_SPAN = new RegExp(
  '\\[' + W + '(signal|whisper)' + W + ':' + W + '([^\\]\\[\\n]+?)' + W + '\\]([^\\[\\]\\n]*?)\\[' + W + '\\\\*\\/' + W + '\\1' + W + '\\]', 'gi')

function completeExactSpan(piece) {
  for (const m of piece.matchAll(CODE_SPAN)) if (parseValue(m[1].toLowerCase(), m[2]) && m[3].trim()) return true
  return false
}

// -- parsing one line of prose -----------------------------------------------------------------
function splitTags(segment) {
  const tokens = []
  let pos = 0
  for (const m of segment.matchAll(TAG)) {
    const g = m.groups
    tokens.push({ kind: 'text', text: segment.slice(pos, m.index) })
    if (g.close) tokens.push({ kind: 'close', tag: g.ckind.toLowerCase() })
    else if (g.okind) tokens.push({ kind: 'open', tag: g.okind.toLowerCase(), value: g.value })
    else if (g.skind) tokens.push({ kind: 'open', tag: g.skind.toLowerCase(), value: '', strong: true })
    else if (g.bkind) {
      // Broken: the keyword goes; a broken closer still closes, a broken opener opens nothing.
      if (g.bclose !== undefined) tokens.push({ kind: 'close', tag: g.bkind.toLowerCase() })
    } else if (g.wkind || g.lkind) tokens.push({ kind: 'weak', tag: (g.wkind || g.lkind).toLowerCase(), raw: m[0] })
    pos = m.index + m[0].length
  }
  tokens.push({ kind: 'text', text: segment.slice(pos) })
  return tokens
}

function parseProseChunk(chunk) {
  const tokens = splitTags(chunk)
  // closerAfter[i]: kinds of closers after i and before the next valid opener, so a lookalike or
  // unknown opener never takes the closer that belongs to a real span after it.
  const valid = tokens.map((t) => t.kind === 'open' && parseValue(t.tag, t.value) !== null)
  const closerAfter = new Array(tokens.length)
  let seen = new Set()
  for (let i = tokens.length - 1; i >= 0; i -= 1) {
    closerAfter[i] = seen
    if (tokens[i].kind === 'close') seen = new Set([...seen, tokens[i].tag])
    else if (valid[i]) seen = new Set()
  }
  tokens.forEach((t, i) => {
    if (t.kind === 'open' && !valid[i] && !closerAfter[i].has(t.tag)) tokens[i] = { kind: 'text', text: '' }
    else if (t.kind === 'weak') tokens[i] = closerAfter[i].has(t.tag) ? { kind: 'open', tag: t.tag, value: '' } : { kind: 'text', text: t.raw }
  })
  const out = []
  let open = null
  let buf = []
  for (const t of tokens) {
    if (t.kind === 'text') (open ? buf : out).push(t.text)
    else if (t.kind === 'open') {
      if (open === null) open = { tag: t.tag, value: t.value } // a nested opener inside a span is dropped
    } else if (t.kind === 'close' && open !== null) {
      const parsed = open.tag === t.tag ? parseValue(open.tag, open.value) : null
      const body = buf.join('')
      if (parsed && body.trim()) {
        out.push({ span: true, tag: open.tag, level: parsed.level, reason: parsed.reason, why: parsed.params.why, check: parsed.params.check, text: body, code: false })
      } else out.push(body)
      open = null
      buf = []
    }
    // a closer with nothing open is removed
  }
  out.push(...buf) // unclosed span: plain text
  return out
}

// Inside code only a complete exact span is read; it keeps its phrase and gets its word, no styling.
function parseCodeChunk(chunk) {
  const out = []
  let pos = 0
  for (const m of chunk.matchAll(CODE_SPAN)) {
    const parsed = parseValue(m[1].toLowerCase(), m[2])
    if (!parsed || !m[3].trim()) continue
    out.push(chunk.slice(pos, m.index))
    out.push({ span: true, tag: m[1].toLowerCase(), level: parsed.level, reason: parsed.reason, why: parsed.params.why, check: parsed.params.check, text: m[3], code: true })
    pos = m.index + m[0].length
  }
  out.push(chunk.slice(pos))
  return out
}

// A keyword cut off at the very end of the reply, or a broken tag, is removed so it never shows.
function stripCut(piece, isLast) {
  let out = piece
  if (isLast) out = out.replace(CUT_END, '')
  return out
}

/** Parse a reply into lines of pieces: strings and span objects. */
export function parse(text) {
  const segs = segments(text)
  const lines = [[]]
  segs.forEach(([code, rawPiece], idx) => {
    if (!code && rawPiece === '\n') { lines.push([]); return }
    const isLast = idx === segs.length - 1
    const cur = lines[lines.length - 1]
    if (code) {
      for (const p of parseCodeChunk(rawPiece)) cur.push(p)
      return
    }
    const piece = stripCut(unhide(rawPiece), isLast)
    for (const p of parseProseChunk(piece)) cur.push(p)
  })
  return lines
}

// -- decisions ---------------------------------------------------------------------------------
export function wordCount(text) {
  return text.split(/\s+/).filter(Boolean).length
}

/**
 * Decide which spans are shown. `checkPassed(check)` says whether a tool call Claude Code
 * reported as successful backs a green. `whisperSeen(phrase)` is true when this phrase was
 * already whispered in an earlier reply of the session. Sets span.show and span.drop.
 */
export function decide(spans, { budget, checkPassed, whisperSeen }) {
  const b = { ...DEFAULT_BUDGET, ...(budget || {}) }
  const gates = spans.filter((s) => s.level in SEVERITY)
  for (const s of spans) {
    if (wordCount(s.text) > b.max_span_words || s.text.length > 8 * b.max_span_words) s.drop = 'too_long'
    else if (s.level === 'go' && !checkPassed(s.check)) s.drop = s.check ? 'check_not_observed' : 'no_check'
  }
  const ranked = gates.filter((s) => !s.drop).sort((a, c) => SEVERITY[a.level] - SEVERITY[c.level])
  for (const s of ranked.slice(b.max_spans)) s.drop = 'over_budget'
  spans.filter((s) => s.level === 'intent').slice(1).forEach((s) => { s.drop = 'over_budget' })
  let whispersLeft = b.max_whispers
  for (const s of spans) {
    if (s.level !== 'whisper' || s.drop) continue
    if (whisperSeen(s.text)) s.drop = 'repeat'
    else if (whispersLeft <= 0) s.drop = 'over_budget'
    else whispersLeft -= 1
  }
  for (const s of spans) s.show = !s.drop
}

// -- rendering plan ----------------------------------------------------------------------------
function clean(text) {
  return text.replace(CONTROL, '')
}

/**
 * Turn decided spans into drawing pieces.
 * opts: { theme, palette, words, noColor }.
 * A piece is a string, or { text, color?, bold?, underline?, italic?, word } for a styled span.
 */
export function plan(lines, opts) {
  const theme = opts.theme === 'light' ? 'light' : 'dark'
  const palette = ['default', 'cvd', 'none'].includes(opts.palette) ? opts.palette : 'default'
  const colors = palette === 'none' || opts.noColor ? null : PALETTES[theme + '/' + palette]
  const wordsMode = opts.words === 'plain_only' ? 'plain_only' : 'always'
  return lines.map((pieces) => {
    const out = []
    let styled = false
    for (const p of pieces) {
      if (typeof p === 'string') { if (p) out.push(p); continue }
      const text = clean(p.text)
      if (!p.show) { out.push(text); continue }
      const word = p.level === 'intent' ? '' : ' (' + WORDS[p.level] + ')'
      if (p.code) { out.push(text + word); continue } // inside code: the word, never markup
      const style = STYLE[p.level]
      const color = colors ? colors[p.level] : null
      if (!color && !Object.keys(style).length) { out.push(text + word); continue }
      // Color is applied: the word may be dropped when the reader asked for words only where
      // color is unavailable. No color: the word is the cue and always stays.
      const shownWord = color && wordsMode === 'plain_only' ? '' : word
      out.push({ text, color, ...style, word: shownWord })
      styled = true
    }
    return { pieces: out, styled }
  })
}

/** Plain text of a plan line: spans as phrase + word, no markup. */
export function plainLine(line) {
  return line.pieces.map((p) => (typeof p === 'string' ? p : p.text + p.word)).join('')
}

/** Remove any exact tag shape that removal of other tags joined back together (prose only). */
export function scrubJoined(text) {
  let out = text
  for (let i = 0; i < 4; i += 1) {
    const next = segments(out).map(([code, piece]) => {
      if (code || piece === '\n') return piece
      return piece.replace(new RegExp(STRICT_CLOSE.source, 'gi'), '').replace(new RegExp(STRICT_OPEN.source, 'gi'), (all, k, v) => (parseValue(k.toLowerCase(), v) ? '' : all))
    }).join('')
    if (next === out) break
    out = next
  }
  return out
}
