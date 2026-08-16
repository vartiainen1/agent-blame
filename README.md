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

# JSON: machine-readable structured result
agent-blame --json src/auth/session.py:142

# VERBOSE: per-evidence weights and reasons
agent-blame --verbose src/auth/session.py:142
```

### Command-line options

| Option | Meaning |
|--------|---------|
| `target` | `<file>:<line>` or `<file>:<start>-<end>` (repo-relative) |
| `--history` | ranked historical timeline for the target |
| `--risk` | historical change/removal risk analysis |
| `--json` | machine-readable JSON output (stable schema) |
| `--verbose` | per-evidence weights and reasons |
| `--cwd DIR` | repository or subdirectory to analyze (default: cwd) |
| `--version` | print version and exit |

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
- **Merge commits** are handled via git's own attribution (`git log
  --follow`, which applies history simplification); a merge commit itself
  may be omitted from a path-limited log even though commits from both
  parents remain visible. Where attribution is ambiguous the tool says so
  rather than manufacturing certainty.
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
  analyzer.py      pipeline orchestration
  repository.py    repository discovery
  git.py           safe Git abstraction (no shell, timeouts)
  history.py       blame, commits, diffs
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

Phase 2 candidates: diff mode (`--diff`), commit mode (`--commit`), stronger
revert/rename/code-movement tracking, caller and symbol relationships,
regression detection, better counter-evidence, caching. Phase 3 candidates:
merge-aware analysis, richer JSON, optional LLM explanation layer that
explains the structured findings without inventing evidence.

The MVP deliberately stops at: repository discovery, safe Git, `file:line`
targets, blame, introducing commits, commit diffs/metadata, relevant history,
evidence model + ranking, confidence, basic counter-evidence, basic risk,
JSON output, secure terminal output, and tests.

---

## License

Local tool for personal/team use. No telemetry, no network, no vendor lock-in.
