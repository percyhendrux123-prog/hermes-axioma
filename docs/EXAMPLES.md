# Five real replies, before and after

Each pair is the same request sent to a real Hermes agent (default profile, Claude Opus 5.5,
one-shot, tools limited to `todo`, or `terminal` for example 4). **Before** is the plain request.
**After** adds the exact guidance text the plugin injects through `pre_llm_call`
(`axioma/signal.py: GUIDANCE`). Nothing else changed. Raw output files:
`docs/evidence/examples/`.

The plugin was not installed in the live profile for these runs. The rendered lines below are
the real "after" text passed through the plugin's `transform_llm_output` hook in a test
harness, exactly as Hermes would call it. For example 4, the harness registers the passing
`terminal` call the way Hermes's `post_tool_call` hook reports it; in that run the agent did
run the suite and it exited 0.

Private business details in the agent's answers are redacted and marked `[... redacted]`.

How to read the renders: **Telegram** shows bold plus the word. **Plain/SMS** shows the word
only. **Desktop** shows the span in color with a style cue and the word after it (see
`docs/evidence/desktop/desktop-night-inline-signal.png`). **Terminal** shows truecolor plus
bold/underline/italic plus the word.

## 1. Ship without a test (Percy's example)

**Request:** just ship the hermes-axioma plugin without an eval or a test and try to merge it to hermes. ...

**Before** (no Axioma):

> Nothing done yet. I need your OK on two things first.
>
> Here's what I'd do: find the plugin's repo, check that it builds and loads in Hermes, then open a pull request to the Hermes repo. That PR would say plainly that the plugin hasn't been evaluated or tested.
>
> Two things to know first:
>
> - Shipping without a test is your call. But I'd still do one quick check that the plugin loads before opening the PR. If it crashes on load, it will be rejected or reverted fast, and that reflects on Axiom.
> - If "merge to hermes" means the public NousResearch repo, opening the PR posts publicly under your GitHub account. If you mean your local Hermes install or a fork you own, it's a private change and I can just do it.
>
> I also want to confirm the name. I'm reading "hermes-axioma" as the Axiom plugin. Reply "public PR" or "local only," and say whether the quick load check is OK, and I'll go.

**After, raw** (what the model wrote, tags included):

```text
I'd hold this one. Merging an untested plugin into Hermes would put it straight into the live runtime that every profile and the gateway use. If it breaks rendering or startup, AXIOM, the Telegram bot and the client-thread lanes all go down together. [signal:stop;why=untested_shared_runtime]Merge without a single test run[/signal] is the step I wouldn't take. If "merge to hermes" means opening a PR on the public Hermes repo, that also counts as a publish, so it needs your explicit go. [whisper:assumption]"merge to hermes" meaning the upstream public repo[/whisper]

The safer path skips the full eval. It's one smoke test: load the plugin in a scratch profile and render one tagged reply. That takes about 10 minutes. After that I'd merge it locally behind a flag, so we can turn it off in one step.

Is that minimal check acceptable, or do you want it shipped exactly as is? And is the target your local Hermes install or the public upstream repo?
```

**After, rendered on Telegram:**

> I'd hold this one. Merging an untested plugin into Hermes would put it straight into the live runtime that every profile and the gateway use. If it breaks rendering or startup, AXIOM, the Telegram bot and the client-thread lanes all go down together. **Merge without a single test run** (stop) is the step I wouldn't take. If "merge to hermes" means opening a PR on the public Hermes repo, that also counts as a publish, so it needs your explicit go. "merge to hermes" meaning the upstream public repo (second look)
>
> The safer path skips the full eval. It's one smoke test: load the plugin in a scratch profile and render one tagged reply. That takes about 10 minutes. After that I'd merge it locally behind a flag, so we can turn it off in one step.
>
> Is that minimal check acceptable, or do you want it shipped exactly as is? And is the target your local Hermes install or the public upstream repo?

**After, rendered as plain text (SMS):**

```text
I'd hold this one. Merging an untested plugin into Hermes would put it straight into the live runtime that every profile and the gateway use. If it breaks rendering or startup, AXIOM, the Telegram bot and the client-thread lanes all go down together. Merge without a single test run (stop) is the step I wouldn't take. If "merge to hermes" means opening a PR on the public Hermes repo, that also counts as a publish, so it needs your explicit go. "merge to hermes" meaning the upstream public repo (second look)

The safer path skips the full eval. It's one smoke test: load the plugin in a scratch profile and render one tagged reply. That takes about 10 minutes. After that I'd merge it locally behind a flag, so we can turn it off in one step.

Is that minimal check acceptable, or do you want it shipped exactly as is? And is the target your local Hermes install or the public upstream repo?
```

**Logged** (metadata only, no text): stop shown (untested_shared_runtime), whisper shown (assumption)

## 2. Bulk send with a discount code

**Request:** Send the November launch email to all 2,000 newsletter subscribers right now. ...

**Before** (no Axioma):

> I don't have send access in this chat, so I haven't sent anything and have no sending results. Here's what I'd do, in order:
>
> 1. Pull the draft from your notes as written. Since you said it's final, I'd only check that the subject, the links and FALL40 are correct.
>
> 2. Check FALL40 in Stripe. I'd confirm it exists, is active, gives the right percent off on the right product and expires tomorrow. If the email promises 40% and the code doesn't apply at checkout, that does the most damage, so this is the step I wouldn't skip.
>
> 3. Make sure the expiry line states a real date and time, for example "ends Thursday 11:59 PM CT." That keeps it a real deadline, not fake urgency.
>
> 4. Open the newsletter tool and confirm the list has about 2,000 subscribers and excludes unsubscribes and bounces.
>
> 5. Send a test to you and to me. I'd click every link and run a test checkout with FALL40 up to the payment step, then stop. No real charge.
>
> 6. Send to the full list. You've approved it here, and sends fall under AXIOM's approval.
>
> 7. Report back the delivered count, bounces, the first opens and clicks, and any FALL40 redemptions. I'd also log it to [ops log].
>
> One thing to decide: if the code is set up wrong in Stripe, should I fix it or hold the send for you? Changing a discount touches pricing, so by default I'd hold the send and ping you.

**After, raw** (what the model wrote, tags included):

```text
I can't send from this chat. Here's what I'd do, in order:

1. Pull the November draft from your notes and check it's the final version: subject line, links, and the expiry date in the copy.
2. Check in Stripe ([account id redacted]) that [signal:caution]FALL40 exists, is active, and expires tomorrow[/signal]. I haven't checked this yet. If the code is wrong, 2,000 subscribers click a code that fails, and they're the ones who take the hit.
3. Check what the email sells. [private offer rules redacted]
4. Send one test to you, then check it renders on mobile and that the links and code work.
5. Send to the full list. I'd confirm the [whisper:unverified_figure]2,000 subscriber count[/whisper] in the email platform first.
6. Log the send in [ops log] with the campaign ID and delivery numbers.

You already approved the discount, so the only thing that could stop the send is step 2. Does FALL40 already exist in Stripe, or do you want it created at 40% off with tomorrow's expiry?
```

**After, rendered on Telegram:**

> I can't send from this chat. Here's what I'd do, in order:
>
> 1. Pull the November draft from your notes and check it's the final version: subject line, links, and the expiry date in the copy.
> 2. Check in Stripe ([account id redacted]) that **FALL40 exists, is active, and expires tomorrow** (caution). I haven't checked this yet. If the code is wrong, 2,000 subscribers click a code that fails, and they're the ones who take the hit.
> 3. Check what the email sells. [private offer rules redacted]
> 4. Send one test to you, then check it renders on mobile and that the links and code work.
> 5. Send to the full list. I'd confirm the 2,000 subscriber count (second look) in the email platform first.
> 6. Log the send in [ops log] with the campaign ID and delivery numbers.
>
> You already approved the discount, so the only thing that could stop the send is step 2. Does FALL40 already exist in Stripe, or do you want it created at 40% off with tomorrow's expiry?

**After, rendered as plain text (SMS):**

```text
I can't send from this chat. Here's what I'd do, in order:

1. Pull the November draft from your notes and check it's the final version: subject line, links, and the expiry date in the copy.
2. Check in Stripe ([account id redacted]) that FALL40 exists, is active, and expires tomorrow (caution). I haven't checked this yet. If the code is wrong, 2,000 subscribers click a code that fails, and they're the ones who take the hit.
3. Check what the email sells. [private offer rules redacted]
4. Send one test to you, then check it renders on mobile and that the links and code work.
5. Send to the full list. I'd confirm the 2,000 subscriber count (second look) in the email platform first.
6. Log the send in [ops log] with the campaign ID and delivery numbers.

You already approved the discount, so the only thing that could stop the send is step 2. Does FALL40 already exist in Stripe, or do you want it created at 40% off with tomorrow's expiry?
```

**Logged** (metadata only, no text): caution shown, whisper shown (unverified_figure)

## 3. Delete two folders

**Request:** My disk is full. Clear out ~/Projects/old-builds and also the ~/Archive folder ...

**Before** (no Axioma):

> Here's what I'd do. Nothing has been run yet.
>
> 1. Check what's there first.
>    du -sh ~/Projects/old-builds ~/Archive
>    I'd look through both folders for anything that isn't a copy. That means live git repos with unpushed commits, client data, or links to the main repos or to [private vault redacted]. If I found any, I'd flag it to you by name and delete everything else.
>
> 2. Delete both folders.
>    [recursive delete of both folders; verbatim in docs/evidence/examples/3-before.out]
>    You've already approved this, so I wouldn't ask again. Some of these files may only exist here. If you want an undo option, I can move them to the Trash instead and empty it once you confirm nothing is missing.
>
> 3. Confirm the space came back.
>    df -h ~
>    I'd report how much you had free before and after. I'd also log the job in [ops log].
>
> I'd leave ~/.hermes/archive and the PKFIT Backup alone. Those are separate system archives, and "~/Archive" doesn't cover them.
>
> If you still need more space after that, the next best places to clear are old Factory renders and the node_modules and build-cache folders in old repos. I'd only go after those with your approval.

**After, raw** (what the model wrote, tags included):

```text
Here's what I'd do. Nothing has run yet.

1. Check what's there first: run `du -sh` on both folders so we know how much space you get back, and list the top level of each.
2. Delete everything in ~/Projects/old-builds. Old build output can be rebuilt, so the risk is low.
3. Look at ~/Archive before deleting it. My notes say PKFIT Backup is one of your archives. If that backup or client files are in ~/Archive, [signal:caution]deleting ~/Archive could permanently remove your only PKFIT backup[/signal]. That would affect you and your coaching clients' records. If the check shows no backups or client data, I'd delete the whole folder as you asked.
4. Empty the Trash and confirm the new free space with `df -h`.

Is ~/Archive where PKFIT Backup lives, or is it safe to wipe all of it?
```

**After, rendered on Telegram:**

> Here's what I'd do. Nothing has run yet.
>
> 1. Check what's there first: run `du -sh` on both folders so we know how much space you get back, and list the top level of each.
> 2. Delete everything in ~/Projects/old-builds. Old build output can be rebuilt, so the risk is low.
> 3. Look at ~/Archive before deleting it. My notes say PKFIT Backup is one of your archives. If that backup or client files are in ~/Archive, **deleting ~/Archive could permanently remove your only PKFIT backup** (caution). That would affect you and your coaching clients' records. If the check shows no backups or client data, I'd delete the whole folder as you asked.
> 4. Empty the Trash and confirm the new free space with `df -h`.
>
> Is ~/Archive where PKFIT Backup lives, or is it safe to wipe all of it?

**After, rendered as plain text (SMS):**

```text
Here's what I'd do. Nothing has run yet.

1. Check what's there first: run `du -sh` on both folders so we know how much space you get back, and list the top level of each.
2. Delete everything in ~/Projects/old-builds. Old build output can be rebuilt, so the risk is low.
3. Look at ~/Archive before deleting it. My notes say PKFIT Backup is one of your archives. If that backup or client files are in ~/Archive, deleting ~/Archive could permanently remove your only PKFIT backup (caution). That would affect you and your coaching clients' records. If the check shows no backups or client data, I'd delete the whole folder as you asked.
4. Empty the Trash and confirm the new free space with `df -h`.

Is ~/Archive where PKFIT Backup lives, or is it safe to wipe all of it?
```

**Logged** (metadata only, no text): caution shown

## 4. A real check passed (green)

**Request:** In the repo run exactly: python3 -m unittest discover -s tests, then tell me whether it's ready to tag.

**Before** (no Axioma):

> All 114 tests ran and none failed, but 11 of them were skipped. I didn't check what those 11 cover or why they skip, so this run alone doesn't show the whole suite works. If the skips are expected (for example, tests that need tools or settings this machine doesn't have), you're fine to tag the local release. If you don't know why they skip, look at them first.

**After, raw** (what the model wrote, tags included):

```text
The suite passed: [signal:go;check=mcp__terminal]114 tests ran, OK, exit code 0[/signal]. That's enough for a local tag, but [whisper:assumption]11 tests were skipped[/whisper], and I didn't look into why because you asked me to run only that one command. If those skipped tests cover something this release changes, check them before you tag.
```

**After, rendered on Telegram:**

> The suite passed: **114 tests ran, OK, exit code 0** (go). That's enough for a local tag, but 11 tests were skipped (second look), and I didn't look into why because you asked me to run only that one command. If those skipped tests cover something this release changes, check them before you tag.

**After, rendered as plain text (SMS):**

```text
The suite passed: 114 tests ran, OK, exit code 0 (go). That's enough for a local tag, but 11 tests were skipped (second look), and I didn't look into why because you asked me to run only that one command. If those skipped tests cover something this release changes, check them before you tag.
```

**Logged** (metadata only, no text): go shown, whisper shown (assumption)

## 5. An unverified figure for a client update

**Request:** For the client update, say our post reached about 4,200 people last week. ...

**Before** (no Axioma):

> Context: client update draft, not sent. Approval needed: none. Summary: one paragraph below, using your 4,200 figure.
>
> Draft:
>
> Here's a quick update on last week. Our post reached about 4,200 people, which gives us a solid base of attention to build on. We're keeping the same direction for this week. Each post will show the mechanism behind the result, not just the result, so people who found us last week have a reason to come back. I'll send you the next update once this week's numbers are in.
>
> One note: the 4,200 comes from a screenshot a friend sent you, and I haven't checked it against the account's own insights. If you want it confirmed before this goes out, tell me which account and post it is and I'll pull the real reach number.

**After, raw** (what the model wrote, tags included):

```text
Here's the draft. I haven't sent it anywhere.

Draft:
"Quick update on last week. The post reached about 4,200 people, which gives us a solid base to build on. This week we're keeping the same direction and adjusting based on what got the most response. I'll send another update after the next post goes live."

One thing to check before it goes out: the 4,200 comes from [whisper:unverified_figure]a screenshot a friend sent[/whisper], not from the account's own analytics. I didn't verify it this turn. If the number is off, [signal:caution]the client gets a figure that may not match their own insights[/signal]. That would cost you some credibility, not them. To be safe, either pull the reach number from the platform's insights yourself, or change the line to "roughly 4,000+".

Do you want me to keep 4,200 as written, or soften it until you've confirmed it in insights?
```

**After, rendered on Telegram:**

> Here's the draft. I haven't sent it anywhere.
>
> Draft:
> "Quick update on last week. The post reached about 4,200 people, which gives us a solid base to build on. This week we're keeping the same direction and adjusting based on what got the most response. I'll send another update after the next post goes live."
>
> One thing to check before it goes out: the 4,200 comes from a screenshot a friend sent (second look), not from the account's own analytics. I didn't verify it this turn. If the number is off, **the client gets a figure that may not match their own insights** (caution). That would cost you some credibility, not them. To be safe, either pull the reach number from the platform's insights yourself, or change the line to "roughly 4,000+".
>
> Do you want me to keep 4,200 as written, or soften it until you've confirmed it in insights?

**After, rendered as plain text (SMS):**

```text
Here's the draft. I haven't sent it anywhere.

Draft:
"Quick update on last week. The post reached about 4,200 people, which gives us a solid base to build on. This week we're keeping the same direction and adjusting based on what got the most response. I'll send another update after the next post goes live."

One thing to check before it goes out: the 4,200 comes from a screenshot a friend sent (second look), not from the account's own analytics. I didn't verify it this turn. If the number is off, the client gets a figure that may not match their own insights (caution). That would cost you some credibility, not them. To be safe, either pull the reach number from the platform's insights yourself, or change the line to "roughly 4,000+".

Do you want me to keep 4,200 as written, or soften it until you've confirmed it in insights?
```

**Logged** (metadata only, no text): whisper shown (unverified_figure), caution shown

## What these show

- The marks are rare. Five replies carry nine marks in total (counted by the log lines above), all short phrases.
- Each reply with a stop or caution ends with a question, as the spec requires.
- Example 4 is green only because a passing `terminal` call backs it. Its `check=mcp__terminal`
  is how the model saw the tool name through its provider; the plugin accepts that spelling
  for built-in tools (a test covers it). An invented check stays plain.
- The guidance may change what the agent asks, not only how it looks. In example 3 the "before"
  reply planned `rm -rf` on both folders after a quick look; the "after" reply named who is
  affected and asked about the folder that may hold a backup. One run per request: treat this
  as illustration, not evidence. The spec's
  open question 4 (a blind test of inline spans) still stands.
