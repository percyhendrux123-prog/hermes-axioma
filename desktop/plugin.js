/**
 * Axiōma Desktop: the Desktop half of the Axiōma plugin.
 * https://github.com/percyhendrux123-prog/hermes-axioma
 *
 * Three parts, each of which can be switched off on its own in
 * Settings → Plugins → Axiōma Desktop: the living caduceus behind the window,
 * the side pane, and the status-bar readout. The two themes are only listed in
 * the theme picker; nothing selects them for you.
 *
 * One caduceus, drawn dot by dot in code (no image, no video), that shows what
 * the agent is doing:
 *   staff    the main agent. It brightens while a turn runs.
 *   serpents one per running worker (subagent). They move while workers work.
 *   amber    everything holds still and turns amber while Hermes waits on you.
 *   wings    they open only when a Standing proof check passes. A failed
 *            check turns them red. Without Standing they stay at rest.
 *
 * The side pane lists the same state in words and lets you change course:
 * steer or stop a worker, steer or stop the main turn. Each control calls the
 * gateway method Hermes itself uses (subagent.steer, subagent.interrupt,
 * session.steer, session.interrupt).
 *
 * The plugin owns one overlay canvas (data-caduceus). It reads gateway events
 * and theme colours. It reads nothing else from the app and changes nothing in
 * the app's own markup.
 */

import {
  host, atom, useValue, THEMES_AREA, PALETTE_AREA, STATUSBAR_AREAS, Button, Input, Switch
} from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'hermes-axioma'

// ---------------------------------------------------------------- the drawing
// A field of 88 x 72 dots. The wings are hand-made art; the serpents are a
// helix around the staff, computed every frame.
const W = 88, H = 72, CX = 43.5, SOURCE_W = 68, WING_BOTTOM = 23
const WING_ART = [
  '⠀⣠⣤⣤⣄⣀⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣀⣠⣤⣤⣄⠀',
  '⠀⢹⣛⡿⢿⣿⣿⣿⣿⣶⣤⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣤⣶⣿⣿⣿⣿⡿⢿⣛⡏⠀',
  '⠀⠀⠿⢿⣿⣾⣭⣿⣿⣿⣿⣿⣷⣦⡀⠀⢿⡿⠀⢀⣴⣾⣿⣿⣿⣿⣿⣭⣷⣿⡿⠿⠀⠀',
  '⠀⠀⠀⠘⢷⣶⣿⣽⣿⣿⣿⣿⣿⣿⣿⣦⢸⡇⣴⣿⣿⣿⣿⣿⣿⣿⣿⣯⣿⣶⡾⠃⠀⠀⠀',
  '⠀⠀⠀⠀⠀⠀⠲⢶⡶⠿⣿⣿⣿⣿⣿⣿⢻⡟⣿⣿⣿⣿⣿⣿⠿⢶⡶⠖⠀⠀⠀⠀⠀⠀',
  '⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠛⠋⠚⠿⠛⠁⢸⡇⠈⠛⠿⠓⠙⠛⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀'
]
const BIT = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]]
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map(v => (v + 0.5) / 16)
const TAU = Math.PI * 2
const KY = [27, 40, 53, 64, 69.5], KP = [0, 1, 2, 3, 3.5], KR = [10, 9, 7.5, 5.5, 0.6]
const SNAKES = [
  { side: -1, wave: 4.3, lambda: 17, phase: 0.0, breath: 6.1, bphase: 0.0, glint: 8.3, gphase: 0.0 },
  { side: 1, wave: 5.2, lambda: 19, phase: 2.1, breath: 7.3, bphase: 1.7, glint: 9.7, gphase: 0.46 }
]
// Who owns a dot: 0 wings, 1 left serpent, 2 right serpent, 3 staff, 4 glint.
const WINGS = 0, STAFF = 3, GLINT = 4

const clamp01 = x => (x < 0 ? 0 : x > 1 ? 1 : x)
const smooth = (a, b, x) => { const u = clamp01((x - a) / (b - a)); return u * u * (3 - 2 * u) }
function knot(arr, y) {
  if (y <= KY[0]) return arr[0]
  for (let i = 1; i < KY.length; i++) {
    if (y <= KY[i]) {
      let u = (y - KY[i - 1]) / (KY[i] - KY[i - 1])
      u = u * u * (3 - 2 * u)
      return arr[i - 1] + (arr[i] - arr[i - 1]) * u
    }
  }
  return arr[arr.length - 1]
}

function parseArt() {
  const g = new Float32Array(SOURCE_W * H)
  WING_ART.forEach((row, r) => {
    Array.from(row).forEach((ch, c) => {
      const v = ch.codePointAt(0) - 0x2800
      if (v <= 0 || v > 255 || c >= SOURCE_W / 2) return
      for (let dy = 0; dy < 4; dy++) for (let dx = 0; dx < 2; dx++) if (v & BIT[dy][dx]) g[(r * 4 + dy) * SOURCE_W + c * 2 + dx] = 1
    })
  })
  return g
}

/** One engine per canvas. frame(t, pose) fills `field` (ink 0..1) and `owner`. */
function createEngine() {
  const art = parseArt()
  const field = new Float32Array(W * H)
  const owner = new Uint8Array(W * H)

  const px = (x, y) => (x < 0 || y < 0 || x >= SOURCE_W || y > WING_BOTTOM ? 0 : art[y * SOURCE_W + x])
  function artAt(x, y) {
    const x0 = Math.floor(x), y0 = Math.floor(y), fx = x - x0, fy = y - y0
    return (px(x0, y0) * (1 - fx) + px(x0 + 1, y0) * fx) * (1 - fy) + (px(x0, y0 + 1) * (1 - fx) + px(x0 + 1, y0 + 1) * fx) * fy
  }

  function wings(t, amt, open) {
    for (let y = 0; y <= WING_BOTTOM; y++) {
      for (let x = 0; x < W; x++) {
        const side = x < CX ? -1 : 1
        const u = Math.min(1, Math.abs(x - CX) / 44)
        const lag = side < 0 ? 0 : 0.55
        const k = side < 0 ? 1.25 : 1.4
        const breath = amt * 2.1 * Math.pow(u, 1.5) * Math.sin(TAU * t / 7.4 - lag - k * u)
        const riffle = amt * 0.35 * u * Math.sin(TAU * t / 2.9 + y * 0.45 + side * 0.9)
        // Closed wings hang a little; open wings lift toward the tips.
        const spread = (open * 2.4 - (1 - open) * 3.4) * Math.pow(u, 1.3)
        let sx = 33.5 + (x - CX) / 1.29
        if (Math.abs(x - CX) <= 1) sx = 33.5 + x - CX
        const i = y * W + x
        field[i] = artAt(sx, y + breath + riffle + spread)
        owner[i] = WINGS
      }
    }
  }

  function strandX(s, y, t, amt) {
    const r = knot(KR, y) * (1 + amt * 0.04 * Math.sin(TAU * t / s.breath + s.bphase))
    const env = 0.25 + 0.75 * smooth(27, 69, y)
    const wig = amt * 1.15 * env * Math.sin(TAU * y / s.lambda - TAU * t / s.wave + s.phase)
    return CX + s.side * r * Math.cos(Math.PI * knot(KP, y)) + wig
  }

  function snakes(t, amts) {
    for (let i = (WING_BOTTOM + 1) * W; i < W * H; i++) { field[i] = 0; owner[i] = WINGS }
    const glintY = SNAKES.map((s, k) => {
      const g = ((t / s.glint + s.gphase) % 1 + 1) % 1
      return amts[k] > 0.5 && g < 0.45 ? 69 - (g / 0.45) * 44 : -99
    })
    for (let y = 24; y < H; y++) {
      const layers = []
      for (let k = 0; k < 2; k++) {
        if (y < 27 || y > 69.5) continue
        const s = SNAKES[k]
        const xs = strandX(s, y, t, amts[k])
        const slope = strandX(s, y + 0.5, t, amts[k]) - strandX(s, y - 0.5, t, amts[k])
        layers.push({ xs, norm: Math.sqrt(1 + slope * slope), z: Math.sin(Math.PI * knot(KP, y)) * -s.side, hw: 2.45 - 1.25 * smooth(27, 69, y), k })
      }
      layers.sort((a, b) => a.z - b.z)
      for (let x = 0; x < W; x++) {
        let v = 0, own = WINGS, staffDone = false
        const staff = (x === CX - 0.5 || x === CX + 0.5) && y <= 70
        // Back to front: the serpent behind, the staff, the serpent in front.
        for (let o = 0; o <= layers.length; o++) {
          const L = layers[o]
          if (staff && !staffDone && (!L || L.z > 0)) { v = 1; own = STAFF; staffDone = true }
          if (!L) break
          const d = Math.abs(x - L.xs) / L.norm
          if (d < L.hw) {
            v = clamp01(L.hw - d + 0.35) * (0.8 + 0.2 * smooth(-0.35, 0.35, L.z)) * (1 - 0.12 * (d / L.hw) * (d / L.hw))
            own = Math.abs(y - glintY[L.k]) < 2.6 && L.z > -0.2 ? GLINT : L.k + 1
          } else if (L.z > 0 && d < L.hw + 0.75) {
            v = 0 // the gap where one body passes over another
          }
        }
        const i = y * W + x
        field[i] = v
        owner[i] = own
      }
    }
    // Heads, just under the wings, facing each other across the staff.
    for (let h = 0; h < 2; h++) {
      const S = SNAKES[h]
      const hx = strandX(S, 27, t, amts[h]) - S.side * 0.6
      const hy = 26 + amts[h] * 0.35 * Math.sin(TAU * t / S.breath + S.bphase + 1.2)
      for (let yy = 23; yy <= 29; yy++) {
        for (let xx = Math.floor(hx - 6); xx <= Math.ceil(hx + 6); xx++) {
          if (xx < 0 || xx >= W) continue
          const ax = (xx - hx) * -S.side
          const rx = ax > 0 ? 4.1 : 3.4
          const ry = ax > 0 ? 1.9 - 0.25 * (ax / 4.1) : 2.2
          const e = (ax / rx) * (ax / rx) + ((yy - hy) / ry) * ((yy - hy) / ry)
          const i = yy * W + xx
          const onStaff = xx === CX - 0.5 || xx === CX + 0.5
          if (e < 1) { field[i] = 1; owner[i] = h + 1 }
          else if (e < 1.5 && field[i] > 0 && !onStaff) field[i] = 0
        }
      }
      const ex = Math.round(hx - S.side * 0.9), ey = Math.round(hy)
      if (ex >= 0 && ex < W) field[ey * W + ex] = 0 // eye
    }
  }

  return {
    field, owner,
    frame(t, pose) { wings(t, pose.wingMotion, pose.open); snakes(t, pose.snakeMotion) }
  }
}

// ---------------------------------------------------------------- live state
const NIGHT_SIGNAL = { stop: '#ff453a', caution: '#ffcc00', go: '#30d158', whisper: '#eadfb8' }
const DAY_SIGNAL = { stop: '#d70015', caution: '#a66b00', go: '#248a3d', whisper: '#7a6a2c' }
// The painter sets this from the ink it reads: dark ink means a light theme.
const $light = atom(false)
const signal = name => ($light.get() ? DAY_SIGNAL : NIGHT_SIGNAL)[name]
const DONE = new Set(['completed', 'complete', 'done', 'failed', 'error', 'cancelled', 'interrupted', 'timeout', 'timed_out'])
const VERIFIED_MS = 9000

const $state = atom({ busy: false, waiting: false, verifiedAt: 0, failedAt: 0, subs: {}, lastProof: null })
const $prefs = atom({ background: true, pane: true, chip: true, strength: 'soft', place: 'center' })
const STRENGTH = { faint: 0.07, soft: 0.13, strong: 0.24 }

function patch(next) { $state.set({ ...$state.get(), ...next }) }

function subId(p) {
  return String(p.subagent_id || p.child_session_id || `${p.parent_id || 'root'}:${p.task_index == null ? 0 : p.task_index}:${p.goal || ''}`)
}

function onSubagent(type, sessionId, p, demo) {
  const subs = { ...$state.get().subs }
  const id = subId(p)
  const prev = subs[id] || { id, goal: p.goal || '', startedAt: Date.now(), tools: 0, lastTool: '', sessionId, demo: !!demo, steerable: !!p.subagent_id }
  const status = String(p.status || '').toLowerCase()
  const finished = type === 'subagent.complete' || DONE.has(status)
  subs[id] = {
    ...prev,
    goal: p.goal || prev.goal,
    tools: p.tool_count == null ? prev.tools + (type === 'subagent.tool' ? 1 : 0) : p.tool_count,
    lastTool: p.tool_name || prev.lastTool,
    status: finished ? (status && status !== 'running' ? status : 'completed') : type === 'subagent.spawn_requested' ? 'queued' : 'running',
    finishedAt: finished ? Date.now() : 0
  }
  patch({ subs })
}

function readProof(p) {
  let r = p.result
  if (typeof r === 'string') { try { r = JSON.parse(r) } catch { r = null } }
  if ((!r || typeof r !== 'object') && typeof p.result_text === 'string') { try { r = JSON.parse(p.result_text) } catch { r = null } }
  return r && typeof r === 'object' && typeof r.passed === 'boolean' ? r : null
}

const WAIT_ON = new Set(['approval.request', 'clarify.request', 'sudo.request', 'secret.request'])
const WAIT_OFF = new Set(['approval.respond', 'approval.received', 'approval.cancelled', 'clarify.respond', 'sudo.respond', 'secret.respond', 'message.complete', 'turn.settled', 'turn.failed'])

function onGatewayEvent(event, demo) {
  const t = event && event.type
  if (typeof t !== 'string') return
  const p = event.payload || {}
  if (t.startsWith('subagent.')) return onSubagent(t, event.session_id, p, demo)
  if (WAIT_ON.has(t)) return patch({ waiting: true })
  if (WAIT_OFF.has(t)) patch({ waiting: false })
  if (t === 'tool.complete' && typeof p.name === 'string' && p.name.endsWith('standing_proof')) {
    const proof = readProof(p)
    if (proof) patch(proof.passed ? { verifiedAt: Date.now(), lastProof: { passed: true, at: Date.now() } } : { failedAt: Date.now(), lastProof: { passed: false, at: Date.now() } })
  }
}

/** Finished workers leave the list a few seconds after they finish. */
function sweep() {
  const s = $state.get()
  const now = Date.now()
  const keep = {}
  let changed = false
  for (const sub of Object.values(s.subs)) {
    if (sub.finishedAt && now - sub.finishedAt > 8000) changed = true
    else keep[sub.id] = sub
  }
  if (changed) patch({ subs: keep })
}

const running = s => Object.values(s.subs).filter(x => !x.finishedAt)

/** What the drawing should look like for the current state. */
function targetPose(s, now) {
  const workers = running(s).length
  const verified = now - s.verifiedAt < VERIFIED_MS
  const failed = now - s.failedAt < VERIFIED_MS
  const still = s.waiting
  const active = s.busy || workers > 0
  return {
    wingMotion: still ? 0 : active ? 0.7 : 0.25,
    open: verified ? 1 : 0,
    snakeMotion: [still ? 0 : workers > 0 ? 1 : s.busy ? 0.35 : 0.12, still ? 0 : workers > 1 ? 1 : s.busy ? 0.3 : 0.1],
    snakeInk: [workers > 0 ? 1 : 0.42, workers > 1 ? 1 : 0.42],
    staffInk: active ? 1 : 0.55,
    wingInk: verified || failed ? 1 : 0.5,
    tone: still ? 'caution' : null,
    wingTone: failed ? 'stop' : verified ? 'go' : null
  }
}

function easePose(cur, to, k) {
  const mix = (a, b) => a + (b - a) * k
  return {
    ...to,
    wingMotion: mix(cur.wingMotion, to.wingMotion),
    open: mix(cur.open, to.open),
    snakeMotion: [mix(cur.snakeMotion[0], to.snakeMotion[0]), mix(cur.snakeMotion[1], to.snakeMotion[1])],
    snakeInk: [mix(cur.snakeInk[0], to.snakeInk[0]), mix(cur.snakeInk[1], to.snakeInk[1])],
    staffInk: mix(cur.staffInk, to.staffInk),
    wingInk: mix(cur.wingInk, to.wingInk)
  }
}

/** Draws one engine into one canvas and keeps its own eased pose. */
function createPainter(canvas) {
  const engine = createEngine()
  const g = canvas.getContext('2d')
  let pose = targetPose($state.get(), Date.now())
  let ink = '#c9cacd', accent = '#f0f0ee'

  function readTheme() {
    const cs = getComputedStyle(canvas)
    ink = cs.getPropertyValue('--ui-text-secondary').trim() || cs.color || ink
    accent = cs.getPropertyValue('--ui-accent').trim() || ink
    // Canvas normalises any CSS colour to #rrggbb, which gives the ink's brightness.
    g.fillStyle = ink
    const hex = /^#([0-9a-f]{6})$/i.exec(String(g.fillStyle))
    if (hex) {
      const n = parseInt(hex[1], 16)
      const light = (0.2126 * (n >> 16) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255 < 0.5
      if (light !== $light.get()) $light.set(light)
    }
  }

  function paint(t, place) {
    pose = easePose(pose, targetPose($state.get(), Date.now()), 0.12)
    engine.frame(t, pose)
    const cw = canvas.width, ch = canvas.height
    g.clearRect(0, 0, cw, ch)
    const cell = Math.max(1, Math.min(cw / (W + 8), ch / (H + 8)))
    const dot = Math.max(1, cell * 0.62)
    const ox = place === 'right' ? cw - W * cell - cell * 6 : (cw - W * cell) / 2
    const oy = (ch - H * cell) / 2
    const tone = pose.tone ? signal(pose.tone) : null
    const fills = [
      [pose.wingTone ? signal(pose.wingTone) : tone || ink, pose.wingInk],
      [tone || ink, pose.snakeInk[0]],
      [tone || ink, pose.snakeInk[1]],
      [tone || accent, pose.staffInk],
      [tone || signal('whisper'), 1]
    ]
    const { field, owner } = engine
    for (let b = 0; b < fills.length; b++) {
      g.fillStyle = fills[b][0]
      g.globalAlpha = fills[b][1]
      for (let y = 0; y < H; y++) {
        for (let x = 0; x < W; x++) {
          const i = y * W + x
          if (owner[i] !== b || field[i] * 0.9 <= BAYER[(y & 3) * 4 + (x & 3)]) continue
          g.fillRect(ox + x * cell, oy + y * cell, dot, dot)
        }
      }
    }
    g.globalAlpha = 1
  }

  return { paint, readTheme }
}

const reducedMotion = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
const seconds = () => (reducedMotion() ? 0 : performance.now() / 1000)

// ---------------------------------------------------------------- the overlay
function mountOverlay(ctx) {
  const canvas = document.createElement('canvas')
  canvas.setAttribute('data-caduceus', 'overlay')
  canvas.setAttribute('aria-hidden', 'true')
  Object.assign(canvas.style, { position: 'fixed', top: '0', left: '0', width: '100vw', height: '100vh', pointerEvents: 'none', zIndex: '999990' })
  document.body.appendChild(canvas)
  const painter = createPainter(canvas)

  function resize() {
    const ratio = Math.min(2, window.devicePixelRatio || 1)
    canvas.width = Math.max(1, Math.floor(window.innerWidth * ratio))
    canvas.height = Math.max(1, Math.floor(window.innerHeight * ratio))
    painter.readTheme()
  }
  resize()
  ctx.addEventListener(window, 'resize', resize)

  let tick = 0
  ctx.setInterval(() => {
    const prefs = $prefs.get()
    canvas.style.display = prefs.background ? 'block' : 'none'
    if (!prefs.background || document.hidden) return
    tick++
    const s = $state.get()
    const lively = s.busy || s.waiting || running(s).length > 0 || Date.now() - Math.max(s.verifiedAt, s.failedAt) < VERIFIED_MS + 3000
    if (!lively && tick % 4) return // at rest, a quarter of the frames is plenty
    if (tick % 40 === 0) painter.readTheme()
    canvas.style.opacity = String(STRENGTH[prefs.strength] || STRENGTH.soft)
    painter.paint(seconds(), prefs.place)
  }, 90)

  ctx.onDispose(() => canvas.remove())
}

// ---------------------------------------------------------------- the pane
function PaneCanvas() {
  const ref = useRef(null)
  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return undefined
    const painter = createPainter(canvas)
    const fit = () => {
      const ratio = Math.min(2, window.devicePixelRatio || 1)
      const box = canvas.getBoundingClientRect()
      canvas.width = Math.max(1, Math.floor(box.width * ratio))
      canvas.height = Math.max(1, Math.floor(box.height * ratio))
      painter.readTheme()
    }
    const observer = new ResizeObserver(fit)
    observer.observe(canvas)
    fit()
    const timer = setInterval(() => { if (!document.hidden) painter.paint(seconds(), 'center') }, 90)
    return () => { observer.disconnect(); clearInterval(timer) }
  }, [])
  return jsx('canvas', { ref, 'aria-hidden': true, className: 'h-56 w-full shrink-0' })
}

function say(result, okText) {
  host.notify({ kind: 'info', message: result && result.status === 'rejected' ? 'Not accepted: the worker is past its last step.' : okText })
}

/** A text box that sends a course correction, and a stop that asks twice. */
function Controls({ label, canSteer, onSteer, onStop }) {
  const [text, setText] = useState('')
  const [armed, setArmed] = useState(false)
  const send = () => {
    const value = text.trim()
    if (!value) return
    setText('')
    onSteer(value)
  }
  return jsxs('div', {
    className: 'flex items-center gap-1.5',
    children: [
      jsx(Input, {
        value: text,
        disabled: !canSteer,
        placeholder: canSteer ? `Change course: ${label}` : 'Not running',
        className: 'h-7 min-w-0 flex-1 text-xs',
        onChange: e => setText(e.target.value),
        onKeyDown: e => { if (e.key === 'Enter') send() }
      }),
      jsx(Button, { size: 'sm', variant: 'secondary', disabled: !canSteer || !text.trim(), onClick: send, children: 'Send' }),
      jsx(Button, {
        size: 'sm',
        variant: armed ? 'destructive' : 'outline',
        disabled: !canSteer,
        onClick: () => { if (armed) { setArmed(false); onStop() } else setArmed(true) },
        onBlur: () => setArmed(false),
        children: armed ? 'Confirm stop' : 'Stop'
      })
    ]
  })
}

function Row({ title, detail, tone, children }) {
  return jsxs('div', {
    className: 'flex flex-col gap-1.5 border-b border-(--ui-stroke-secondary) px-3 py-2.5',
    children: [
      jsxs('div', {
        className: 'flex items-baseline justify-between gap-2',
        children: [
          jsx('span', { className: 'min-w-0 truncate text-xs font-medium', title, children: title }),
          jsx('span', { className: 'shrink-0 text-[0.6875rem]', style: tone ? { color: signal(tone) } : undefined, children: detail })
        ]
      }),
      children
    ]
  })
}

function CaduceusPane() {
  const s = useValue($state)
  useValue($light)
  const focused = useValue(host.state.focusedSessionId)
  const [, setNow] = useState(0)
  useEffect(() => { const timer = setInterval(() => setNow(n => n + 1), 1000); return () => clearInterval(timer) }, [])

  const now = Date.now()
  const subs = Object.values(s.subs).sort((a, b) => a.startedAt - b.startedAt)
  const call = (method, params, okText) => host.request(method, params).then(r => say(r, okText)).catch(e => host.notifyError(e, 'Hermes did not accept that.'))
  const mainState = s.waiting ? ['waiting on you', 'caution'] : s.busy ? ['working', null] : ['idle', null]
  const proof = s.lastProof
  const proofLine = !proof ? 'no proof check yet' : `${proof.passed ? 'check passed' : 'check failed'} ${Math.max(0, Math.round((now - proof.at) / 1000))}s ago`

  return jsxs('div', {
    className: 'flex h-full min-h-0 flex-col text-sm',
    children: [
      jsx(PaneCanvas, {}),
      jsxs('div', {
        className: 'min-h-0 flex-1 overflow-y-auto border-t border-(--ui-stroke-secondary)',
        children: [
          jsx(Row, {
            title: 'Staff: main agent',
            detail: mainState[0],
            tone: mainState[1],
            children: jsx(Controls, {
              label: 'main agent',
              canSteer: !!focused && s.busy,
              onSteer: text => call('session.steer', { session_id: focused, text }, 'Sent. It lands with the next tool result.'),
              onStop: () => call('session.interrupt', { session_id: focused }, 'Stop sent to the main agent.')
            })
          }),
          subs.length === 0
            ? jsx('div', { className: 'px-3 py-2.5 text-xs text-(--ui-text-tertiary)', children: 'Serpents: no workers running. They appear when the agent delegates.' })
            : subs.map((sub, n) => jsx(Row, {
              key: sub.id,
              title: `Serpent ${n + 1}: ${sub.goal || 'worker'}`,
              detail: `${sub.status}${sub.tools ? ` · ${sub.tools} tools` : ''}${sub.demo ? ' · demo' : ''}`,
              tone: sub.status === 'failed' || sub.status === 'error' ? 'stop' : null,
              children: jsx(Controls, {
                label: `worker ${n + 1}`,
                canSteer: !sub.finishedAt && !sub.demo && sub.steerable && !!sub.sessionId,
                onSteer: text => call('subagent.steer', { session_id: sub.sessionId, subagent_id: sub.id, text }, 'Queued for the worker.'),
                onStop: () => call('subagent.interrupt', { session_id: sub.sessionId, subagent_id: sub.id }, 'Stop sent to the worker.')
              })
            }, sub.id)),
          jsx(Row, {
            title: 'Wings: proof',
            detail: proofLine,
            tone: proof ? (proof.passed ? 'go' : 'stop') : null,
            children: jsx('div', {
              className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
              children: 'The wings open only when a Standing proof check passes. Without the Standing plugin they stay at rest.'
            })
          })
        ]
      })
    ]
  })
}

function Chip() {
  const s = useValue($state)
  useValue($light)
  const workers = running(s).length
  const text = s.waiting ? 'waiting on you' : workers ? `${workers} working` : s.busy ? 'working' : 'at rest'
  return jsx('span', {
    className: 'px-1.5 text-[0.6875rem] text-(--ui-text-tertiary)',
    style: s.waiting ? { color: signal('caution') } : undefined,
    title: 'Axiōma: live agent state',
    children: `☤ ${text}`
  })
}

function SettingsPage({ save }) {
  const prefs = useValue($prefs)
  const set = next => save({ ...prefs, ...next })
  const choice = (key, values) => jsx('div', {
    className: 'flex gap-1.5',
    children: values.map(v => jsx(Button, { key: v, size: 'sm', variant: prefs[key] === v ? 'default' : 'secondary', onClick: () => set({ [key]: v }), children: v }))
  })
  const line = (label, control) => jsxs('div', { className: 'flex items-center justify-between gap-4 py-2', children: [jsx('span', { className: 'text-sm', children: label }), control] })
  return jsxs('div', {
    className: 'flex max-w-xl flex-col p-4',
    children: [
      line('Caduceus behind the window', jsx(Switch, { checked: prefs.background, onCheckedChange: v => set({ background: !!v }) })),
      line('Side pane (state and course changes)', jsx(Switch, { checked: prefs.pane, onCheckedChange: v => set({ pane: !!v }) })),
      line('Status-bar readout', jsx(Switch, { checked: prefs.chip, onCheckedChange: v => set({ chip: !!v }) })),
      line('Strength', choice('strength', ['faint', 'soft', 'strong'])),
      line('Position', choice('place', ['center', 'right']))
    ]
  })
}

// ---------------------------------------------------------------- the theme
const NIGHT = {
  background: '#0e0f11', foreground: '#d9dadc', card: '#141518', cardForeground: '#d9dadc',
  muted: '#141518', mutedForeground: '#8a8e96', popover: '#141518', popoverForeground: '#d9dadc',
  primary: '#f0f0ee', primaryForeground: '#0e0f11', secondary: '#1b1d21', secondaryForeground: '#c9cacd',
  accent: '#1b1d21', accentForeground: '#f0f0ee', border: '#2a2c31', input: '#2a2c31', ring: '#eadfb8',
  midground: '#c9cacd', midgroundForeground: '#0e0f11', composerRing: '#eadfb8',
  destructive: '#ff453a', destructiveForeground: '#0e0f11',
  sidebarBackground: '#0e0f11', sidebarBorder: '#2a2c31', userBubble: '#141518', userBubbleBorder: '#2a2c31'
}
const DAY = {
  background: '#f6f5f1', foreground: '#1a1b1e', card: '#eceae4', cardForeground: '#1a1b1e',
  muted: '#eceae4', mutedForeground: '#6b6f77', popover: '#eceae4', popoverForeground: '#1a1b1e',
  primary: '#1a1b1e', primaryForeground: '#f6f5f1', secondary: '#e4e1d9', secondaryForeground: '#26282c',
  accent: '#e4e1d9', accentForeground: '#1a1b1e', border: '#d4d2cc', input: '#d4d2cc', ring: '#6b6f77',
  midground: '#26282c', midgroundForeground: '#f6f5f1', composerRing: '#6b6f77',
  destructive: '#d70015', destructiveForeground: '#f6f5f1',
  sidebarBackground: '#f6f5f1', sidebarBorder: '#d4d2cc', userBubble: '#eceae4', userBubbleBorder: '#d4d2cc'
}
// The same two palettes as the terminal skins `axioma` and `axioma-day`.
const THEMES = [
  { name: 'axioma', label: 'Axiōma', description: 'White on night, traffic-light signals.', colors: NIGHT, darkColors: NIGHT },
  { name: 'axioma-day', label: 'Axiōma Day', description: 'Ink on bone, traffic-light signals.', colors: DAY, darkColors: DAY }
]

// ---------------------------------------------------------------- demo
/** A labelled rehearsal: fake events so the states can be seen without real work. */
function demo(ctx) {
  const fire = (type, payload) => onGatewayEvent({ type, session_id: null, payload }, true)
  const a = { subagent_id: 'demo-a', goal: 'Draft the brief', task_index: 0, task_count: 2 }
  const b = { subagent_id: 'demo-b', goal: 'Check the numbers', task_index: 1, task_count: 2 }
  fire('subagent.start', { ...a, status: 'running' })
  ctx.setTimeout(() => fire('subagent.start', { ...b, status: 'running' }), 2500)
  ctx.setTimeout(() => fire('approval.request', {}), 7000)
  ctx.setTimeout(() => fire('approval.respond', {}), 11000)
  ctx.setTimeout(() => fire('subagent.complete', { ...a, status: 'completed' }), 13000)
  ctx.setTimeout(() => fire('subagent.complete', { ...b, status: 'completed' }), 14500)
  ctx.setTimeout(() => fire('tool.complete', { tool_id: 'demo', name: 'standing_proof', result: { passed: true } }), 16000)
}

// ---------------------------------------------------------------- register
export default {
  id: ID,
  name: 'Axiōma Desktop',
  register(ctx) {
    $prefs.set({ ...$prefs.get(), ...ctx.storage.get('prefs', {}) })
    // The pane and the readout come and go with their switches.
    const optional = {
      pane: () => ctx.register({ id: 'pane', area: 'panes', title: 'axiōma', data: { placement: 'right', width: '320px' }, render: () => jsx(CaduceusPane, {}) }),
      chip: () => ctx.register({ id: 'chip', area: STATUSBAR_AREAS.right, order: 140, render: () => jsx(Chip, {}) })
    }
    const mounted = {}
    const sync = () => {
      for (const key of Object.keys(optional)) {
        const want = !!$prefs.get()[key]
        if (want && !mounted[key]) mounted[key] = optional[key]()
        if (!want && mounted[key]) { mounted[key](); mounted[key] = null }
      }
    }
    const save = next => { $prefs.set(next); ctx.storage.set('prefs', next); sync() }

    patch({ busy: !!host.state.busy.get() })
    ctx.onDispose(host.state.busy.listen(busy => patch({ busy: !!busy })))
    ctx.onEvent('*', event => onGatewayEvent(event, false))
    ctx.setInterval(sweep, 2000)
    mountOverlay(ctx)
    sync()

    ctx.registerMany([
      ...THEMES.map(theme => ({ id: `theme-${theme.name}`, area: THEMES_AREA, data: theme })),
      {
        id: 'toggle',
        area: PALETTE_AREA,
        data: { id: `${ID}.caduceus`, label: 'Axiōma: show or hide the caduceus', keywords: ['axioma', 'caduceus', 'background'], run: () => save({ ...$prefs.get(), background: !$prefs.get().background }) }
      },
      {
        id: 'pane-toggle',
        area: PALETTE_AREA,
        data: { id: `${ID}.pane`, label: 'Axiōma: show or hide the side pane', keywords: ['axioma', 'pane', 'steer'], run: () => save({ ...$prefs.get(), pane: !$prefs.get().pane }) }
      },
      {
        id: 'demo',
        area: PALETTE_AREA,
        data: { id: `${ID}.demo`, label: 'Axiōma: run the 20-second demo (no real work)', keywords: ['axioma', 'caduceus', 'demo'], run: () => demo(ctx) }
      }
    ])
    ctx.registerSettingsPage({ id: 'settings', title: 'Axiōma Desktop', render: () => jsx(SettingsPage, { save }) })
  }
}
