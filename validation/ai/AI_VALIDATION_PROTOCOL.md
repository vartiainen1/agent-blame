# agent-blame — Phase 6A: Adversarial AI Validation Protocol

**STATUS: EXECUTED 2026-08-18.** Controlled task experiments comparing
normal Git tooling (baseline) against normal Git tooling + agent-blame
(treatment), using simulated AI developer personas on genuinely independent
model runs.

This is **NOT real human validation**. No human participants exist for this
phase; AI personas are simulations. Nothing in this phase upgrades the
product classification (remains USEFUL MVP (C), provisional).

## 1. Research question

Does agent-blame reduce repository-archaeology effort, improve historical
understanding, expose evidence that is difficult to obtain manually, or
improve decision quality — compared with normal Git tooling alone?

Measured by **archaeology effort** (how much investigation was needed to
reach a trustworthy answer), not raw elapsed seconds (Phase 4 already
established agent-blame is not necessarily faster per command).

## 2. Independence model

- Each session is a **fresh, isolated model context** (a separate ollama
  chat with no shared history). No session sees another session's
  transcript, commands, or conclusions.
- Personas map to distinct models where available (see §3), so persona
  results are independent model runs — but all are qwen3-coder /
  qwen2.5-coder family runs of the *same AI system family*.
- **Honest statement**: "Six simulated personas were evaluated by
  independent local model runs of the same AI system family." They are not
  six independent human participants, and no statistical independence
  across models is claimed.

## 3. Session matrix (18 natural + 8 guided = 26 sessions)

A **guided round** was added post-hoc after the natural round exposed a
treatment-delivery failure: no natural treatment session ever invoked
agent-blame successfully (discoverability failure). The guided round
re-runs each task's treatment session with agent-blame's own `--help`
text embedded in the system prompt, isolating discoverability (natural
round) from value (guided round). See AI_VALIDATION_REPORT.md §4.

Task → persona → model. Baseline and treatment always use the **same
persona and model** (fair comparison). Ordering alternates (odd task
numbers: baseline first; even: treatment first) and is recorded per
session in the transcript header.

| # | Task | Persona | Model | Repo | Type |
|---|------|---------|-------|------|------|
| 1 | T1 WHY | P4 Less Git-Experienced | qwen2.5-coder:14b | requests | baseline |
| 2 | T1 WHY | P4 Less Git-Experienced | qwen2.5-coder:14b | requests | treatment |
| 3 | T1 WHY | P1 Git Expert | qwen3-coder:30b-agent | requests | baseline |
| 4 | T1 WHY | P1 Git Expert | qwen3-coder:30b-agent | requests | treatment |
| 5 | T2 MOVED | P3 Maintenance Dev | qwen3-coder:30b-robust | requests | baseline |
| 6 | T2 MOVED | P3 Maintenance Dev | qwen3-coder:30b-robust | requests | treatment |
| 7 | T3 CHANGE REVIEW | P5 Code Reviewer | qwen3-coder:30b-agent | rich | baseline |
| 8 | T3 CHANGE REVIEW | P5 Code Reviewer | qwen3-coder:30b-agent | rich | treatment |
| 9 | T4 COMMIT | P2 Senior Dev | qwen3-coder:30b | requests | baseline |
| 10 | T4 COMMIT | P2 Senior Dev | qwen3-coder:30b | requests | treatment |
| 11 | T5 CALLER RISK | P1 Git Expert | qwen3-coder:30b-agent | flask | baseline |
| 12 | T5 CALLER RISK | P1 Git Expert | qwen3-coder:30b-agent | flask | treatment |
| 13 | T6 REGRESSION | P3 Maintenance Dev | qwen3-coder:30b-robust | requests | baseline |
| 14 | T6 REGRESSION | P3 Maintenance Dev | qwen3-coder:30b-robust | requests | treatment |
| 15 | T7 INSUFFICIENT | P5 Code Reviewer | qwen3-coder:30b-agent | requests | baseline |
| 16 | T7 INSUFFICIENT | P5 Code Reviewer | qwen3-coder:30b-agent | requests | treatment |
| 17 | T8 NEGATIVE | P6 Adversarial Skeptic | qwen3-coder:30b | requests | baseline |
| 18 | T8 NEGATIVE | P6 Adversarial Skeptic | qwen3-coder:30b | requests | treatment |

Task 1 runs with two personas (P4 and P1) to contrast discoverability for
a less git-experienced developer vs a git expert on the same task.

## 4. Session flow (per session)

1. **Setup**: repo verified clean; for T3, the prepared diff is applied to
   the working tree (restored after the session).
2. **Prompt**: system prompt (persona + environment) + task text. No
   feature hints, no expected-answer hints.
3. **Agentic loop**: the persona proposes a bash command (fenced block);
   the harness executes it (command budget 15, wall-clock budget 12 min,
   output truncated to 3000 chars) and returns output. Repeat until the
   persona emits `FINAL ANSWER:` or a budget is exhausted.
4. **Teardown**: transcript JSONL written to `transcripts/`; for T3 the
   working tree is restored and verified clean.

## 5. Command environment

- Working directory: the repository root in `/tmp/ab-eval/`.
- Allowed: `git` (read-only subcommands only — `commit/checkout/reset/
  clean` are blocked), `grep`/`rg`, `find`, `cat`/`head`/`tail`/`wc`/`sed`,
  `ls`, `pwd`, `python` (read-only), `agent-blame` (treatment only).
- Blocked: any write to the repository, `rm -rf`, network commands.
- Baseline PATH: no `agent-blame`; the system prompt does not mention it.
- Treatment PATH: a shim `agent-blame` (runs the local install via `uv
  run`) is prepended; the system prompt mentions only that the tool exists.

## 6. Measurement (recorded per session in the transcript + analysis)

Per session: task, persona, model, baseline/treatment, ordering, every
command executed, command count, git-command count, agent-blame commands,
wall-clock duration, files/commits inspected, raw evidence discovered,
final conclusion verbatim, confidence stated, mistakes, false assumptions,
corrections, whether the conclusion matched git-verified ground truth,
whether important evidence was missed, whether evidence was invented.

## 7. Scoring dimensions (per task, both approaches)

| Dim | Definition |
|-----|-----------|
| A. Correctness | reached git-verified truth? (match to `AI_GROUND_TRUTH.md`) |
| B. Completeness | discovered important historical context beyond the bare answer? |
| C. Evidence quality | claims traceable to actual repository evidence? |
| D. False-confidence rate | confidently claimed something unsupported? |
| E. Investigation effort | how much manual archaeology was required (commands, digging)? |
| F. Discoverability | could the persona discover useful functionality without being told? |
| G. Decision usefulness | would the discovered information affect a developer's decision? |
| H. Redundancy | did agent-blame merely restate what one git command gives trivially? |

Scores are recorded with transcript evidence. No arbitrary weighting —
each dimension is reported separately; A–E decide value, H guards against
overclaiming.

## 8. Trust calibration checks (in analysis)

- HIGH confidence + wrong answer = most serious finding; flag it.
- "Historical removal risk" must not be read as "unsafe".
- "No caller found" must not be read as "unused".
- "No regression found" must not be read as "no regression ever happened".
- INSUFFICIENT EVIDENCE must not be read as "nothing happened".
- Movement origin must be distinguished from last modifier.
- Confidence level must be appropriate to the evidence (T3 MEDIUM not
  HIGH; T7 INSUFFICIENT, not invented).

## 9. Adversarial / negative-control sessions

- T8 (negative control) runs with the Adversarial Skeptic persona — the
  explicit attempt to prove the tool unnecessary on a target where little
  value is expected.
- Blind discovery is measured from all treatment transcripts: did the
  persona find `--help`, WHY, HISTORY, RISK, CALLERS, MOVEMENT, REGRESSION,
  `--diff`, `--commit` without any hint?

## 10. Honesty rules

- Six simulated personas, evaluated by independent local model runs of the
  same AI system family. **Not human participants.** State this in the
  report's first section and wherever participants are discussed.
- No invented quotes, counts, or findings. Everything in the report cites
  a transcript file.
- Report positive AND negative findings. Negative findings are the
  valuable half.
- The classification stays **USEFUL MVP (C), provisional** — AI testing
  alone cannot move it.
- The feature set stays frozen; no agent-blame changes are made during the
  study unless a genuine correctness bug blocks execution (then: log →
  regression test → fix → full suite → AREA commit).
