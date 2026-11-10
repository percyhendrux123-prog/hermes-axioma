# A342 handoff: Axiōma 0.6.0

## STATUS: unshipped; final completion blocked on host capabilities

Both requested pieces are implemented and locally exercised. No push, remote change, deploy,
plugin installation or live data change was performed. This is not native Desktop acceptance.

- Repository: `/home/cua/repos/hermes-axioma`
- Branch: `inline-card`, based exactly on `1c171771de51ad3219824e893ee38461d34102d9`
- Final production-code commit: `d86b5c99ab419dddee2cce0ae160e4ff114d3302`
- Final test commit: `3a27b04f3a3a635494613dcc10f998b5633c8249`
- Actual test-output commit: `22e9b8a664a9a7a7950a0b490fceb13cdc964094`
- Use the entire branch history, not only the last source commit: per the card, every edited file
  was checkpointed in its own commit. Later commits are disclosure/handoff evidence only.

## CHANGED

- Optional `axioma` transcript directive, plain bounded attrs, day/night palettes, signal, affects,
  question, optional green resolution, Hold / Go ahead, and the human-decision notice.
- Session-targeted replies with streaming and one-click locks; insert-only fallback; older hosts
  without an owning session id fail closed rather than address another active chat.
- Desktop-only per-turn model guidance. Directive attributes remain opaque to legacy span transforms.
- Additive nullable `events.task_id` migration; task-worker signal excerpt limited to 160 characters.
  Non-task audit remains hash-only. Old rows and sealed metadata are preserved.
- Read-only profile-local board projection, worst light wins, latest signal sentence/excerpt and
  observation count; pure synchronous one-badge decoration, throttled scoped cache and stale-data removal.
- Independent default-on Inline cards and Board lights switches, version 0.6.0, README and catalog disclosures.

Files changed:
`__init__.py`, `axioma/advisor.py`, `axioma/audit.py`, `axioma/signal.py`,
`dashboard/manifest.json`, `dashboard/plugin_api.py`, `desktop/plugin.js`, `plugin.yaml`,
`README.md`, `CATALOG-DISCLOSURE.txt`, `tests/desktop_check.mjs`, `tests/test_inline_board.py`,
`tests/test_advisor.py`, `tests/test_fingerprint.py`, `tests/test_signal.py`, `tests/test_whisper.py`,
plus this handoff, `docs/A342-REVIEW-BRIEF.md`, `docs/evidence/a342-local-checks.txt`.

## VERIFIED EVIDENCE

Actual full output: `docs/evidence/a342-local-checks.txt`.
Python 3.12.3, Node v24.21.0. Test-only venv: `/tmp/a342-tests` (FastAPI/httpx/PyYAML; no Hermes).

```text
$ python3 -m unittest discover -s tests
Ran 308 tests in 13.173s
OK (skipped=14)
exit=0

$ HERMES_KANBAN_TASK=t_synthetic python3 -m unittest discover -s tests
Ran 308 tests in 13.219s
OK (skipped=14)
exit=0

$ node tests/desktop_check.mjs
91 passed, 0 failed
exit=0

$ node --check --input-type=module < desktop/plugin.js
exit=0

$ git diff 1c17177 --check
exit=0
```

The current FastAPI/Starlette TestClient prints a third-party httpx deprecation warning, preserved
in the output. The 14 skips require a Hermes runtime. Baseline system Python was 294 OK, 16 skipped;
PyYAML in the test venv enables the two former YAML skips, and 14 new tests were added.

Tests cover real SQLite old-DB migration and byte-preserving HTTP GET, a real FastAPI router loaded
standalone like the host, actual signal producers, worst-light/count/latest separation, worker and
non-worker environments, and SDK-stubbed directive rendering/actions/badge registration/refresh.
The added-production-line security scan found no shell injection, unsafe deserialization or SQL
interpolation patterns. Its secret-pattern match was the non-secret generated placeholder
`token = 'AXIOMADIRECTIVE' + uuid.uuid4().hex`, not a credential. This is not admission validation.

### Composer finding

Provided v0.23.0 `apps/desktop/src/sdk/composer.ts:119-126` has
`host.composer.submit(sessionId, text) -> boolean`. Therefore these cards **submit**, not just insert.
They submit only `Hold.` / `Go ahead.` in the card's owning chat. Insert-only hosts use
`insertText(sessionId, text)` and explicitly say the user must review/send the draft. Neither path
answers a host approval prompt, approves a tool call or executes the proposed action.

### API mechanism

The authoritative Desktop SDK docs expose `ctx.rest`; `host.request` is JSON-RPC, not HTTP.
`ctx.rest('/board-lights', {method:'GET', timeoutMs:10000})` reaches the plugin's authenticated,
profile-aware namespace. `dashboard/manifest.json` declares `api: plugin_api.py`, with a hidden tab.
The provided v0.23.0 `hermes_cli/web_server_dashboard.py:1181-1248` imports it standalone and mounts
its FastAPI APIRouter under `/api/plugins/hermes-axioma` with host profile/enable gates.
Only GET `/board-lights` is implemented. It returns `{task_id: {light, count, signal, at}}`.
The route resolves the active home without creating directories, then opens the existing audit in
SQLite `mode=ro`. Missing/unmigrated DBs return `{}`. `decorate` never reads files, messages or tools.

### Adversarial review

Required native command was attempted with the saved brief:

```text
hermes -p codereview chat --query-file /home/cua/repos/hermes-axioma/docs/A342-REVIEW-BRIEF.md -Q
bash: hermes: command not found
exit=127
```

No Hermes install or profile configuration workaround was attempted. Two supplemental independent,
read-only subagent passes were run, not misrepresented as native codereview-profile approval.
Every concrete finding was reproduced by a failing regression and fixed:
1. Legacy tags inside attrs mutated cards into KaTeX and double-counted: protect directive data.
2. Case duplicates, padded keys and UTF-16 limits diverged: match frontend normalization/host length.
3. `plugin_data_dir` created directories on GET: resolve the documented profile path without mkdir.
4. Python Unicode attr/whitespace grammar diverged: ASCII names plus exact JavaScript whitespace.

After the final fix, all full checks above passed. No third review pass was run (two-pass maximum).

## RISKS / ASSUMPTIONS

- **No passing Standing proof yet.** This worker called `standing_proof` for the exact Space git
  command. `standing:80` returned `unavailable`: command not on the owner's read-only list. No pass
  or demotion. Host file proofs cannot see Space files; an approved reachable command/HTTP target
  must be supplied and checked in the worker session before marking this task done.
- **Native codereview, `hermes plugins validate`, live Desktop and authenticated `ctx.rest` transport
  remain unverified here.** AXIOM owns the host checks; the Space has no Hermes executable by design.
- **Board data is active-profile-local.** `plugin_data_dir` follows the current profile. A task whose
  worker wrote into a sibling profile's audit will have no badge in this profile. No sibling DB scan,
  cross-profile union, cross-board rollup or undocumented channel was invented. AXIOM must accept
  this visibility boundary or explicitly authorize a separate design change.
- **Compatibility:** all three new Desktop contracts and session targeting exist in v0.23.0 refs.
  The existing `requires_hermes >=0.22.5` floor may be wrong for these Desktop features; it is retained
  with explicit warning rather than guessing their first release. Native host acceptance is needed.
- Model-written GO is not permission or verified approval. Board count means observations, not
  authorizations, unique actions or an exactly-once ledger; repeated final transforms can add counts.
- A 160-character signal excerpt is new task-worker retention. It is not secret-scrubbed; do not put
  sensitive words in signals. Full messages, task prose, questions, affects and raw tool args are not
  returned by the route. Disabling renderer switches stops UI/reads, not Python audit retention.
- The one-click lock survives re-renders of the mounted card, not reload or host remount.

## APPROVAL NEEDED / NEXT

AXIOM: export `inline-card` through the approved Space-to-host flow while the Space is still alive;
run native codereview with the saved brief, plugin validation, and real Desktop checks (both themes,
streaming/one-click actions, split-chat targeting, switches, board refresh and profile changes).
Provide an owner-allowlisted read-only Standing target for this worker session. No follow-up cards
were created; AXIOM's session owns the next step. No production deployment or push is authorized here.

## SAFE ROLLBACK

Code baseline: `1c171771de51ad3219824e893ee38461d34102d9`. No live DB was touched in this Space.
Before enabling 0.6.0 on host, preserve a local pre-upgrade audit DB backup. A code-only rollback to
0.5.2 is insufficient after migration: its old INSERT uses positional three-column VALUES and cannot
write to a four-column events table. Roll back code **and** the pre-upgrade DB copy under owner
control, or retain the explicit-column writer; do not delete live records or run an unapproved
down-migration. This handoff does not perform any rollback or live data operation.
