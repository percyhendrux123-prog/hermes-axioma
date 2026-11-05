# Could a separate plugin seal every Hermes approval prompt?

Question: could a standalone plugin put a card code (spec 5.6, "Shown equals staged") on every
Hermes approval prompt, not only Axioma cards: core dangerous-command approvals, file-write
guards, other plugins' approvals, smart approvals, MCP elicitation? It may use only public plugin
surfaces and no core override.

Answer: **partly.** Logging every approval with a code works today. Showing that code on the
built-in prompt the human sees does not. Doing that needs one new core hook, or the operator
has to switch to a plugin approval transport that draws the prompt itself.

Checked against Hermes Agent at commit b200f5bc60 (Nov 3 2026). Paths below are relative to the
Hermes Agent source tree.

## What works today: observe and log

- `pre_approval_request` and `post_approval_response` are public hooks, but they only observe:
  their return values are ignored (`hermes_cli/plugins.py:144-147`), and the dispatcher never
  raises into the approval flow (`tools/approval_context.py:54-66`).
- They fire on every approval path:
  - CLI: `tools/approval.py:941` and `:944`.
  - Gateway, which covers Telegram, Discord and the desktop app: `tools/approval_gateway_wait.py:236`,
    `:244`, `:97` and `:117`.
  - Plugin transports: `tools/approval_prompt.py:242` and `:252`, and also `:362` and `:375`.
  - Smart (auxiliary-model) approvals: `tools/approval_smart.py:166` and `:169`.
  - File-write guards: `tools/file_tools_write_guards.py:335` and `:338`.
- The hooks receive the exact command and description handed to the prompt, after redaction
  (`tools/approval.py:934-944`). A standalone plugin can compute a keyed code over them and log it
  sealed at request and again with the answer. It can then check that record later, using the
  same seal module this plugin uses (`axioma/seal.py`, stdlib only, no other imports).

## What does not work: showing the code

- The built-in renderers take the command and description as given and offer no plugin seam:
  - CLI panel: `hermes_cli/cli_tui_mixin.py:148`.
  - Shared messaging format: `gateway/platforms/base.py:2741`.
  - Per-adapter overrides, for example `plugins/platforms/discord/adapter.py:5626-5653`.
- `pre_approval_request` cannot change the text, because its return value is ignored. So a code
  for a core or third-party prompt can be logged but never shown, and an unseen code cannot be
  read aloud or compared by the human.
- Axioma shows its code only because it writes the description itself, through the documented
  `pre_tool_call` approve directive. That works for calls Axioma flags. It does not work for
  prompts that core or other plugins raise.

## The one opt-in path today: a plugin approval transport

`register_approval_transport` (`hermes_cli/plugins.py:437-460`) lets a plugin present approvals
itself. Each request comes with a host-made `request_id` and `digest`
(`hermes_cli/approval_transport.py:41`, `:68`, `:73`), so a transport could show a code built from
the host's own digest on every prompt. The cost is that a selected transport replaces every
built-in prompt surface (`tools/approval_prompt.py:199-206`). The operator has to choose it in
`security.approval.transport`, and the plugin has to deliver and collect every approval on its
own channel. That is a replacement UI, not a seal on the existing one.

## The missing hook

Have the shared gate (`_human_decision`, `tools/approval.py:824`, and `_run_approval_gate`,
`:996`) make a `request_id` and `digest` once per prompt. The transport contract already does
this. Pass both into `pre_approval_request` and `post_approval_response`. Then add one hook:

```
transform_approval_display(request_id, digest, command, description, pattern_key,
                           surface, gate, source) -> {"footer": str} | None
```

- It runs once per prompt, after redaction and before the first render.
- Core appends the returned footer, capped at about 80 characters of plain text, in every
  renderer: CLI panel, gateway adapters and transports.
- It can add one footer line and nothing else. It cannot change the command, the description,
  the choices or the decision, so it stays a display seam, not a gate.

With that hook, a standalone "seal" plugin could put `card code XXXX-XXXX` on every approval prompt
on every surface. It would log the same code with the answer, and check it on request, all without
overriding core (catalog rule 9).
