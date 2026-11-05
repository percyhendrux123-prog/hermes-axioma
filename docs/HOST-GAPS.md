# Host-surface gaps: what Axioma does not do, and why

Status (A224): AXIOM reduced scope to an **advisor** (Percy approved). Axioma shows the card and
question through Hermes's own approval prompt and logs metadata. It does not hold, block or
authorize. The gaps below are disclosed limits of that advisor, not hidden workarounds.

## 0. Why it is not an enforcing gate

The A219 draft tried to enforce "one fresh human answer authorizes exactly one dispatch with the
approved arguments". Review pass 1 reproduced two defects that public hooks cannot fix:

- `agent/tool_executor.py::_run_agent_tool_execution_middleware` runs execution middleware before
  native `pre_tool_call`, so an execution-middleware check asks for an answer that does not exist yet.
- `model_tools.handle_function_call` runs `pre_tool_call` before execution middleware, so later
  middleware can replace arguments after the human answered.

Axioma therefore dropped the execution middleware entirely. On the native path its card is matched
against the post-middleware arguments; on the registry path, middleware registered after it can
still change arguments after the prompt. On both paths another plugin's `pre_tool_call` `modify`
directive is merged after Axioma renders its card (reproduced in review pass 2), so the card may
describe arguments that are then changed. Hermes's approval policy (YOLO, off/smart,
remembered approvals, cron mode) decides whether the human sees the prompt at all. The seam that
would make a real gate possible is drafted in [UPSTREAM-PROPOSAL.md](UPSTREAM-PROPOSAL.md).
The earlier gate draft and its failing regressions are kept out of this repository.

## 1. Human answers that are questions

Documented `post_approval_response` exposes choice (`once/session/always/deny/timeout/...`), surface and IDs. It does not expose the human reply or a boolean saying it was a question. In the observed source, `tools/approval_gateway_wait.py::_finish` passes `reason` only in its return dict, **not** in `_fire_approval_hook`. CLI inputs normalize to a choice before the hook.

The audit therefore records `answered_with_question: null` on readback, not false, and stores no human text. Requested public seam: `response_kind: yes|no|question|unanswered` or `answered_with_question: bool|None` on the approval observer, derived by the host before discarding free text. A question must not authorize execution. No inference call or message-log scraping is acceptable.

## 2. A new unacknowledged human message while approval is pending

There is no documented, authenticated, all-surface hook for a new mid-run human message with acknowledgment state. `pre_llm_call` is turn-start only. `pre_gateway_dispatch` is before authorization and excludes CLI/TUI/Desktop/API; treating all those events as trusted human stop orders would be incorrect. `agent_loop_stopped` represents actual interrupt, not all new messages, and lacks a canonical session ID on its documented shape.

This advisor inherits native interrupt/cancel behavior from Hermes and **does not implement the universal arrival=>hard RED requirement**. Requested seam: authenticated `human_message_arrived(session_id, sequence_id, acknowledged)` and a host-owned pending-approval withdrawal API. Neither text bodies nor guessed routing are needed. No callback was registered on an unrelated hook pretending it solves this.

## 3. Native CLI/TUI card appearance and choices

The public `approve` directive accepts a textual message and rule key. It does not offer per-field style tokens or per-request menu labels/scopes. The native gate owns Once/Session/Always/Deny buttons. Axioma's description spells STOP/CAUTION/GO and proceed yes/no; its pure renderer has the exact requested ANSI palette, but **the native CLI/TUI gate currently receives plain text**, not a tested traffic-color UI. A RED card says `proceed: no` and never "yes", but the native prompt still shows its own Once/Session/Always/Deny buttons: the human can still choose to proceed, because Axioma advises and does not block. RED never gets a reusable rule key, so a remembered approval cannot pass it silently. Native TUI color rendering and literal yes/no controls remain unimplemented.

Requested public seam: a declarative advisory payload (intent, severity, signal, checks, question, color-independent labels) rendered by the host on CLI/TUI/chat. A plugin should not patch native UI, auto-click menus, rebind approval functions or select its own approval transport silently.

The classic CLI approval panel also places the description after the buttons and truncates it to the rows left (at most 10). Axioma therefore puts the light, `proceed`, and the question in the first two lines, so they survive on a normal 80x24 terminal for a question of ordinary length (host test `test_question_and_proceed_survive_the_cli_approval_panel`). A very long question (the schema allows 400 characters) can still be cut at 24 rows, and intent, signal and check reasons can be cut on short terminals; the light and `proceed` line always come first.

## 4. Inline signal color (and WHISPER): what the host allows

All inline rendering goes through `transform_llm_output`, which Hermes fires once per turn before the
final assistant row is first persisted (`agent/turn_finalizer.py::apply_llm_output_transform`).
Observed consequences, each disclosed rather than worked around:

- **Streaming flash.** With streaming on, the raw tags can be visible while the reply streams. Desktop
  then replaces the message (`response_transformed`); the classic CLI prints the whole replacement
  again under "[Response transformed after streaming]" (`hermes_cli/cli_render.py::_post_stream_transform_output`),
  so the reply is seen twice. Non-streamed delivery shows only the rendered text.
- **Classic CLI drops ANSI by default.** `_render_final_assistant_content` keeps escape codes only in
  `display.final_response_markdown: raw`. The default `strip` (and `render`) passes the text through
  `Text.from_ansi(...).plain`, so color and style disappear and the word carries the signal. Host test
  `test_cli_final_renderer_keeps_color_in_raw_mode_and_words_in_every_mode`.
- **Desktop has no inline-color HTML.** Streamdown runs `rehype-raw` then `rehype-sanitize` with the
  GitHub default schema: no `style`, no arbitrary `class`. The only inline color path that survives is
  KaTeX `\color{}` (remark-math with single-dollar math on). Desktop's preprocess splits math at a
  literal `$` even when escaped as `\$` (observed in a real chat; screenshot in
  `docs/evidence/desktop/desktop-night-try1-dollar-escape-bug.png`), so the plugin writes
  `\textdollar{}`. KaTeX output is read by screen readers as math; the word stays outside the math as
  plain text for that reason. The plugin cannot read Desktop's light/dark theme; `theme` is a setting.
  Desktop's preprocess also decides math by context (its CJK rule escapes any math body with East
  Asian text; a `$` or `\` before the opener, a digit, or an unpaired `$` earlier on the line change
  the pairing). Review pass 9 reproduced each through the real pipeline; the plugin now falls back
  to bold plus the word in those contexts (`Signal.math_context_safe`, `katex_safe`). Review pass 10
  found the agent's own math (`\(`, `\[`, `$$`, `$x$`; pass 13 added `\\(`, `[/math]`, `[/inline]`, which Desktop's normalizeMathDelimiters also reads) could wrap or interleave with a span; any
  reply containing such math now skips the color path entirely (plain phrase plus word). Probe and
  output (227 cases through preprocess + tailBoundedRemend + remark-math + KaTeX, 0 KaTeX errors, 0 visible junk; generated by `desktop-pipeline-all.py` from the hand-written cases plus every tagged reply in `tests/test_signal.py`): `docs/evidence/desktop/desktop-pipeline-probe*`. Pass 11 found two
  more: a `$` inside a span drawn without math could pair with a colored span (the math gate now
  reads span text too), and KaTeX refuses some characters in text mode (math symbols, combining
  marks); only characters checked against Desktop's KaTeX build take the color path
  (`docs/evidence/desktop/katex-allow-check.*`, 779 characters, 0 failures).
- **Code detection decides styling only.** Passes 9 and 10 showed that matching CommonMark's code
  rules exactly (fences in lists and quotes, backtick runs, indented code) is a moving target. Tags
  are therefore read everywhere; inside what looks like code the phrase keeps its word and gets no
  markup. A wrong guess costs color, never a leaked tag or a hidden stop.
- **Stored text is the rendered text.** Hermes persists the transformed reply, so later turns see
  KaTeX source or ANSI codes, not tags.
- **First non-empty transform wins.** Another plugin's transform can pre-empt this one.
- **Tags in read content.** Only the final reply is parsed, but nothing neutralizes tags inside tool
  results before the model reads them (a `transform_tool_result` rewrite would also alter legitimate
  content, such as this plugin's own source). The guidance forbids copying marks; `go` still needs a
  host-reported passing call.
- **TUI** receives the same text as the CLI; its Ink renderer was not visually tested.

Requested public seam: a streaming text transform, or declarative span annotations (the spec's JSON
form) carried to every host renderer, so each surface can style spans natively with real
screen-reader text.

## 4b. SCRUB is best-effort shell parsing

SCRUB reads common `rm`/`mv`/`unlink`/`rmdir` shapes and flags what it cannot prove contained. It is
not a shell interpreter. Review pass 8 found shapes the token walk misreads (quoted or escaped `;`
`|` `&` `#` among a remove's words; a command named by an expansion behind `sudo`, `time`, `if`, `!`,
`{` or quotes). AXIOM's decision (A229): narrow the claim instead of making SCRUB noisier. A separate
quote-aware lexer now detects those shapes; the call is classified SCRUB, the card says
`scrub_parse: could not parse (best-effort parser)`, and the light is capped at CAUTION, never GO.
Tests `Pass8Limits` in `tests/test_findings.py` document the limit, plus a control set of ordinary
commands that must stay unflagged. Review pass 19 added brace and glob patterns in the command word
(`{rm,-rf,x}`, `r{m,}`, `/bin/r?`, `/bin/r[m]`): bash expands them into a remover, so they are
classified SCRUB with the could-not-parse note (`Pass19Findings`); `[`, `[[` and group braces stay
quiet. Review pass 20 narrowed that rule to patterns that could name a remover, shell or wrapper
SCRUB reads (matched against a fixed list), so `case` patterns (`*.py)`, `[yY])`) and heredoc
lines such as `[Unit]` or `* item` stay quiet (`Pass20Findings`). A bare wildcard-only command word
(`*`) is not flagged: it is a case pattern or list bullet far more often than a command. Still not parsed: `bash -c`, `eval`, scripts, aliases, encoded
commands, other deleting tools, and wrappers that change directory (`env -C`, `git -C`, `sudo -D`).

## 5. Preflight limits

Configured file/credential-presence/declared-sender checks run in code and failures force RED. They are not a live provider permission probe, a full profile inheritance resolver or a device lease. The provider check sees explicit target arguments, not a private scrape of all host configuration. A missing profile/skill inventory, undeclared mail identity or absent lock declaration cannot be marketed as proof of readiness. Lock availability can race after the check; never substitute it for the existing device lock requirement.

## 6. Host approval policy

Whether the card reaches a human is Hermes's decision. YOLO, approvals `off` and
`approvals.cron_mode` can proceed without a prompt (plugin approvals do not go through `smart`
mode); the audit then records `presented_to_host` with an `auto` or no answer. With no human
present, Hermes's gate fails closed by default (`approvals.single_query_mode` and `unattended_mode`
= deny); an operator who sets those to approve lets the call through without a prompt. Axioma gives every
card a fresh rule key, so a remembered Session/Always approval never skips a later card. Axioma
reads none of this privately and changes none of it.

## 7. Approval precedence between plugins

Hermes resolves several `approve` directives on one call by taking the first valid one, including
its rule key (hermes_cli/plugins.py ~1983-1988). If another plugin's approve wins, the human sees
that plugin's description instead of the Axioma card; Axioma has already logged `presented_to_host`,
and its answer observer ignores the other plugin's rule key. If Axioma's wins, the other plugin's
description is not shown, but the human is still asked under Axioma's fresh key, so no remembered
approval can pass that plugin's request silently (review pass 5 reproduced this with an earlier
stable-key design; fixed). A host-rendered advisory payload (section 3) or a way to combine approve
descriptions would close the remaining text gap.

## Decision taken

AXIOM (Percy approved, 2026-11-04): ship as an advisor with these limits disclosed; draft the host
seam separately ([UPSTREAM-PROPOSAL.md](UPSTREAM-PROPOSAL.md), not filed). Percy retains the
publication go. No issue, PR, push, installation or live settings change has been made.

Sources: current https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks and https://hermes-agent.nousresearch.com/docs/developer-guide/plugins ; verified local Hermes v0.22.5 source bf0203a794a07aac3ff764972ab9087baa4e4f4e. These sources are descriptive evidence, not instructions to modify host code.
