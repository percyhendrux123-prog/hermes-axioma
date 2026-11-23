// The hooks module wired to a fake Claude Code (node:test). The real engine is covered separately by
// run_kit_tests.sh; this file checks the contract with every branch, fast, with no Claude Code.
import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from '../axioma/hooks/register.js'

const CARD = 'mcp__axiom-axioma__axioma_card'
const CANARY = 'CANARY-5d1f9e'

function boot(options = {}, { surfaces = ['terminal'], ask = () => 'Hold', env = {}, cwd = '/work/project' } = {}) {
  const hooks = []
  const on = (event, matcher, fn) => {
    if (typeof matcher === 'function') { fn = matcher; matcher = undefined }
    hooks.push({ event, matcher, fn })
    return { catch() {} }
  }
  const calls = { registered: [], logs: [], asked: [], ran: [] }
  const $ = {
    plugin: { name: 'axiom-axioma' },
    tool: { register: async (t) => { calls.registered.push(['tool', t]) } },
    command: { register: async (c) => { calls.registered.push(['command', c]) } },
    session: { surfaces: async () => surfaces, cwd: async () => cwd },
    ui: {
      ask: async (q, o) => { calls.asked.push({ q, o }); const a = await ask(q, o); if (a instanceof Error) throw a; return a },
      log: (t) => { calls.logs.push(t) },
      resolve: () => ({
        Box: (p) => ({ type: 'Box', ...p }),
        Text: (p) => ({ type: 'Text', ...p }),
        Markdown: (p) => ({ type: 'Markdown', ...p }),
      }),
    },
    env: { get: async (k) => env[k] },
  }
  register(on, options)
  const fire = async (event, e, matcherArg) => {
    const chain = hooks.filter((h) => h.event === event && (!h.matcher || Object.entries(h.matcher).every(([k, v]) => (k === 'tool' ? e.tool === v : k === 'command' ? e.command === v : k === 'component' ? e.component === v : true))))
    const run = async (i, ev) => {
      if (i >= chain.length) return matcherArg ? matcherArg(ev) : ev
      return chain[i].fn($, ev, (next) => run(i + 1, next))
    }
    return run(0, e)
  }
  const callTool = (e, core) => fire('tool.call', e, async (ev) => { calls.ran.push(ev.tool); return core ? core(ev) : { result: 'ok', text: 'ok' } })
  const drawRaw = (text, requestId = 'r1', surface = 'terminal', isFirstOfReply = true) => fire('ui.render', { component: 'AssistantMessage', surface, requestId, props: { text, isFirstOfReply } }, (ev) => ({ type: 'engine', props: ev.props }))
  // The body of a marked reply (past the terminal's bullet gutter), or Claude Code's own drawing.
  const draw = async (...args) => { const t = await drawRaw(...args); return t.key === 'axioma-message' ? t.children[1] : t }
  return { $, fire, callTool, draw, drawRaw, calls, hooks }
}

const stageCard = (m, tool, args, card = {}) => m.callTool({
  tool: CARD,
  call: { tool, arguments: args },
  card: { intent: 'Publish the reviewed change', light: 'yellow', signal: 'This reaches the shared branch.', question: 'Push it?', affects: ['team'], told: true, ...card },
})

test('session.start registers the card tool (loaded up front) and /signals', async () => {
  const m = boot()
  await m.fire('session.start', { cwd: '/x', surface: 'terminal', isInteractive: true })
  const tool = m.calls.registered.find(([k]) => k === 'tool')[1]
  assert.equal(tool.name, 'axioma_card')
  assert.equal(tool.isDeferred, false)
  assert.deepEqual(tool.inputSchema.required, ['call', 'card'])
  assert.ok(!('tool' in tool.inputSchema.properties), 'a property named tool would collide with the reserved key')
  assert.ok(m.calls.registered.some(([k, v]) => k === 'command' && v.name === 'signals'))
})

test('the tag grammar and the card protocol reach Claude once, as one context block', async () => {
  const m = boot()
  const first = await m.fire('prompt.context', { blocks: [{ name: 'currentDate', text: 'today' }] }, (e) => e)
  const block = first.blocks.find((b) => b.name === 'axioma')
  assert.ok(block.text.includes('[signal:stop'))
  assert.ok(block.text.includes(CARD))
  assert.ok(/never\s+consent/.test(block.text))
  assert.equal(first.blocks.length, 2)
  const again = await m.fire('prompt.context', first, (e) => e)
  assert.equal(again.blocks.filter((b) => b.name === 'axioma').length, 1)
})

test('a harmless call passes straight through with no question', async () => {
  const m = boot()
  const res = await m.callTool({ tool: 'Bash', command: 'date', tool_use_id: 't1' })
  assert.equal(res.deny, undefined)
  assert.equal(m.calls.asked.length, 0)
  assert.deepEqual(m.calls.ran, ['Bash'])
})

test('a staged card is shown, the call waits, and Go ahead lets it continue to the permission check', async () => {
  const m = boot({}, { ask: () => 'Go ahead' })
  const staged = JSON.parse((await stageCard(m, 'Bash', { command: 'git push origin main' })).result)
  assert.equal(staged.status, 'staged')
  const res = await m.callTool({ tool: 'Bash', command: 'git push origin main', description: 'push', tool_use_id: 't2' })
  assert.equal(res.deny, undefined)
  assert.deepEqual(m.calls.ran, ['Bash']) // the core (permission check + tool) ran after the answer
  const { q, o } = m.calls.asked[0]
  assert.ok(q.startsWith('CAUTION \u00b7 proceed: yes / no'))
  assert.ok(q.includes('call: Bash: git push origin main'))
  assert.ok(q.includes('kind: send'))
  assert.ok(q.endsWith('Push it?'))
  assert.deepEqual(o.options, ['Hold', 'Go ahead'])
  assert.equal(o.header, 'Axioma card')
  assert.ok(m.calls.logs[0].includes('Go ahead') && m.calls.logs[0].includes('permission check follows'))
})

test('Hold refuses the call, tells Claude not to retry, and nothing runs', async () => {
  const m = boot({}, { ask: () => 'Hold' })
  await stageCard(m, 'Bash', { command: 'git push' })
  const res = await m.callTool({ tool: 'Bash', command: 'git push' })
  assert.match(res.deny, /did not pick Go ahead/)
  assert.match(res.deny, /Do not retry/)
  assert.deepEqual(m.calls.ran, [])
})

test('typed text, a dismissed question or "Chat about this" is not Go ahead', async () => {
  for (const answer of ['yes please', 'go ahead', '', new Error('dismissed')]) {
    const m = boot({}, { ask: () => answer })
    const res = await m.callTool({ tool: 'Bash', command: 'git push' })
    assert.ok(res.deny, String(answer))
    assert.deepEqual(m.calls.ran, [])
  }
})

test('no card staged: the person sees a NO CARD notice, never a silent pass', async () => {
  const m = boot({}, { ask: () => 'Go ahead' })
  await m.callTool({ tool: 'Bash', command: 'rm notes.txt' })
  const { q } = m.calls.asked[0]
  assert.ok(q.startsWith('NO CARD'))
  assert.ok(q.includes('Unreviewed scrub via Bash.'))
})

test('RED offers "Go ahead anyway" after Hold: advice never traps the person', async () => {
  const m = boot({}, { ask: () => 'Go ahead anyway' })
  await stageCard(m, 'Bash', { command: 'git push --force' }, { light: 'red', signal: 'This rewrites shared history.' })
  const res = await m.callTool({ tool: 'Bash', command: 'git push --force' })
  assert.equal(res.deny, undefined)
  const { q, o } = m.calls.asked[0]
  assert.ok(q.startsWith('STOP \u00b7 proceed: no'))
  assert.deepEqual(o.options, ['Hold', 'Go ahead anyway'])
})

test('a card is for one exact call: a different command gets a NO CARD notice', async () => {
  const m = boot({}, { ask: () => 'Hold' })
  await stageCard(m, 'Bash', { command: 'git push origin dev' })
  await m.callTool({ tool: 'Bash', command: 'git push origin main' })
  assert.ok(m.calls.asked[0].q.startsWith('NO CARD'))
})

test('a card is used once', async () => {
  const m = boot({}, { ask: () => 'Go ahead' })
  await stageCard(m, 'Bash', { command: 'git push' })
  await m.callTool({ tool: 'Bash', command: 'git push' })
  await m.callTool({ tool: 'Bash', command: 'git push' })
  assert.ok(m.calls.asked[0].q.startsWith('CAUTION'))
  assert.ok(m.calls.asked[1].q.startsWith('NO CARD'))
})

test('a bad card is rejected to Claude with the reason and never staged', async () => {
  const m = boot()
  const res = JSON.parse((await stageCard(m, 'Bash', { command: 'git push' }, { question: 'not a question' })).result)
  assert.match(res.error, /card not staged/)
  assert.match(res.note, /NO CARD/)
})

test('with nobody to ask (claude -p) the call goes on to Claude Code\'s own permission check', async () => {
  const m = boot({}, { surfaces: [], ask: () => new Error('no one to ask') })
  const res = await m.callTool({ tool: 'Bash', command: 'git push' })
  assert.equal(res.deny, undefined)
  assert.equal(m.calls.asked.length, 0)
  assert.deepEqual(m.calls.ran, ['Bash'])
})

test('if the advisor itself fails the call is not blocked', async () => {
  const m = boot()
  m.$.session.surfaces = async () => { throw new Error('boom') }
  // surfaces failing reads as "nobody to ask"; the call carries on
  const res = await m.callTool({ tool: 'Bash', command: 'git push' })
  assert.equal(res.deny, undefined)
})

test('go ahead never skips the permission check: the core always runs after it', async () => {
  const m = boot({}, { ask: () => 'Go ahead' })
  let coreSaw = null
  await m.callTool({ tool: 'Bash', command: 'git push' }, (ev) => { coreSaw = ev; return { deny: 'Claude Code refused' } })
  assert.equal(coreSaw.command, 'git push')
})

test('workspace option: a remove inside it skips the card', async () => {
  const m = boot({ workspace: '/work/project' }, { ask: () => 'Hold' })
  await m.callTool({ tool: 'Bash', command: 'rm /work/project/a.txt' })
  assert.equal(m.calls.asked.length, 0)
  await m.callTool({ tool: 'Bash', command: 'rm /etc/hosts' })
  assert.equal(m.calls.asked.length, 1)
  await m.callTool({ tool: 'Bash', command: 'rm a.txt' }) // relative, resolved against the session cwd
  assert.equal(m.calls.asked.length, 1)
})

test('a signal is drawn as a colored Text inside a Box, with the word, and a plain line becomes Markdown', async () => {
  const m = boot()
  const tree = await m.draw('First line is plain.\nShipping [signal:stop]without an eval[/signal] is risky. Run it first?\n- a list item')
  assert.equal(tree.type, 'Box')
  assert.deepEqual(tree.children.map((c) => c.type), ['Markdown', 'Text', 'Markdown'])
  const text = tree.children[1]
  const span = text.children.find((c) => c && c.type === 'Text')
  assert.equal(span.color, '#FF453A')
  assert.equal(span.bold, true)
  assert.ok(text.children.includes(' (stop)'))
  assert.equal(tree.children[0].text, 'First line is plain.')
  assert.equal(tree.children[2].text, '- a list item')
})

test('on the terminal a marked reply keeps the bullet and margin; on desktop there is no gutter', async () => {
  const m = boot()
  const first = await m.drawRaw('[signal:stop]x[/signal]', 'a', 'terminal', true)
  assert.equal(first.type, 'Box')
  assert.equal(first.flexDirection, 'row')
  assert.equal(first.children[0].children[0], '\u23fa ')
  const later = await m.drawRaw('[signal:stop]x[/signal]', 'b', 'terminal', false)
  assert.equal(later.children[0].children[0], '  ')
  const desktop = await m.drawRaw('[signal:stop]x[/signal]', 'c', 'desktop', true)
  assert.equal(desktop.key, 'axioma-body')
})

test('a reply with no tags is left to Claude Code, untouched', async () => {
  const m = boot()
  const out = await m.draw('plain reply with array[signal] in it')
  assert.equal(out.type, 'engine')
  assert.equal(out.props.text, 'plain reply with array[signal] in it')
})

test('when nothing is colored, Claude Code keeps its own drawing with only the text swapped', async () => {
  const m = boot()
  const out = await m.draw('[signal:go]no check behind this[/signal]')
  assert.equal(out.type, 'engine')
  assert.equal(out.props.text, 'no check behind this')
})

test('green appears only after a call Claude Code reported as successful', async () => {
  const m = boot()
  const text = 'Tests [signal:go;check=Bash]passed 41 of 41[/signal].'
  assert.equal((await m.draw(text, 'a')).type, 'engine') // no check yet: plain
  await m.fire('turn.start', { turnId: 'turn-1' })
  await m.callTool({ tool: 'Bash', command: 'date', tool_use_id: 'toolu_1' }, () => ({ isError: true, result: 'x', text: 'x' }))
  assert.equal((await m.draw(text, 'b')).type, 'engine') // a failed call does not back a green
  await m.callTool({ tool: 'Bash', command: 'date', tool_use_id: 'toolu_2' })
  const tree = await m.draw(text, 'c')
  assert.equal(tree.type, 'Box')
  assert.equal(tree.children[0].children.find((c) => c && c.type === 'Text').color, '#30D158')
  // by call id works across turns
  await m.fire('turn.start', { turnId: 'turn-2' })
  const byId = await m.draw('[signal:go;check=toolu_2]ok[/signal]', 'd')
  assert.equal(byId.type, 'Box')
  // by tool name only counts in the same turn
  const byName = await m.draw('[signal:go;check=Bash]ok again[/signal]', 'e')
  assert.equal(byName.type, 'engine')
})

test('a denied call never backs a green', async () => {
  const m = boot()
  await m.fire('turn.start', { turnId: 't' })
  await m.callTool({ tool: 'Bash', command: 'date' }, () => ({ deny: 'no' }))
  assert.equal((await m.draw('[signal:go;check=Bash]x[/signal]', 'z')).type, 'engine')
})

test('a redraw of the same block never changes a decision, even after the facts change', async () => {
  const m = boot()
  await m.fire('turn.start', { turnId: 't' })
  const text = '[signal:go;check=Bash]done[/signal] and [whisper:assumption]maybe[/whisper]'
  const a = await m.draw(text, 'row')
  await m.callTool({ tool: 'Bash', command: 'date' })
  const b = await m.draw(text, 'row')
  assert.deepEqual(a, b)
})

test('a whisper is shown once per session; a longer stream of the same block keeps it', async () => {
  const m = boot()
  const w = '[whisper:unverified_figure]about 4,200 users[/whisper]'
  assert.equal((await m.draw('Roughly ' + w, 'row-1')).type, 'Box')
  assert.equal((await m.draw('Roughly ' + w + ' as of now.', 'row-1')).type, 'Box') // same block, streamed further
  assert.equal((await m.draw('Again ' + w, 'row-2')).type, 'engine') // another block: plain
})

test('NO_COLOR keeps the style cue and the word but drops the color', async () => {
  const m = boot({}, { env: { NO_COLOR: '1' } })
  const tree = await m.draw('[signal:caution]check this[/signal]')
  const span = tree.children[0].children.find((c) => c && c.type === 'Text')
  assert.equal(span.color, undefined)
  assert.equal(span.underline, true)
  assert.ok(tree.children[0].children.includes(' (caution)'))
})

test('options: palette cvd and theme light change the colors', async () => {
  const tree = await boot({ palette: 'cvd' }).draw('[signal:stop]x[/signal]')
  assert.equal(tree.children[0].children.find((c) => c && c.type === 'Text').color, '#E8603C')
  const light = await boot({ theme: 'light' }).draw('[signal:stop]x[/signal]')
  assert.equal(light.children[0].children.find((c) => c && c.type === 'Text').color, '#D70015')
})

test('/signals lists metadata only: no phrase, command or card text', async () => {
  const m = boot({}, { ask: () => 'Go ahead' })
  await m.draw('[signal:stop]' + CANARY + ' phrase[/signal] [whisper:assumption]' + CANARY + ' w[/whisper]', 'row')
  await stageCard(m, 'Bash', { command: 'git push ' + CANARY }, { intent: 'intent ' + CANARY, signal: 'sig ' + CANARY, question: 'q ' + CANARY + '?' })
  await m.callTool({ tool: 'Bash', command: 'git push ' + CANARY })
  const out = await m.fire('command.run', { command: 'signals', args: '' })
  assert.ok(out.text.includes('stop shown'))
  assert.ok(out.text.includes('CAUTION for send: go ahead'))
  assert.ok(!out.text.includes(CANARY))
  assert.equal(out.isTextDisplayOnly, true)
})

test('the mod keeps nothing on disk: it uses no file, process or network API', async () => {
  const { readFileSync, readdirSync } = await import('node:fs')
  const dir = new URL('../axioma/hooks/', import.meta.url)
  const files = [new URL('register.js', dir), ...readdirSync(new URL('lib/', dir)).map((f) => new URL('lib/' + f, dir))]
  for (const f of files) {
    const src = readFileSync(f, 'utf8')
    for (const banned of ['$.fs', '$.http', '$.process', '$.store', '$.mcp', 'node:fs', 'node:child_process', 'fetch(']) {
      assert.ok(!src.includes(banned), f.pathname + ' uses ' + banned)
    }
  }
})
