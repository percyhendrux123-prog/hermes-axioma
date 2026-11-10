# A342 adversarial review brief

Goal: Axiōma 0.6.0, optional ::axioma inline advice cards and kanban lights. Local branch only.
Repo: /home/cua/repos/hermes-axioma
Baseline: 1c171771de51ad3219824e893ee38461d34102d9
Candidate: inline-card (review current tip). No pushes, remotes, installation into profiles or live data.

Try to break the implementation against the list below. Report concrete defects only with a
reproduction and file/line citations. Read-only review: do not edit/commit, install Hermes, fetch
other repos, use credentials or access client data. Test text and databases are synthetic.

## Acceptance
- Named axioma directive at transcript.directives; Inline cards default on and unregisters when off.
- Card shows stop/caution/go/whisper words and existing day/night palettes, signal, affects, question,
  Hold / Go ahead; optional green on stop. Unknown light neutral. No HTML/Markdown rendering.
- Allowlisted attrs, length caps, remove controls/bidi. Malformed or missing required attrs renders
  original source plainly without buttons, no throw. Host parser is lenient so source validated too.
- Buttons submit Hold. / Go ahead. through host.composer.submit(props.sessionId,text), never active
  chat fallback. Insert-only fallback explicit. Disable while streaming and after first click.
  All cards say Axiōma advises, the person decides. GO is not permission or verified approval.
- pre_llm_call advertises directive only when advisor.safe_surface() is desktop, checked per turn;
  no directive instruction on CLI, messaging, dashboard, acp or unknown surface.
- Each audit write reads HERMES_KANBAN_TASK. Additive, idempotent old-DB migration; no old seals broken.
- Read-only GET /api/plugins/hermes-axioma/board-lights returns only task-id keyed light/count/signal/at.
  No raw args, whole messages/task prose, audit digests/metadata or paths. Latest sentence/excerpt <=160.
  No DB mutation on GET; empty for missing/old unassigned DB. Worst stop>caution>go>whisper wins;
  count signal observations + presented_to_host, not stage/answer lifecycle duplicates.
- Board lights default on, can unregister/stop reads; decorate synchronous pure lookup, unknown null.
  One badge/plugin/card, label <=24, tooltip <=160, correct host tone red/yellow/green (whisper neutral).
  ctx.rest GET only, refresh starts no more than once/30s even rapid toggles, no stale profile cache or
  late in-flight response after scope switch/disable/dispose. Failed reads clear stale badges.
- Version 0.6.0. README + catalog disclosure describe both switches, API, audit task column and new
  task-only 160-char signal retention. No cross-profile claims. Non-task audit keeps no signal text.
- v0.23.0 refs confirm directives/sessionId/composer.submit/card.badges. Existing >=0.22.5 agent floor
  retained with explicit Desktop compatibility uncertainty, no invented minimum version.

## Files to inspect
__init__.py, axioma/advisor.py, axioma/audit.py, axioma/signal.py,
dashboard/manifest.json, dashboard/plugin_api.py, desktop/plugin.js,
plugin.yaml, README.md, CATALOG-DISCLOSURE.txt,
tests/test_inline_board.py, tests/test_fingerprint.py, tests/desktop_check.mjs.

## Checks
- /tmp/a342-tests/bin/python3 -m unittest discover -s tests
- node tests/desktop_check.mjs
- git diff 1c17177 --check
Baseline system Python: 294 OK, 16 skipped; test venv with PyYAML executes 2 formerly skipped tests.
Latest: 304 OK, 14 host-runtime skips; Desktop 81 passed, 0 failed.
The test venv contains FastAPI/httpx/PyYAML only; Hermes is intentionally absent. FastAPI's latest
TestClient currently emits a third-party httpx deprecation warning; do not confuse it with a plugin bug.

## Contract evidence / boundaries
Provided Hermes v0.23.0 source /home/cua/hermes-ref:
- apps/desktop/src/lib/transcript-directives.ts: props/sessionId and data render contract.
- apps/desktop/src/sdk/composer.ts: submit(sessionId,text) is available, fail closed on absent surface.
- apps/desktop/src/contrib/kanban-card-badges.tsx: pure decorate, caps and memoization.
- hermes_cli/web_server_dashboard.py: discovery dashboard/manifest.json/api; standalone module import,
  APIRouter mounted under /api/plugins/<name>, host auth/profile/consent gates.
Authoritative Desktop SDK docs confirm ctx.rest(namespaceRelativePath,{method,timeoutMs}), profile-aware:
https://hermes-agent.nousresearch.com/docs/developer-guide/desktop-plugin-sdk

Unverified: native host validation/live Desktop, actual authenticated ctx.rest path, package admission,
cross-profile worker visibility (deliberately not added), v0.22.5 Desktop compatibility. The directive
is recorded as advice, not a cryptographically verified screen observation. Mounted click latch does
not survive reload. Counts are observations, not exactly-once ledger events. Excerpts are not secret-scrubbed.
Standing proof standing:80 unavailable: exact Space git command not owner-allowlisted. No passing proof yet.
