# agent-blame

**Deterministic Git archaeology: why this code exists, how it evolved, and what historical evidence matters before you change or remove it.**

[![CI](https://github.com/vartiainen1/agent-blame/actions/workflows/ci.yml/badge.svg)](https://github.com/vartiainen1/agent-blame/actions/workflows/ci.yml)
[![license](https://img.shields.io/github/license/vartiainen1/agent-blame)](https://github.com/vartiainen1/agent-blame/blob/master/LICENSE)
[![python](https://img.shields.io/badge/python-3.9%20%7C%203.11%20%7C%203.12-3776AB)](https://github.com/vartiainen1/agent-blame/actions)
[![dependencies-0](https://img.shields.io/badge/dependencies-0-brightgreen)](https://github.com/vartiainen1/agent-blame)
[![Visitors](https://visitor-badge.laobi.icu/badge?page_id=vartiainen1.agent-blame&left_text=Visitors&right_color=2F80ED)](https://github.com/vartiainen1/agent-blame)
[![companion-error-log](https://img.shields.io/badge/companion-agent--error--log-2ea44f)](https://github.com/vartiainen1/agent-error-log)
[![companion-decision-log](https://img.shields.io/badge/companion-agent--decision--log-2ea44f)](https://github.com/vartiainen1/agent-decision-log)
[![companion-log-ai](https://img.shields.io/badge/companion-agent--log--ai-2ea44f)](https://github.com/vartiainen1/agent-log-ai)
[![companion-memory](https://img.shields.io/badge/companion-agent--memory-2ea44f)](https://github.com/vartiainen1/agent-memory)
[![companion-diff-gate](https://img.shields.io/badge/companion-agent--diff--gate-2ea44f)](https://github.com/vartiainen1/agent-diff-gate)

`agent-blame` is a local-first, dependency-free command-line tool that answers a question `git blame` never does: not *who* changed a line, but *why* that code exists and what its history says about changing it.

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

---

## Why it exists

When you meet unfamiliar code, you usually have three questions:

1. **WHY?** — Why was this code introduced?
2. **HISTORY?** — What happened to it after it was introduced?
3. **RISK?** — What historical evidence should I consider before changing or removing it?

Answering manually means `git blame` + `git log` + `git show`, searching tests, and hunting for regressions, reverts, and replacements. The information exists but is scattered. `agent-blame` connects it.

| Tool | Answers |
|------|---------|
| `git blame` | Who changed this? |
| `git log` | What changed? |
| `git show` | What did a commit do? |
| **`agent-blame`** | Why was this introduced, how did it evolve, what evidence supports that, and what should I know before changing or removing it? |

The core is **not AI**. It is a deterministic historical-analysis algorithm. The repository is the source of truth; the algorithm decides which evidence matters; counter-evidence prevents simplistic conclusions; confidence communicates uncertainty; risk analysis flags what deserves further investigation.

---

## Installation

Requires **Python 3.9+** and **git** on PATH. No dependencies — stdlib only.

```bash
# from the project root
pip install -e .          # optional: adds the `agent-blame` command
# or run directly without installing:
python -m agent_blame --help
```

---

## Quick start

Run from anywhere inside a git repository:

```bash
agent-blame src/auth/session.py:142     # why does this line exist?
agent-blame --diff                      # what history explains my current changes?
agent-blame --commit d037a21            # why does the code this commit changed exist?
```

### Target forms

Four target forms are accepted (parsing/UX only — the analysis engine is identical for all of them):

| Form | Example | Behavior |
|------|---------|----------|
| `file:line` (canonical) | `agent-blame src/auth.py:142` | WHY analysis of that line (or `file:start-end`) |
| `file:function` | `agent-blame src/auth.py:authenticate` | resolves the function/method/class to its DEFINING line via Python AST and analyzes it — "resolved 'authenticate' to line 40" is printed. Qualified names (`Server.handle`) are the identity; an unqualified name must be unique in the file (ambiguity is a clean error naming the candidates) |
| `file` (bare) | `agent-blame src/auth.py` | prints the file's blame-able lines — Python files show the symbol table with each symbol's defining line, other files show the line count — and points you at `agent-blame <file>:<line>` (an affordance, not an error) |
| `<sha>` (bare) | `agent-blame d037a21` | equivalent to `--commit d037a21` (verified with `git rev-parse`, so a file whose name looks like a sha is never hijacked) |

Symbol resolution reads the repository at HEAD (the analyzed revision), and is Python-only — the same honesty rule as caller analysis.

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

## What it reports

### Facts, inferences, counter-evidence

The tool strictly separates:

- **FACT** — directly observable repository information ("line 142 was introduced by commit 72ac91").
- **INFERENCE** — a conclusion derived from multiple evidence items, phrased as a suggestion backed by named evidence.
- **COUNTER-EVIDENCE** — evidence that weakens or contradicts an inference (a later revert, removed lines, a replacement implementation).
- **CONFIDENCE** — how strongly the available evidence supports the conclusion.
- **RISK** — how much historical evidence suggests that changing/removing the code deserves further investigation.

The tool never presents inference as fact, and it is comfortable saying **INSUFFICIENT EVIDENCE** instead of manufacturing an explanation.

### Confidence levels

| Level | Meaning |
|-------|---------|
| `HIGH` | strong, consistent supporting evidence |
| `MEDIUM` | moderate supporting evidence |
| `LOW` | weak supporting evidence |
| `CONTRADICTORY` | counter-evidence directly contradicts the explanation |
| `INSUFFICIENT` | not enough evidence to infer anything |

The numeric score is a deterministic weighted sum of the available evidence, **not** a statistical probability. Counter-evidence is subtracted from a capped supporting sum, so negative evidence is never hidden by a pile of supporting items. An explicit revert anywhere in the file's history caps the level at MEDIUM.

### Risk levels

| Level | Meaning |
|-------|---------|
| `LOW` | historical evidence suggests removal deserves little extra caution |
| `MEDIUM` | some risk signals present |
| `HIGH` | multiple risk signals (reverts, regression history, tests, frequent changes) |
| `UNKNOWN` | insufficient/ambiguous history |

Risk is never a safety guarantee. The tool reports "historical removal risk: HIGH" — never "safe to delete". The developer makes the final decision.

### Caller / symbol analysis

When the analyzed lines sit inside a Python function/method/class, `agent-blame` finds the symbol, scans the repository at the **analyzed revision** for references, and classifies every relationship — there is no `--callers` mode; callers are contextual evidence inside every mode.

| Relationship | Meaning | Evidence weight |
|--------------|---------|-----------------|
| `DIRECT_CALL` | bare/aliased call resolved via same-module scope or a resolved from-import | strong (`live_caller` +0.20) |
| `ATTRIBUTE_CALL` | `module.func()` / `Class.method()` where the receiver resolves to the target's module | strong (`live_caller` +0.20) |
| `IMPORT_REFERENCE` | the target symbol or module is imported | weak (+0.10) |
| `POSSIBLE_CALL` | name matches but resolution is ambiguous | very weak (+0.05) |
| `TEXTUAL_MATCH` | the name appears as text only (strings/comments) | **zero** — reported for transparency, never scored |
| `UNRESOLVED` | dynamic patterns (`getattr`/`eval`/reflection) | **zero** — never scored |

A confirmed caller always outweighs any number of textual matches. Comment/string mentions are never callers, and a module that defines its own `load()` is never credited as calling `check_errors.load()`.

### Code movement / rename tracking

**A movement commit is never reported as the code's original introduction.** `agent-blame new.py:<line>` reports *"moved here by B, originally introduced by A"* — from three evidence sources: git rename metadata, blame-origin capture with bounded chain walks (including multiple sequential moves), and symbol-level continuity for partial moves git's similarity threshold misses.

| Type | Meaning | Confidence |
|------|---------|-----------|
| `RENAME` | git-confirmed file rename | HIGH |
| `CODE_MOVEMENT` | symbol continuity confirmed, source removed | HIGH |
| `POSSIBLE_MOVEMENT` | strong similarity but incomplete/ambiguous | MEDIUM / AMBIGUOUS |
| `COPY` | strong similarity but the source still exists | HIGH |

A copy is never called a move; unsupported languages get no symbol-level claim.

### Regression detection

**"Has this code caused problems before?"** — as historical *evidence*, never a verdict. The tool identifies later commits that appear to fix or revert behavior associated with the target:

> CORRELATION IS NOT PROOF OF CAUSATION.

Findings are classified on a strength ladder — `EXPLICIT_REVERT` (git's structured `This reverts commit <sha>` trailer, blame-confirmed), `LIKELY_REGRESSION_FIX`, `POSSIBLE_REGRESSION_FIX`, `CORRECTIVE_CHANGE`, and `NO_REGRESSION_EVIDENCE` — with a false-positive guard: a "fix" to an unrelated symbol in the same file is NOT reported as a regression for the target, and a pre-introducer revert is never cited against newer code.

---

## JSON output

The JSON schema is stable and documented for machine consumers:

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

DIFF and COMMIT modes reuse the same conventions (`mode: "diff"` with `scope` + `files[]`, `mode: "commit"` with a `commit` metadata section + `changes[]`), so existing consumers work across modes. All repository-derived strings are sanitized of terminal control characters.

---

## Security & privacy

**The repository is treated as untrusted input.**

- The tool **never executes repository code**: no tests, builds, package managers, project scripts, hooks, or importing project modules — and no `eval`.
- Git is invoked with **argument arrays only** — never `shell=True`, never shell interpolation of repository-supplied paths or refs.
- Every git call has a **timeout** so a hanging repository cannot hang the tool.
- **Terminal output is sanitized**: ANSI escape sequences and C0 control characters are stripped from every repository-derived string before printing. A malicious commit message cannot clear your terminal, move your cursor, or spoof output.

**Local-first by design.** No telemetry, no analytics, no repository uploads, no network requests. Your source code and git history never leave your machine.

**Deterministic.** Given the same repository state, tool version, and configuration, the analysis produces the same result. No randomness in ranking, no hidden external APIs.

---

## Known limitations

- **Shallow clones** produce `LIMITED HISTORY` warnings; the original introduction may not be available locally. The tool distinguishes "history is unavailable" from "no historical evidence exists".
- **Rewritten history** (filter-branch, rebase) can orphan or alter introducing commits; the tool reports what the current history actually shows.
- **Line-range mapping across history is approximate** — later commits that "removed lines in this file" are flagged conservatively.
- **Merge commits** in `--commit` mode use the first parent as the baseline (the standard "merge diff" view) and say so; full merge interpretation is a documented limitation.
- **The after-commit scan is bounded** (newest 30 commits per file) and limited to commits reachable from HEAD.
- **Caller analysis is Python-only and conservative by design.** Other languages produce no symbol analysis (honest absence, never a regex guess presented as AST-level truth). Dynamic patterns (`getattr`, `eval`, plugin loading, monkey patching) are `UNRESOLVED` and never scored.
- Message-text signals (fix/regression/security word matches) are **weak** signals by design and never decisive on their own.
- The tool does **not** perform formal static analysis; it is a historical evidence tool.

---

## Validation

The tool is evaluated — not just tested:

- **321 automated tests** (stdlib `unittest`, no dependencies) that build miniature git repositories with known histories — introduction, modification, rename, revert, regression, misleading and malicious messages, Unicode paths, shallow clones, deleted files — and assert on the algorithm's conclusions, not just exit codes.
- **Real-repository evaluation** against requests, flask, and rich found and fixed three genuine bugs (a confidence-destroying chronology bug, replacement counter-evidence stacking, and a revert/corrective double-count) and two performance problems (49 s → 12.5 s on a rename-heavy commit; 1,693 → 568 git calls). Phase 3 record: `PHASE3_EVALUATION.md`.
- **Simulated external-developer validation** (no human participants available in the build environment) found and fixed a false-caller correctness bug and output-noise problems. Phase 4 record: `PHASE4_VALIDATION.md`.
- **Adversarial AI validation** (Phases 6A–6C) measured how agents discover and invoke the tool; the `<file>:<line>` invocation contract was identified as the adoption blocker, and target resolution was extended to accept bare files, `file:function`, and bare shas. Records: `PHASE6_VALIDATION.md`, `PHASE6B_DISCOVERABILITY.md`, `PHASE6C_VALUE_PROPOSITION.md`.

**Honest status: real human validation remains outstanding.** The 5-developer study package in `validation/` is complete and verified against current repositories, but no real human study has been conducted — no results in this project's records come from real people. Claims about real developer usefulness, trust, and repeated voluntary use remain unvalidated. Current classification: **USEFUL MVP (C), PROVISIONAL**. The final classification may move in either direction after a real study.

---

## Development

```bash
# run the full test suite (stdlib unittest, no dependencies)
python -m unittest discover -s tests

# individual suites
python -m unittest tests.test_target -v
python -m unittest tests.test_cli -v
python -m unittest tests.test_diff -v
python -m unittest tests.test_commit -v
python -m unittest tests.test_callers -v
python -m unittest tests.test_perf -v
```

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

## Companion tools

`agent-blame` is the **history layer** of the agent-tool family — the other
members remember what happened so an AI coding agent can learn and stay
honest:

| Repo | What it does | How it works |
|---|---|---|
| [agent-error-log](https://github.com/vartiainen1/agent-error-log) | what BROKE | text log + linter + git gate |
| [agent-decision-log](https://github.com/vartiainen1/agent-decision-log) | what was CHOSEN and why | append-only decisions + currency chain |
| [agent-log-ai](https://github.com/vartiainen1/agent-log-ai) | *why* it kept happening | heuristics select → LLM reasons |
| [agent-memory](https://github.com/vartiainen1/agent-memory) | persistent project knowledge | typed, trusted, auditable memory |
| [agent-diff-gate](https://github.com/vartiainen1/agent-diff-gate) | what must never be COMMITTED | pre-commit diff scan + gate |
| **agent-blame (this)** | **why the code exists** | **deterministic git archaeology** |

## License

MIT — see [LICENSE](LICENSE).
