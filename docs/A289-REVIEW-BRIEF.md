# A289 adversarial review brief

Repository: /home/cua/repos/hermes-axioma
Baseline: fdd1fee06a2e63ffa3eb74f8e894c626c9b0651e (0.3.0)
Candidate: local main, 0.3.1; no push/PR/catalog edit authorized.

## Goal and acceptance list
Try to break the A287 Hermes-axioma fixes. Report concrete defects only with reproductions and file/line citations. Do not modify source, install a plugin, run network commands, use real credentials or read real keys. All test keys/data are synthetic temporary files.

- A1: README inventory discloses configured external skill/lock metadata probes and path/symlink resolution; CATALOG-DISCLOSURE.txt supplies the exact catalog addition.
- A4: key and immediate parent must be current-user owned, appropriate file/directory types and owner-only after tightening; refused/ineffective chmod must fail closed for durable verification with a clear message. Cached keys must not bypass rechecks. Symlinks are refused, without chmod of their target.
- A2: SEND/SPIN command regexes use the existing normalized command helper, including backslash-newline/CRLF continuations. Classification must not mutate exact staged arguments.
- A3: invalid skill-profile keys and preflight list settings flag config errors, retain individually valid rules and produce RED/axioma_config failures. Inaccessible required skill metadata produces RED/skills: fail, not generic advisory unavailable.
- A5: approval-renderer/internal localization imports live behind one compatibility function, with built-in English fallback if absent/incompatible. README discloses internal dependency and fallback limits. Card verification remains conservative; no approval state reads/overrides.
- A6: malformed-tag promise covers only completed transformed eligible prose; exceptions for malformed-only replies, code/lookalikes and streaming are disclosed in README and exact catalog replacement. README has catalog-name install/enable commands.
- Version 0.3.1 in README and plugin.yaml. No new test failures; note host-only skips.

## Changed files
README.md, CATALOG-DISCLOSURE.txt, axioma/seal.py, axioma/advisor.py, axioma/audit.py, axioma/policy.py, axioma/checks.py, tests/test_marketplace.py, plugin.yaml. This brief/evidence is handoff documentation only.

## Verification
Run from the repository:
- python3 -m unittest discover -s tests -v
- python3 -m unittest discover -s tests -p test_marketplace.py -v
- git diff fdd1fee --check

Current local result after both supplemental review fixes: 232 tests run, no failures/errors, 14 skipped (tests/test_host.py requires Hermes runtime). Bare python and the hermes CLI are absent in this Linux Space. Native validation/doctor/install and real host rendering have not been run here; AXIOM must validate at the exact exported commit before re-pinning.

## Supplemental adversarial review
The required command was attempted: hermes -p codereview chat --query-file /home/cua/repos/hermes-axioma/docs/A289-REVIEW-BRIEF.md -Q. Actual result: exit 127, `hermes: command not found`. No Hermes installation or configuration change was attempted.

A separate read-only reviewer subagent (not the codereview profile) found that pending approval answers could still be sealed using a cached durable key without a permission recheck. Reproduced locally with a failing synthetic regression. Fixed in Advisor.record: supplied durable keys are rechecked against the currently safe on-disk key before signing; an unsafe or replaced key produces an unsealed, throwaway-marked record, so restoring permissions cannot retroactively certify that answer. All 231 tests passed afterward (14 skips).

The second and final supplemental pass found no remaining defect in that fix, but reproduced a separate adjacent path: after rejecting a symlink key parent, best-effort audit logging followed the same symlink to chmod its target directory. Reproduced independently with a failing synthetic regression, then fixed Audit._owner_only to inspect the path itself and tighten only current-user-owned regular files/directories, never symlink targets. Final strict suite: `python3 -W error -m unittest discover -s tests -v`, 232 run, 14 skipped, no failures/errors. Full output: docs/evidence/tests-v0.3.1-space.txt. Both original review findings are fixed; no third review pass was run (two-pass limit).

Baseline independently rerun from a temporary git archive of fdd1fee: 221 tests, no failures/errors, the same 14 host skips. Added-line static scan found no matching hardcoded secret, shell=True/os.system, eval/exec, pickle or SQL f-string patterns; this limited scan is not native admission validation.

Standing proof attempted in this worker session: HTTP catalog snapshot check at https://raw.githubusercontent.com/NousResearch/hermes-agent/main/plugin-catalog/hermes-axioma.yaml, expecting the baseline full SHA. Result standing:29 = unavailable (not owner-allowlisted/target unavailable); no pass or demotion. This is not a passing proof and does not certify the local changes. Do not mark done until AXIOM obtains a relevant passing proof, native codereview and host validation. This handoff requests review only.
