// Signal grammar, limits and rendering plan (node:test, no Claude Code needed).
import test from 'node:test'
import assert from 'node:assert/strict'
import { decide, parse, plan, plainLine, replyHasTags, scrubJoined, DEFAULT_BUDGET, GUIDANCE } from '../axioma/hooks/lib/signal.mjs'

const opts = { theme: 'dark', palette: 'default', words: 'always' }
const spansOf = (lines) => lines.flat().filter((p) => typeof p !== 'string')
function run(text, { passed = () => false, seen = () => false, budget, o = opts } = {}) {
  const lines = parse(text)
  const spans = spansOf(lines)
  decide(spans, { budget, checkPassed: passed, whisperSeen: seen })
  return { lines, spans, planned: plan(lines, o) }
}
const flat = (planned) => planned.map(plainLine).join('\n')

test('a stop and a caution are read and styled with color, a style cue and a word', () => {
  const { spans, planned } = run('Shipping [signal:stop;why=no_eval]without an eval[/signal] and [signal:caution]merge to main[/signal] now?')
  assert.deepEqual(spans.map((s) => [s.level, s.show]), [['stop', true], ['caution', true]])
  const pieces = planned[0].pieces.filter((p) => typeof p !== 'string')
  assert.equal(pieces[0].color, '#FF453A')
  assert.equal(pieces[0].bold, true)
  assert.equal(pieces[0].underline, true)
  assert.equal(pieces[0].word, ' (stop)')
  assert.equal(pieces[1].color, '#FFCC00')
  assert.equal(pieces[1].underline, true)
  assert.equal(pieces[1].word, ' (caution)')
  assert.equal(flat(planned), 'Shipping without an eval (stop) and merge to main (caution) now?')
})

test('a reply with no tags is never touched', () => {
  for (const text of ['plain words', 'df[signal > 0] and mask[sig[0]] and arr[whisper = 3]', 'see array[signal] and samples[signal_1]']) {
    assert.equal(replyHasTags(text), false, text)
  }
})

test('exact tags, closers and cut-off tags make a reply "tagged"', () => {
  assert.equal(replyHasTags('x [signal:stop]y[/signal]'), true)
  assert.equal(replyHasTags('x [/signal]'), true)
  assert.equal(replyHasTags('x [signal:stop;why=a'), true) // a cut-off stream
  assert.equal(replyHasTags('x [sig'), true)
  assert.equal(replyHasTags('x [signal:danger]y'), false) // unknown level alone: left as written
})

test('no nesting: a nested opener is dropped and the inner text stays plain', () => {
  const { spans, planned } = run('[signal:stop]outer [signal:caution]inner[/signal] tail[/signal]')
  assert.equal(spans.length, 1)
  assert.equal(spans[0].level, 'stop')
  assert.equal(flat(planned), 'outer inner (stop) tail')
})

test('spans never cross a line: an unclosed span is plain text', () => {
  const { spans, planned } = run('[signal:stop]first line\nsecond line[/signal]')
  assert.equal(spans.length, 0)
  assert.equal(flat(planned), 'first line\nsecond line')
})

test('malformed tags are removed in a tagged reply and never leak', () => {
  const text = '[signal:danger]drop the table[/signal] and [signal]x[/signal] and [signal:stop]ok[/signal] and [/whisper] done'
  const { planned } = run(text)
  const out = flat(planned)
  assert.ok(!/\[\/?(signal|whisper)/i.test(out), out)
  assert.ok(out.includes('ok (stop)'))
})

test('a lookalike with no closer is left alone even in a tagged reply', () => {
  const { planned } = run('array[signal] and [signal:caution]this[/signal]')
  assert.equal(flat(planned), 'array[signal] and this (caution)')
})

test('a lookalike opener never takes the closer of a real span after it', () => {
  const { spans } = run('arr[signal] and [signal:stop]x[/signal]')
  assert.deepEqual(spans.map((s) => s.level), ['stop'])
})

test('rarity budget: at most 3 signals (most severe kept), 2 whispers, 1 intent', () => {
  const text = [
    '[signal:go;check=Bash]a[/signal]', '[signal:caution]b[/signal]', '[signal:stop]c[/signal]', '[signal:caution]d[/signal]',
    '[whisper:assumption]w1[/whisper]', '[whisper:assumption]w2[/whisper]', '[whisper:assumption]w3[/whisper]',
    '[signal:intent]i1[/signal]', '[signal:intent]i2[/signal]',
  ].join(' ')
  const { spans } = run(text, { passed: () => true })
  const shown = (lvl) => spans.filter((s) => s.level === lvl && s.show).length
  assert.equal(shown('stop') + shown('caution') + shown('go'), 3)
  assert.equal(shown('stop'), 1) // severe ones win
  assert.equal(shown('whisper'), 2)
  assert.equal(shown('intent'), 1)
  assert.deepEqual(spans.filter((s) => !s.show).map((s) => s.drop).sort(), ['over_budget', 'over_budget', 'over_budget'])
})

test('a span longer than the word limit renders plain', () => {
  const long = Array.from({ length: DEFAULT_BUDGET.max_span_words + 1 }, (_, i) => 'w' + i).join(' ')
  const { spans, planned } = run('[signal:caution]' + long + '[/signal]')
  assert.equal(spans[0].drop, 'too_long')
  assert.equal(flat(planned), long)
})

test('green only from a real check', () => {
  const none = run('[signal:go]passed[/signal]')
  assert.equal(none.spans[0].drop, 'no_check')
  assert.equal(flat(none.planned), 'passed')
  const wrong = run('[signal:go;check=Bash]passed[/signal]', { passed: () => false })
  assert.equal(wrong.spans[0].drop, 'check_not_observed')
  const ok = run('[signal:go;check=Bash]passed[/signal]', { passed: (c) => c === 'Bash' })
  assert.equal(ok.spans[0].show, true)
  assert.equal(ok.planned[0].pieces[0].italic, true)
  assert.equal(ok.planned[0].pieces[0].color, '#30D158')
})

test('a whisper is shown once, then plain', () => {
  const { spans, planned } = run('[whisper:unverified_figure]about 4,200 users[/whisper]', { seen: () => true })
  assert.equal(spans[0].drop, 'repeat')
  assert.equal(flat(planned), 'about 4,200 users')
})

test('whisper reasons must be known', () => {
  const { spans } = run('[whisper:vibes]x[/whisper] [whisper:assumption]y[/whisper]')
  assert.deepEqual(spans.map((s) => s.text), ['y'])
})

test('nothing inside code is styled: a complete exact span keeps its phrase and word only', () => {
  const { planned } = run('Run `[signal:stop]rm x[/signal]` first\n```\n[signal:caution]danger[/signal] and df[signal > 0]\n```\n    [signal:go;check=a]indented[/signal]')
  const out = flat(planned)
  assert.ok(out.includes('`rm x (stop)`'), out)
  assert.ok(out.includes('danger (caution) and df[signal > 0]'), out)
  assert.ok(planned.every((l) => !l.styled))
})

test('in code, every other bracket stays as written', () => {
  const { planned } = run('```\nsamples[signal:end]\nx[signal:stop]\nd[/signal]\nq[signal:end] + w[/signal]\n```')
  assert.equal(flat(planned), '```\nsamples[signal:end]\nx[signal:stop]\nd[/signal]\nq[signal:end] + w[/signal]\n```')
})

test('palettes: cvd changes the colors, none keeps style and words only', () => {
  const t = '[signal:stop]x[/signal]'
  assert.equal(run(t, { o: { ...opts, palette: 'cvd' } }).planned[0].pieces[0].color, '#E8603C')
  assert.equal(run(t, { o: { ...opts, theme: 'light' } }).planned[0].pieces[0].color, '#D70015')
  const none = run(t, { o: { ...opts, palette: 'none' } }).planned[0].pieces[0]
  assert.equal(none.color, null)
  assert.equal(none.bold, true)
  assert.equal(none.word, ' (stop)')
})

test('NO_COLOR drops color but keeps the style cue and the word', () => {
  const lines = parse('[signal:caution]x[/signal]')
  decide(spansOf(lines), { checkPassed: () => false, whisperSeen: () => false })
  const piece = plan(lines, { ...opts, noColor: true })[0].pieces[0]
  assert.equal(piece.color, null)
  assert.equal(piece.underline, true)
  assert.equal(piece.word, ' (caution)')
})

test('words: plain_only drops the word only where color is drawn; no color keeps it', () => {
  const t = '[signal:stop]x[/signal]'
  assert.equal(run(t, { o: { ...opts, words: 'plain_only' } }).planned[0].pieces[0].word, '')
  assert.equal(run(t, { o: { ...opts, words: 'plain_only', palette: 'none' } }).planned[0].pieces[0].word, ' (stop)')
})

test('a whisper with no color and no style is phrase plus word', () => {
  const { planned } = run('[whisper:assumption]maybe[/whisper]', { o: { ...opts, palette: 'none' } })
  assert.equal(flat(planned), 'maybe (second look)')
})

test('control, bidi and escape characters never ride into a span', () => {
  const { planned } = run('[signal:stop]ab\u202ecd\u001b[31m[/signal]')
  assert.ok(!/[\u202e\u001b]/.test(flat(planned)))
})

test('a tag hidden behind zero-width characters is still read', () => {
  const { spans } = run('[sig\u200bnal:stop]x[/signal]')
  assert.equal(spans.length, 1)
})

test('a stream cut off mid-tag shows no raw tag', () => {
  for (const partial of ['ok [signal:stop;why=no_', 'ok [signal:stop]phrase [/sign', 'ok [sig']) {
    const { planned } = run(partial)
    assert.ok(!/\[/.test(flat(planned)), partial + ' -> ' + flat(planned))
  }
})

test('removal that joins text into a new tag does not leave a live one', () => {
  const { planned } = run('[signal:danger]x[[/signal]/signal] [signal:stop]y[/signal]')
  assert.ok(!/\[\/signal\]/.test(scrubJoined(flat(planned))))
})

test('the same text always gives the same decisions', () => {
  const t = '[signal:stop]a[/signal] [signal:caution]b[/signal]'
  assert.deepEqual(flat(run(t).planned), flat(run(t).planned))
})

test('the guidance teaches the grammar and the limits', () => {
  for (const needle of ['[signal:stop', '[signal:caution]', '[signal:go;check=', '[whisper:', 'at most 3 signals', '2 whispers', 'nest']) {
    assert.ok(GUIDANCE.includes(needle) || GUIDANCE.toLowerCase().includes(needle.toLowerCase()), needle)
  }
  assert.ok(!/consent/i.test(GUIDANCE))
})
