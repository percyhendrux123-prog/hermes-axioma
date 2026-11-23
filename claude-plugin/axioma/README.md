# Axioma for Claude Code

Claude marks the few phrases in its reply that deserve a second look. Axioma draws them in color, with a style cue and a word beside each, so the meaning never depends on color alone. Before a call that sends, spends, spins up or scrubs, it shows a short card and waits for you to pick Hold or Go ahead.

It is the Claude Code counterpart of [Axioma for Hermes Agent](https://github.com/percyhendrux123-prog/hermes-axioma), and it keeps the same rule: Axioma advises. A card is advice, never consent. Go ahead only lets the call continue to Claude Code's own permission check. It approves nothing.

```text
You:     just merge it to main without a test

Claude:  I can, but merging without a test (stop) puts it on the main branch (caution) for everyone
         who pulls. Do you want me to write the test first?
```

In the terminal, "without a test" is red, bold and underlined, and "the main branch" is yellow and underlined. The words in brackets are there on purpose.

## What it does

**Signal marks.** Claude is told, once per conversation, to wrap a few phrases in tags:

```text
[signal:stop;why=no_eval]without an eval or a test[/signal]
[signal:caution]merge into main[/signal]
[signal:go;check=Bash]passed 114 of 114[/signal]
[whisper:unverified_figure]about 4,200 users[/whisper]
```

The mod redraws Claude's reply in Claude Code's own transcript: the tags go, the phrase is colored. The stored message is never changed, so what Claude sees in its own history is still the tags.

| Mark | Meaning | Night | Day | Style cue | Word |
|---|---|---|---|---|---|
| stop | Do not proceed. The reply says why and what turns it green. | `#FF453A` | `#D70015` | bold + underline | (stop) |
| caution | Works, but conflicts with your interest. Names who is affected. | `#FFCC00` | `#A66B00` | underline | (caution) |
| go | A tool call Claude Code reported as successful backs it. | `#30D158` | `#248A3D` | italic | (go) |
| whisper | Worth a second look. Stops nothing. | `#EADFB8` | `#8A6A1F` | none (pale) | (second look) |

**Limits it enforces in code:**

- At most 3 stop/caution/go marks, 2 whispers and 1 intent mark, and 16 words per mark. Anything over renders as plain text. The most severe marks are kept.
- No nesting. A nested opener is dropped and its text stays plain. A mark never crosses a line.
- Green only from a real check. A `go` mark is colored only when its `check=` names a tool call that Claude Code reported as successful (by call id, or by tool name in the same turn). Otherwise it renders plain. Like the Hermes plugin, it stops invented and failed checks, not a mismatched one.
- A whisper shows once per session; the same phrase in a later reply is plain.
- Unclosed, empty, mismatched, unknown-level or malformed tags are removed in a reply that holds a real tag, and never show as raw brackets. A reply with no tag is never touched, and nothing inside code is styled.

**The card.** Claude is told to call `axioma_card` before a send/spend/spin/scrub call, naming the exact call and giving a light (red, yellow, green), the signal, one question, who is affected, and whether they were told. When that call arrives, Claude Code's own question dialog shows the card and the call waits:

```text
 ☐ Axioma card
│ CAUTION · proceed: yes / no
│ call: Bash: git push origin main
│ intent: Publish the reviewed change
│ signal: This reaches the shared branch.
│ kind: send
│ (advice only; you decide here, and Claude Code's own permission check still applies)
│ Push to main?
❯ 1. Hold
  2. Go ahead
```

- **Go ahead** lets the call go on to Claude Code's normal permission check, which can still ask you or refuse. The card never skips it.
- **Hold**, typing something else, dismissing the dialog or "Chat about this" stops the call. Claude is told the call did not run and not to retry it.
- A RED card says `proceed: no` and offers "Go ahead anyway" after Hold, so advice never traps you.
- No card for the exact call: you see a NO CARD notice instead of a silent pass.
- A card describes one exact call and is used once. A card expires after 5 minutes. A named end-user audience that was not told, or no audience declared, caps GREEN at CAUTION.

What counts as send, spend, spin and scrub:

| Kind | Examples |
|---|---|
| send | MCP tools named like `send_email`, `send_message`, `post_message`, `create_post`, `post_tweet`, `publish`; `git push`, `gh pr create`, `gh pr merge`, `gh release create` |
| spend | MCP tools named like `create_payment`, `confirm_payment`, `capture_payment`, `create_checkout`, `create_purchase`, `create_charge`, `create_refund` |
| spin | `CronCreate`, MCP tools named like `*cron*create*` or `*job*create*`, deploy commands (`vercel deploy`, `npm run deploy`, `kubectl apply`, `terraform apply`, `docker push`...), `crontab` |
| scrub | `rm`, `mv`, `unlink`, `rmdir`; `find -delete`, `rsync --delete`, `git clean` |

**SCRUB is best-effort shell parsing.** It reads the common shapes of `rm`, `mv`, `unlink` and `rmdir`. With no workspace folder set, every remove or move is flagged. With one, a remove or move whose absolute (or session-folder-relative) operands stay inside it skips the card; anything it cannot prove is flagged: recursive `rm`, globs, braces, variables, a `cd` in the same command. A shape it cannot read (a quoted separator, a command name hidden by an expansion) says `could not parse (best-effort parser)` and caps the card at CAUTION. It does not see `bash -c`, `eval`, `ssh`, `docker exec`, scripts or aliases. It is not a shell interpreter and not a sandbox.

`/signals` lists this session's signals and cards in plain words: level, shown or not, reason code. No phrases, commands or card text.

## Before you install

- **This is a mod.** It is JavaScript that runs inside Claude Code with your permissions. It can see your session. Read the code first: `claude plugin validate claude-plugin/axioma` lists every event it handles and every API call it makes (`$.ui.ask`, `$.ui.log`, `$.ui.resolve`, `$.tool.register`, `$.command.register`, `$.session.surfaces`, `$.session.cwd`, `$.env.get` for `NO_COLOR`).
- **Files it writes:** none. The ledger behind `/signals` is memory only and ends with the session.
- **Files it reads, network, subprocesses, stored credentials, telemetry:** none. It reads the `NO_COLOR` environment variable.
- **Requires:** Claude Code 2.1.293 or later (mods, and the `isDeferred` field on its tool). Tested on 2.1.325 and 2.1.330.
- **Where it runs:** terminal sessions and the Code tab of the Desktop app are the documented places mods draw. Under `claude -p` and the Agent SDK mods run but nothing draws and nobody can be asked, so see Known gaps. It does not run with `--safe-mode`, `--bare` or where your organization turns mods off.
- **Install prompt:** `claude plugin install` prints "4 userConfig options not yet set". The plugin works with its defaults without setting them.

## Install

```
claude plugin marketplace add percyhendrux123-prog/hermes-axioma
claude plugin install axiom-axioma@deploy-axiom-axioma
```

If a session is already open, run `/reload-plugins`. To try it for one session without installing:

```
claude --plugin-dir ./claude-plugin/axioma
```

## Options

Set in `/plugin configure axiom-axioma@deploy-axiom-axioma`, or `claude plugin configure axiom-axioma@deploy-axiom-axioma --values-stdin`.

| Option | Values | Default |
|---|---|---|
| `theme` | `dark` or `light`. The plugin cannot see your terminal theme. | `dark` |
| `palette` | `default` (traffic colors), `cvd` (color-vision-safe), `none` (style and words only) | `default` |
| `words` | `always`, or `plain_only` (words only where color is off) | `always` |
| `workspace` | An absolute folder. Removes and moves that stay inside it skip the card. | none |

`NO_COLOR` in the environment does the same as `palette: none`. The `cvd` palettes are the Hermes plugin's, which were checked by simulation under protan, deutan and tritan vision, not with people who have color-vision deficiency.

## What was checked

- **Unit tests (node:test):** `node --test claude-plugin/tests/*.test.mjs`, 82 tests on the signal grammar and limits, the card, the classifier and the mod's hooks against a fake Claude Code. They also assert that the mod uses no file, process or network API.
- **Claude Code's own test kit:** `claude-plugin/tests/run_kit_tests.sh`, 6 tests that load the real hooks module and mount the real render site for the terminal and Desktop surfaces.
- **Live, terminal:** a real interactive Claude Code session in a throwaway config, driven through tmux: marks drawn with color, style and words; the card dialog; Go ahead; Hold with a NO CARD notice; `/signals`; the options reaching the mod. A `claude -p` run showed the tag instructions reaching Claude, Claude staging a card, and the call going on when nobody can be asked. The captured output is in [docs/evidence/claude-code-live-check.txt](../../docs/evidence/claude-code-live-check.txt).
- **Desktop app: not run.** The same render tree was mounted for the Desktop surface in the test kit, and the docs list the assistant-message and question-dialog render sites as available there. Nobody has looked at it in the app.

## Known gaps

What the Claude Code version does differently from, or not at all compared with, the Hermes plugin. Nothing here is claimed as parity.

- **The card holds the call.** Hermes shows its card inside its own approval prompt and never holds anything. Mods cannot change Claude Code's permission prompt, so here the card is a separate question before the call, and Hold stops the call. You may see two prompts: the card, then Claude Code's own.
- **No one to ask, no card.** Under `claude -p` and the Agent SDK nothing can be asked, so the card is skipped and Claude Code's own permission decides. The same happens if the mod cannot reach a surface.
- **Not ported:** the Charter interview, standing rules and preflights (`checks.deny`, `senders`, `skills`, `provider_conflicts`, `locks`), custom `policy.add` and `policy.remove`, card codes and `/signals verify`, the sealed SQLite audit and anything that persists between sessions, kanban board lights, the Desktop caduceus pane and the Desktop `::axioma` card directive. The ledger is memory only.
- **Limits apply per drawn text block, not per whole reply.** A reply with text between tool calls is drawn as several blocks, so it can show more than 3 marks in total.
- **Marked lines are drawn as plain text.** A line that holds a colored mark loses markdown on that line (bold, links, inline code show as typed). Lines with no mark keep Claude Code's markdown drawing.
- **The parser is a port, not a copy.** Invisible-character, cut-off-stream and spliced-tag handling is simpler than the Hermes parser's. Removing a tag can in rare cases join its neighbours into something tag-shaped; the plugin re-scans four times and removes what it finds. Not run against the Hermes test suite.
- **Streaming not observed.** Whether Claude Code draws a half-streamed reply through the render hook was not observed. Cut-off tags are covered by unit tests only.
- **The stored message keeps the tags.** Claude sees its own tags in history, and copying text out of the stored transcript gives the tags, not the drawn words.
- **Not classified as spin:** subagent spawns (Hermes classifies `delegate_task`). PowerShell removes are not parsed (PowerShell `git push` and deploy commands are).
- **SCRUB containment is textual.** Symlinks are not resolved (the mod reads no files).
- **A card matches one exact call.** Only a Bash `description` is ignored when matching. A card whose arguments differ in any other way is not used and you see NO CARD.
- **A failing mod does not block.** If the hook itself throws or times out, Claude Code skips it and the call goes on to its own permission check.
- **The card is plain text in the question dialog.** The light is a word, not a color, and the dialog wording ("Type something", "Chat about this") is Claude Code's.
- **`go` by tool name** counts any successful call of that tool in the turn, so a passing `Read` can back "all tests passed". It stops invented and failed checks, not a mismatched one.
- **Directory:** this plugin ships code, so it is not eligible for the Claude plugin directory unless the publisher is verified. Install it from GitHub as above.

## Undo

`claude plugin uninstall axiom-axioma` and, if you added the marketplace, `claude plugin marketplace remove deploy-axiom-axioma`. It wrote nothing to disk, so there is nothing to delete.

## How it was made

I designed it, set the rules for what it may do, and tested it on my own system. AI agents wrote the code under my spec and review. I read JavaScript and Python; I don't claim to write them by hand.

Percy Keith, Deploy Axiom. MIT license.
