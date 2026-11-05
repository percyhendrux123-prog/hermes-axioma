# Axiōma Signal Spec v0.1

**Inline signal color for agent output.**

- Status: **draft v0.1, public for comment.**
- Date: 2026-11-04
- Owner: none. Given to the public domain (section 9).
- Reference implementation: [`hermes-axioma`](https://github.com/percyhendrux123-prog/hermes-axioma) (Hermes Agent plugin, MIT)
- License: this text CC0 1.0 (public domain); code MIT (section 9)

> If there's no one looking out for those who cannot see, then you become eyes. If there's no one
> there to carry those in need another step further, we become the wagon.

That is why this exists, and why accessibility is its first design rule, not a feature added later.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are used as in RFC 2119.

---

## 1. Purpose

Agents now write most of what people read before they act. A reply can look calm and complete
while one phrase inside it would cost the person money, send something they cannot take back, or
start a job they did not mean to start. A reader skimming the reply has no way to see which phrase
that is.

This spec defines a small, shared way for an agent to mark **the few spans of its own reply that
deserve the human's attention**, and for any host (terminal, desktop app, web chat, messaging app)
to show those spans the same way, with or without color.

It is written so that an agent, a host and a reader who have never met can agree on what a mark
means.

### The axiom

> Nothing sends, spends, or spins without the one who holds the gate.

Every rule below serves that line. The signal does not hold the gate. It helps the person who does.

### What the signal is, and is not

- It **advises**. It never blocks, approves or executes anything. Enforcement, where it exists,
  belongs to the host's own approval system.
- It is **judged against the human's interest**, not against the model's confidence, and not
  against the system's safety alone.
- It is **tied to actions**: sending (messages, email, posts), spending (money, paid compute),
  spinning (starting jobs, deploys, changes to live services) and, since the blind replay, scrubbing
  (deletes and moves that cannot be undone).
- A reply that carries a stop or caution **ends in a question** to the human, not an instruction.
  We advise in the open, never direct in secret. The person keeps the decision and is invited to
  think, not prompted to comply.
- **Every flag is logged** and can be listed on request. Nothing is marked in a way the human
  cannot later audit.

### Prior art, stated fairly

Axiōma builds on work that already showed highlighting inside AI output helps people.

1. **Microsoft Research, "Appropriate reliance on Generative AI: Research synthesis"**
   (Passi, Dhanorkar, Vorvoreanu, MSR-TR-2024-7, March 2024). Reviews about 50 papers. Among its
   design suggestions: use highlights in GenAI output to convey model uncertainty. It reports that
   highlighting low-probability tokens is "partially effective", that results depend on the task,
   and that highlighting parts likely to need edits worked better than highlighting
   low-probability tokens in a code task (Vasconcelos et al., 2023). It also warns that these
   strategies can backfire and must be tested in context. The 2025 follow-up ("Lessons learned")
   names the UX goal plainly: signal to users when to verify.
   https://www.microsoft.com/en-us/research/publication/appropriate-reliance-on-generative-ai-research-synthesis/
2. **Spatharioti, Rothschild, Goldstein, Hofman, "Effects of LLM-based Search on Decision Making:
   Speed, Accuracy, and Overreliance"**, CHI 2025, doi:10.1145/3706598.3714082. In a second
   experiment, a color-coded highlighting scheme based on token generation probabilities helped
   people catch errors. On the hard task where the model erred, accuracy was 26% without
   highlights and 58% / 53% with them, without hurting other outcomes. The authors note the domain
   was narrow (choosing between pairs of cars).
3. **VS Code `chat.tools.riskAssessment.enabled`** (experimental, introduced in VS Code 1.120).
   Adds an AI-generated risk badge to terminal command confirmations: Safe (green), Caution
   (orange), Review carefully (red), each with a one-sentence explanation. This is the closest
   shipped analog to an action-tied traffic light.
   https://code.visualstudio.com/updates/v1_120

**What Axiōma adds** (and only this; the rest is borrowed):

| | Token highlighting (MSR, CHI 2025) | VS Code risk badge | Axiōma |
|---|---|---|---|
| Judged against | model's own uncertainty | the command's effect on the system | **the human's interest**, including people downstream |
| Attached to | any token | one terminal command, in a dialog | **spans of normal prose**, tied to send / spend / spin / scrub |
| Ends with | nothing | an explanation | **a question back to the human** |
| Record | none specified | none specified | **every stop, caution and whisper logged and listable** |
| Without color | not specified | badge text | **required words, screen-reader text, copy keeps meaning** |
| Green means | high model confidence | "reads files or prints output" | **a real check passed** (never the agent's say-so, never read text) |

Honest gap: the studies above measured probability-based highlights. Axiōma's spans are chosen by
the agent and by code checks, not by token probabilities. Our own blind replay (section 8)
measured pre-action cards, not inline spans. **There is no evidence yet that inline Axiōma spans
help readers.** That test is still to be run.

---

## 2. Levels

Five levels. Four of them use the global traffic-light colors; one is a near-white gold. Meaning
belongs to the level and its word, never to the color (colors are remappable, section 4.6).

| Level | Word | Default color | Meaning |
|---|---|---|---|
| `intent` | intent | white (ink on light themes) | What the person is trying to achieve, restated cleanly. Not a warning. At most one per reply. |
| `go` | GO | green | This part is up to standard **because a real check passed** (tests ran, file exists, sender verified, preflight passed). |
| `caution` | CAUTION | yellow | It works on its own terms, but it starts a sequence that conflicts with the person's interest unless addressed (a downstream person loses something, a cost recurs, a rule is bent). |
| `stop` | STOP | red | The request was understood and the output may be ready, but do not proceed. The reply MUST say what is wrong and what would turn it green. |
| `whisper` | second look | pale gold, close to text color | Worth a second look but stops nothing: a low-confidence claim, an unverified figure, voice drift, an assumption stated as fact. |

Rules per level:

- **stop** MUST be accompanied, in the same reply, by (a) the reason in plain words and (b) the
  path to green. A stop with no path is not allowed.
- **caution** SHOULD name who or what is affected.
- **go** MUST reference a check the host or tool layer actually observed (section 5.1). Without
  one, it is not `go`; leave the text unmarked.
- **whisper** is shown once per item per session. It is never repeated, never escalated, and is
  never the first chance to correct something; normal checks come first. It carries a reason:
  `low_confidence`, `unverified_figure`, `voice_drift` or `assumption`.
- **intent** is optional. It is the only level that is not a signal about risk.
- Yes and no are spelled out in words. Nothing relies on the reader decoding a color to learn
  whether to proceed.
- Any reply containing `stop` or `caution` MUST end with a question addressed to the human.

### 2.1 When NOT to mark (the rarity budget)

Color only works if it is rare. If every reply glows, people stop reading the color, and the one
red phrase that matters is lost. Producers MUST follow this budget by default:

- **Mark spans, not sentences.** A span SHOULD be 12 words or fewer. Never mark a whole paragraph.
- **At most 3 stop/caution/go spans per reply**, and at most 2 whispers. If more seem needed, the
  agent should stop and ask instead of coloring.
- **Marked text SHOULD be under 10% of the reply.**
- **Mark only what changes a decision.** If the human would do the same thing whether or not they
  noticed the span, leave it plain.
- **Do not mark routine success.** "The file saved" is not `go`. Use `go` only where a verified
  check removes a doubt the human actually has.
- **Never mark for emphasis, tone, persuasion or style.** Color is not bold. It is not a sales tool.
- **Never mark the human's own words to argue with them.** Restating intent is allowed; scoring
  the person is not.
- **Do not repeat a mark** for the same issue later in the same thread. One clear sign, then it is
  on the human.
- **Do not mark what you cannot back.** No `go` without a check, no `stop` without a reason and a
  path.

Hosts SHOULD expose the budget as settings and MAY log budget violations as producer errors.

---

## 3. Markup

### 3.1 Inline span syntax (portable)

One syntax, plain ASCII, safe to type, safe to stream, and readable even if nothing renders it.
It matches the tag shape used by the reference implementation (`[whisper:reason]...[/whisper]`,
extended to `[signal:...]...[/signal]` in the reference plugin).

```text
open   = "[" kind ":" value *( ";" key "=" token ) "]"
close  = "[/" kind "]"
kind   = "signal" / "whisper"
value  = for signal:  "intent" / "go" / "caution" / "stop"
                      (aliases, accepted by renderers: "white" / "green" / "yellow" / "red")
         for whisper: "low_confidence" / "unverified_figure" / "voice_drift" / "assumption"
key    = "check" / "why" / "id"
token  = 1*64( ALPHA / DIGIT / "_" / "-" / "." )
```

Examples:

```text
I can merge this, but [signal:stop;why=no_eval]without an eval or a test[/signal] the
[signal:caution]merge into Hermes[/signal] would land under your name.
The suite [signal:go;check=call_8f2a]passed 41 of 41[/signal] on the plugin.
The estimate is [whisper:unverified_figure]about 4,200 users[/whisper].
Do you want me to run the eval first?
```

Rules:

- Producers SHOULD emit meaning names (`stop`, `caution`, `go`, `intent`). Color aliases exist so
  that v0.1 of the reference plugin and early tags stay valid; they MAY be deprecated in v1.0.
- Spans MUST NOT nest and MUST NOT cross line breaks in v0.1.
- `check` is required for `go` at Integrity conformance (section 6). `why` is a short reason code.
  `id` is an optional producer span ID.
- **Tags never leak.** A renderer MUST remove every opening or closing tag of a known kind, even
  if unclosed, empty, nested, or carrying an unknown value. An unknown or invalid span renders as
  plain text without marking. An empty span renders nothing. A reply that was only tags renders as
  a short honest placeholder, never the raw tags.
- Text inside a span is ordinary text and keeps its own markdown.

### 3.2 JSON form (for hosts)

Hosts that carry structured messages SHOULD convert tags to annotations once, at the edge, and
pass the clean text plus spans to every renderer. This is also the shape proposed for the Hermes
host seam.

```json
{
  "axioma": "0.1",
  "text": "I can merge this, but without an eval or a test the merge into Hermes would land under your name.\nThe suite passed 41 of 41 on the plugin.\nThe estimate is about 4,200 users.\nDo you want me to run the eval first?",
  "spans": [
    {"start": 22, "end": 47, "level": "stop", "label": "STOP", "why": "no_eval", "id": "sp_01"},
    {"start": 52, "end": 69, "level": "caution", "label": "CAUTION", "id": "sp_02"},
    {"start": 108, "end": 123, "level": "go", "label": "GO", "check": "call_8f2a", "check_verified": true, "id": "sp_03"},
    {"start": 155, "end": 172, "level": "whisper", "label": "second look", "reason": "unverified_figure", "first_in_session": true, "id": "sp_04"}
  ],
  "ends_with_question": true
}
```

- `start` and `end` are offsets in **Unicode code points** into `text`, end exclusive. (JavaScript
  hosts must convert from UTF-16; see open questions.)
- `label` is the words that stand in for color everywhere color is unavailable.
- `check_verified` is set by the host, never by the producer.
- `first_in_session` is set by the host for whispers; renderers MUST NOT style a whisper whose
  value is false.

---

## 4. Rendering per surface

### 4.1 Required on every surface: never color alone

Color is one of at least two cues. Every level has a style cue that works without color, a word
for copy and plain text, and screen-reader text. (WCAG 2.2 Success Criterion 1.4.1, Use of Color.)

| Level | Style cue (rich surfaces) | Word (plain, copy, speech) |
|---|---|---|
| intent | strongest text color, no decoration | `intent:` before the span |
| go | dashed underline | `(GO)` after the span |
| caution | wavy underline | `(CAUTION)` after the span |
| stop | bold plus solid underline | `(STOP)` after the span |
| whisper | thin dotted underline | `(second look)` after the span |

### 4.2 Terminal (ANSI)

- Color: 24-bit SGR `ESC[38;2;R;G;Bm`. Reset with `ESC[39m` (default foreground) and the matching
  attribute-off codes, **never** a hard-coded color and never a full `ESC[0m` that wipes the
  user's own styling.
- Style: stop `ESC[1m` + `ESC[4m`; caution `ESC[4:3m` (curly); go `ESC[4:5m` (dashed); whisper
  `ESC[4:4m` (dotted).
- If the terminal's support for extended underlines is unknown, the renderer MUST append the word
  from 4.1 instead of relying on underline style. Renderers MUST NOT guess support from timing or
  probing escape responses mid-stream.
- `NO_COLOR` set in the environment: no color codes; style and words still apply.
- Not a TTY (piped, logged): words only, no escape codes.

### 4.3 Web and desktop apps

Render each span as an element with a class per level, a data attribute, and visually hidden text:

```html
<span class="ax ax-stop" data-axioma-level="stop">without an eval or a test<span class="ax-sr"> (STOP)</span></span>
```

```css
.ax-stop    { color: var(--ax-stop);    font-weight: 600; text-decoration: underline solid; }
.ax-caution { color: var(--ax-caution); text-decoration: underline wavy; }
.ax-go      { color: var(--ax-go);      text-decoration: underline dashed; }
.ax-whisper { color: var(--ax-whisper); text-decoration: underline dotted 1px; }
.ax-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
```

- **Screen readers:** use real visually hidden text, as above. Do not rely on `aria-label` on a
  plain `span`; many screen readers ignore it there. Do not put signals in `aria-live` regions.
- **Copy:** visually hidden text is normally included when the user copies; hosts MUST test that
  the copied text contains the word, or install a copy handler that adds it (section 5.4).
- **Hover or focus** MAY show the reason and the check reference.
- **Math-renderer hacks** (for example KaTeX `\color{}` in a desktop chat) give color only, read
  badly in screen readers and lose meaning on copy. They are acceptable for a demo but are **not
  conformant** unless the word is also present in the text.
- Streaming: the host SHOULD hold back output from an unmatched `[` until the tag resolves (64
  characters at most), so tags never flash on screen. Where a host cannot, the flash must be
  documented, as the reference plugin does (`docs/HOST-GAPS.md`, section 4).

### 4.4 Markdown-only surfaces

No color is available. Use markdown emphasis plus the word:

```markdown
I can merge this, but **without an eval or a test** (STOP) the _merge into Hermes_ (CAUTION) ...
```

- stop: `**bold**` + `(STOP)`; caution: `_italic_` + `(CAUTION)`; go: plain + `(GO)`; whisper:
  plain + `(second look)`, or nothing on surfaces where the operator has turned the marker off
  (whisper is still logged).
- Do not use block callouts for inline spans; they turn a phrase into a card, which this spec
  avoids on purpose.

### 4.5 Plain text, SMS, Telegram and other messaging

- Words are the signal. `without an eval or a test (STOP)`.
- Telegram MAY add bold/underline through its supported markup, but the word is still required.
- No emoji in place of words. Emoji render differently per device, are read aloud inconsistently,
  and carry their own cultural meanings.
- On SMS, keep the question as the last line.

### 4.6 Palette, contrast and color-vision testing

Default palettes (from the Axiōma skins):

| Level | Night (bg `#0E0F11`) | Day (bg `#F6F5F1`) |
|---|---|---|
| text / intent | `#F0F0EE` | `#1A1B1E` |
| stop | `#FF453A` | `#D70015` |
| caution | `#FFCC00` | `#A66B00` |
| go | `#30D158` | `#248A3D` |
| whisper | `#EADFB8` | `#8A6A1F` |

**Method.** Each color is converted to linear sRGB, transformed with the Machado, Oliveira and
Fernandes (2009) matrices at severity 1.0 for protanopia, deuteranopia and tritanopia, then
compared pairwise with CIEDE2000. Contrast against the background uses the WCAG 2.x relative
luminance formula. Reference: G. M. Machado, M. M. Oliveira, L. A. F. Fernandes, "A
Physiologically-based Model for Simulation of Color Vision Deficiency", IEEE TVCG 15(6):1291-1298,
2009, doi:10.1109/TVCG.2009.113. Script: `tools/cvd_check.py` (stdlib only); output saved in
`tools/cvd_check.out.txt`.

**Results (CIEDE2000; higher means easier to tell apart; below about 10 is hard, below 3 is
nearly the same color):**

| Pair | Night normal | Night protan | Night deutan | Day normal | Day protan | Day deutan |
|---|---|---|---|---|---|---|
| stop / caution | 46.6 | 30.9 | 18.0 | 28.6 | 13.0 | **1.7** |
| stop / go | 77.1 | 26.2 | **7.9** | 68.7 | 17.4 | **9.4** |
| caution / go | 35.5 | **6.5** | 14.2 | 38.2 | **7.0** | **9.9** |
| caution / whisper | 19.8 | 19.1 | 18.7 | **8.3** | **2.9** | **5.8** |

Contrast vs background: night palette 5.6:1 or better on every level. Day palette: stop 4.9:1,
whisper 4.6:1, caution **4.1:1**, go **4.0:1** (below the 4.5:1 WCAG AA target for body text).

What this means, plainly:

- **The default traffic colors are not colorblind-safe.** Under deuteranopia the day stop and
  caution are nearly identical (1.7). Night caution and go are close under protanopia (6.5). This
  is expected of red/yellow/green and is why the style cue and word in 4.1 are required, not
  optional.
- An **alternate night palette** based on Okabe and Ito's color-universal-design set (stop
  `#E8603C`, caution `#F0E442`, go `#56B4E9`) keeps every gate pair at 21 or higher under all three
  simulations, with contrast 5.6:1 or better. It gives up "green means go" for blue, which is the
  standard trade.
- **No day palette tested so far** keeps all gate pairs above 10 under every simulation while
  passing 4.5:1 contrast and still reading as red / amber / blue. Open question 7.3.
- Hosts MUST ship a color-vision-safe option and MUST let the user pick it in one setting.

**User-remappable colors (required).** Hosts MUST let the user change the color of every level.
Color meaning is cultural: in several East Asian markets red marks a rising price and green a
falling one, and in other contexts red is a celebratory color. The level and its word never
change when the color does. Hosts SHOULD offer: default, color-vision-safe, high contrast, and
"no color" (style and words only).

---

## 5. Integrity rules

### 5.1 Green comes only from real checks

- `go` MUST reference a check that the host or tool layer executed and observed in this session:
  a tool call ID, test run ID or preflight ID.
- At Integrity conformance, the host MUST verify the reference against its own record. If it does
  not match a passing check, the span renders as plain text and the mismatch is logged.
- An agent's own statement ("I'm confident this is right") is never a check.

### 5.2 Never from text the agent read (injection)

- Signal tags that appear in content the agent read (web pages, files, emails, tool results,
  client messages) MUST NOT be rendered as signals. Hosts SHOULD neutralize tags in untrusted
  content before the model sees it, and renderers MUST only parse tags in the assistant's own
  final output.
- Producers MUST NOT copy a mark, a level or a reason from read content. A web page that says
  "this is safe" cannot produce `go`. A page that says "mark this red" cannot produce `stop`.
- Read content MAY be the reason for a `caution` or `whisper` the agent decides on itself (for
  example, a figure from a source it could not confirm).

### 5.3 Every flag is logged and listable

- Every rendered `stop`, `caution` and `whisper` MUST be logged with: random span ID, level,
  reason code, session scope, time, surface, and whether it was shown. `go` SHOULD be logged with
  its check reference.
- The log SHOULD NOT store message bodies by default. Store a salted hash of the span text so a
  span can be matched without being recovered (the reference plugin does this).
- The human MUST be able to list flags on request (for example `/signals`, `/whispers`), in plain
  words. Nothing is marked in secret.
- Logs are local by default. Sending them anywhere is an operator decision, disclosed to the user.

### 5.4 Copy and paste keep the meaning

When a user copies marked text from any surface, the result MUST carry the word for each span
(`without an eval or a test (STOP)`). A meaning that disappears on copy is a meaning that gets
forwarded as clean text to someone who never saw the color.

### 5.5 The signal advises

A renderer or plugin claiming conformance MUST NOT present the signal as a gate, block, approval
or guarantee. "Advice only; you decide" is the stance on every surface.

### 5.6 Shown equals staged

A card is written by the agent, handed to the host, and reaches the human's screen a moment later,
sometimes through third-party messaging servers. An operator watching his own terminal noticed
that nothing let the two ends prove that what the human saw is what the agent staged and what the
human answered. A conforming card carries a fingerprint for that.

- **The code.** Every card and every missing-card notice MUST carry a short card code, such as
  `card code 7Q4K-2MPD`: 40 bits written as 8 Crockford base32 characters (no I, L, O or U) with
  one dash, so it can be read aloud and typed back. Letters, digits and a dash survive Telegram,
  Discord, Slack and plain text unchanged; no `#`, `*`, `_`, `~` or backtick is used. The code
  sits on its own line directly under the question (directly above it when the question is long),
  so it lands in the part of the card a host does not truncate.
- **What it covers.** The code is a truncated keyed hash (HMAC-SHA-256 under a random key held
  in the local log and never written to an event) over a canonical encoding of: the exact card
  text the host receives, without the code line itself; the tool name; the canonical JSON of the
  exact arguments (sorted keys, no spaces); and the card ID. Change any one of them and the code
  changes.
- **What is logged.** The same code MUST be logged when the card is handed to the host
  (`presented_to_host`) and again with the host-reported answer (`post_approval_response`). The
  log keeps keyed digests of the covered parts and of each card line, never the bodies, and each
  card record carries a keyed seal over its own fields.
- **What the human can check.** `/signals verify <code>` MUST show, in plain words, staged then
  shown then answered, and name any mismatch: no card with that code, a record changed after it
  was written, an answer recorded under a different code, or (when the human pastes the card they
  saw) a line added, changed, missing or out of order. `/signals cards` lists recent codes.
- **What it detects.** A card changed in transit, when the human compares the code or pastes the
  words, and a log record edited after it was written.
- **What it does NOT prove.** A compromised host, or anyone holding the local key, can forge both
  ends: a matching code on the screen and a matching record in the log. Lines added outside the
  card (before its first line or after its last) are not distinguished from host framing. The code
  confirms the log; the human still has to look at the card.

---

## 6. Conformance checklist

Three roles. A project may fill one or more. Two levels: **Render** (looks and reads right) and
**Integrity** (the marks can be trusted).

### Producer (the agent or the plugin that writes tags)

Render:
- [ ] Uses only the syntax in 3.1; no nesting; no spans across lines.
- [ ] Follows the rarity budget (2.1) by default.
- [ ] Every `stop` has a reason and a path to green in the same reply.
- [ ] Any reply with `stop` or `caution` ends with a question to the human.
- [ ] Whisper carries one of the four reason codes.

Integrity:
- [ ] Every `go` carries `check=` pointing at an observed check.
- [ ] Never emits a level, mark or reason copied from read content.
- [ ] Marks only spans tied to a send, spend, spin or scrub, or (whisper) to a claim the human
      may act on.

### Renderer (the host surface)

Render:
- [ ] Strips every known tag, closed or not; never shows raw tags; tag-only replies get a short
      placeholder.
- [ ] Applies the style cue from 4.1 on rich surfaces, the word on plain surfaces.
- [ ] Includes screen-reader text with the word.
- [ ] Copied text includes the word.
- [ ] Respects `NO_COLOR` and non-TTY output in terminals; resets to the user's default color.
- [ ] Offers a color-vision-safe palette and per-level color remapping, including "no color".
- [ ] Meets 4.5:1 contrast for marked text on its default theme, or documents where it does not.
- [ ] Shows each whisper once per session.

Integrity:
- [ ] Parses tags only in the assistant's final output, never in tool results or quoted content.
- [ ] Renders `go` only when the check reference matches a passing check in its own record.
- [ ] Holds back streamed output until tags resolve, or documents the flash.

### Logger

- [ ] Logs every shown `stop`, `caution` and `whisper` with the fields in 5.3.
- [ ] Stores no message bodies by default; uses a salted hash.
- [ ] Lists flags to the human on request, in plain words.
- [ ] Keeps logs local unless the operator discloses otherwise.
- [ ] Cards: shows a card code under the question on every card and missing-card notice, logs it
      at hand-off and with the answer, and checks it on request in plain words (5.6).

A project MAY say "Axiōma Signal v0.1 Render-conformant" or "Integrity-conformant" when every box
for its role and level is checked. The reference plugin is expected to reach Render conformance
for the terminal first; see its `docs/HOST-GAPS.md` for what the Hermes host does not yet allow.

---

## 7. Open questions

1. **Offsets.** Code points (chosen here) versus UTF-16 code units (native to JavaScript) versus
   bytes. Pick one for v1.0 and ship conversion helpers.
2. **Whisper and accessibility.** Whisper is meant to be almost invisible to a casual reader. A
   dotted underline and screen-reader text make it more visible than the original design.
   Is the dotted underline the right floor, or should whisper be screen-reader and copy only?
3. **A colorblind-safe day palette.** None found yet that keeps red/amber readable, separates all
   pairs under deuteranopia and protanopia, and passes 4.5:1 on the bone background. Needs a
   designer pass and testing with people who have CVD, not only simulation.
4. **Evidence for inline spans.** The blind replay in section 8 measured cards. Inline spans need their own blind test:
   same replies with and without marks, scored on whether readers catch the real problem and how
   often they are misled by a false `go`.
5. **Who checks the rarity budget?** Producer self-limits, host enforces, or both? What happens
   to the 4th span: dropped, downgraded, or logged as an error?
6. **Scrub as a named action.** The axiom names send, spend, spin. Deletes were added after the blind replay.
   Keep the axiom line as written and list scrub in the rules, or change the line?
7. **`go` on surfaces without a check record.** Plain chat apps cannot verify a check ID. Should
   `go` simply never render there?
8. **Multiple producers.** If two plugins mark the same span, which level wins? Proposed: the
   most severe, with both logged.
9. **Translation.** The words (STOP, CAUTION, GO, second look) need agreed translations per
   language, and the level token stays English.
10. **Naming.** Should "Axiōma-conformant" mean passing a public test suite? The name is not
    reserved; the test suite would be the only meaning of it.
11. **Streaming seam.** The holdback rule needs a host hook. The Hermes host proposal (`docs/UPSTREAM-PROPOSAL.md`)
    is the first test of whether hosts will carry span annotations.

---

## 8. Evidence to date

A blind replay of 50 real requests from three weeks of agent operations (anonymized; 18 real
problems, 28 routine), tested model-written **cards** before the plugin existed:

| Measure | Result |
|---|---|
| Fired exactly when the send/spend/spin rule says | 50/50 |
| Real problems flagged STOP or CAUTION | 13/18 (72%) |
| Flagged and named the actual problem | 9/18 strict; 13/18 with partial hits |
| Routine actions wrongly flagged | 6/28 (21%); 2/28 (7%) with no basis |
| The question would have surfaced the real issue | 10/18 fully; 17/18 at least partly |
| Expected STOP came back STOP | 1 of 4 |

Lessons carried into this spec: the question is the most valuable part (section 2); stops are
under-called, so hard stops belong in code checks; downstream people must be considered before
`go`; deletes needed their own trigger. Limits: small sample, one run, one grader, the case writer
knew outcomes; treat rates as directional (about plus or minus 15 points). Cards are not inline
spans (open question 4).

---

## 9. License and acknowledgments

- **This spec text: CC0 1.0 Universal (public domain dedication).** No owner, no permission, no
  credit required. Anyone may copy, change, translate or build it into anything.
- **Code (reference plugin, renderer library, test tools): MIT**, the same license as Hermes Agent,
  so it can move upstream without friction.

Why no owner: this was not made by one person. It came to this moment through many hands, and
without any one of them it would not exist. It belongs to the people who come after.

### Acknowledgments

- Hermes Agent, Nous Research and every contributor to them. The agent this was built in, and the
  open ground it grew from.
- The researchers who studied highlighting AI output before us (section on prior art).
- Hipparchus of Athens, whose roadside herms carried short maxims to anyone walking past.
- The people this is for: anyone who reads an agent's words before acting on them, and especially
  those who cannot see the color.

---

*Draft v0.1, public for comment. Issues and pull requests welcome.*
