// Mod-level tests: run through Claude Code's own test kit (`claude plugin test`), which loads the
// real hooks module and fires events through it. See run_kit_tests.sh.
import { expect, test } from 'claude-code/testing'

const MSG = (text: string, surface: 'terminal' | 'desktop' = 'terminal', requestId = 'row-1') => ({
  plugin: 'axiom-axioma',
  component: 'AssistantMessage',
  requestId,
  surface,
  viewport: { columns: 100, rows: 30 },
  props: { text, isFirstOfReply: true },
}) as const

// Register the stubs Claude Code would answer in a real session. Stubs must exist before the
// test's first call on `$`.
function stubs(on: any, { surfaces = ['terminal'], ask }: { surfaces?: string[]; ask?: (q: string) => string | Promise<string> } = {}) {
  on('tool.register', () => ({ value: undefined }))
  on('command.register', () => ({ value: undefined }))
  on('session.start', () => ({ cwd: '/tmp/axioma-test' }))
  on('session.surfaces', () => ({ value: surfaces }))
  on('ui.log', () => ({ value: undefined }))
  // $.ui.ask reaches the stubs as a call to the AskUserQuestion tool; every other call just "runs".
  on('tool.call', async (_$: any, e: any) => {
    if (e.tool !== 'AskUserQuestion') return { result: 'ran' }
    const q = String(e.questions[0].question)
    if (!ask) return { result: { answers: { [q]: 'Hold' } } }
    return { result: { answers: { [q]: await ask(q) } } }
  })
}

async function start($: any) {
  await $.session.start({ cwd: '/tmp/axioma-test', surface: 'terminal', isInteractive: true })
}

test('a stop mark is drawn as its own colored Text, with the word, on terminal and desktop', async ($, on) => {
  on('env.get', () => ({ value: undefined }))
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount(MSG('Shipping [signal:stop;why=no_eval]without an eval[/signal] is risky. Run it first?', surface))
    const span = await ui.find({ type: 'Text', text: 'without an eval' })
    expect(span).toBeDefined()
    // the first Text found is the line; its child is the colored span
    const child: any = (span as any).children.find((c: any) => c && c.type === 'Text')
    expect(child.props.color).toBe('#FF453A')
    expect(child.props.bold).toBe(true)
    expect(child.props.underline).toBe(true)
    expect(await ui.find({ type: 'Text', text: /\(stop\)/ })).toBeDefined()
    await ui.unmount()
  }
})

test('a reply with no tags is left to Claude Code', async ($, on) => {
  on('env.get', () => ({ value: undefined }))
  const ui = await $.ui.mount(MSG('Nothing marked here, just array[signal] and df[sig > 0].'))
  expect(await ui.keepsBeneath()).toBe(true)
  await ui.unmount()
})

test('the card tool stages a card and the matching send is held, then allowed on Go ahead', async ($, on) => {
  let asked = ''
  stubs(on, { ask: (q) => { asked = q; return 'Go ahead' } })
  await start($)
  const staged = await $.tool.call({
    tool: 'mcp__axiom-axioma__axioma_card',
    call: { tool: 'Bash', arguments: { command: 'git push origin main' } },
    card: { intent: 'Publish the reviewed change', light: 'yellow', signal: 'This reaches the shared branch.', question: 'Push to main?', affects: ['the team'], told: true },
  } as any)
  expect(String(JSON.stringify(staged))).toContain('staged')
  const res: any = await $.tool.call({ tool: 'Bash', command: 'git push origin main' })
  expect(res.deny).toBeUndefined()
  expect(asked).toContain('CAUTION')
  expect(asked).toContain('Push to main?')
})

test('Hold denies the call and tells Claude not to retry', async ($, on) => {
  stubs(on, { ask: () => 'Hold' })
  await start($)
  const res: any = await $.tool.call({ tool: 'Bash', command: 'git push origin main' })
  expect(String(res.deny)).toContain('did not pick Go ahead')
})

test('a harmless command is never asked about', async ($, on) => {
  let asked = false
  stubs(on, { ask: () => { asked = true; return 'Hold' } })
  await start($)
  const res: any = await $.tool.call({ tool: 'Bash', command: 'date' })
  expect(res.deny).toBeUndefined()
  expect(asked).toBe(false)
})

test('with nobody to ask the call goes on to Claude Code\'s own permission check', async ($, on) => {
  stubs(on, { surfaces: [], ask: () => { throw new Error('no one to ask') } })
  await start($)
  const res: any = await $.tool.call({ tool: 'Bash', command: 'git push origin main' })
  expect(res.deny).toBeUndefined()
})
