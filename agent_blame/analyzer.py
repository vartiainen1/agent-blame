"""The analysis pipeline (spec section 5):

    CLI -> repository discovery -> git abstraction -> history extraction
    -> target/code analysis -> historical graph -> evidence discovery
    -> evidence ranking -> inference + counter-evidence -> confidence
    -> risk analysis -> structured result

This module wires the stages together for one target and produces the
structured AnalysisResult. It is deliberately the only place that knows
the order; every stage stays independently testable.
"""

from __future__ import annotations

from typing import List

from .confidence import compute_confidence
from .evidence import collect_evidence, dedupe_evidence, detect_counterevidence
from .git import GitError
from .graph import build_graph
from .history import (blame_target, file_commits, file_diff_stats,
                      file_exists_at)
from .inference import infer_original_vs_current, infer_purpose
from .models import AnalysisResult, Confidence, Inference, Target
from .ranking import rank_evidence
from .repository import Repository
from .risk import analyze_risk


class AnalysisMemo:
    """Shared cache for a multi-target run (used by --diff).

    Diff mode analyzes many line ranges that share the same files and
    commits. Without sharing, each target would re-run `git log --follow`
    for its file and re-fetch every commit's metadata/diffs - the N+1
    pattern this memo exists to prevent. One memo is created per run and
    threaded through every analyze() call.
    """

    def __init__(self) -> None:
        self._commits: dict = {}      # (file, revision) -> List[CommitInfo]
        self._stats: dict = {}        # (file, revision) -> {sha: (added, removed)}
        self.commit_map: dict = {}    # sha -> CommitInfo (all fetched so far)
        self.diff_memo: dict = {}     # (sha, file) -> CommitDiff
        # Symbol/caller caches (Phase 2C) - one repo scan per revision.
        self._py_sources: dict = {}   # revision -> {path: content}
        self._asts: dict = {}         # (revision, path) -> ast.Module | None
        self._symbols: dict = {}      # (revision, path) -> List[Symbol]

    def file_commits(self, repo: Repository, file: str, revision: str = "HEAD"):
        """Commits touching `file` before `revision`, fetched once per key."""
        key = (file, revision)
        if key not in self._commits:
            commits = file_commits(repo, file, revision=revision)
            self._commits[key] = commits
            for c in commits:
                self.commit_map.setdefault(c.sha, c)
        return self._commits[key]

    def file_stats(self, repo: Repository, file: str, revision: str = "HEAD"):
        """Per-commit added/removed counts for `file`, one git call per key."""
        key = (file, revision)
        if key not in self._stats:
            self._stats[key] = file_diff_stats(repo, file, revision=revision)
        return self._stats[key]

    # -- symbol/caller caches (Phase 2C) --------------------------------

    def py_sources(self, repo: Repository, revision: str = "HEAD"):
        """All Python source at `revision`, fetched ONCE per revision.

        Two git calls total per revision (ls-tree + one cat-file batch),
        so N analyzed targets never multiply the repository scan.
        """
        if revision not in self._py_sources:
            from .symbols import load_py_sources  # lazy: avoids import cycle
            self._py_sources[revision] = load_py_sources(repo, revision)
        return self._py_sources[revision]

    def file_ast(self, revision: str, path: str, content: str):
        """Parsed AST for one file at one revision (cached, parse-only)."""
        key = (revision, path)
        if key not in self._asts:
            import ast as _ast
            try:
                self._asts[key] = _ast.parse(content)
            except (SyntaxError, ValueError):
                self._asts[key] = None
        return self._asts[key]

    def file_symbols(self, revision: str, path: str, content: str):
        """Extracted symbols for one file at one revision (cached)."""
        key = (revision, path)
        if key not in self._symbols:
            from .symbols import extract_symbols  # lazy: avoids import cycle
            self._symbols[key] = extract_symbols(content, path)
        return self._symbols[key]


def analyze(repo: Repository, target: Target, mode: str = "why",
            memo: AnalysisMemo = None,
            revision: str = "HEAD",
            change_map: dict = None) -> AnalysisResult:
    """Run the full pipeline for one target.

    Handles the known edge cases:
      - file does not exist at the analyzed revision -> warning,
        history-only analysis
      - shallow clone -> LIMITED HISTORY warning
      - unborn repo / no commits -> INSUFFICIENT with warning
      - target line beyond the file's length -> clean warning, INSUFFICIENT

    `memo` (optional) shares commit/diff caches across calls - pass the
    same AnalysisMemo when analyzing several targets from one run (diff /
    commit mode) so git facts are fetched at most once.

    `revision` anchors the analysis: blame and the "commits touching this
    file" walk run against `revision` instead of HEAD. Commit mode passes
    the target commit's parent so the analysis describes the state BEFORE
    the commit; the commit itself can then never be mis-attributed as the
    introducer of the behavior it changes (chronology correctness).

    `change_map` ({path: status}) marks caller files that the analyzed
    change deletes/modifies, so caller status is revision-honest
    (DELETED / MODIFIED) instead of blindly LIVE.

    INTEGRITY RULE: line-level evidence (blame, introducing commits, later
    modifications of the TARGET LINES, confidence, risk) is only produced
    when `git blame` actually returned lines for the target. If blame
    fails or returns nothing, the analysis degrades to the factual history
    chain plus an INSUFFICIENT confidence - never a confident explanation
    built from unrelated file-level history. "Insufficient evidence" is
    always preferred over a plausible-but-wrong explanation.
    """
    if memo is None:
        memo = AnalysisMemo()
    warnings: List[str] = list(repo.warnings)
    has_history = bool(repo.head)

    if repo.shallow:
        warnings.append(
            "LIMITED HISTORY: this repository appears to be a shallow clone; "
            "the original introduction may not be available locally."
        )

    exists = file_exists_at(repo, revision, target.file)
    if not exists:
        warnings.append(
            f"file {target.file} does not exist at {revision}; only "
            f"historical evidence from remaining history is available."
        )

    result = AnalysisResult(target=target, mode=mode,
                            repository=repo.to_dict(), warnings=warnings)

    # --- Blame the target range (facts) --------------------------------
    blame_lines = []
    if exists:
        try:
            blame_lines = blame_target(repo, target, revision=revision)
        except GitError as e:
            # e.g. line number beyond the file's length: git exits 128.
            # Never leak a traceback - a clean warning is the contract.
            detail = str(e)
            detail = detail.split("git: ", 1)[-1].strip() or detail
            warnings.append(f"could not blame {target.file}:{target.start_line}-"
                            f"{target.end_line}: {detail}")
            blame_lines = []
        for bl in blame_lines:
            result.facts.append({
                "kind": "blame",
                "line": bl.line_no,
                "commit": bl.commit,
                "summary": bl.summary,
                "author": bl.author,
                "date": bl.author_time,
                "text": f"line {bl.line_no} introduced by {bl.commit[:8]}: "
                        f"{bl.summary}",
            })

    # --- Commits touching the file (fetched ONCE, reused everywhere) ----
    commits = memo.file_commits(repo, target.file, revision=revision)
    result.history = [_commit_row(c) for c in commits]

    # If the target lines could not be blamed, we have NO line-anchored
    # evidence: report the factual history chain and stop. Confidence is
    # INSUFFICIENT - not a guess assembled from unrelated file history.
    if not blame_lines:
        result.confidence = Confidence(
            "INSUFFICIENT", 0.0,
            reasons=["target lines could not be blamed (missing file or "
                     "out-of-range line); no line-anchored evidence"],
        )
        return result

    # --- Historical graph (targeted expansion) --------------------------
    graph, introducing, later = build_graph(repo, target, blame_lines=blame_lines,
                                            commits=commits)

    # --- Evidence collection + ranking ----------------------------------
    # commit_map / diff_memo come from the shared memo when provided, so
    # multiple targets in one run (diff/commit mode) reuse every git fact.
    stats = memo.file_stats(repo, target.file, revision=revision)
    evidence = collect_evidence(repo, target, graph, introducing, later,
                                commit_map=memo.commit_map, diff_memo=memo.diff_memo,
                                stats=stats)
    counter = detect_counterevidence(repo, target, introducing, later,
                                     commit_map=memo.commit_map, diff_memo=memo.diff_memo,
                                     stats=stats)
    all_evidence = dedupe_evidence([*evidence, *counter])

    # --- Caller relationships (Phase 2C, revision-aware) ---------------
    # Appended AFTER dedupe: each caller is a distinct item and must never
    # be collapsed on (kind, commit=None). Only resolves when the target
    # line is inside a Python symbol; TEXTUAL/UNRESOLVED findings stay in
    # result.callers with zero evidence weight.
    from .symbols import collect_caller_evidence  # lazy: avoids import cycle
    caller_ev, caller_refs, target_sym = collect_caller_evidence(
        repo, target, revision=revision, memo=memo, change_map=change_map)
    result.callers = [c.to_dict() for c in caller_refs]
    result.symbol = target_sym.to_dict() if target_sym is not None else None
    all_evidence = [*all_evidence, *caller_ev]
    ranked = rank_evidence(all_evidence)

    for e in ranked:
        d = e.to_dict()
        (result.counter_evidence if e.is_counter else result.evidence).append(d)

    # --- Inference -------------------------------------------------------
    inferences: List[Inference] = []
    inferences.extend(infer_purpose(all_evidence))
    inferences.extend(infer_original_vs_current(all_evidence))
    result.inferences = [inf.to_dict() for inf in inferences]

    # --- Confidence ------------------------------------------------------
    result.confidence = compute_confidence(all_evidence)

    # --- Risk -------------------------------------------------------------
    result.risk = analyze_risk(all_evidence, has_history)

    return result


def _commit_row(c) -> dict:
    return {
        "sha": c.sha,
        "date": c.author_date,
        "subject": c.subject,
        "author": c.author,
    }
