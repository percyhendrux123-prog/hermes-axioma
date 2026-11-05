> Note (A224): this eval predates the plugin and calls the card a "gate signal". The shipped plugin is an advisor, not a gate: it shows the card through Hermes's approval prompt and never blocks. The eval text below is unchanged.

# Does the gate signal help? A blind replay on real operations history

**Summary (anonymized; no client names, no client data).**

Before shipping the gate signal, we tested it on our own history. The gate is a card that appears only before an agent **sends** (a message, email or post), **spends** (money or paid compute) or **spins** (starts jobs, deploys, changes live services). The card states the intent, shows one light (STOP, CAUTION or GO), and ends with a question back to the human.

**Method**
- We took 50 real requests from three weeks of running agents for a small agency and its clients.
- About half were routine. 18 had a real problem that we knew about afterwards: a send from an address that can only receive, a config change that was reverted within half an hour, a stop instruction lost mid-change, a model switch that crashed background jobs, and a client data file headed to the wrong model provider.
- For each request we wrote only what the agent knew at that moment. A fresh model, with no tools and no knowledge of outcomes, produced the card.
- We graded every card against what actually happened.

**Results (n = 50; 18 real problems, 28 fine, 2 contested, 2 out of scope)**

| | |
|---|---|
| Fired exactly when the send/spend/spin rule says | 50/50 |
| Real problems flagged STOP or CAUTION | 13/18 (72%) |
| Flagged and named the actual problem | 9/18 strict, 13/18 with partial hits |
| Routine actions wrongly flagged | 6/28 (21%), of which 2/28 (7%) had no basis at all |
| The question would have surfaced the real issue | 10/18 fully, 17/18 at least partly |
| Should have been STOP | 1 of 4 came back STOP; 3 came back CAUTION |

**What we learned**
- **The question is the most valuable part.** In 3 of the 5 problems that got a GO, the question still pointed at the issue.
- **It misses the downstream human.** Clean, requested, backed-up changes read as GO even when the people on the receiving end would be confused or lose something.
- **It under-calls stops.** An ambiguous instruction mid-action and a breach of a standing data rule both came back as CAUTION. These need to be hard STOP rules in code, not judgment calls.
- **Some failures can't be seen from the request.** A missing skill or a leftover credential has to be caught by a preflight check in code.
- **Deletes fall outside send, spend and spin.** One harmful deletion passed silently, so we are adding a fourth trigger for destructive file operations.

**Verdict: it helps, with changes.** The plugin ships with hard STOP triggers, a downstream-people check before GO, code preflight checks and the delete trigger. The question stays on every card.

**Limits**
- The person who wrote the cases knew the outcomes.
- The sample is small and the test ran once.
- One person graded the cards.
- Treat the rates as directional (±15 points).

---

Copied from the operator-approved public-safe summary only. Its prospective phrase “the plugin ships” describes the evaluation recommendation, **not a claim that this local candidate has shipped or met all acceptance criteria**. See HOST-GAPS.md and README.md for implementation status.
