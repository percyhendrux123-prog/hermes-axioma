// Logic checks for desktop/plugin.js. Run: node tests/desktop_check.mjs
// Stubs the Hermes SDK and React, then drives the plugin with gateway events.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
let src = readFileSync(join(here, '..', 'desktop', 'plugin.js'), 'utf8')
src = src.replace(/^import[\s\S]*?from '[^']+'\n/gm, '')
src = src.replace('export default', 'const __plugin =')
src += '\nreturn { __plugin, $state, $prefs, $light, onGatewayEvent, targetPose, easePose, sweep, running, createEngine, overlayBox, signal, readProof, THEMES, W, H, VERIFIED_MS }\n'

const atom = v => {
  let value = v
  const subs = new Set()
  return { get: () => value, set: n => { value = n; subs.forEach(f => f(n)) }, listen: f => { subs.add(f); return () => subs.delete(f) } }
}
const requests = []
const composerCalls = []
let themeMode = 'dark'
let hooks = [], cursor = 0
const useRef = value => { const i = cursor++; return hooks[i] ??= { current: value } }
const useState = value => { const i = cursor++; if (!(i in hooks)) hooks[i] = value; return [hooks[i], v => { hooks[i] = typeof v === 'function' ? v(hooks[i]) : v }] }
const host = {
  state: { busy: atom(false), focusedSessionId: atom('sess-1') },
  request: (method, params) => { requests.push([method, params]); return Promise.resolve({ status: 'ok' }) },
  composer: { submit: (id, text) => { composerCalls.push([id, text]); return true } },
  notify: () => {}, notifyError: () => {}
}
const noop = () => null
const api = new Function(
  'host', 'atom', 'useValue', 'THEMES_AREA', 'PALETTE_AREA', 'STATUSBAR_AREAS', 'Button', 'Input', 'Switch',
  'useEffect', 'useRef', 'useState', 'jsx', 'jsxs', 'useTheme', src
)(host, atom, a => a.get(), 'themes', 'palette', { right: 'statusbar.right' }, noop, noop, noop,
  noop, useRef, useState, (type, props) => ({ type, props }), (type, props) => ({ type, props }), () => ({ resolvedMode: themeMode }))

let pass = 0, fail = 0
const check = (name, ok) => { ok ? pass++ : fail++; console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}`) }
const fresh = () => api.$state.set({ busy: false, waiting: false, verifiedAt: 0, failedAt: 0, subs: {}, lastProof: null })
const pose = () => api.targetPose(api.$state.get(), Date.now())
const fire = (type, payload = {}, session_id = 'sess-1') => api.onGatewayEvent({ type, session_id, payload }, false)

// idle
fresh()
let p = pose()
check('idle: staff dim, serpents dim, wings closed, no tone', p.staffInk === 0.55 && p.snakeInk[0] === 0.42 && p.snakeInk[1] === 0.42 && p.open === 0 && p.tone === null && p.wingTone === null)
check('idle: slow motion, not frozen', p.wingMotion === 0.25 && p.snakeMotion[0] === 0.12)

// main turn busy, no workers
api.$state.set({ ...api.$state.get(), busy: true })
p = pose()
check('busy: staff bright, serpents still dim', p.staffInk === 1 && p.snakeInk[0] === 0.42 && p.snakeMotion[0] === 0.35)

// one worker
fresh()
fire('subagent.start', { subagent_id: 'a', goal: 'Draft', status: 'running' })
p = pose()
check('one worker: first serpent lit and moving, second dim', p.snakeInk[0] === 1 && p.snakeMotion[0] === 1 && p.snakeInk[1] === 0.42 && p.snakeMotion[1] < 1)
check('one worker: staff bright (active)', p.staffInk === 1)
check('one worker: steerable with session id', api.$state.get().subs.a.steerable === true && api.$state.get().subs.a.sessionId === 'sess-1')

// two workers
fire('subagent.start', { subagent_id: 'b', goal: 'Check', status: 'running' })
p = pose()
check('two workers: both serpents lit and moving', p.snakeInk[0] === 1 && p.snakeInk[1] === 1 && p.snakeMotion[1] === 1)
fire('subagent.tool', { subagent_id: 'a', tool_name: 'terminal' })
check('worker tool event counts and names the tool', api.$state.get().subs.a.tools === 1 && api.$state.get().subs.a.lastTool === 'terminal')

// waiting on the human
fire('approval.request')
p = pose()
check('waiting: everything still and amber', p.tone === 'caution' && p.wingMotion === 0 && p.snakeMotion[0] === 0 && p.snakeMotion[1] === 0)
fire('approval.respond')
p = pose()
check('answered: amber clears, motion returns', p.tone === null && p.snakeMotion[0] === 1)
for (const t of ['clarify.request', 'sudo.request', 'secret.request']) { fire(t); check(`${t} sets waiting`, api.$state.get().waiting === true); fire('turn.settled') }
check('turn.settled clears waiting', api.$state.get().waiting === false)

// worker finishes
fire('subagent.complete', { subagent_id: 'a', status: 'completed' })
check('one finished: one still running', api.running(api.$state.get()).length === 1)
fire('subagent.progress', { subagent_id: 'b', status: 'failed' })
check('failed status ends the worker and keeps the word', api.running(api.$state.get()).length === 0 && api.$state.get().subs.b.status === 'failed')
const st = api.$state.get()
api.$state.set({ ...st, subs: { ...st.subs, a: { ...st.subs.a, finishedAt: Date.now() - 9000 } } })
api.sweep()
check('sweep removes workers finished 8s ago, keeps recent', !api.$state.get().subs.a && !!api.$state.get().subs.b)

// proof pass
fresh()
fire('tool.complete', { name: 'standing_proof', result: { passed: true } })
p = pose()
check('proof pass: wings open green', p.open === 1 && p.wingTone === 'go' && p.wingInk === 1)
check('proof pass: wings close after the hold', api.targetPose(api.$state.get(), Date.now() + api.VERIFIED_MS + 1).open === 0)

// proof fail
fresh()
fire('tool.complete', { name: 'mcp__standing__standing_proof', result: JSON.stringify({ passed: false }) })
p = pose()
check('proof fail: wings red and stay closed', p.open === 0 && p.wingTone === 'stop')

// things that must NOT open the wings
fresh()
fire('tool.complete', { name: 'terminal', result: { passed: true } })
fire('tool.complete', { name: 'standing_proof', result: 'not json' })
fire('tool.complete', { name: 'standing_proof', result: { passed: 'yes' } })
fire('tool.complete', { name: 'standing_proof' })
p = pose()
check('wings stay shut for other tools and malformed proofs', p.open === 0 && p.wingTone === null && api.$state.get().lastProof === null)
check('proof read from result_text', api.readProof({ result_text: '{"passed":true}' })?.passed === true)

// junk events
let threw = false
try { api.onGatewayEvent(null); api.onGatewayEvent({}); api.onGatewayEvent({ type: 5 }); api.onGatewayEvent({ type: 'subagent.start' }) } catch { threw = true }
check('junk events do not throw', !threw)

// easing
const eased = api.easePose({ ...pose(), open: 0 }, { ...pose(), open: 1 }, 0.12)
check('easing moves part of the way', Math.abs(eased.open - 0.12) < 1e-9)

// drawing engine
const engine = api.createEngine()
const count = (o, f) => { let n = 0; for (let i = 0; i < api.W * api.H; i++) if (engine.owner[i] === o && engine.field[i] > 0.5) n++; return f ? n : n }
engine.frame(3.3, { wingMotion: 0.7, open: 0, snakeMotion: [1, 1] })
const closed = Array.from(engine.field)
check('engine: wings, both serpents and staff all drawn', count(0) > 100 && count(1) > 50 && count(2) > 50 && count(3) > 20)
check('engine: every value is ink 0..1', closed.every(v => v >= 0 && v <= 1 && Number.isFinite(v)))
engine.frame(3.3, { wingMotion: 0.7, open: 1, snakeMotion: [1, 1] })
let diff = 0; for (let i = 0; i < 24 * api.W; i++) if (Math.abs(engine.field[i] - closed[i]) > 0.3) diff++
check('engine: open wings differ from closed wings', diff > 40)
engine.frame(0, { wingMotion: 0, open: 0, snakeMotion: [0, 0] })
const still = Array.from(engine.field)
engine.frame(0, { wingMotion: 0, open: 0, snakeMotion: [0, 0] })
check('engine: same input gives the same frame', still.every((v, i) => v === engine.field[i]))

// signal colours follow the theme
api.$light.set(false); const night = api.signal('go')
api.$light.set(true); const day = api.signal('go')
check('signal colours switch for a light theme', night === '#30d158' && day === '#248a3d')
api.$light.set(false)

// register: parts are separately removable
const regs = [], disposed = [], contributions = new Map(), cleanups = [], intervals = []
const storage = new Map()
const ctx = {
  storage: { get: (k, d) => (storage.has(k) ? storage.get(k) : d), set: (k, v) => storage.set(k, v) },
  register: r => { regs.push(r.id); contributions.set(r.id, r); let live = true; return () => { if (!live) return; live = false; disposed.push(r.id); regs.splice(regs.indexOf(r.id), 1); if (contributions.get(r.id) === r) contributions.delete(r.id) } },
  registerMany: list => list.forEach(r => regs.push(r.id)),
  registerSettingsPage: r => { ctx.settings = r },
  onDispose: fn => cleanups.push(fn), onEvent: (pat, fn) => { ctx.handler = fn }, setInterval: (fn, ms) => { intervals.push([fn, ms]); return noop }, setTimeout: fn => fn(), addEventListener: () => {}
}
const canvasStub = { setAttribute() {}, style: {}, getContext: () => ({ fillRect() {}, clearRect() {} }), remove() {} }
globalThis.document = { createElement: () => canvasStub, body: { appendChild() {} }, hidden: false }
globalThis.window = { innerWidth: 1200, innerHeight: 800, devicePixelRatio: 2 }
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '', color: '#c9cacd' })
api.__plugin.register(ctx)
check('plugin id and name', api.__plugin.id === 'hermes-axioma' && api.__plugin.name === 'Axiōma Desktop')
check('register: pane, readout, two themes, three commands, settings', ['pane', 'chip', 'theme-axioma', 'theme-axioma-day', 'toggle', 'pane-toggle', 'demo'].every(id => regs.includes(id)) && !!ctx.settings)
const save = ctx.settings.render().props.save
save({ ...api.$prefs.get(), pane: false })
check('pane switch removes only the pane', disposed.includes('pane') && regs.includes('chip') && storage.get('prefs').pane === false)
save({ ...api.$prefs.get(), chip: false })
check('readout switch removes the readout', disposed.includes('chip'))
save({ ...api.$prefs.get(), pane: true, chip: true })
check('switching back on re-registers both', regs.includes('pane') && regs.includes('chip'))
fresh()
ctx.handler({ type: 'approval.request', payload: {} })
check('live gateway events reach the state', api.$state.get().waiting === true)
check('themes carry the same names as the terminal skins', api.THEMES.map(t => t.name).join() === 'axioma,axioma-day')
check('no gateway call is made without a click', requests.length === 0)

// Inline directive: exercise the registered component, not a separately copied sanitizer.
const directive = () => contributions.get('inline')
check('inline: default-on named directive in the documented area', directive()?.area === 'transcript.directives' && directive()?.data?.name === 'axioma')
save({ ...api.$prefs.get(), inline: false })
check('inline: switch unregisters so source stays text', !directive())
save({ ...api.$prefs.get(), inline: true })
check('inline: switching back on registers', !!directive())
if (directive()) {
  const attrs = { light: 'caution', signal: 'Check the audience.', question: 'Proceed?', affects: 'The team' }
  const source = a => `::axioma{${Object.entries(a).map(([k, v]) => `${k}="${v}"`).join(' ')}}`
  const props = a => ({ attrs: a, source: source(a), sessionId: 'owner-session', streaming: false })
  const render = p => { cursor = 0; return directive().data.render(p) }
  const nodes = tree => !tree || typeof tree !== 'object' ? [] : [tree, ...[tree.props?.children].flat(Infinity).flatMap(nodes)]
  const text = tree => typeof tree === 'string' ? tree : tree && typeof tree === 'object' ? [tree.props?.children].flat(Infinity).map(text).join(' ') : ''
  const buttons = tree => nodes(tree).filter(n => n.props?.onClick)
  hooks = []
  let tree = render(props(attrs))
  check('inline: signal, affects, question and human decision notice', ['Check the audience.', 'The team', 'Proceed?', 'Axiōma advises, the person decides.'].every(t => text(tree).includes(t)))
  check('inline: two named buttons', buttons(tree).map(n => n.props.children).join() === 'Hold,Go ahead')
  tree = render({ ...props(attrs), streaming: true })
  buttons(tree)[0].props.onClick()
  check('inline: streaming disables both and ignores stale/manual clicks', buttons(tree).every(n => n.props.disabled) && composerCalls.length === 0)
  tree = render(props(attrs))
  const oldButtons = buttons(tree)
  await oldButtons[1].props.onClick()
  await oldButtons[0].props.onClick()
  tree = render(props(attrs))
  check('inline: submits exact reply to owning session once', JSON.stringify(composerCalls) === JSON.stringify([['owner-session', 'Go ahead.']]))
  check('inline: both stay disabled after a click', buttons(tree).every(n => n.props.disabled))
  hooks = []
  tree = render(props({ ...attrs, light: 'stop', green: 'Run the test.' }))
  check('inline: stop includes what turns it green', text(tree).includes('What turns it green:') && text(tree).includes('Run the test.'))
  check('inline: stop uses night palette', nodes(tree).some(n => n.props.style?.color === '#ff453a'))
  themeMode = 'light'; hooks = []
  tree = render(props({ ...attrs, light: 'stop' }))
  check('inline: day palette independent of background switch', nodes(tree).some(n => n.props.style?.color === '#d70015'))
  themeMode = 'dark'
  for (const light of ['caution', 'go', 'whisper', 'unknown']) {
    hooks = []; tree = render(props({ ...attrs, light }))
    check(`inline: ${light} renders without throwing and never grants permission`, text(tree).includes('Axiōma advises, the person decides.') && (light !== 'unknown' || text(tree).includes('ADVICE')))
  }
  hooks = []
  tree = render(props({ ...attrs, signal: '<img src=x onerror=alert(1)>**text**\u202e\x00' + 'x'.repeat(600), onclick: 'IGNORE ME' }))
  check('inline: HTML/markdown are text, controls removed, unknown keys ignored', !nodes(tree).some(n => n.type === 'img' || n.props.dangerouslySetInnerHTML) && !text(tree).includes('\u202e') && !text(tree).includes('\x00') && !text(tree).includes('IGNORE ME'))
  check('inline: overlong signal capped', !text(tree).includes('x'.repeat(401)))
  for (const p of [props({ light: 'stop' }), { attrs: null, source: '<b>bad</b>' }, { ...props(attrs), source: '::axioma{signal="x" garbage question="?"}' }, { ...props(attrs), attrs: { ...attrs, question: {} } }]) {
    hooks = []; tree = render(p)
    check('inline: malformed/missing attrs render source plainly without actions', text(tree).includes(p.source) && buttons(tree).length === 0)
  }
  hooks = []; tree = render({ ...props(attrs), sessionId: null })
  check('inline: unknown owner fails closed instead of targeting active chat', buttons(tree).every(n => n.props.disabled))
  const submit = host.composer.submit
  delete host.composer.submit
  host.composer.insertText = async (id, reply) => { composerCalls.push([id, reply]); return true }
  hooks = []; tree = render(props(attrs)); await buttons(tree)[0].props.onClick(); tree = render(props(attrs))
  check('inline: older insert-only host targets owner and explains draft', composerCalls.at(-1).join() === 'owner-session,Hold.' && text(tree).includes('Inserted'))
  host.composer.submit = submit
}

// overlay box: stays clear of the plugin's own pane
const ob = api.overlayBox
check('overlay: no pane, whole window', JSON.stringify(ob(1920, 1080, null)) === JSON.stringify({ left: 0, width: 1920, height: 1080 }))
check('overlay: hidden pane (zero rect), whole window', ob(1920, 1080, { left: 0, width: 0, height: 0 }).width === 1920)
check('overlay: pane on the right, stops at its left edge', JSON.stringify(ob(1920, 1080, { left: 1340, width: 340, height: 900 })) === JSON.stringify({ left: 0, width: 1340, height: 1080 }))
check('overlay: pane on the left, starts at its right edge', JSON.stringify(ob(1920, 1080, { left: 0, width: 320, height: 900 })) === JSON.stringify({ left: 320, width: 1600, height: 1080 }))
check('overlay: too little room left, whole window', ob(400, 800, { left: 100, width: 300, height: 700 }).width === 400)

console.log(`\n${pass} passed, ${fail} failed`)
process.exit(fail ? 1 : 0)
