# agent-blame

**Understand why code exists, how it evolved, and what its history tells you
before you change it.**

`agent-blame` is a local-first, deterministic Git archaeology tool.

Git tells you *who* changed code. `agent-blame` tells you *why* it exists,
*how* it evolved, and what historical evidence you should consider before
changing or removing it.

The core is **not AI**. It is a deterministic historical-analysis algorithm.
The repository is the source of truth; the algorithm decides which evidence
matters; counter-evidence prevents simplistic conclusions; confidence
communicates uncertainty; risk analysis helps developers decide what deserves
further investigation. An optional LLM may explain the structured findings
later, but it will never replace the evidence engine.

---

## Why it exists

When you meet unfamiliar code you usually have three questions:

1. **WHY?** — Why was this code introduced?
2. **HISTORY?** — What happened to it after it was introduced?
3. **RISK?** — What historical evidence should I consider before changing or
   removing it?

Answering those manually means `git blame` + `git log` + `git show` +
searching tests + hunting for regressions, reverts, and replacements. The
information exists but is scattered. `agent-blame` connects it.

It is deliberately different from `git blame`:

| Tool | Answers |
|------|---------|
| `git blame` | Who changed this? |
| `git log` | What changed? |
| `git show` | What did a commit do? |
| **`agent-blame`** | Why was this introduced, how did it evolve, what evidence supports that, and what should I know before changing or removing it? |

---

## Installation

Requires **Python 3.9+** and **git** on PATH. No dependencies (stdlib only).

```bash
# from the project root
pip install -e .          # optional: adds the `agent-blame` command
# or run directly without installing:
python -m agent_blame --help
```

---

## Basic usage

Run from anywhere inside a git repository:

```bash
agent-blame src/auth/session.py:142
```

```text
WHY DOES THIS CODE EXIST?

  Target: src/auth/session.py:142

Confidence
  Level: HIGH
  Score: 1.00
    - 3 supporting evidence item(s)
    - 1 counter-evidence item(s)

Facts
  ✓ line 142 introduced by 72ac91: Add concurrency guard

Inferences
  · The introducing commit message references concurrency-related concerns;
    the code may have been introduced to address that area (evidence: 72ac91)

Evidence
  ✓ lines 142-142 introduced by 72ac91: Add concurrency guard
  ✓ commit 72ac91 added test file(s): tests/test_concurrent_refresh.py
  ✓ later commit 91b22c modified the file: Fix refresh race
  ✗ later commit 91b22c removed lines from src/auth/session.py

Historical chain
  91b22c  2023-03-04  Fix refresh race
  72ac91  2023-02-12  Add concurrency guard

Historical removal risk
  Level: HIGH
    - regression/fix history around this code (1 fix-related commit(s))
    - tests were introduced together with this code (behavior is exercised)

Note: this is historical evidence, not a safety guarantee. The developer
makes the final decision.
```

### Target forms

Four target forms are accepted (Phase 6C entry-point resolution — parsing
and UX only; the analysis engine is identical for all of them):

| Form | Example | Behavior |
|------|---------|----------|
| `file:line` (canonical) | `agent-blame src/auth.py:142` | WHY analysis of that line (or `file:start-end`) |
| `file:function` | `agent-blame src/auth.py:authenticate` | resolves the function/method/class to its DEFINING line via Python AST and analyzes it — "resolved 'authenticate' to line 40" is printed. Qualified names (`Server.handle`) are the identity; an unqualified name must be unique in the file (ambiguity is a clean error naming the candidates) |
| `file` (bare) | `agent-blame src/auth.py` | prints the file's blame-able lines — Python files show the symbol table with each symbol's defining line, other files show the line count — and points you at `agent-blame <file>:<line>` (an affordance, not an error) |
| `<sha>` (bare) | `agent-blame d037a21` | equivalent to `--commit d037a21` (verified with `git rev-parse`, so a file whose name looks like a sha is never hijacked) |

Symbol resolution reads the repository at HEAD (the analyzed revision),
and is Python-only — the same honesty rule as caller analysis.

### Modes

```bash
# WHY (default): why does this code exist?
agent-blame src/auth/session.py:142

# Range target
agent-blame src/auth/session.py:130-160

# HISTORY: how did this code evolve?
agent-blame --history src/auth/session.py:142

# RISK: historical change/removal risk
agent-blame --risk src/auth/session.py:142

# DIFF: historical context for your current working-tree changes
agent-blame --diff

# DIFF, staged changes only (git diff --cached)
agent-blame --diff --staged

# COMMIT: historical context for a specific commit
agent-blame --commit d037a21
agent-blame --commit HEAD~1

# JSON: machine-readable structured result
agent-blame --json src/auth/session.py:142
agent-blame --commit d037a21 --json

# VERBOSE: per-evidence weights and reasons
agent-blame --verbose src/auth/session.py:142
```

### Command-line options

| Option | Meaning |
|--------|---------|
| `target` | `<file>:<line>` / `<file>:<start>-<end>` (canonical), `<file>:<function>` (resolved to its defining line), `<file>` (blame-able lines), or a bare `<sha>` (→ `--commit`) |
| `--history` | ranked historical timeline for the target |
| `--risk` | historical change/removal risk analysis |
| `--diff` | DIFF mode: analyze the current working-tree changes |
| `--commit REV` | COMMIT mode: analyze one commit (sha, abbrev, `HEAD`, `HEAD~1`, ...) |
| `--staged` | with `--diff`: analyze staged changes (`git diff --cached`) |
| `--json` | machine-readable JSON output (stable schema) |
| `--verbose` | per-evidence weights and reasons |
| `--cwd DIR` | repository or subdirectory to analyze (default: cwd) |
| `--version` | print version and exit |

---

## DIFF mode

`agent-blame --diff` answers: *"I changed this code - what does its history
have to say about my change?"* It analyzes the developer's current changes
and provides historical context for the changed regions:

```text
developer changes code
        \/
agent-blame --diff
        \/
identify changed files + hunks (git diff)
        \/
group changed lines by shared historical evidence
        \/
existing pipeline per group (blame -> evidence -> confidence -> risk)
        \/
human-readable + JSON output
```

Example output:

```text
DIFF ANALYSIS  (WORKING TREE changes vs HEAD)

src/auth/session.py  (modified)

  Changed: lines 142-148
    -  142  def refresh(token):
    +  142  def refresh(token, force=False):
    ...
  Historical context
    • line 142 introduced by 81f3a2: Add concurrency guard for token refresh

  Why (inferred)
    · The introducing commit message references concurrency-related concerns

  Related evidence
    ✓ lines 142-148 introduced by 81f3a2: Add concurrency guard
    ✓ commit 81f3a2 added test file(s): tests/test_concurrent_refresh.py
    ✓ 3 later commits modified this file (aggregated)

  Counter-evidence
    ✗ 2 later commit(s) removed lines from src/auth/session.py

  Historical change risk: HIGH
  Confidence: HIGH
```

### Scopes

Two diff scopes are supported and explicit:

| Scope | Command | What is analyzed |
|-------|---------|------------------|
| working tree | `agent-blame --diff` | `git diff` — unstaged working-tree changes |
| staged | `agent-blame --diff --staged` | `git diff --cached` — staged changes |

Untracked files are **not** part of `git diff`; they are reported as new
files with no historical evidence (stage them to include them).

### How it avoids noise

- **Hunks, not lines.** Changed lines are grouped into hunks; each hunk is
  analyzed once, never per-line.
- **Evidence-signature merging.** Hunks whose analysis is identical (same
  introducing commits, same evidence, same confidence/risk) are merged into
  one group with all their ranges — *"these 8 changed lines share the same
  historical context"* instead of 8 duplicate explanations.
- **Per-commit evidence is aggregated in the terminal — in every mode.** A
  file touched by 80 commits does not print 80 near-identical bullets; the
  terminal shows "N later commits modified this file" (WHY / HISTORY /
  RISK / DIFF / COMMIT all use the same renderer). Caller facts are listed
  once, in the Callers section, not duplicated in Evidence. The WHY / RISK
  historical chain shows the newest 25 commits with a pointer to `--history`
  for the full timeline (HISTORY mode shows everything). The JSON output
  keeps the full per-commit list for machine consumption.

### Honesty rules (same as the rest of the tool)

- **Added lines have no history** — never fabricated. The surrounding
  context (nearest previous-revision lines) is analyzed instead, and the
  limitation is stated explicitly.
- **Deleted lines are analyzed against the previous revision** (HEAD): blame
  on the old lines surfaces the introducing commit, history, and risk of
  removing them.
- **A brand-new file has no base version** — reported as new, no analysis.
- **Binary files** are reported, not parsed.
- **Renames** are analyzed against the pre-rename path (blame must run
  against the name the file had at HEAD); the new path is shown in the
  output.

### Diff JSON

The diff JSON reuses the existing schema: `mode: "diff"`, plus `scope` and
`files[]`, where each file has `status`, `path`, `old_path` (renames), and
`groups[]`. Each group carries the merged `ranges`, the `changes` (per-line
side/type/text), and the full `analysis` sub-object — the same evidence,
counter-evidence, confidence, risk, history, and warnings structures as WHY
mode. Machine consumers get complete per-commit evidence; nothing is lost.

### Known limitations (documented, not hidden)

- `git log --follow` (history simplification) may omit a merge commit from a
  path-limited log; commits from both parents remain visible.
- Per-commit added/removed counts come from `git log --numstat`; counts can
  differ by ±1 from diff-based counting on files whose line endings were
  normalized — immaterial to the thresholds used.
- In `--diff` mode, a pure rename with no content change is reported without
  per-line analysis, but carries the movement classification (type, mover,
  origin). `--commit` mode instead analyzes the whole moved file against the
  baseline (bounded by a size guard for binary blobs).

---

## COMMIT mode

`agent-blame --commit <rev>` answers: *"what did this commit change, and
what historical context explains those changes?"* It analyzes one commit
against its parent (the baseline) and separates the timeline into three
strictly distinct phases:

```text
BEFORE THIS COMMIT        (the baseline state, analyzed by the engine)
   historical origin + evolution of the changed behavior
        \/
TARGET COMMIT             (the event - its diff vs the baseline)
        \/
AFTER THIS COMMIT         (bounded scan of later commits touching each file)
```

The revision argument accepts everything git itself resolves safely: full
SHAs, abbreviated SHAs, `HEAD`, `HEAD~1`, and other commit-ishes. Values
starting with `-` are rejected outright (they can never become git options).

```text
COMMIT ANALYSIS

  Commit: d037a219  fix: start.py now picks the newest session note by date
  Author: Buffy
  Date: 2026-08-16T07:26:07+02:00
  Parents: bb2dfd60
  Baseline: bb2dfd60
  Changed files: 4

CHANGE  src/retry.py  (modified)

  Changed: line 3
    -    3      time.sleep(13)
    +    3      time.sleep(7)
  Historical context (before this commit)
    • line 3 introduced by 18eea955: Add rate-limit handling

  Related evidence
    ✓ lines 3-3 introduced by 18eea955: Add rate-limit handling
    ✓ current test file(s) reference this module: tests/test_retry.py

  Counter-evidence
    None found.

  Historical change risk: MEDIUM
  Confidence: MEDIUM

  After this commit
    · 2 later commit(s) touched this file after this commit (1 revert(s), 1 fix/regression-related)
```

### Chronology is guaranteed, not hoped for

The before-state analysis blames the changed lines against the commit's
**parent**, so the introducing commits are those of the *previous* behavior.
The analyzed commit can never be credited as the origin of the change it
makes. A revert commit correctly reports the reverted commit (`revert_of`)
and attributes the previous behavior to that reverted commit.

### How commits are handled

- **Root commit** — no parent: every file is reported as new, with no
  fabricated history, and a warning states there is no previous revision.
- **Merge commit** — the first parent is the documented baseline (the
  standard "merge diff" view), with a warning that full merge interpretation
  is a documented limitation.
- **Deleted files** — the old lines are analyzed against the baseline
  revision, surfacing the deleted code's introducers and risk.
- **Added files** — `NEW FILE`, no prior history; tests introduced with the
  commit are reported as direct facts.
- **Renames** — history follows the pre-rename path; a pure rename analyzes
  the whole moved file (size-guarded for binary blobs).
- **Binary files** — reported, never parsed.
- **Reverts** — `revert_of` is derived from git's own structured
  "This reverts commit <sha>" trailer (never from the word "revert" alone),
  and blame independently confirms the reverted commit as the origin.

### Commit JSON

Commit mode keeps the same JSON conventions with `mode: "commit"`, a `commit`
metadata section (sha, parents, author, date, subject, body, is_merge,
is_root, revert_of), the baseline used as `parent`, and `changes[]` — one
entry per changed file with the same `groups[]` structure as diff mode (each
carrying the full before-state `analysis`), plus an `after` section holding
the bounded later-commit scan. Existing WHY/HISTORY/RISK/DIFF JSON consumers
are unaffected.

---

## Caller / symbol analysis

Every mode (WHY, RISK, `--diff`, `--commit`) now answers one more question
about the code you are looking at: **who calls it?** When the analyzed
lines sit inside a Python function/method/class, `agent-blame` finds the
symbol, scans the repository at the **analyzed revision** for references,
and classifies every relationship. There is no `--callers` mode — callers
are contextual evidence inside every existing mode.

```text
Source file
  → language detector (Python via stdlib AST — parsed, never executed)
  → symbol extraction (functions/methods/classes, qualified names)
  → reference/caller search (imports + call sites, AST-level)
  → caller evidence → existing ranking → confidence → risk
```

### Relationship types (explicit, conservative)

| Relationship | Meaning | Evidence weight |
|--------------|---------|-----------------|
| `DIRECT_CALL` | bare/aliased call resolved via same-module scope or a resolved from-import | strong (`live_caller` +0.20) |
| `ATTRIBUTE_CALL` | `module.func()` / `Class.method()` where the receiver resolves to the target's module | strong (`live_caller` +0.20) |
| `IMPORT_REFERENCE` | the target symbol or module is imported | weak (+0.10) |
| `POSSIBLE_CALL` | name matches but resolution is ambiguous (no import, star import, unknown receiver type) | very weak (+0.05) |
| `TEXTUAL_MATCH` | the name appears as text only (strings/comments/unrelated identifiers) | **zero** — reported for transparency, never scored |
| `UNRESOLVED` | dynamic patterns (`getattr`/`eval`/reflection) | **zero** — never scored |

**Trustworthiness is the goal**: a confirmed caller always outweighs any
number of textual matches, and a weak match is never presented as a
confirmed caller. Comment/string `authenticate()` and `authenticate_other`
are never callers; a module that imports `authenticate` from `mod_a` is
never credited as a caller of `mod_b`'s `authenticate`; a file that
defines its own `load()` is never credited as calling `check_errors.load()`.

### Live / deleted / modified callers

A caller is **LIVE** only when the reference exists at the analyzed
revision (historical code never inherits callers that did not exist yet).
In `--diff`/`--commit`, callers in files that the change deletes or
modifies are marked **DELETED** / **MODIFIED** — the status is
revision-honest, never blindly live. The terminal renders these distinctly:
`✓` LIVE (exists at the analyzed revision), `~` MODIFIED (exists, but its
file is part of the analyzed change — it is NOT dead), `✗` DELETED (the
only genuinely dead status).

### What it never claims

- **"unused"** — the tool says "No confirmed callers found". Reflection,
  dynamic imports, plugin loading, CLI entry points and framework
  registration can all use a symbol without static analysis seeing it.
- **"safe" / "unsafe"** — risk reasons report counts ("2 confirmed live
  caller(s) depend on this code") and never absolute safety claims.

### Symbol identity

Symbols carry a stable identity: repository-relative path + **qualified**
name + kind + source range (`src/auth.py:Server.handle`). Bare display
names are never used as identities, so two modules with the same function
name cannot collide.

### JSON

`AnalysisResult` gains two additive fields: `symbol` (the resolved target
symbol dict, or `null`) and `callers[]` — one entry per caller with
`symbol`, `path`, `name`, `line`, `call_sites`, `relationship`, `status`,
`confidence` and `text`. TEXTUAL_MATCH / UNRESOLVED findings appear as
aggregated single entries with a count. Existing schema keys are
unchanged.

---

## Code movement / rename tracking

The central rule of this phase (spec 2D/23): **a movement commit is never
reported as the code's original introduction.**

```text
INTRODUCTION  (commit A: adds foo in old.py)
    ↓
MOVEMENT      (commit B: moves foo to new.py)   ← never called the origin
    ↓
MODIFICATION  (commit C: changes foo)           ← still credits A + B
```

`agent-blame new.py:<line>` reports *"moved here by B, originally
introduced by A"* — and only says "original introduction" when the
evidence supports it (spec 2D/10).

### Three sources of movement evidence (strength order)

1. **Git rename metadata** — `git diff -M` R<score> entries are
git-confirmed file renames (`RENAME`).
2. **Blame origin capture** — `git blame --line-porcelain` carries the
pre-rename path; the tool now records it, and a **bounded chain walk**
(`git log --follow` + per-commit name-status diffs, capped) finds *which
commit moved the code* — including multiple sequential moves
(`old.py → middle.py → new.py` traces back to the true origin).
3. **Symbol-level continuity** (Python, stdlib `ast` + `difflib`, parse
only) — catches the **partial moves** git's similarity threshold misses
(a symbol that leaves one file and appears in another). This is the case
that would otherwise blame the MOVE commit as the introduction; the tool
corrects it via a `git grep`-gated origin check that is one cheap call
when no candidate exists.

### Classification

| Type | Meaning | Confidence |
|------|---------|-----------|
| `RENAME` | git-confirmed file rename (R<score>) | HIGH |
| `CODE_MOVEMENT` | symbol continuity confirmed, source removed | HIGH |
| `POSSIBLE_MOVEMENT` | strong similarity but incomplete/ambiguous | MEDIUM / AMBIGUOUS |
| `COPY` | strong similarity but the source still exists | HIGH |

Similarity is a documented **heuristic** (word-level token ratio,
`difflib.SequenceMatcher`), never a probability. "Removed from source"
means the implementation is gone — a name that survives only as a
diverged stub/rewrite counts as removed (the real code moved).
Ambiguity (two equally plausible origins) degrades to
`POSSIBLE_MOVEMENT`/`AMBIGUOUS`, never a confident guess.

### Honesty rules

- A copy is **never** called a move (`COPY`, not `CODE_MOVEMENT`).
- Unsupported languages get no *symbol*-level claim (a git-detected file
rename is language-agnostic and still reported as `RENAME`).
- The raw blame **fact** stays raw (git said what it said); the
**evidence** layer carries the correction — the introducing evidence is
re-attributed to the origin with a "moved here by" note.
- Movement is **context, not risk**: it appears in risk reasons but never
drives the level by itself ("moved = high risk" is forbidden, spec 2D/25).

### Where it lands

- **WHY / HISTORY / RISK**: a `Movement` section (type, mover, origin,
full multi-hop chain when present) + a `code_movement` evidence item
(weight +0.10, documented heuristic).
- **`--diff`**: worktree renames (untracked new path + deleted old path)
are detected and traced; added ranges inside a moved symbol are analyzed
against the SOURCE at HEAD instead of "no previous version".
- **`--commit`**: the commit's changes are classified (`RENAME` /
`CODE_MOVEMENT` / `POSSIBLE_MOVEMENT` / `COPY`) with `FROM`/`TO`/origin;
added ranges of moved symbols are analyzed against the source at the
parent revision.

### JSON

Additive fields only: `movement` on `AnalysisResult` (and on each
`CommitChange` / `DiffFile`), with `type`, `source_path`, `source_symbol`,
`dest_path`, `dest_symbol`, `moved_by`, `origin`, `origin_path`,
`confidence`, `signals` and (for the chain) `chain[]`. All pre-existing
schema keys are unchanged.

### Known limitations (documented, not hidden)

- **Merge commits** use the first-parent baseline; movement analysis
across merges is not attempted (documented in commit mode).
- **Shallow clones**: `LIMITED HISTORY` — a truncated history may hide the
true origin; the tool says so instead of guessing.
- **Similarity is heuristic**: near-identical small functions in unrelated
files can score high; the margin + source-removal rules are the
conservative guard, and ambiguity is reported as such.

---

## Regression detection

Phase 2E answers: **"has this code caused problems before?"** — as
historical *evidence*, never as a verdict. The tool identifies later
commits that appear to fix or revert behavior associated with the target,
and classifies the relationship. The central rule:

> CORRELATION IS NOT PROOF OF CAUSATION.

The tool says "commit C explicitly reverts B" or "evidence indicates C
corrected behavior introduced by B" — never "B caused the bug" or "this
code is buggy". A revert proves the change was reversed, not that it was
wrong.

### Classification ladder (strongest first)

- **EXPLICIT_REVERT** — the commit message carries git's structured
  `This reverts commit <sha>` trailer. HIGH when the reverted commit is
  the target's introducer (blame-confirmed), MEDIUM when it merely
  touched the file, and **skipped entirely** when it is unrelated.
- **LIKELY_REGRESSION_FIX** — fix/regression language PLUS a strong
  overlap signal: the message explicitly references an introducing
  commit, or the commit both removed code (corrective shape) and changed
  tests.
- **POSSIBLE_REGRESSION_FIX** — fix language PLUS one weak overlap
  signal (corrective shape or test changes). LOW confidence — reported
  transparently, never decisive.
- **CORRECTIVE_CHANGE** — a `Revert ...` subject *without* a structured
  trailer, touching the target file. Weakened because without the
  trailer the revert cannot be linked deterministically to a commit.
- **NO_REGRESSION_EVIDENCE** — everything else, including fix language
  with no overlap (the word "fix" alone never establishes a regression)
  and reverts of unrelated files.

### Overlap: the false-positive guard

A later commit touching the same **file** is weak evidence; the same
**symbol** is stronger. When the target resolves to a Python symbol, the
tool verifies (via the Phase 2C AST machinery, in the commit's parent
coordinate space) that the corrective commit actually changed lines
inside that symbol. A "fix" to an unrelated symbol in the same file is
NOT reported as a regression for the target.

### Chronology guard (Phase 3)

`later` history is strictly newer than the newest introducing commit.
Pre-introducer reverts and fixes are NOT cited against the analyzed code
(Phase 3 found requests' 2013–2019 reverts being cited against 2026 code,
zeroing confidence to CONTRADICTORY everywhere). Two exceptions keep
legitimate findings:

- a pre-introducer fix is surfaced when an **introducing** commit
  explicitly reverts it (then the fix IS the subject of the lineage);
- a `Revert ...` subject without a trailer is only a CORRECTIVE_CHANGE
  when it shows verified symbol overlap **or** strictly corrective shape
  (`removed > added`) — flask's 2018 "revert copyright year" 1/1 edit is
  not correction evidence.

### Integration

- **WHY / HISTORY / RISK**: a `Historical regression evidence` section.
- **--commit**: the after-scan classifies later reverts/fixes of the
  analyzed commit; a revert commit itself is classified per change
  (DIRECT_RANGE_OVERLAP when the reverted commit is blamed as the origin
  of the previous behavior).
- **--diff**: each changed region flows through the same engine, so the
  current change's regression history surfaces automatically.
- Movement-aware: the fix sequence follows code across renames (Phase 2D
  identity), so a fix AFTER a move is still attributed to the ORIGINAL
  introducer, never the mover.

### JSON

Additive field `regressions` on `AnalysisResult` and on each
`CommitChange` (and inside `CommitChange.after`): a list of
`{type, confidence, relationship, original_commit, fix_commit,
reverted_commit, target_path, target_symbol, signals, explanation}`.
Every pre-existing schema key is unchanged.

### Evidence weights (heuristics, not probabilities)

`explicit_revert` −0.25 (counter), `regression_fix` +0.15,
`possible_regression_fix` +0.05, `corrective_change` −0.10. All
documented as heuristics in ranking.py; regression evidence strengthens
risk the same way the existing revert/fix signals do.

### Known limitations (documented, not hidden)

- **Shallow clones**: truncated history may hide regression patterns; the
  tool reports `LIMITED HISTORY` instead of concluding "no regressions".
- **Message language is evidence, not proof**: a commit that says "fix"
  but only renames a variable produces no finding unless a verified
  overlap exists.
- **Symbol overlap is Python-only** (Phase 2C scope); for other
  languages only file-level and test-evidence signals apply.
- **Quiet is not "no regressions"**: on revert-free repos the findings
  list is empty; that means no evidence was found, not that the code is
  regression-free. Phase 3 verified real repos (requests, flask, rich)
  produce zero false regressions.

---

## How it works

The pipeline (every stage is independently testable):

```text
CLI
 -> repository discovery
 -> safe Git abstraction
 -> history extraction (blame, commits, diffs)
 -> targeted historical graph
 -> evidence discovery
 -> evidence ranking (deterministic weights)
 -> inference + counter-evidence
 -> confidence
 -> risk analysis
 -> structured result (terminal + JSON)
```

### Facts, inferences, counter-evidence

The tool strictly separates:

- **FACT** — directly observable repository information ("line 142 was
  introduced by commit 72ac91").
- **INFERENCE** — a conclusion derived from multiple evidence items, phrased
  as a suggestion backed by named evidence ("the introducing commit message
  references concurrency-related concerns").
- **COUNTER-EVIDENCE** — evidence that weakens or contradicts an inference
  ("a later commit reverted this behavior", "a later commit removed these
  lines", "a replacement implementation was introduced").
- **CONFIDENCE** — how strongly the available evidence supports the
  conclusion.
- **RISK** — how much historical evidence suggests that changing/removing
  the code deserves further investigation.

The tool never presents inference as fact, and it is comfortable saying
**INSUFFICIENT EVIDENCE** instead of manufacturing an explanation.

### Confidence levels

| Level | Meaning |
|-------|---------|
| `HIGH` | strong, consistent supporting evidence |
| `MEDIUM` | moderate supporting evidence |
| `LOW` | weak supporting evidence |
| `CONTRADICTORY` | counter-evidence directly contradicts the explanation |
| `INSUFFICIENT` | not enough evidence to infer anything |

The numeric score is a deterministic weighted sum of the available evidence,
**not** a statistical probability. Supporting weights are summed and capped at
1.0; counter-evidence is then **subtracted** from that cap, so negative
evidence is never hidden by a large pile of supporting items. An explicit
revert anywhere in the file's history caps the level at MEDIUM (a revert
means the "why does this exist" story is murky). Weights are heuristics, not
scientifically validated probabilities.

### Risk levels

| Level | Meaning |
|-------|---------|
| `LOW` | historical evidence suggests removal deserves little extra caution |
| `MEDIUM` | some risk signals present |
| `HIGH` | multiple risk signals (reverts, regression history, tests, frequent changes) |
| `UNKNOWN` | insufficient/ambiguous history |

Risk is never a safety guarantee. The tool reports "historical removal risk:
HIGH" — never "safe to delete". The developer makes the final decision.

### Evidence ranking

Every evidence kind carries a documented weight (see `agent_blame/ranking.py`):

| Kind | Weight |
|------|--------|
| `introduced_by` (direct line introduction) | +0.30 |
| `test` / `same_commit_test` (tests with the code or covering the module) | +0.20 |
| `modified_by` (later modification) | +0.18 |
| `fix_related` (commit message references fix/regression — weak) | +0.15 |
| `live_caller` (AST-confirmed direct/attribute caller) | +0.20 |
| `import_reference` (module/symbol imported elsewhere) | +0.10 |
| `possible_caller` (name matches, resolution ambiguous) | +0.05 |
| `same_file` | +0.10 |
| `temporal` | +0.03 |
| `deleted_lines` (later removal — counter) | −0.15 |
| `replacement` (superseding implementation — counter) | −0.20 |
| `revert` (explicit revert — counter) | −0.25 |

A caller that lives in a **test file** is real evidence but weaker: its
`live_caller` weight drops to +0.10 (tests exercise the code, but a test
is not a production dependency). Caller weights are heuristics, documented
in `agent_blame/ranking.py` — never a claim of statistical probability.

With `--verbose`, each evidence item prints its weight and reasons, so the
final score is fully explainable and auditable.

---

## JSON output

The JSON schema is stable and documented so future coding agents can consume
it:

```bash
agent-blame src/auth/session.py:142 --json
```

```json
{
  "tool": "agent-blame",
  "version": "0.1.0",
  "target": {"file": "src/auth/session.py", "start_line": 142, "end_line": 142},
  "mode": "why",
  "repository": {"root": "/path/to/repo", "head": "<sha>", "shallow": false},
  "confidence": {"level": "HIGH", "score": 1.0, "reasons": ["..."]},
  "facts": [{"kind": "blame", "line": 142, "commit": "<sha>", "summary": "...", "text": "..."}],
  "inferences": [{"text": "...", "evidence_kinds": ["introduced_by"], "confidence": "MEDIUM"}],
  "evidence": [{"kind": "introduced_by", "commit": "<sha>", "text": "...", "weight": 0.3, "reasons": ["..."], "is_counter": false}],
  "counter_evidence": [{"kind": "revert", "commit": "<sha>", "text": "...", "weight": -0.25, "is_counter": true}],
  "history": [{"sha": "<sha>", "date": "2023-02-12T10:00:00+00:00", "subject": "...", "author": "..."}],
  "risk": {"level": "HIGH", "reasons": ["..."]},
  "warnings": []
}
```

All repository-derived strings in the JSON output are sanitized of terminal
control characters.

---

## Security model

The repository is treated as **untrusted input**.

- The tool **never executes repository code**: no tests, no builds, no
  package managers, no project scripts, no hooks, no importing project
  modules, no `eval`.
- Git is invoked with **argument arrays only** — never `shell=True`, never
  shell interpolation of repository-supplied paths or refs.
- Every git call has a **timeout** so a hanging repository cannot hang the
  tool.
- Output is decoded with `errors='replace'` so hostile encodings cannot
  crash the tool.
- **Terminal output is sanitized**: ANSI escape sequences (clear-screen,
  cursor moves, OSC title hacks, color codes) and C0 control characters are
  stripped from every repository-derived string before printing. A malicious
  commit message cannot clear your terminal, move your cursor, or spoof
  output. This is covered by dedicated tests.

## Privacy

- **Local-first by design.** No telemetry, no analytics, no repository
  uploads, no network requests. Your source code and git history never leave
  your machine.
- The core tool needs no network access at all.

## Determinism

Given the same repository state, tool version, and configuration, the
analysis produces the same result. No randomness in ranking, no hidden
external APIs, no network requests for analysis. The output is reproducible
and trustworthy.

---

## Limitations

- **Shallow clones** produce `LIMITED HISTORY` warnings; the original
  introduction may not be available locally. The tool distinguishes
  "history is unavailable" from "no historical evidence exists".
- **Rewritten history** (filter-branch, rebase) can orphan or alter
  introducing commits; the tool reports what the current history actually
  shows.
- **Line-range mapping across history is approximate** — later commits that
  "removed lines in this file" are flagged conservatively; exact line
  mapping across refactors is a documented limitation, not a claim of
  precision.
- **Merge commits** in `--commit` mode use the first parent as the baseline
  (the standard "merge diff" view) and say so; full merge interpretation is
  a documented limitation. In `--diff`/WHY modes, `git log --follow` applies
  history simplification and a merge commit itself may be omitted from a
  path-limited log even though commits from both parents remain visible.
  Where attribution is ambiguous the tool says so rather than manufacturing
  certainty.
- **The after-commit scan is bounded** (newest 30 commits per file) and
  limited to commits reachable from HEAD that are not ancestors of the
  analyzed commit; on an unmerged branch this reflects HEAD's view of
  "after".
- **Caller analysis is Python-only and conservative by design.** Other
  languages produce no symbol analysis (honest absence, never a regex
  guess presented as AST-level truth). Python is statically typed only in
  the import graph: `obj.method()` receivers are POSSIBLE, dynamic
  patterns (`getattr`, `eval`, decorators that register functions, plugin
  loading, monkey patching) are UNRESOLVED and never scored. Local
  shadowing via assignment can fool same-module attribution (documented
  limitation). The source index is fetched once per revision (2 git
  calls) and capped at 20 000 Python files.
- Message-text signals (fix/regression/security word matches) are **weak**
  signals by design and never decisive on their own.
- The tool does **not** perform formal static analysis; it is a historical
  evidence tool.

## Development

```bash
# run the full test suite (stdlib unittest, no dependencies)
python -m unittest discover -s tests -v

# individual suites
python -m unittest tests.test_target -v
python -m unittest tests.test_output -v
python -m unittest tests.test_git -v
python -m unittest tests.test_analyzer -v
python -m unittest tests.test_cli -v
python -m unittest tests.test_diff -v
python -m unittest tests.test_commit -v
python -m unittest tests.test_callers -v
python -m unittest tests.test_perf -v
```

Tests build **miniature git repositories with known histories** (introduction,
modification, rename, revert, regression, misleading messages, malicious
messages, Unicode paths, shallow clones, deleted files) and assert on the
**algorithm's conclusions** — not just exit codes.

### Project layout

```text
agent_blame/
  __init__.py      version + package doc
  cli.py           argparse CLI
  analyzer.py      pipeline orchestration (+ AnalysisMemo for multi-target runs)
  diff.py          --diff mode: diff parsing, grouping, noise control
  commit.py        --commit mode: revision-aware baseline + before/after chronology
  symbols.py       caller/symbol analysis (Python AST, conservative)
  repository.py    repository discovery
  git.py           safe Git abstraction (no shell, timeouts)
  history.py       blame, commits, diffs (batched metadata + numstat)
  graph.py         targeted historical graph
  evidence.py      evidence + counter-evidence discovery
  ranking.py       deterministic evidence weights
  confidence.py    confidence levels
  inference.py     purpose inference (evidence-backed only)
  risk.py          historical removal risk
  output.py        terminal-safe rendering + JSON
tests/
  gitfixture.py    miniature-repo fixture builder
  test_*.py        suites
```

---

## Phase 3: product validation & accuracy review (complete)

Phase 3 was a feature-frozen evaluation against four real repositories
(requests, flask, rich, Freebuff). The permanent record is
`PHASE3_EVALUATION.md`; the machine-readable dataset is `eval_dataset.json`.

It found and fixed three genuine bugs (a confidence-destroying chronology
bug where old reverts were cited against new code, replacement counter-
evidence stacking, and a revert/corrective double-count), two performance
problems (49 s → 12.5 s on a rename-heavy commit; 1,693 → 568 git calls),
a commit-mode bug (pure renames reported no movement), and two regression
noise sources (pre-introducer fixes, trivial revert-subject edits).

**Result: 270 tests green; zero false HIGH-confidence claims; zero
CONTRADICTORY confidence; ground-truth verified against git; classified
USEFUL MVP** (developers can benefit today, with honest limits).

---

## Phase 4: external developer validation (complete)

Phase 4 was a simulated external-developer study (no human participants
available in the build environment — see `PHASE4_VALIDATION.md` for the
methodology and a ready-to-run real-developer protocol). It found and fixed:

- **a false-caller correctness bug** — `_classify_call` never verified the
  callee name, so any bare call whose name was an import alias
  (`cast(...)`, `parse_url(...)`) inside the target's class was credited as
  a DIRECT caller (requests `prepare_url` gained 4 fabricated callers); now
  only calls that actually name the target (or a deterministically-resolved
  alias) are callers,
- **output noise** — WHY/HISTORY/RISK printed every per-commit
  `modified_by` bullet (rich: 528 lines, 199 near-identical bullets); now
  aggregated like diff/commit (82 lines, zero information loss — JSON
  keeps the full list), with the WHY/RISK chain capped at 25 + a `--history`
  pointer,
- **a misleading caller marker** — MODIFIED callers rendered with the
  "dead" marker; now `✓` LIVE / `~` MODIFIED / `✗` DELETED.

**Result: 279 tests green; JSON byte-identical across runs; zero
false-high-confidence findings; MVP classification: USEFUL MVP (C).**
Honest finding from the time-to-answer study: agent-blame is not faster
than a known `git blame` command — its value is discovery, aggregation, and
classification effort, not wall-clock speed.

---

## Phase 5: real-world validation preparation (complete — study not yet run)

Phase 5 froze the feature set and prepared a **real 5-developer validation
study**. The honest status is unchanged from Phase 4: **real human
validation remains outstanding** — this environment has no access to
participants, and no results in this project's records come from real
people. What Phase 5 delivered is a complete, executable study package in
`validation/` so a third-party facilitator can run it without knowing the
internals:

- `validation/STUDY_PROTOCOL.md` — recruitment, environment setup,
  session flow (30–45 min per participant), honesty rules, report template.
- `validation/PARTICIPANT_QUICKSTART.md` — participant-facing; no
  internals and no hints about which features are expected to be useful.
- `validation/TASK_SHEET.md` — five realistic tasks: understand code
  history, moved code, change review (your own diff), dependency/risk
  before modifying, commit investigation.
- `validation/MEASUREMENT_FORM.md` — per-participant observation form,
  verbatim questionnaire (16 questions incl. "what would you have done
  without agent-blame?"), trust-calibration table, evidence-based
  scorecards, 36-section report template.
- `validation/REFERENCE_TARGETS.md` — facilitator-only ground truth,
  verified 2026-08-17 against requests/flask/rich `main`, with exact git
  verification commands for trust calibration.

The quick-start path was verified end-to-end (fresh venv, `pip install -e
.`, `agent-blame` runs from any cwd inside a repo), and all six reference
targets reproduce their documented answers. The MVP classification remains
**USEFUL MVP (C)**; the final classification after a real study may move it
in either direction.

---

## Roadmap (not yet built)

Completed: `--diff` (2A), `--commit` (2B), caller/symbol relationships
(2C, conservative Python AST), code-movement/rename tracking (2D), and
regression detection (2E) — all on one deterministic engine (many target
selectors: `file:line`, `--history`, `--risk`, `--diff`, `--commit`).

Phase 3/4 candidates (not started): merge-aware analysis, richer JSON,
optional LLM explanation layer that explains the structured findings
without inventing evidence. Advanced caller/movement-assisted attribution
and blame-ancestry views were explicitly deferred per the Phase 2
stop-conditions. Phase 4 confirmed the feature freeze: requested features
(blame-ancestry views, non-Python languages, LLM layer) are logged in
`PHASE4_VALIDATION.md`, not built.

---

## License

Local tool for personal/team use. No telemetry, no network, no vendor lock-in.
