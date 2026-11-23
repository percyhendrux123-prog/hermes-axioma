// Which calls get a card (node:test). Harmless stand-in commands only; nothing here runs a command.
import test from 'node:test'
import assert from 'node:assert/strict'
import { classify, scrubs, unparsed, lex } from '../axioma/hooks/lib/classify.mjs'

const bash = (command, opts) => classify('Bash', { command }, opts)

test('plain commands get no card', () => {
  for (const c of ['date', 'echo hello', 'ls -la', 'git status', 'git log --oneline', 'cat notes.txt', 'npm test', 'grep -r "push" .']) {
    assert.deepEqual(bash(c).categories, [], c)
  }
})

test('send: git push, gh pr create/merge, and messaging/posting tools', () => {
  assert.deepEqual(bash('git push origin main').categories, ['send'])
  assert.deepEqual(bash('git -C repo push').categories, ['send'])
  assert.deepEqual(bash('gh pr create --fill').categories, ['send'])
  assert.deepEqual(bash('gh pr merge 4').categories, ['send'])
  for (const t of ['mcp__mail__send_email', 'mcp__chat__send_message', 'mcp__chat__post_message', 'mcp__social__create_post', 'mcp__x__post_tweet', 'mcp__blog__publish_page']) {
    assert.deepEqual(classify(t, {}).categories, ['send'], t)
  }
})

test('spend: payment tools', () => {
  for (const t of ['mcp__pay__create_payment', 'mcp__pay__confirm_payment', 'mcp__pay__capture_payment', 'mcp__shop__create_checkout', 'mcp__shop__create_purchase', 'mcp__pay__create_charge', 'mcp__pay__create_refund']) {
    assert.deepEqual(classify(t, {}).categories, ['spend'], t)
  }
})

test('spin: deploys, scheduled jobs, cron', () => {
  assert.deepEqual(bash('vercel deploy --prod').categories, ['spin'])
  assert.deepEqual(bash('npm run deploy').categories, ['spin'])
  assert.deepEqual(bash('kubectl apply -f x.yaml').categories, ['spin'])
  assert.deepEqual(bash('terraform apply').categories, ['spin'])
  assert.deepEqual(bash('docker push img').categories, ['spin'])
  assert.deepEqual(bash('crontab -l').categories, ['spin'])
  assert.deepEqual(classify('CronCreate', {}).categories, ['spin'])
  assert.deepEqual(classify('mcp__sched__job_create', {}).categories, ['spin'])
})

test('a PowerShell command is checked against the same send and spin rules', () => {
  assert.deepEqual(classify('PowerShell', { command: 'git push' }).categories, ['send'])
})

test('categories keep a fixed order and can combine', () => {
  assert.deepEqual(bash('git push && rm old.txt').categories, ['send', 'scrub'])
})

test('scrub: every remove or move is flagged when no workspace is set', () => {
  for (const c of ['rm file.txt', 'rm -rf build', 'mv a b', 'unlink x', 'rmdir d', 'RM x', 'sudo rm x', '(rm x)', 'echo hi; rm x', 'ls | xargs rm']) {
    assert.deepEqual(bash(c).categories, ['scrub'], c)
  }
})

test('scrub: deletion computed elsewhere is always flagged', () => {
  for (const c of ['find . -name "*.o" -delete', 'find . -exec rm {} ;', 'rsync -a --delete src/ dst/', 'git clean -fd', 'git -C x clean -n']) {
    assert.deepEqual(bash(c).categories, ['scrub'], c)
  }
})

test('scrub with a workspace: absolute paths inside it skip the card, outside get one', () => {
  const o = { roots: ['/work/project'] }
  assert.deepEqual(bash('rm /work/project/a.txt', o).categories, [])
  assert.deepEqual(bash('mv /work/project/a /work/project/b', o).categories, [])
  assert.deepEqual(bash('rm /work/other/a.txt', o).categories, ['scrub'])
  assert.deepEqual(bash('rm /work/project/../other/a.txt', o).categories, ['scrub'])
  assert.deepEqual(bash('rm /work/projectile/a', o).categories, ['scrub'])
})

test('scrub with a workspace: unknown shapes are never assumed contained', () => {
  const o = { roots: ['/work/project'] }
  assert.deepEqual(bash('rm a.txt', o).categories, ['scrub']) // relative, cwd unknown
  assert.deepEqual(bash('rm a.txt', { ...o, cwd: '/work/project' }).categories, [])
  assert.deepEqual(bash('rm /work/project/*.o', o).categories, ['scrub']) // glob
  assert.deepEqual(bash('rm -r /work/project/dir', o).categories, ['scrub']) // recursive
  assert.deepEqual(bash('rm --recursive /work/project/dir', o).categories, ['scrub'])
  assert.deepEqual(bash('rm --rec /work/project/dir', o).categories, ['scrub'])
  assert.deepEqual(bash('cd /tmp && rm /work/project/x', o).categories, ['scrub'])
  assert.deepEqual(bash('rm $F', o).categories, ['scrub'])
  assert.deepEqual(bash('rmdir -p /work/project/a/b', o).categories, ['scrub'])
  assert.deepEqual(bash('rm', o).categories, ['scrub'])
  assert.deepEqual(bash('mv -t /work/other /work/project/a', o).categories, ['scrub'])
})

test('a command that only mentions rm in text is not a remove', () => {
  assert.deepEqual(bash('echo "how to rm a file"').categories, [])
  assert.deepEqual(bash('git commit -m "rm old files"').categories, [])
  assert.deepEqual(bash('ls rmdir-notes').categories, [])
})

test('could not parse: a hidden command name is flagged and marked unparsed', () => {
  for (const c of ['$DEL x', '"$(echo rm)" x', 'r{m,} x', '/bin/r? x', 'rm ";" x', "rm '#a' b"]) {
    const r = bash(c)
    assert.ok(r.categories.includes('scrub'), c)
    assert.equal(r.unparsed, true, c)
  }
  assert.equal(bash('rm a.txt').unparsed, false)
  assert.equal(unparsed('echo hi'), false)
})

test('lex reads quotes, escapes and separators', () => {
  const segs = lex("echo 'a b' \"c d\" e\\ f; rm x | cat")
  assert.deepEqual(segs.map((s) => s.map((w) => w.text)), [['echo', 'a b', 'c d', 'e f'], ['rm', 'x'], ['cat']])
  assert.throws(() => lex("echo 'open"))
})

test('an unterminated quote falls back to a coarse check', () => {
  assert.equal(scrubs("rm 'x"), true)
  assert.equal(scrubs("echo 'x"), false)
})

test('scrub can be switched off', () => {
  assert.deepEqual(bash('rm x', { scrubEnabled: false }).categories, [])
})

test('known blind spots are really blind: bash -c, eval and ssh bodies are not read', () => {
  // Documented limit. The call is classified by its outer command only.
  assert.deepEqual(bash("bash -c 'rm x'").categories, [])
  assert.deepEqual(bash("ssh host 'rm x'").categories, [])
  assert.deepEqual(bash("eval 'rm x'").categories, [])
})
