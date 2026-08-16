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
from .history import blame_target, file_commits, file_diff_stats, file_exists_at_head
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
        self._commits: dict = {}      # file -> List[CommitInfo]
        self._stats: dict = {}        # file -> {sha: (added, removed)}
        self.commit_map: dict = {}    # sha -> CommitInfo (all fetched so far)
        self.diff_memo: dict = {}     # (sha, file) -> CommitDiff

    def file_commits(self, repo: Repository, file: str):
        """Commits touching `file`, fetched once per file and cached."""
        if file not in self._commits:
            commits = file_commits(repo, file)
            self._commits[file] = commits
            for c in commits:
                self.commit_map.setdefault(c.sha, c)
        return self._commits[file]

    def file_stats(self, repo: Repository, file: str):
        """Per-commit added/removed counts for `file`, one git call per file."""
        if file not in self._stats:
            self._stats[file] = file_diff_stats(repo, file)
        return self._stats[file]


def analyze(repo: Repository, target: Target, mode: str = "why",
            memo: AnalysisMemo = None) -> AnalysisResult:
    """Run the full pipeline for one target.

    Handles the known edge cases:
      - file does not exist at HEAD -> warning, history-only analysis
      - shallow clone -> LIMITED HISTORY warning
      - unborn repo / no commits -> INSUFFICIENT with warning
      - target line beyond the file's length -> clean warning, INSUFFICIENT

    `memo` (optional) shares commit/diff caches across calls - pass the
    same AnalysisMemo when analyzing several targets from one run (diff
    mode) so git facts are fetched at most once.

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

    exists = file_exists_at_head(repo, target.file)
    if not exists:
        warnings.append(
            f"file {target.file} does not exist at HEAD; only historical "
            f"evidence from remaining history is available."
        )

    result = AnalysisResult(target=target, mode=mode,
                            repository=repo.to_dict(), warnings=warnings)

    # --- Blame the target range (facts) --------------------------------
    blame_lines = []
    if exists:
        try:
            blame_lines = blame_target(repo, target)
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
    commits = memo.file_commits(repo, target.file)
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
    # multiple targets in one run (diff mode) reuse every git fact.
    stats = memo.file_stats(repo, target.file)
    evidence = collect_evidence(repo, target, graph, introducing, later,
                                commit_map=memo.commit_map, diff_memo=memo.diff_memo,
                                stats=stats)
    counter = detect_counterevidence(repo, target, introducing, later,
                                     commit_map=memo.commit_map, diff_memo=memo.diff_memo,
                                     stats=stats)
    all_evidence = dedupe_evidence([*evidence, *counter])
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
