// Which tool calls get an Axioma card: send, spend, spin, scrub.
//
// Port of axioma/policy.py for Claude Code's tool names. Explicit matching, not semantic shell
// analysis and not a sandbox. SCRUB is BEST-EFFORT parsing of Bash: it reads the common shapes of
// rm / mv / unlink / rmdir and flags what it cannot prove contained. A remove or move whose shape
// it cannot read says so ("could not parse") and is capped at CAUTION, never GO. It does not read
// bash -c, eval, ssh, docker exec, scripts, aliases or encoded commands.

const REMOVERS = ['rm', 'mv', 'unlink', 'rmdir']
const SHELL_TOOLS = ['Bash']
const CATEGORIES = ['send', 'spend', 'spin', 'scrub']

// Always SCRUB: deletion whose targets are computed elsewhere (not provable from the command line).
const ALWAYS_SCRUB = /\bfind\b[^\n;&|]*\s-(?:delete|exec(?:dir)?\s+(?:\S*\/)?(?:rm|unlink|rmdir)\b)|\brsync\b[^\n;&|]*\s--(?:del\b|delete|remove-source-files)|\bgit\s+(?:-\S+\s+(?:\S+\s+)?)*clean\b/i

// Rules. `tool` is a glob matched case-insensitively against Claude Code's tool name (an MCP tool
// is mcp__server__tool). `command` is a regex over the Bash command.
export const DEFAULT_RULES = [
  { id: 'email-send', category: 'send', tool: '*send_email*' },
  { id: 'message-send', category: 'send', tool: '*send_message*' },
  { id: 'post', category: 'send', tool: '*create_post*' },
  { id: 'post-message', category: 'send', tool: '*post_message*' },
  { id: 'tweet', category: 'send', tool: '*post_tweet*' },
  { id: 'publish', category: 'send', tool: '*publish*' },
  { id: 'payment', category: 'spend', tool: '*create_payment*' },
  { id: 'payment-confirm', category: 'spend', tool: '*confirm_payment*' },
  { id: 'payment-capture', category: 'spend', tool: '*capture_payment*' },
  { id: 'checkout', category: 'spend', tool: '*create_checkout*' },
  { id: 'purchase', category: 'spend', tool: '*create_purchase*' },
  { id: 'charge', category: 'spend', tool: '*create_charge*' },
  { id: 'refund', category: 'spend', tool: '*create_refund*' },
  { id: 'cron-tool', category: 'spin', tool: 'CronCreate' },
  { id: 'cron-create', category: 'spin', tool: '*cron*create*' },
  { id: 'jobs', category: 'spin', tool: '*job*create*' },
  {
    id: 'deploy', category: 'spin', tool: 'Bash',
    command: /\b(?:netlify|vercel|fly(?:ctl)?|firebase|wrangler|railway)\s+(?:[^\n;&|]*\s)?(?:deploy|publish)\b|\b(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:deploy|publish)\b|\bkubectl\s+(?:apply|create|rollout)\b|\bterraform\s+apply\b|\bdocker\s+(?:push|stack\s+deploy)\b/i,
  },
  { id: 'push', category: 'send', tool: 'Bash', command: /\bgit\s+(?:-[^\n;&|]*\s)?push\b|\bgh\s+(?:pr\s+(?:create|merge)|release\s+create)\b/i },
  { id: 'terminal-jobs', category: 'spin', tool: 'Bash', command: /\bcrontab\b/i },
]

function globToRegex(glob) {
  return new RegExp('^' + glob.replace(/[.+^${}()|\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.') + '$', 'i')
}

// -- a small quote-aware shell lexer ------------------------------------------------------------
const SEPARATORS = ';&|()\n'
const OPAQUE = ';&|#()'
const PREFIXES = new Set(['sudo', 'doas', 'time', 'nohup', 'exec', 'command', 'builtin', 'env', 'nice', 'ionice', 'timeout', 'stdbuf', 'xargs', 'then', 'do', 'else', 'elif', 'if', 'while', 'until', '!', '{'])
const ARG_OPTS = { sudo: 'ugCDhprtUT', doas: 'uC', env: 'uCS', nice: 'n', ionice: 'cnp', timeout: 'sk', stdbuf: 'ioe', xargs: 'IdEeLnPs' }

function newWord() {
  return { text: '', opaque: false, expands: false, bare: false, glob: false }
}

/** Segments of words. Throws on an unterminated quote. */
export function lex(command) {
  const segments = []
  let words = []
  let word = null
  let i = 0
  const n = command.length
  while (i < n) {
    const c = command[i]
    if (c === ' ' || c === '\t' || SEPARATORS.includes(c)) {
      if (word !== null) { words.push(word); word = null }
      if (SEPARATORS.includes(c) && words.length) { segments.push(words); words = [] }
    } else if (c === '#' && word === null) {
      while (i < n && command[i] !== '\n') i += 1
      continue
    } else {
      word = word || newWord()
      if (c === '\\') {
        i += 1
        if (i < n) { word.opaque ||= OPAQUE.includes(command[i]); word.text += command[i] }
      } else if (c === "'") {
        const close = command.indexOf("'", i + 1)
        if (close < 0) throw new Error('unterminated quote')
        const body = command.slice(i + 1, close)
        word.opaque ||= [...OPAQUE].some((x) => body.includes(x))
        word.text += body
        i = close
      } else if (c === '"') {
        i += 1
        while (i < n && command[i] !== '"') {
          if (command[i] === '\\' && i + 1 < n && '$`"\\\n'.includes(command[i + 1])) i += 1
          else if (command[i] === '$' || command[i] === '`') word.expands = true
          word.opaque ||= OPAQUE.includes(command[i])
          word.text += command[i]
          i += 1
        }
        if (i >= n) throw new Error('unterminated quote')
      } else {
        if (c === '$' || c === '`') { word.expands = true; word.bare = true }
        if ('*?[{'.includes(c)) word.glob = true
        word.text += c
      }
    }
    i += 1
  }
  if (word !== null) words.push(word)
  if (words.length) segments.push(words)
  return segments
}

function baseName(p) {
  const parts = p.split('/')
  return parts[parts.length - 1]
}

/** Index of the command word of a segment, skipping assignments, prefixes and their options. */
export function commandIndex(words) {
  let i = 0
  let prefix = null
  while (i < words.length) {
    const text = words[i].text
    if (prefix === null && /^[A-Za-z_][A-Za-z0-9_]*=/.test(text)) { i += 1; continue }
    if (PREFIXES.has(text) && !words[i].expands) {
      prefix = text
      i += 1
      if (prefix === 'timeout') {
        while (i < words.length && words[i].text.startsWith('-')) i += 1
        i += 1
      }
      continue
    }
    if (prefix && text.startsWith('-') && text.length > 1) {
      const letter = text.startsWith('--') ? '' : text[1]
      i += letter && (ARG_OPTS[prefix] || '').includes(letter) && text.length === 2 ? 2 : 1
      continue
    }
    if (prefix === 'env' && text.includes('=')) { i += 1; continue }
    return i
  }
  return null
}

function misread(word) {
  return word.opaque && word.text && ([...word.text].every((c) => ';&|()'.includes(c)) || word.text.startsWith('#'))
}

// The command name comes from an expansion or a glob/brace pattern: what runs is not visible here.
function namedByExpansion(words) {
  const at = commandIndex(words)
  if (at === null) return false
  const w = words[at]
  if (w.glob && !['[', '[[', '{', '}', ']]'].includes(w.text) && /[^*?]/.test(baseName(w.text))) {
    if (/\{[^{}]*,[^{}]*\}/.test(w.text) || /[*?[]/.test(baseName(w.text))) return true
  }
  if (!w.expands) return false
  return w.bare || /[$`]/.test(baseName(w.text))
}

/** True when SCRUB could not parse a remove or move (best effort; plain commands are untouched). */
export function unparsed(command) {
  if (!/['"\\$`*?[{]/.test(command)) return false
  let segments
  try { segments = lex(command) } catch { return /\b(?:rm|mv|unlink|rmdir)\b/i.test(command.replace(/['"\\]/g, '')) }
  for (const words of segments) {
    const at = commandIndex(words)
    if (at === null) continue
    if (namedByExpansion(words)) return true
    const name = baseName(words[at].text).toLowerCase()
    if (REMOVERS.includes(name) && words.slice(at + 1).some(misread)) return true
  }
  return false
}

function isInside(path, roots) {
  return roots.some((r) => path === r || path.startsWith(r.endsWith('/') ? r : r + '/'))
}

function normalizePath(p) {
  const abs = p.startsWith('/')
  const out = []
  for (const part of p.split('/')) {
    if (!part || part === '.') continue
    if (part === '..') out.pop()
    else out.push(part)
  }
  return (abs ? '/' : '') + out.join('/')
}

/**
 * Does the command remove or move something it cannot prove stays inside `roots`?
 * With no roots every remove or move is flagged. `cwd` lets a relative operand be checked.
 * Symlinks are not resolved here (no file access): see Known gaps.
 */
export function scrubs(command, { roots = [], cwd = null } = {}) {
  const raw = command.replace(/\\\r?\n/g, '')
  const unquoted = raw.replace(/['"\\]/g, '')
  if (ALWAYS_SCRUB.test(unquoted)) return true
  let segments = []
  let lexFailed = false
  try { segments = lex(raw) } catch { lexFailed = true }
  if (lexFailed) return /\b(?:rm|mv|unlink|rmdir)\b/i.test(unquoted) || /(?:^|[;&|(\n]|\$\()\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*[$`]/.test(raw)
  if (segments.some(namedByExpansion)) return true
  const all = segments.flat()
  let seenCommand = false
  for (const words of segments) {
    const at = commandIndex(words)
    if (at === null) continue
    const name = baseName(words[at].text).toLowerCase()
    if (!REMOVERS.includes(name)) continue
    seenCommand = true
    // xargs appends targets from stdin: never provable from the command line.
    if (words.slice(0, at).some((w) => w.text === 'xargs')) return true
    const rest = words.slice(at + 1)
    const operands = []
    for (let j = 0; j < rest.length; j += 1) {
      const t = rest[j].text
      if (t === '--') { for (const x of rest.slice(j + 1)) operands.push(x.text); break }
      if (name === 'rm' && t.startsWith('--') && t.length > 2 && '--recursive'.startsWith(t)) return true
      if (name === 'rm' && t.startsWith('-') && !t.startsWith('--') && /r/i.test(t.slice(1))) return true
      if (name === 'rmdir' && (t === '--parents' || (t.startsWith('-') && !t.startsWith('--') && t.slice(1).includes('p')))) return true
      const opt = t.split('=')[0]
      if (name === 'mv' && t.startsWith('--') && opt.length > 2 && '--target-directory'.startsWith(opt)) {
        if (t.includes('=')) operands.push(t.split('=').slice(1).join('='))
        else if (j + 1 < rest.length) { operands.push(rest[j + 1].text); j += 1 }
        continue
      }
      if (name === 'mv' && t.startsWith('-') && !t.startsWith('--') && t.slice(1).includes('t')) {
        const attached = t.slice(t.indexOf('t', 1) + 1)
        if (attached) operands.push(attached)
        else if (j + 1 < rest.length) { operands.push(rest[j + 1].text); j += 1 }
        continue
      }
      if (!t.startsWith('-')) operands.push(t)
    }
    if (!roots.length) return true // workspace unknown is not evidence of containment
    if (!operands.length) return true // targets come from elsewhere
    if (all.some((w) => ['cd', 'pushd', 'popd'].includes(baseName(w.text).toLowerCase()))) return true
    for (const operand of operands) {
      if (/[$*?~`{}[\]]/.test(operand)) return true
      if (!operand.startsWith('/') && !cwd) return true
      const full = normalizePath(operand.startsWith('/') ? operand : cwd + '/' + operand)
      if (!isInside(full, roots)) return true
    }
  }
  if (!seenCommand && /[$`]/.test(raw)) return true
  return false
}

/**
 * Classify one call. args are the tool's own arguments (e.command for Bash).
 * Returns { categories: ['send', ...], unparsed: boolean }. Categories are in a fixed order.
 */
export function classify(tool, args, { roots = [], cwd = null, scrubEnabled = true } = {}) {
  const found = new Set()
  const command = typeof args?.command === 'string' ? args.command.replace(/\\\r?\n/g, '') : ''
  // A PowerShell command is checked against the same send/spin command rules; SCRUB reads Bash only.
  const ruleTool = tool === 'PowerShell' ? 'Bash' : tool
  for (const rule of DEFAULT_RULES) {
    if (!globToRegex(rule.tool).test(ruleTool)) continue
    if (rule.command && !rule.command.test(command)) continue
    found.add(rule.category)
  }
  let cantParse = false
  if (scrubEnabled && SHELL_TOOLS.includes(tool) && command) {
    cantParse = unparsed(command)
    if (scrubs(command, { roots, cwd }) || cantParse) found.add('scrub')
  }
  return { categories: CATEGORIES.filter((c) => found.has(c)), unparsed: cantParse && found.has('scrub') }
}

export { CATEGORIES }
