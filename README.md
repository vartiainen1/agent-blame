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
| `target` | `<file>:<line>` or `<file>:<start>-<end>` (repo-relative) |
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
- **Per-commit evidence is aggregated in the terminal.** A file touched by
  80 commits does not print 80 near-identical bullets; the terminal shows
  "N later commits modified this file". The JSON output keeps the full
  per-commit list for machine consumption.

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
  per-line analysis. `--commit` mode instead analyzes the whole moved file
  against the baseline (bounded by a size guard for binary blobs).

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
| `same_file` | +0.10 |
| `temporal` | +0.03 |
| `deleted_lines` (later removal — counter) | −0.15 |
| `replacement` (superseding implementation — counter) | −0.20 |
| `revert` (explicit revert — counter) | −0.25 |

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

## Roadmap (not yet built)

Phase 2 remaining: commit mode (`--commit`), stronger revert/rename/code-
movement tracking, caller and symbol relationships, regression detection,
better counter-evidence, caching. Phase 3 candidates: merge-aware analysis,
richer JSON, optional LLM explanation layer that explains the structured
findings without inventing evidence.

The MVP deliberately stops at: repository discovery, safe Git, `file:line`
targets, blame, introducing commits, commit diffs/metadata, relevant history,
evidence model + ranking, confidence, basic counter-evidence, basic risk,
JSON output, secure terminal output, and tests. Phase 2A added `--diff` and
Phase 2B added `--commit` on top of the same single engine (one pipeline,
many target selectors: `file:line`, `--history`, `--risk`, `--diff`,
`--commit`).

Phase 2 remaining: stronger revert/rename/code-movement tracking, caller and
symbol relationships, regression detection, better counter-evidence,
caching. Phase 3 candidates: merge-aware analysis, richer JSON, optional LLM
explanation layer that explains the structured findings without inventing
evidence.

---

## License

Local tool for personal/team use. No telemetry, no network, no vendor lock-in.
