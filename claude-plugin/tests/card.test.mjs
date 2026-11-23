// Card validation, light adjustment, text and matching (node:test).
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  CardStore, TTL_MS, CAPACITY, applyChecks, argsOf, callSummary, cardKey, renderCard, renderNotice, validateCard,
} from '../axioma/hooks/lib/card.mjs'

const card = (over = {}) => ({ intent: 'Share the reviewed demo', light: 'green', signal: 'The synthetic draft matches the audience.', question: 'Is this the audience you intended?', affects: ['team'], told: true, ...over })

test('a good card validates and is copied', () => {
  const c = card()
  const out = validateCard(c)
  assert.deepEqual(out, c)
  assert.notEqual(out, c)
})

test('bad cards are rejected with a reason', () => {
  const bad = [
    null, [], 'x', {}, card({ extra: 1 }), card({ light: 'blue' }), card({ light: 'GREEN' }), card({ intent: '' }), card({ intent: 'a'.repeat(401) }),
    card({ question: 'No question mark' }), card({ question: 'Two? Questions?' }), card({ signal: 'One. Two sentences here.' }),
    card({ told: 'yes' }), card({ affects: [1] }), card({ affects: Array(13).fill('x') }), card({ affects: ['a\u0007b'] }), card({ intent: 'line\nbreak' }),
    card({ signal: 'hidden\u202ebidi' }),
  ]
  for (const b of bad) assert.throws(() => validateCard(b), undefined, JSON.stringify(b)?.slice(0, 60))
})

test('affects may be a single string', () => {
  assert.doesNotThrow(() => validateCard(card({ affects: 'the team' })))
})

test('a named end-user audience that was not told caps green at yellow', () => {
  const { card: out, results } = applyChecks(card({ affects: ['end_users'], told: false }))
  assert.equal(out.light, 'yellow')
  assert.ok(results.some((r) => r.check === 'downstream_informed' && !r.pass))
  assert.equal(applyChecks(card({ affects: ['end_users'], told: true })).card.light, 'green')
})

test('no affects declared caps green at yellow; red and yellow are never changed', () => {
  const { affects, ...bare } = card()
  assert.equal(applyChecks(bare).card.light, 'yellow')
  assert.equal(applyChecks(card({ light: 'red', affects: ['everyone'], told: false })).card.light, 'red')
  assert.equal(applyChecks(card({ light: 'yellow' })).card.light, 'yellow')
})

test('an unparsed remove caps green at yellow and says so', () => {
  const { card: out, results } = applyChecks(card(), { unparsed: true })
  assert.equal(out.light, 'yellow')
  assert.ok(results.some((r) => r.check === 'scrub_parse' && /could not parse/.test(r.note)))
})

test('RED never says yes; the question is the last line; it says advice only', () => {
  const red = renderCard({ card: card({ light: 'red' }), kind: ['send'], call: 'Bash: git push' })
  const lines = red.split('\n')
  assert.equal(lines[0], 'STOP \u00b7 proceed: no')
  assert.ok(!/yes/.test(lines[0]))
  assert.equal(lines.at(-1), 'Is this the audience you intended?')
  assert.ok(red.includes('advice only'))
  assert.ok(red.includes('call: Bash: git push'))
  assert.ok(red.includes('kind: send'))
  const yellow = renderCard({ card: card({ light: 'yellow' }), kind: ['scrub', 'send'] })
  assert.equal(yellow.split('\n')[0], 'CAUTION \u00b7 proceed: yes / no')
  assert.ok(yellow.includes('kind: scrub+send'))
})

test('the no-card notice names the kind and the tool, and is not a stop', () => {
  const n = renderNotice({ tool: 'Bash', kind: ['scrub'], call: 'Bash: rm x' })
  assert.equal(n.split('\n')[0], 'NO CARD \u00b7 proceed: yes / no')
  assert.ok(n.includes('Unreviewed scrub via Bash.'))
  assert.ok(n.includes('the agent supplied no card'))
  assert.ok(n.endsWith('What do you need to know before this runs?'))
})

test('callSummary is one short line', () => {
  assert.equal(callSummary('Bash', { command: 'git push\n  origin main' }), 'Bash: git push origin main')
  assert.ok(callSummary('Bash', { command: 'x'.repeat(500) }).length < 175)
  assert.equal(callSummary('Bash', {}), 'Bash')
  assert.equal(callSummary('mcp__a__b', { to: 'x' }), 'mcp__a__b: {"to":"x"}')
})

test('argsOf drops the envelope; the card key ignores key order and a Bash description', () => {
  const e = { tool: 'Bash', tool_use_id: 't1', agentId: 'a', command: 'ls', description: 'list' }
  assert.deepEqual(argsOf(e), { command: 'ls', description: 'list' })
  assert.equal(cardKey('Bash', { command: 'ls', description: 'x' }), cardKey('Bash', { description: 'y', command: 'ls' }))
  assert.notEqual(cardKey('Bash', { command: 'ls' }), cardKey('Bash', { command: 'ls -la' }))
  assert.notEqual(cardKey('mcp__a__b', { a: 1 }), cardKey('mcp__a__b', { a: 2 }))
  assert.notEqual(cardKey('mcp__a__b', { description: 'x' }), cardKey('mcp__a__b', { description: 'y' }))
})

test('a staged card is for one exact call and is used once', () => {
  const s = new CardStore()
  s.stage({ tool: 'Bash', arguments: { command: 'git push' }, card: card() }, 'id1')
  assert.equal(s.take('Bash', { command: 'git push origin main' }), null) // different call
  const item = s.take('Bash', { command: 'git push' })
  assert.equal(item.id, 'id1')
  assert.equal(s.take('Bash', { command: 'git push' }), null) // used up
})

test('a replacement, even a bad one, retires the earlier card', () => {
  const s = new CardStore()
  s.stage({ tool: 'Bash', arguments: { command: 'x' }, card: card() }, 'a')
  assert.throws(() => s.stage({ tool: 'Bash', arguments: { command: 'x' }, card: card({ light: 'nope' }) }, 'b'))
  assert.equal(s.take('Bash', { command: 'x' }), null)
})

test('a bad envelope is refused', () => {
  const s = new CardStore()
  for (const env of [null, {}, { tool: 'Bash', card: card() }, { tool: 'Bash', arguments: [], card: card() }, { tool: '', arguments: {}, card: card() }, { tool: 'B', arguments: {}, card: card(), extra: 1 }]) {
    assert.throws(() => s.stage(env, 'x'))
  }
})

test('cards expire and the store is bounded', () => {
  let t = 1000
  const s = new CardStore(() => t)
  s.stage({ tool: 'Bash', arguments: { command: 'old' }, card: card() }, 'old')
  t += TTL_MS + 1
  assert.equal(s.take('Bash', { command: 'old' }), null)
  for (let i = 0; i < CAPACITY + 20; i += 1) s.stage({ tool: 'Bash', arguments: { command: 'c' + i }, card: card() }, 'i' + i)
  assert.ok(s.cards.size <= CAPACITY)
})
