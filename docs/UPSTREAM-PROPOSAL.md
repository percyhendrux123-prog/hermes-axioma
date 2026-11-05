# DRAFT: upstream proposal for a final-authorization plugin seam

**Status: draft only. Not filed.** Intended as a Nous Research hermes-agent issue. AXIOM and Percy
decide whether and when it is filed. Observed against Hermes v0.22.5,
`bf0203a794a07aac3ff764972ab9087baa4e4f4e`.

## Summary

Plugins can ask Hermes to request human approval for any tool call (`pre_tool_call` →
`{"action": "approve"}`), but they cannot reliably know that **the arguments the human approved are
the arguments that run**, or that **a fresh human, not a remembered or automatic policy, answered
for this one dispatch**. We propose one small host-owned hook that fires at the last point before
dispatch, with final arguments, and a per-request approval option that only a live human can satisfy.

## Problem (reproduced, synthetic data)

1. **Hook order differs between the two dispatch paths.**
   - Registry path, `model_tools.handle_function_call`: `pre_tool_call` (and the approval prompt)
     runs **before** `tool_execution` middleware. A later middleware can replace the arguments after
     the human answered; a synthetic handler then receives the changed arguments.
   - Native agent path, `agent/tool_executor.py::_run_agent_tool_execution_middleware`: execution
     middleware runs **first**, then `pre_tool_call` inside `_dispatch_authorized_once` with the
     final arguments. A plugin that binds answers in execution middleware therefore checks before
     any approval exists.
   No single public surface sees "final arguments" on both paths. In addition, another plugin's
   `pre_tool_call` `modify` directive is merged after every hook has returned, so a hook that
   renders an approval description describes arguments that may then change.
2. **No way to require a fresh human.** `approve` goes through `request_tool_approval`, which
   correctly honors YOLO, approvals `off`/`smart`, remembered Session/Always keys and cron mode.
   A plugin that needs "a live human must answer this one" (payments, irreversible identity changes)
   has no public way to opt out of those for a single request, and no host-owned token that ties
   the answer to the one dispatch that follows.
3. **The approval observer loses the human's words.** `post_approval_response` carries a normalized
   choice; a free-text reply (for example a question back to the agent) is dropped, and the gateway
   `/deny` reason is not forwarded. Plugins cannot measure "the human answered with a question"
   without scraping transcripts, which they should not do.

## Proposal

### A. `pre_tool_dispatch` hook (final arguments, both paths)

Fires exactly once per dispatch, after all request/execution middleware and `modify` directives,
immediately before the registry handler runs, on both dispatch paths.

```python
def pre_tool_dispatch(tool_name, args, *, session_id, tool_call_id, turn_id, task_id,
                      approval_receipt=None, **kwargs) -> dict | None:
    # args: the final canonical arguments (read-only mapping)
    # approval_receipt: see B, or None if no approval happened for this call
    # return {"action": "block", "message": "..."} to veto; anything else proceeds
```

- `tool_name` is canonical (aliases such as `cronjob` → `cronjob_manage` already applied).
- Arguments are frozen after this hook; nothing downstream may change them.
- Same block precedence and fail-closed behavior as `pre_tool_call`.

### B. Fresh-human approval with a host-owned receipt

Extend the `approve` directive:

```python
{"action": "approve", "message": "...", "rule_key": "...", "require_fresh_human": True}
```

- `require_fresh_human: True` means YOLO, `off`, `smart`, remembered keys and cron auto-approval
  do **not** satisfy this request. With no human present it fails closed (as today).
- On a live human "once", the host issues an `approval_receipt`
  `{request_id, args_digest, decided_by: "human", choice, surface}` bound to this `tool_call_id`,
  and passes it to `pre_tool_dispatch`. If the final arguments' digest differs, the host (or the
  plugin, via A) can veto. Receipts are single-use and never persisted.

### C. Response kind on the approval observer

Add `response_kind: "yes" | "no" | "question" | "unanswered"` (or
`answered_with_question: bool | None`) to `post_approval_response`, derived by the host before it
discards free text. No reply text needs to reach plugins. A question must never count as approval.

## Why this is small

- A is one new hook call at the one place both paths already converge (the registry dispatch).
- B reuses the existing gate; it adds one flag and a receipt object.
- C is one field on an existing observer.
- No plugin needs private imports, monkeypatching or its own approval transport.

## What we did meanwhile

`hermes-axioma` ships as an advisor only: it shows a card through `approve` and logs metadata, and
says plainly that it is not a gate. With A and B it could offer an opt-in enforcing mode for
operators who want one.

## Tests we would contribute

- Native and registry paths: a later middleware rewriting arguments after a human "once" is
  vetoed by `pre_tool_dispatch` when the receipt digest differs.
- `require_fresh_human` under YOLO / off / smart / remembered key / cron: no execution without a
  live answer; unattended fails closed.
- Receipt replay: a second dispatch with the same receipt is vetoed.
- `response_kind` for CLI and gateway replies, including `/deny <reason>`.
