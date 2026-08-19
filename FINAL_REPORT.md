# agent-blame — Final Project Report (v0.1.0)

**Version:** 0.1.0 — **feature-frozen.** This document is the durable
close-out record for the v0.1.0 project. It summarizes the complete
project, the validation evidence (and its honest limits), and what
remains.

**Status line:** 321 tests green; both repositories clean; classification
**USEFUL MVP (C) — PROVISIONAL**; real human validation **NOT RUN**
(independent participants currently unavailable).

---

## A. What agent-blame is

agent-blame is a **local-first, deterministic, stdlib-only Git-archaeology
CLI** (Python 3.9+, no dependencies, no network). It answers *why* code
exists, *how* it evolved, *who* calls it, and what historical evidence
matters before changing or removing it — by **aggregating evidence Git
already keeps but keeps scattered**: introducing commits, later
modifications, code movement, callers, risk signals, and regression/revert
history.

It is deliberately **not a prettier `git blame`**. `git blame` answers
"who changed this line"; agent-blame answers "why does this code exist,
and what should I know before touching it?" The core is a deterministic
historical-analysis algorithm — no AI, no LLM, no telemetry. The
repository is the source of truth; the tool reports evidence and says
`INSUFFICIENT EVIDENCE` when it does not know.

Honest positioning (stated plainly to evaluators): it is **not faster
than a known `git blame` command**; its value is discovery and
aggregation — knowing which commands to run and combining the results.

---

## B. What shipped

| Stage | What shipped |
|-------|--------------|
| **Core** | Pipeline: repository discovery → safe git abstraction → blame/history extraction → targeted historical graph → evidence discovery → deterministic ranking → inference + counter-evidence → confidence → risk → structured terminal + JSON output. Facts, inferences, and counter-evidence strictly separated; output sanitized against malicious repository content (no shell, timeouts, no code execution). |
| **Phase 2A — `--diff`** | Historical context for the developer's current working-tree (or staged) changes; hunks grouped and merged by evidence signature to avoid noise; honest handling of added/deleted/renamed/binary/new files. |
| **Phase 2B — `--commit`** | Historical context for one commit against its parent (chronology-guaranteed: the analyzed commit can never be credited as the origin of the change it makes); root/merge/revert/delete/rename handling. |
| **Phase 2C — callers/symbols** | Conservative Python AST (parse-only) symbol + caller analysis enriching every mode: DIRECT_CALL / ATTRIBUTE_CALL / IMPORT_REFERENCE / POSSIBLE_CALL (scored) and TEXTUAL_MATCH / UNRESOLVED (zero weight, reported for transparency); revision-honest LIVE / MODIFIED / DELETED caller status; qualified-name identity. |
| **Phase 2D — code movement** | A move is **never** reported as an introduction. Three evidence sources: git rename metadata, blame-origin capture + bounded movement-chain walk, and symbol-level continuity for the partial moves git misses. Classification RENAME / CODE_MOVEMENT / POSSIBLE_MOVEMENT / COPY; movement is context, never a risk level by itself. |
| **Phase 2E — regression detection** | Later commits that revert/fix the target's history, classified on a strict ladder (EXPLICIT_REVERT → LIKELY → POSSIBLE → CORRECTIVE_CHANGE → NO_REGRESSION_EVIDENCE). The central rule: **correlation is not proof of causation** — the tool says "reverts" / "evidence indicates", never "caused a bug". Symbol-overlap false-positive guard; chronology guard (pre-introducer history is never cited against new code). |
| **Phase 3 — real-repo evaluation** | Feature-frozen evaluation against requests, flask, rich. Found and fixed three genuine correctness bugs (confidence-destroying chronology, replacement counter-evidence stacking, revert/corrective double-count), two performance problems (**49 s → 12.5 s** on a rename-heavy commit; 1,693 → 568 git calls), a commit-mode bug, and two regression-noise sources. **270 tests green; zero false HIGH-confidence claims; zero CONTRADICTORY confidence.** |
| **Phase 4 — simulated external-developer validation** | Simulated external developers (no real participants available). Found and fixed a false-caller correctness bug, output noise (528→82 lines with zero information loss), and a misleading caller marker. **279 tests green; JSON byte-identical across runs; USEFUL MVP (C).** |
| **Phase 5 — study package** | The complete, executable real 5-developer study package (`validation/`): protocol, participant quick start, task sheet, measurement form (36-section report template), reference targets with git-verified ground truth. |
| **Phase 6A/6B/6C — adversarial AI validation** | 26+12 AI sessions on real repos. Established: the tool's value is demonstrated once it is used (guided round 25/25), but natural discovery of the primary invocation contract was the blocker (0/8 natural, 0/3 after help-text improvements, 1/6 in Condition C). |
| **§15 — target resolution** | The Phase 6C outcome, implemented: bare `file` (prints the file's blame-able lines — symbol table for Python, line count otherwise), `file:function` (AST-resolved to the defining line with an explicit "resolved to line N" note), and bare `<sha>` (equivalent to `--commit <sha>`). Parsing/entry-point/UX only — engine, ranking, confidence, movement, regression, evidence, JSON schema, and help text unchanged. **321 tests green (+37).** |

**Measurable headline results:** 321 tests passing · Phase 3 performance
~49 s → ~12.5 s on the rename-heavy commit · Phase 6C Condition C natural
valid invocations **1/6 → 2/6** after the §15 fix.

---

## C. Validation evidence — what each kind proves, and does not

### 1. Automated tests (321, all green)

**Proves:** the engine's behavior on scripted miniature repositories with
known histories — introduction, modification, movement, rename, revert,
regression sequences, misleading and malicious commit messages, Unicode
paths, shallow clones, deleted files, line ranges, every CLI mode, every
JSON schema contract, security properties (no control-char leakage, no
shell), determinism (byte-identical JSON across runs).

**Does NOT prove:** that any real developer finds the tool useful,
understandable, or worth installing. Tests verify the algorithm against
its specification, not the product against the market.

### 2. Real-repository evaluation (Phase 3)

**Proves:** the algorithm behaves correctly on real, large, messy history
(requests/flask/rich full clones): no false HIGH-confidence findings, no
CONTRADICTORY confidence, chronology and movement corrections hold against
git-verified ground truth, and performance is acceptable on
rename/refactor-heavy history.

**Does NOT prove:** that any human would reach for the tool, trust its
output, or prefer it over plain git. Correctness on real data ≠ adoption.

### 3. Simulated external-developer evaluation (Phase 4)

**Proves:** the tool survives adversarial use by simulated "external
developers" — the exercise caught a real false-caller correctness bug and
real output-noise problems that unit tests had missed.

**Does NOT prove:** anything about real developers. The "developers" were
AI agents (or scripted simulations) in a build environment with no human
participants. It is explicitly labeled a simulation in the record.

### 4. Adversarial AI validation (Phase 6A/6B/6C)

**Proves:** for the tested model family (qwen3-coder), the value
proposition is perceived once the tool is used (guided round: 25/25 usable
calls with git-verified ground truth); the adoption blocker is the
invocation contract, not capability awareness; the §15 target-resolution
change converted one previously failing function-name invocation and
raised natural valid invocations from 1/6 to 2/6.

**Does NOT prove:** that humans behave like these agents. The findings are
AI evidence about a specific model family's tool-use behavior — a signal
about friction points, not a substitute for human observation.

### 5. Human validation

**Status: NOT RUN — 0 real participants.**

**Proves:** nothing about real humans yet. No quotes, usability results,
adoption intent, or satisfaction scores in this project come from real
developers. Every claim about real developer usefulness, trust,
comprehension, or repeated voluntary use is therefore **unvalidated**.

---

## D. Phase 6C conclusion (recorded)

- The target-resolution change was **implemented as planned** — bare
  `file`, `file:function`, and bare `<sha>` are supported, parsing/UX
  only.
- The exact Condition C retest improved natural valid invocations from
  **1/6 → 2/6** sessions.
- The predefined **≥3/6 success target was not reached** (2/6).
- **One previously failing function-name invocation was successfully
  converted**: ST5's identical command (`app.py:dispatch_request`, which
  failed with "bad line spec" before the fix) now resolves to the
  git-verified defining line 969 without reading `--help`.
- The **dominant remaining failure class** (4/6 sessions) was agents
  inventing Git-style flags (`--file`, `--function`, `--line`, `-L`,
  `--show-code`, `--all`) without discovering the CLI interface — they
  never read `--help`, never ran a bare-file or colon form, and so never
  saw the affordances.
- **Further parser changes are unlikely to address that failure class
  directly**: it is upstream of syntax (an agent that invents flags it
  never saw cannot be reached by more target forms). The result stands
  unchanged from the Phase 6C report; no re-interpretation.

---

## E. Human-validation limitation (explicit)

- The **5-developer study package is complete** (`validation/`) — protocol,
  participant materials, measurement form, reference targets.
- The **facilitator run plan has been verified against the current
  repositories** — all six reference targets reproduce with agent-blame
  0.1.0 on the current clones (verified 2026-08-19), and no broken
  artifacts were found.
- **No real human study has been conducted.**
- **Independent participants are currently unavailable.**
- Therefore claims about **real developer usefulness, trust, and repeated
  voluntary use remain unvalidated.**

The final classification stays **USEFUL MVP (C), PROVISIONAL** — this is
not a downgrade of the project because the study could not be run, and
"provisional" is not removed. The classification rests on AI simulation
and real-repo correctness evidence; only observed human behavior can move
it.

---

## F. Explicit scope boundary (intentionally NOT built)

The following are deliberately **out of scope for v0.1.0** and were not
built:

- merge-aware analysis (first-parent baseline only, documented limitation)
- non-Python language support beyond the conservative Python AST (callers /
  symbols / function resolution)
- LLM / AI explanation layer
- web UI
- persistent indexing / cache
- blame-ancestry views
- richer JSON schema
- new evidence types
- further `--help` wording iteration (tested in Phase 6B; 0/3 conversion)

These were deferred by the Phase 2 stop-conditions, the Phase 4 feature
freeze, and the Phase 6 explicit don't-build list. They are not forgotten
features; they are deliberate boundaries.

---

## G. Final known limitations

1. **Invocation discovery remains a real problem.** The primary target
   contract (`<file>:<line>`) is not what unfamiliar users (AI or human)
   naturally reach for; the new forms (`file:function`, bare file, bare
   sha) converted 2/6 AI sessions, and the dominant remaining failure was
   agents inventing flags without reading the interface at all. The value
   proposition is still only visible *after* a successful invocation.
2. **No human validation.** Real developer usefulness, trust calibration,
   comprehension of the output vocabulary ("Historical removal risk:
   HIGH", "INSUFFICIENT EVIDENCE"), and reuse intent are unmeasured.
3. **Documented engine limits** (unchanged, see README): shallow-clone
   history limits, approximate line mapping across history, merge commits
   use the first parent, the after-commit scan is bounded (30 commits/file),
   and message-text signals are weak by design.
4. **Honest product positioning:** not faster than a known `git blame`
   command; an aggregation and discovery layer, not a speed hack.

---

## H. Future work (beyond v0.1.0)

The following are **potential future validation experiments — recorded,
not implemented, and not part of the frozen v0.1.0 scope**:

- **Worked-example experiment for flag-invention agents** — test whether
  putting a single worked example in the task environment converts the
  4/6 failure class that never reads `--help` (harness change only).
- **Natural bare-SHA adoption measurement** — the bare-sha form was never
  naturally exercised by any session in either Condition C run; its
  `--commit` equivalence is test-covered, its natural adoption unmeasured.
- **Skeptic rerun after exposure to real output** — the Phase 6B/6C
  adversarial skeptic rejected the tool from a capability description
  alone; re-running it after showing real output is a cheap, un-run
  experiment.
- **The real 5-developer human study** — if independent participants later
  become available, the package and verified facilitator plan in
  `validation/` are ready to run unchanged. This is the only evidence that
  can move the classification off "provisional."

---

## Verdict

agent-blame v0.1.0 is **feature-frozen and complete within its declared
scope**: a deterministic, local-first Git-archaeology tool with 321 green
tests, correctness demonstrated on real repositories, and a value
proposition demonstrated (not assumed) under adversarial AI validation.
The remaining gap — real human validation — is an **evidence limitation,
not an unfinished product feature**: the study is ready to run, and
independent participants are currently unavailable. The classification
remains **USEFUL MVP (C), PROVISIONAL**, honestly and without inflation.
