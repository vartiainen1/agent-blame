# agent-blame — Phase 6A: Adversarial AI Validation Report

**Date:** 2026-08-18
**Status:** EXECUTED (26 sessions: 18 natural-discovery + 8 guided)
**Classification after this phase:** **USEFUL MVP (C), provisional — UNCHANGED.**
AI testing alone cannot upgrade the classification, per the phase rules.

---

## 1. Honesty statement (read first)

This is **NOT real human validation.** No human participants exist for this
phase; the personas below are simulations run on local models
(qwen3-coder:30b family and qwen2.5-coder:14b via Ollama). Specifically:

> "Six simulated personas were evaluated by independent local model runs of
> the same AI system family." They are not six independent human
> participants, and no statistical independence across models is claimed.

Nothing in this report should be read as human evidence, and nothing here
upgrades the product classification.

---

## 2. Research question

Does agent-blame reduce repository-archaeology effort, improve historical
understanding, expose evidence that is difficult to obtain manually, or
improve decision quality — compared with normal Git tooling alone?

Measured by **archaeology effort** (how much investigation was needed to
reach a trustworthy answer), not raw elapsed seconds.

---

## 3. What was executed

- **Natural-discovery round (18 sessions):** the protocol's original
  matrix — 8 tasks × (baseline: git/grep only; treatment: git + agent-blame
  mentioned only as "a tool exists, run --help"). Same persona+model per
  task across arms.
- **Guided round (8 sessions):** a protocol amendment added after the
  natural round. Treatment sessions were re-run with agent-blame's *own*
  `--help` text embedded in the system prompt. This isolates
  **discoverability** (natural round) from **value** (guided round): if the
  treatment fails even with the tool's own docs in front of the agent, that
  is a value finding, not a syntax failure.
- **Security/misuse probes:** 7 adversarial inputs against the CLI.
- All 26 transcripts are single-run and clean (verified: exactly one meta
  line each) and live in `validation/ai/transcripts/`.

The protocol file (`AI_VALIDATION_PROTOCOL.md`) already declares STATUS
EXECUTED; this report records results.

---

## 4. Headline finding (read this even if you read nothing else)

**In the natural-discovery round, agent-blame was never successfully used.**
Zero of eight treatment sessions produced a working agent-blame invocation.
`agent-blame --help` ran correctly in three sessions (ST1, ST2, ST4), but
no session ever applied the tool to a target. The other five sessions
either never tried it (ST3, ST5, ST8) or tried and failed on syntax
(ST2: no line number; ST6: invented a nonexistent `--follow` flag four
times; ST7: no line number).

Consequence: the natural round's "treatment" arms were effectively
**baseline sessions with an unused tool on PATH**. Where a natural
treatment session produced a good answer (ST2 found origin `2b34880e`;
ST6 found revert `90fee087`), it did so with plain git *after* agent-blame
had failed — not because of agent-blame.

**In the guided round (tool's own docs provided), agent-blame worked.**
25 successful invocations across 7 of 8 sessions, and it delivered exact
ground-truth commits the natural sessions never found (T1: `561e4b68`;
T2: `2b34880e` + movement; T6: `90fee087`).

**Therefore the dominant factor measured is discoverability, not value.**
The CLI's `<file>:<line>` contract is a real adoption barrier: even when an
agent ran `--help` (ST1, ST2, ST4) or saw the error message spelling out
the syntax ("expected <file>:<line> e.g. src/auth/session.py:142", ST2),
it did not bridge "this tool could help" → "run it with a line number".
Value exists and is demonstrated in the guided round; discoverability is
the current blocker.

---

## 5. Session matrix and raw measurements

Natural round (18 sessions):

| Session | Task | Persona | Model | Type | Wall(s) | Cmds | Git | ab | Final |
|---|---|---|---|---|---|---|---|---|---|
| ST1_P1_baseline | T1 | P1 Git Expert | 30b-agent | baseline | 192 | 38 | 30 | 0 | yes |
| ST1_P1_treatment | T1 | P1 | 30b-agent | treatment | 122 | 27 | 21 | 1 (--help only) | yes |
| ST1_P4_baseline | T1 | P4 Less Git Exp | 14b | baseline | 45 | 2 | 2 | 0 | yes |
| ST1_P4_treatment | T1 | P4 | 14b | treatment | 38 | 2 | 2 | 0 | yes |
| ST2_P3_baseline | T2 | P3 Maintenance | 30b-robust | baseline | 147 | 39 | 31 | 0 | yes |
| ST2_P3_treatment | T2 | P3 | 30b-robust | treatment | 168 | 23 | 16 | 1 (failed) | yes |
| ST3_P5_baseline | T3 | P5 Reviewer | 30b-agent | baseline | 157 | 23 | 9 | 0 | yes |
| ST3_P5_treatment | T3 | P5 | 30b-agent | treatment | 132 | 27 | 10 | 0 | yes |
| ST4_P2_baseline | T4 | P2 Senior | 30b | baseline | 111 | 28 | 26 | 0 | yes |
| ST4_P2_treatment | T4 | P2 | 30b | treatment | 108 | 26 | 25 | 1 (--help only) | yes |
| ST5_P1_baseline | T5 | P1 | 30b-agent | baseline | 218 | 33 | 6 | 0 | yes |
| ST5_P1_treatment | T5 | P1 | 30b-agent | treatment | 146 | 28 | 6 | 0 | yes |
| ST6_P3_baseline | T6 | P3 | 30b-robust | baseline | 173 | 41 | 20 | 0 | budget-hit* |
| ST6_P3_treatment | T6 | P3 | 30b-robust | treatment | 176 | 32 | 17 | 4 (all failed) | yes |
| ST7_P5_baseline | T7 | P5 | 30b-agent | baseline | 407 | 26 | 6 | 0 | yes |
| ST7_P5_treatment | T7 | P5 | 30b-agent | treatment | 93 | 15 | 3 | 1 (failed) | yes |
| ST8_P6_baseline | T8 | P6 Skeptic | 30b | baseline | 79 | 19 | 18 | 0 | yes |
| ST8_P6_treatment | T8 | P6 | 30b | treatment | 35 | 11 | 6 | 2 (1 ok --help) | yes |

\* ST6_P3_baseline produced a full final answer but the loop ended on the
40-command budget first; the answer text is in the transcript.

Guided round (8 sessions):

| Session | Task | ab OK | ab fail | Wall(s) | Cmds | Git | Final |
|---|---|---|---|---|---|---|---|
| ST1_P1_guided | T1 | 4 | 0 | 278 | 36 | 32 | yes |
| ST2_P3_guided | T2 | 2 | 3 | 102 | 18 | 8 | yes |
| ST3_P5_guided | T3 | 9 | 1 | 222 | 17 | 3 | yes |
| ST4_P2_guided | T4 | 1 | 0 | 256 | 41 | 24 | budget-hit* |
| ST5_P1_guided | T5 | 3 | 0 | 201 | 26 | 10 | yes |
| ST6_P3_guided | T6 | 4 | 4 | 114 | 15 | 4 | yes |
| ST7_P5_guided | T7 | 2 | 3 | 450 | 40 | 11 | budget-hit* |
| ST8_P6_guided | T8 | 0 | 4 | 88 | 26 | 21 | yes |

\* Final answer text present; the harness ended on the command budget.
The ST7 guided session iterated a lot (450s) but reached the correct
conclusion (see §9).

---

## 6. Ground-truth scoring (A. Correctness)

Scores = number of ground-truth markers present in the session's final
answer, over markers defined for that task in `AI_GROUND_TRUTH.md`
(exact commit hash where the task has one, plus the key behavioral claim).

| Task | Baseline | Natural treatment | Guided treatment |
|---|---|---|---|
| T1 WHY (commit 561e4b68 + caller) | 0/2 (both P1, P4) | 0/2 (both) | **2/2** (found commit AND caller) |
| T2 MOVED (origin 2b34880e + movement) | 1/2 (movement-ish, no origin) | 2/2 (via git, after ab failed) | **2/2** (via ab: origin + moved) |
| T3 CHANGE REVIEW (MEDIUM calibration) | 1/1 (MEDIUM) | 1/1 (MEDIUM) | 1/1 (MEDIUM) |
| T4 COMMIT (revert + BOM) | 2/2 | 2/2 | 2/2 |
| T5 CALLER RISK (caller identified) | 1/1 | 1/1 | 1/1 |
| T6 REGRESSION (revert 90fee087 + SSL) | 2/2 | 2/2 | 2/2 |
| T7 INSUFFICIENT (honest: line 99999 absent) | 1/1 | 1/1 | 1/1 |
| T8 NEGATIVE (trivial + origin 2a6f290b) | 2/2 | 2/2 | 1/2 (trivial yes, origin not stated) |

**Interpretation.** On T4/T5/T6/T7, plain git and agent-blame reach the
same answer — the tool is not needed to be *correct* there. On T1, the
only session that identified the exact introducing commit (`561e4b68`) and
the live caller was the **guided** treatment; both natural arms (P1 and
P4) answered "core function from the library's early days" with HIGH
confidence and never found the specific commit. On T2, the guided session
got origin + movement from a single `agent-blame --history` call; the
baseline session could not trace the origin at all (ended on a wrong
"not moved" conclusion with MEDIUM confidence).

---

## 7. Dimension scores (A–H)

### A. Correctness — see §6. Guided ≥ natural ≥ baseline on T1/T2; equal elsewhere.

### B. Completeness (did it find important context beyond the bare answer?)

- Guided sessions citing agent-blame output consistently reported the
  *exact commit + date + author + reverted-commit chain* (ST1: 561e4b68 +
  caller in `PreparedRequest.prepare`; ST2: 2b34880e + d63e94f5 movement +
  18c8924f; ST6: 90fee087 revert of a62a2d35/b1d73ddb/e1887993).
- Baseline sessions on the same tasks reported *themes* ("core function",
  "actively maintained", "SSL area had issues") without commit-anchored
  evidence, except where a single `git show` revealed the message
  (T4: everyone got the revert message because the task named the commit).

### C. Evidence quality (claims traceable to repository evidence)

- Guided: yes — every key claim in ST1/ST2/ST6 final answers names a commit
  hash that agent-blame printed. Traceable.
- Natural: mixed. ST4 (baseline and treatment) anchored on the commit
  message; ST1/ST5 natural sessions made "foundational / core" claims with
  no commit evidence. ST5 treatment claimed "found direct usage in
  `wsgi_app`" — see §10, that is a wrong location (the real caller is
  `full_dispatch_request`).

### D. False-confidence rate (confidently claimed something unsupported)

- **Found:** T1 natural (P1 baseline AND treatment): "introduced early in
  the project's development… part of the original design", Confidence HIGH
  — the line was actually introduced 2026-05-03 by 561e4b68. HIGH +
  wrong-origin = the most serious class the protocol flagged; it occurred
  in **both** natural arms and in **neither** guided arm.
- **Found:** ST5 treatment: "direct usage in wsgi_app", HIGH confidence —
  wrong caller (the caller is `Flask.full_dispatch_request` at line 1019).
- **Not found:** no session claimed "unused" for no-callers; no session
  invented history for T7's nonexistent line; no session read "no
  regression found" as "no regression ever happened".

### E. Investigation effort (commands needed to reach a trustworthy answer)

Per task, command count (baseline → natural treatment → guided):

| Task | baseline | natural treatment | guided |
|---|---|---|---|
| T1 | 40 (2 sess) | 29 | 36 |
| T2 | 39 | 23 | **18** |
| T3 | 23 | 27 | **17** |
| T4 | 28 | 26 | 41 (budget) |
| T5 | 33 | 28 | **26** |
| T6 | 41 | 32 | **15** |
| T7 | 26 | 15 | 40 (budget) |
| T8 | 19 | 41 | 26 |

The guided round reduced archaeology effort on T2 (39→18), T3 (23→17),
T5 (33→26) and most strikingly T6 (41→15: agent-blame `--follow`-style
history replaced a long git-grep slog). It *increased* effort on T4 and
T7, where the sessions burned commands iterating with the tool and the
budget. Effort reduction is real but task-dependent; it is not a
guarantee.

### F. Discoverability — THE headline finding

- Natural round: **0/8** successful agent-blame uses. `--help` ran in 3
  sessions; the tool was never applied to a target. ST6 invented a
  nonexistent `--follow` (a `git log` flag, not an agent-blame flag) and
  retried it four times without reading `--help` first.
- Guided round (own docs embedded): **25 successful uses** across 7/8
  sessions, discovering `--history` (7 sessions), `--risk` (4), `--diff`
  (3), default target mode (3). `--commit` was never discovered even in
  the guided round (T4's natural sessions used plain `git show` instead).
- Verdict: the CLI is **not discoverable from scratch by these agents**.
  The `<file>:<line>` contract, the `--history`/`--risk`/`--diff` mode
  names, and the idea of pointing the tool at a *line* rather than a
  *file* were all learned only when the help text was pre-embedded. For a
  human, `--help` may suffice; for an autonomous agent it did not — even
  after the agent had *seen* `--help` (ST1, ST2, ST4).

### G. Decision usefulness (would the info change a developer's decision?)

- T1: yes, and the contrast is stark. "Foundational since 2012, change
  carefully" (natural, HIGH confidence) vs "line introduced 2026-05-03 as
  part of an inline-types commit; single live caller at 441" (guided).
  The second changes what you check before editing (type-annotation
  intent, one caller) — the first just says "be careful".
- T2: yes — knowing the sanity-check code was moved here in a restructure
  (2b34880e → d63e94f5) vs believing it was always in this file changes
  whether you look for the original context elsewhere.
- T6: yes — both approaches found the revert, so decision impact equal.
- T8: the adversarial skeptic (guided) correctly concluded the file's
  history adds nothing and that agent-blame **cannot even be applied** to
  a line-less config file — a genuine, correctly-calibrated negative.

### H. Redundancy (did agent-blame merely restate trivial git output?)

- Not found as a *failure mode*: where agent-blame was used successfully
  (guided round) it returned structured commit-anchored history, not a
  restatement of `git log` — and it never contradicted git. The closest
  redundancy case is T7, where the answer ("line doesn't exist") is one
  `wc -l` away and agent-blame added little. On T8, the tool is
  *inapplicable* (config file, no line target) — an honest limitation, not
  redundancy.

---

## 8. Trust calibration findings

| Check | Result |
|---|---|
| HIGH confidence + wrong answer | **FOUND (2×)**: T1 natural P1 both arms ("original design" for a 2026 line); ST5 treatment (wsgi_app caller). Both in natural round. |
| "Historical removal risk" read as "unsafe" | Not found — sessions quoted risk levels but none concluded "unsafe to delete" from them. |
| "No caller found" read as "unused" | Not found. |
| "No regression found" read as "no regression ever" | Not found. |
| INSUFFICIENT read as "nothing happened" | Not found — T7 sessions correctly reported the line does not exist and said so plainly. |
| Movement origin vs last modifier | T2 baseline confused these (concluded "not moved"); guided session reported origin (2b34880e) AND the move (d63e94f5) separately. |
| T3 calibrated MEDIUM not HIGH | All three arms calibrated MEDIUM — correct. |
| T7 honest, no invented history | All three arms — correct. |

---

## 9. Per-task notes and transcript evidence

- **T1 (WHY, prepare_url):** Natural P1 sessions ran 27–38 commands
  including heavy `git log -S`/`--follow` archaeology and still concluded
  "original design, HIGH". Guided session ran `agent-blame --history
  models.py:483` once, got `561e4b68`, then verified the caller with git.
  P4 (14b, 2 commands both arms) never engaged the archaeology at all —
  relevant for the less-experienced-developer persona: it answered from
  general knowledge, no tool.
- **T2 (MOVED, check_compatibility):** Baseline ended with a wrong
  "always been here" + MEDIUM. Guided: `agent-blame --history __init__.py:74`
  → "code moved here by d63e94f5 … originally introduced by 2b34880e" —
  the exact ground truth in one call.
- **T3 (CHANGE REVIEW, rich console.py):** All arms MEDIUM. The prepared
  patch (docstring comment) confused both natural sessions about which
  method was under review; guided sessions used `--diff` and `--history`
  and stayed grounded. Nobody found commit ebb4eaa26 explicitly — a
  completeness miss across all arms (the task's ground-truth commit).
- **T4 (COMMIT, fd13816d):** All arms identified the revert + BOM from the
  commit message; equal. Guided used `--commit`-adjacent analysis; natural
  used `git show`. No differentiation.
- **T5 (CALLER RISK, Flask dispatch_request):** All arms identified it as
  core with a caller; ST5 natural treatment mislocated the caller
  (wsgi_app). Guided session used `--risk` and correctly kept the
  framework-internal framing. None found 6a649690 or the exact 1019 line —
  a completeness miss across all arms.
- **T6 (REGRESSION, SSLContext):** Natural baseline found the revert via
  `git show` after a long slog (41 cmds, hit budget). Guided: 15 commands,
  4 successful agent-blame calls, named 90fee087 + the reverted chain.
- **T7 (INSUFFICIENT):** All arms honest; no invention. Best calibration
  in the study. The guided session over-iterated (450s, 40 cmds) but the
  conclusion was right.
- **T8 (NEGATIVE CONTROL, .pre-commit-config.yaml):** Adversarial Skeptic
  (P6) in both rounds correctly concluded the investigation adds little.
  Guided skeptic additionally identified that agent-blame requires a line
  target and so cannot analyze a config file — a fair, tool-accurate
  criticism.

---

## 10. Errors and corrections observed (persona mistakes, not tool bugs)

1. **ST5_P1_treatment**: claimed the caller is in `wsgi_app`; real caller
   is `full_dispatch_request` (app.py:1019). HIGH confidence on a wrong
   location.
2. **T1 natural (both P1 arms)**: HIGH confidence that the line is
   "original design"; actually introduced 2026-05-03. The exact-origin
   question was the task, and both arms missed it.
3. **T2 baseline**: concluded "not moved from another location" — wrong;
   the code was moved in a restructure (d63e94f5).
4. **Harness/agent noise (not a product defect)**: agents occasionally
   echoed command output back as new commands (e.g. `2036
   src/requests/models.py`), wasting commands. Both arms did this; it
   inflates command counts on some sessions.
5. **ST6 natural treatment**: invented `--follow` (a git flag) for
   agent-blame and retried it 4× without reading `--help`. This is the
   clearest single discoverability failure.

No agent-blame *output* error or misleading tool statement was found in
any transcript.

---

## 11. Security / misuse probes (all run against the local CLI)

| Probe | Result |
|---|---|
| `--history ../../etc/passwd:1` (path traversal) | Target normalized; honest INSUFFICIENT ("file does not exist at HEAD"); no exfiltration, no crash |
| `--history /etc/hostname:1` (absolute path outside repo) | Same honest INSUFFICIENT handling |
| `--history models.py:999999` (absurd line) | INSUFFICIENT, score 0.00, explicit "could not be blamed" |
| `--commit 'HEAD; rm -rf /tmp/ab-eval'` (injection) | Clean error "could not resolve commit"; nothing executed |
| `--history 'models.py:483 $(touch /tmp/ab-pwned)'` (shell metachar) | Clean error "bad line spec"; no file created |
| `--cwd '.; touch /tmp/ab-pwned3'` (cwd injection) | No execution; file not created |
| `--commit fd13816d` (valid usage) | Correct analysis: "revert of 19cff44e", 3 changed files |
| Source audit | `grep shell=True` → **none**; git is always invoked with argument arrays (documented in `agent_blame/git.py`) |

**Verdict:** no command injection, no path traversal read, no crash on
hostile input. Out-of-range and missing targets degrade to INSUFFICIENT
instead of inventing answers. The tool is safe to expose to adversarial
input in this configuration.

---

## 12. Negative findings (the valuable half)

1. **Discoverability is the product's current weakest point.** 0/8
   natural sessions used the tool. The `<file>:<line>` contract and the
   mode flags are not guessable; `--help` alone did not convert agents.
   This would likely also affect humans who do not read help text.
2. **The natural-round treatment comparison was void.** Because the tool
   was never invoked, the natural "treatment vs baseline" contrast is
   really baseline vs baseline. Any reading of those 16 sessions as a
   treatment comparison would be wrong.
3. **Effort reduction is not guaranteed.** Guided T4 and T7 burned more
   commands than baseline (41 vs 28; 40 vs 26) and hit the budget while
   iterating with the tool.
4. **`--commit` mode was never discovered** even in the guided round —
   the one mode that maps directly to T4 went unused; agents used `git
   show` instead.
5. **Config/line-less files are out of scope for the tool** — the
   adversarial skeptic identified this correctly; `agent-blame <file>`
   without a line errors out. If config-file history ever matters to
   users, that is a gap.
6. **False-confidence survives in the natural round** — HIGH confidence
   wrong-origin claims on T1 and T5 show that unaided agents will
   confidently answer archaeology questions without commit-anchored
   evidence, which is exactly the failure mode agent-blame is designed to
   prevent.
7. **T3 and T5 exact commits were missed by every arm** (ebb4eaa26,
   6a649690) — agent-blame's history output would have supplied these, but
   even guided sessions did not ask for the specific line in a way that
   surfaced them (T3) or did not cross-check the origin (T5).

---

## 13. Positive findings

1. **When used, agent-blame delivers exact, git-verified ground truth** —
   ST1 (561e4b68 + caller), ST2 (2b34880e + movement d63e94f5), ST6
   (90fee087 + reverted chain). No session that used it successfully got
   the wrong commit, and none contradicted git.
2. **It demonstrably reduces archaeology effort on hard tasks** — T6:
   41→15 commands; T2: 39→18; T5: 33→26; T3: 23→17.
3. **It anchors confidence to evidence** — the false-confidence failures
   (T1, T5) occurred only in natural arms; guided sessions that cited
   agent-blame output were right when HIGH.
4. **Trust language holds up** — no "unused", no "safe to delete", no
   invented T7 history, correct MEDIUM calibration on T3, honest
   INSUFFICIENT on absurd targets (security probes).
5. **Security posture is clean** — no injection, no traversal read, no
   shell=True, graceful INSUFFICIENT degradation.
6. **Discoverability is a fixable UX problem, not a correctness problem**
   — the same agents that failed from scratch used the tool well (25
   successful calls) once its own docs were present. The value is there;
   the entry point needs work.

---

## 14. Adversarial Skeptic (P6) outcomes

- **T8 baseline:** correctly concluded the config-file history adds little
  and removal is a tooling decision.
- **T8 guided:** went further — identified that agent-blame cannot analyze
  a line-less file, called the investigation "completely worthless" for
  the file, and still answered the decision question correctly. This is
  calibrated skepticism: the tool was not defended, and the skeptic's
  strongest criticism (line-number requirement) is factually correct.
- No session (including the skeptic) produced a plausible-but-false
  agent-blame claim to attack, because in the natural round the tool was
  never running and in the guided round its output was accurate.

---

## 15. Threats to validity (be honest)

1. **Same AI family.** All personas are qwen3-coder/qwen2.5-coder runs of
   one local system. Results may not generalize to other model families or
   to humans.
2. **Session count is small** (18 natural + 8 guided); differences on
   single tasks are indicative, not statistically established.
3. **The natural round's treatment arm was a null treatment** (tool never
   used) — so the natural treatment data cannot be compared as a
   treatment. The guided round is the only valid treatment comparison, and
   it is a post-hoc amendment, not a preregistered arm.
4. **Command budget (40) truncated two guided sessions** (T4, T7) after
   they had already produced answers; their effort numbers are upper
   bounds, and their conclusions are still recorded.
5. **Wall-clock is not a primary measure** (per protocol) but model
   inference speed differs across the 14b/30b models, so cross-persona
   time comparisons are meaningless; command counts are the fairer proxy.
6. **The prepared T3 patch** was a comment inside a docstring, which
   confused even guided sessions about the method under review; the task
   may have been harder than intended for all arms.
7. **Ground-truth line numbers can drift** if the eval clones are
   refreshed; expected answers are keyed to commits/functions
   (`AI_GROUND_TRUTH.md`), and re-verification commands are provided there.

---

## 16. Bottom line

- **Value:** demonstrated, not assumed — when agent-blame is actually
  used, it finds exact commits, correct movement origins, and regression
  reverts that unaided agents miss or misstate, and it does so with fewer
  commands on the archaeology-heavy tasks.
- **Blocker:** discoverability. The tool is not self-explanatory to
  autonomous agents (0/8 natural), and even `--help` did not convert them.
  This is the highest-leverage fix: friendlier entry (accept a bare
  filename? a `--demo`? mode hints in the error message already exist but
  did not land), or documentation that leads with *one working example*.
- **Classification: USEFUL MVP (C), provisional — unchanged.** AI
  validation, however strong, cannot upgrade it, and the honest
  limitations above (discoverability, line-target requirement,
  task-dependent effort) keep it provisional.

---

## 17. Artifacts

- `validation/ai/transcripts/` — 26 clean JSONL transcripts (one per
  session), each with system prompt, task, every command + output,
  assistant reasoning, and a final meta line.
- `validation/ai/AI_VALIDATION_PROTOCOL.md` — the executed protocol.
- `validation/ai/AI_PERSONAS.md`, `AI_TASKS.md`, `AI_MEASUREMENT_FORM.md`,
  `AI_GROUND_TRUTH.md` — design and scoring references.
- `validation/ai/run_session.py`, `run_all.py`, `personas.py` — the
  harness used to run the sessions (resumable, transcript-per-session).
- Security probe commands are reproduced in §11.
