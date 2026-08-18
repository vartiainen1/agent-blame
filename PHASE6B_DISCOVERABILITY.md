# agent-blame — Phase 6B: Discoverability Analysis & Minimal UX Fix

**Date:** 2026-08-18
**Classification:** USEFUL MVP (C), provisional — **unchanged** unless evidence
compels otherwise. Phase 6B is a UX/discoverability experiment only: **no new
features, no engine, ranking, confidence, movement, or regression changes.**

---

## 1. Phase 6A finding (the problem being investigated)

Phase 6A executed 26 AI sessions (18 natural-discovery + 8 guided) on real
`requests` / `flask` / `rich` repositories with git-verified ground truth.
The key result:

- **Natural discovery: 0/8 successful agent-blame uses.**
- **Guided (tool's own `--help` embedded in the prompt): 25/25 usable calls.**

The evidence shows agent-blame can provide useful historical information when
correctly invoked, but its **primary invocation contract (`<file>:<line>`)
was not discovered naturally** by the tested AI agents.

**Honest scoping:** this does NOT prove humans would behave identically, and
it does NOT prove the product has no value. It proves one specific thing:
*the tool's value was demonstrated under guidance, but its primary invocation
contract was not discovered naturally by the tested AI agents.* That is the
problem this phase investigates.

---

## 2. Natural-discovery failure taxonomy (from the 8 treatment transcripts)

Every natural-discovery treatment session's interaction with agent-blame was
classified. Full evidence: `validation/ai/transcripts/ST{1,3,5,7,8}_*_treatment.jsonl`
and the Phase 6A report §4, §12.

| # | Session (task) | What the agent did | Failure class |
|---|---|---|---|
| 1 | ST1_P1_treatment (T1 WHY) | Ran `--help`, saw usage, then **never constructed any valid invocation** — fell back to git entirely | **B. Help-read, never applied** |
| 2 | ST1_P4_treatment (T1 WHY) | Ran 2 git commands total; **never touched agent-blame** | **A. Never attempted** |
| 3 | ST2_P3_treatment (T2 MOVED) | Ran bare `agent-blame src/requests/__init__.py` → got full error spelling out `expected <file>:<line> e.g. src/auth/session.py:142` → then `--help` → **never retried with a line number** | **C. Error seen, not corrected** |
| 4 | ST3_P5_treatment (T3 REVIEW) | **Never ran agent-blame** (0 ab commands) | **A. Never attempted** |
| 5 | ST4_P2_treatment (T4 COMMIT) | Ran `--help`, saw `--commit REV` exists, **never used it** — solved with `git show` | **B. Help-read, never applied** |
| 6 | ST5_P1_treatment (T5 CALLERS) | **Never ran agent-blame** (0 ab commands) | **A. Never attempted** |
| 7 | ST6_P3_treatment (T6 REGRESSION) | Invented **`--follow`** (a `git log` flag, not an agent-blame flag) and retried it **4×** without ever running `--help` | **D. Flag invention** |
| 8 | ST7_P5_treatment (T7 INSUFFICIENT) | Ran bare `agent-blame src/requests/models.py` → got the full error with the syntax example → **never retried with a line number** | **C. Error seen, not corrected** |
| 9 | ST8_P6_treatment (T8 NEGATIVE) | Ran `--help`, then bare `agent-blame .pre-commit-config.yaml` → error → never retried (concluded the file's history is trivial) | **C. Error seen, not corrected** |

### Taxonomy summary

- **A. Never attempted (3/9):** agent-blame was never even tried. The agent
  defaulted to git and stayed there.
- **B. Help read, never applied (2/9):** `--help` was seen, but the agent
  never bridged "I have a target" → "agent-blame <file>:<line>". Notably
  ST1's task text literally contained "around line 483" and ST4's task was a
  commit while `--commit REV` was right there in the help.
- **C. Error seen, not corrected (3/9):** the bare-file error already says
  `expected <file>:<line> e.g. src/auth/session.py:142` — the agents saw the
  **full** message (verified: 124-126 chars, not truncated) and still never
  added a line number. **The existing error message is not sufficient.**
- **D. Flag invention (1/9):** `--follow` assumed from git knowledge; help
  never consulted.

### What this says about the CLI

1. The **error message** is already actionable and still failed → the problem
   is upstream of errors: agents don't get far enough to iterate, or don't
   recognize the tool as relevant.
2. The **help text** is a bare argparse listing: `target <file>:<line>` with
   **zero examples** and no mapping from developer questions to commands.
   "What do I type to ask WHY about a line?" is not answered.
3. The **value proposition** ("why use this instead of git blame?") is in the
   README but effectively invisible from `--help`; agents defaulted to git
   because nothing advertised a compelling reason to switch.
4. The **`<file>:<line>` target** is the single most-missed contract (ST2,
   ST7, ST8 all tripped on it; ST1 never got there).

---

## 3. Current CLI UX review (fresh-developer view)

Current `agent-blame --help` (verbatim, Phase 6A state):

```
usage: agent-blame [-h] [--history] [--risk] [--diff] [--commit REV]
                   [--staged] [--json] [--verbose] [--cwd CWD] [--version]
                   [target]

Deterministic Git archaeology: why this code exists, how it evolved, and what
historical evidence matters before changing or removing it. No LLM, no network
- the repository is the source of truth.

positional arguments:
  target        <file>:<line> or <file>:<start>-<end>

options:
  -h, --help    show this help message and exit
  --history     show the ranked historical timeline for the target
  --risk        historical change/removal risk analysis
  --diff        DIFF mode: analyze the current working-tree changes
  --commit REV  COMMIT mode: analyze a specific commit (sha, abbrev, HEAD,
                HEAD~1, ...)
  --staged      with --diff: analyze staged changes (git diff --cached)
  --json        machine-readable JSON output (stable schema)
  --verbose     verbose output: per-evidence weights and reasons
  --cwd CWD     repository or subdirectory to analyze (default: cwd)
  --version     show program's version number and exit
```

As a developer who has never seen the tool, can I answer the 8 questions?

| Question | Answerable from current `--help`? |
|---|---|
| 1. What is this tool for? | Partly — the description is decent |
| 2. When should I use it? | **No** — no scenario, no "instead of git blame" framing |
| 3. What argument do I give it? | Partly — `target <file>:<line>` is stated but never shown |
| 4. How do I investigate a specific line? | **No example** — the syntax is stated but not demonstrated |
| 5. How do I investigate my current diff? | Yes-ish — `--diff` exists, but no example |
| 6. How do I investigate a commit? | Yes-ish — `--commit REV` exists, no example |
| 7. What does the output mean? | **No** — no sample output anywhere in help |
| 8. What if I don't know the line number? | **No** — no guidance at all |

Error messages are already good (the bare-file error spells out the fix), and
the README is genuinely good (table vs `git blame`, worked example, modes
section). The gap is **`--help`**: it is a flag listing, not an entry point.

---

## 4. Root cause

**The CLI's first-run surface (`--help`) communicates syntax but not usage.**
A new user (human or AI) reads `target <file>:<line>` but never sees:

- one complete example invocation,
- the mapping from *developer question* → *command* (WHY→`file:line`,
  MY DIFF→`--diff`, THIS COMMIT→`--commit`, etc.),
- the differentiation from `git blame` / plain git ("why" vs "who"),
- what the output looks like or what to do when they don't know a line.

Because `--help` is the discoverability surface the study actually tested
(agents that engaged did so via `--help`), and it fails to answer "what do I
type?", the observed failure (0/8) follows. The error message is *not* the
primary problem: it is already actionable and was still ignored (class C).

---

## 5. UX hypothesis (written before the change)

> **Hypothesis H6B:** The primary failure is that the CLI does not clearly
> communicate that `agent-blame <file>:<line>` is the basic WHY target and
> does not show a single worked example in `--help`. Adding (a) a compact
> "Quick start" with 3 complete examples, (b) question-first wording for the
> target/modes, and (c) a one-line differentiation from `git blame` will let
> an unfamiliar agent (and human) construct a valid invocation from `--help`
> alone, raising natural discovery above 0/8 without any engine change.

**Success criterion (strong form, per phase §7):** an unfamiliar agent can
inspect `--help`, recognize when agent-blame is appropriate, construct a
valid invocation, and obtain useful evidence **without being explicitly told
the command syntax**. Measured on the previously failing tasks T1/T2/T6.

**Human relevance check (phase §4):** the change targets what a human would
also need — a first-run example and question→command mapping. It is not an
AI-only accommodation; it is standard CLI entry-point hygiene. The AI result
is evidence of friction, not proof of human behavior.

---

## 6. Planned changes (smallest justified set)

All changes are confined to `agent_blame/cli.py` (help text + argument
help) and `agent_blame/target.py` (error message wording). **No analysis,
ranking, confidence, movement, regression, or output logic changes.**

1. **`--help` gains a "Quick start" epilog** with exactly three complete
   examples, wording chosen from the evidence:
   - `agent-blame src/auth/session.py:142` → "why does this line exist?"
   - `agent-blame --diff` → "what historical context explains my current changes?"
   - `agent-blame --commit <sha>` → "why does the code changed by this commit exist?"
   Plus one line that differentiates from git without marketing: the tool
   combines introducing commits, later modifications, movement, callers,
   risk, and regression/revert evidence — it is an aggregation layer over
   git, not a prettier `git blame`.
2. **Argument help strings rewritten question-first**:
   - `target`: "WHY: <file>:<line> or <file>:<start>-<end> — why does this code exist?"
   - `--history`: "HOW: ranked historical timeline — how did this code evolve?"
   - `--risk`: "RISK: historical change/removal risk analysis — what should I know before changing/removing it?"
   - `--diff`: "DIFF: historical context for your current working-tree changes"
   - `--commit REV`: "COMMIT: historical context for one commit (why does the code this commit changed exist?)"
3. **Bare-file error reworded** to lead with the fix and include a concrete
   example line of the user's own file (was: generic example). Still exit 2,
   still sanitized, same parse behavior — wording only.
4. **README**: no structural change needed (it is already good); only the
   mode table example section is cross-checked for consistency with the new
   help wording. No new sections, no marketing.

**Explicitly NOT done (phase §13):** no default mode, no `--follow` alias,
no auto-target discovery, no new capabilities, no engine changes, no ranking
changes, no README restructure.

---

## 7. Before/after examples

| Before | After |
|---|---|
| `agent-blame` (no args) → bare flag listing | `agent-blame` (no args) → usage + Quick start with 3 worked examples |
| `target  <file>:<line> or <file>:<start>-<end>` | `target  WHY: <file>:<line> or <file>:<start>-<end> — why does this code exist?` |
| `agent-blame file.py` → "target 'file.py' has no line number; expected <file>:<line> e.g. src/auth/session.py:142" | `agent-blame file.py` → "target 'file.py' needs a line number: e.g. agent-blame file.py:1 — expected <file>:<line> (src/auth/session.py:142)" |
| No mention of why to use it vs git | One line: aggregates introducing commits / later modifications / movement / callers / risk / regression-revert evidence — an archaeology layer over git |

---

## 8. Natural-discovery retest (RESULTS — executed 2026-08-18)

Same personas/models as Phase 6A, fresh sessions (new contexts, no shared
history), no guided instructions — the agent receives the repo, the task,
agent-blame on PATH, and `--help` available. Three sessions on the
previously failing tasks: **ST1_P1_6B (T1 WHY), ST2_P3_6B (T2 MOVEMENT),
ST6_P3_6B (T6 REVERT)**. Transcripts:
`validation/ai/transcripts/ST{1,2,6}_*_6B.jsonl`.

### Results

| Session | agent-blame seen? | First ab attempt | Outcome | Failure class |
|---|---|---|---|---|
| ST1_P1_6B (T1) | yes — ran `--help`, saw FULL new help incl. Quick start (1844 chars, verified) | none — never constructed any invocation | 0 ab invocations; answered from git | **B (unchanged)** |
| ST2_P3_6B (T2) | yes — saw the FULL improved bare-file error (203 chars, verified) | `agent-blame src/requests/__init__.py` (bare) | error printed the fix with the agent's own file (`...':1`); agent **never retried with a line number** | **C (unchanged)** |
| ST6_P3_6B (T6) | no — never ran `--help` | `agent-blame --follow ...` (invented flag, 1×) | `unrecognized arguments: --follow`; agent went back to git | **D (unchanged)** |

**Outcome: 0/3 successful agent-blame uses — the UX change did NOT improve
natural discovery in this retest.** Phase 6A was 0/8; this retest is 0/3 on
the three tasks most likely to benefit. The failure classes are identical
(B: help read but never applied; C: error seen but not corrected; D: flag
invention without help).

### What this means (honest)

- **The help text was not the (only) blocker.** ST1 read the new Quick start
  with three worked examples and still never typed `agent-blame
  models.py:483` — the task text even said "around line 483".
- **The error message was not the blocker.** ST2 saw an error that literally
  said `add :LINE ... e.g. 'src/requests/__init__.py':1` and did not retry.
- **These agents' failure is upstream of text:** they do not bridge
  "a tool exists" → "this tool applies to my target", and they do not
  iterate after a helpful error. No amount of `--help` wording alone has
  been shown to fix that for this model family (n=3 retest + 8 Phase 6A
  natural sessions, all qwen3-coder).
- **This is AI evidence, not human evidence.** A human who reads
  `agent-blame file.py:LINE` in an error, or a Quick start with examples,
  would very plausibly retry. The retest does not prove the UX change is
  useless for humans — it proves it did not convert these AI agents.
- The change is still kept: it answers the eight first-run questions (§3)
  that the old help left open, and it is strictly additive (no behavior
  change, 284 tests green, JSON deterministic, security audit clean).

---

## 9. Adversarial skeptic check (RESULTS — executed 2026-08-18)

Asked P6 (qwen3-coder:30b, Adversarial Skeptic persona) the exact question
with the **new** `--help` in front of it, without giving the answer:

> "Why would I use agent-blame instead of Git?"

**Answer: "I wouldn't use `agent-blame` instead of Git."** The skeptic
characterized the tool as "a GUI wrapper around `git blame` that makes it
look like it's doing something smarter than it actually is", claimed
`git blame` / `git log --follow -p` / `git show` already provide the
context, and dismissed risk/history/aggregation as "things you can do
manually with standard Git tools, just with a bit more effort."

**Interpretation (honest):** the skeptic is the adversarial control — its
job is to find reasons not to use the tool, and it did. Two readings:

1. **The differentiation message did not land with this persona.** Even the
explicit "aggregates evidence git keeps scattered ... answers WHY, not just
WHO" line was rejected as redundant with `git log --follow -p`.
2. **This is a fair adversarial finding, not a bug in the wording.** A
skeptic who believes raw git is sufficient will say so; Phase 6A's T8
skeptic similarly concluded the tool adds nothing on a config file. The
value claim that does survive adversarial review is *effort*: Phase 6A
measured the tool answering in 1 call what the natural baseline took
15-41 git commands to find (T6: 41→15 commands) — but the skeptic, asked
about *why*, not *how much work*, did not weigh that.

**Both outcomes were recorded as required:** the skeptic still would not
use it, and the legitimate-reason answer (archaeology / movement /
aggregated context) was NOT produced unprompted by this persona. A human
skeptic may differ; this is AI evidence.

---

## 10. Remaining limitations (honest)

- The retest uses the same AI family (qwen3-coder) — it is AI evidence, not
  human validation.
- Small session counts (3 retest sessions + 8 Phase 6A natural) are
  indicative, not statistical.
- The retest could not separate "the change is insufficient" from "these
  agents do not act on any CLI text"; the failure classes are identical
  before/after, which points to the latter, but a human-in-the-loop study
  would be needed to test the former.
- A better `--help` does not fix class-A/D agents that never look at help
  at all (ST1_P4, ST3_P5, ST5_P1 in Phase 6A; ST6 in both rounds); the
  README already covers the "why" case but agents in the study did not read
  it.
- The adversarial skeptic's rejection is one model run; a different model
  family or a human might weigh the effort savings (41→15 commands on T6)
  differently.

---

## 11. Whether further UX work is justified

**Yes, but with a different lever than help text.** The retest shows
help/error wording alone does not convert these agents (0/3, unchanged
failure classes). The evidence points to two higher-leverage directions,
neither implemented here (both deferred, per phase §13):

1. **A friendly entry point for the bare-file case.** Three agents (ST2,
   ST7, ST8 in Phase 6A; ST2 in the retest) ran `agent-blame <file>` and
   stopped at the error. A *suggestion* (not a default mode) — e.g. when a
   bare file is given, print the file's blame-able lines and say
   "run `agent-blame <file>:<line>` on one of these" — would convert the
   single most-common failed first step. This is a UX affordance, not a
   new analysis capability.
2. **Make the tool's first output teach usage.** The strongest Phase 6A
   evidence for value is that the tool found exact commits in 1 call where
   git took 15-41 commands. Surfacing a compact "what it did" line in
   default output (e.g. "found the introducing commit; N later
   modifications; movement detected") would make the differentiation
   visible in the tool's own output rather than only in help text.

Both are deliberately **not** implemented in this phase: the phase is a
controlled experiment, the smallest change was made and measured (0/3), and
adding more would conflate the measurement. The honest conclusion is that
the CLI now answers the eight first-run questions better (a genuine UX
improvement, kept), but **natural discovery by these AI agents was not
improved by help/error wording alone** — that question remains open for
human users and for the entry-point suggestions above.

---

## 12. Change summary (what was actually changed)

| File | Change | Behavior impact |
|---|---|---|
| `agent_blame/cli.py` | `--help` gains a Quick start epilog with 3 worked examples; argument help rewritten question-first (WHY/HOW/RISK/DIFF/COMMIT); one-line differentiation from `git blame` | Help text only — no mode/parse/analysis change |
| `agent_blame/target.py` | Bare-file error reworded to lead with the fix and echo the user's own file (`...':1` example) | Error wording only — same exit code 2, same sanitize, same parse |
| `tests/test_cli.py` | 5 new deterministic tests: Quick start present, git-blame differentiation, question-first wording, no-target help, bare-file error teaches `:LINE` | Tests only |
| `PHASE6B_DISCOVERABILITY.md` | This document | Docs only |

**Explicitly NOT changed:** analysis engine, ranking, confidence,
movement, regression detection, JSON schema, output renderers, README
structure, no new capabilities, no default mode, no `--follow` alias.

**Security/regression verification (phase §10):** 284 tests green (279
before + 5 new); `grep` audit clean (no shell=True, no eval/exec of repo
content, no network imports); output sanitization (`_CSI_RE`/`_CTRL_RE`)
intact; JSON byte-identical across two runs on the same target; existing
CLI error-path tests unchanged and passing; no product code outside the two
listed files was touched.
