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
        # Movement caches (Phase 2D) - path-restricted, memoized.
        self._py_sources_limited: dict = {}   # (revision, paths) -> {path: str}
        self._worktree: dict = {}             # paths -> {path: str}
        self._index: dict = {}                # paths -> {path: str}

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

    def py_sources_limited(self, repo: Repository, revision: str,
                           paths):
        """Python source for a SUBSET of paths at `revision`, cached.

        Movement analysis only needs the changed paths (a move's source
        and destination are both in the change by definition), so the
        scan is proportional to the change size, not the repository.
        """
        key = (revision, tuple(sorted(paths)))
        if key not in self._py_sources_limited:
            from .symbols import load_py_sources  # lazy: avoids import cycle
            self._py_sources_limited[key] = load_py_sources(
                repo, revision, paths=list(paths))
        return self._py_sources_limited[key]

    def worktree_sources(self, root: str, paths):
        """Working-tree content for `paths` (unstaged diff "after" side)."""
        key = tuple(sorted(paths))
        if key not in self._worktree:
            from .symbols import worktree_sources
            self._worktree[key] = worktree_sources(list(paths), root)
        return self._worktree[key]

    def index_sources(self, repo: Repository, paths):
        """Index (staged) content for `paths` (staged diff "after" side)."""
        key = tuple(sorted(paths))
        if key not in self._index:
            from .symbols import index_sources
            self._index[key] = index_sources(repo, list(paths))
        return self._index[key]

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

    # --- Movement (Phase 2D) ------------------------------------------
    # Standalone modes only: --diff / --commit classify movement at the
    # change boundary (parent->commit, HEAD->worktree) where BOTH trees
    # are known; the shared pipeline here corrects the one dangerous case
    # blame alone gets wrong - code MOVED between files that git's
    # similarity detection missed, where blame credits the MOVE commit as
    # the introduction. Confirmed movement becomes one evidence item that
    # flows through the existing ranking/confidence/risk (it must NEVER
    # turn the mover into the "original introduction" fact).
    if mode in ("why", "history", "risk"):
        movement = _build_standalone_movement(repo, memo, target, revision,
                                              blame_lines)
        if movement is not None:
            result.movement = movement
            from dataclasses import replace
            from .models import EvidenceItem
            from .ranking import weight_for
            moved_by = movement.get("moved_by") or "?"
            origin = movement.get("origin") or "?"
            # Re-attribute the introducing EVIDENCE from the mover to the
            # TRUE origin: the mover is never the introduction (Phase 2D
            # core rule). Raw blame FACTS stay raw (honest git data); the
            # evidence layer carries the correction.
            if origin != "?" and moved_by != "?":
                origin_ci = memo.commit_map.get(origin)
                if origin_ci is None:
                    from .history import commit_info
                    origin_ci = commit_info(repo, origin)
                origin_subj = origin_ci.subject if origin_ci else ""
                fixed = []
                for e in all_evidence:
                    if e.kind == "introduced_by" and e.commit == moved_by:
                        head = e.text.split(" introduced by ", 1)[0]
                        fixed.append(replace(
                            e, commit=origin,
                            text=(f"{head} introduced by {origin[:8]}: "
                                  f"{origin_subj} (moved here by "
                                  f"{moved_by[:8]})"),
                            reasons=[*e.reasons,
                                     "re-attributed: this commit MOVED the "
                                     "code; the mover is not the introduction"]))
                    else:
                        fixed.append(e)
                all_evidence = fixed
            all_evidence = [*all_evidence, EvidenceItem(
                kind="code_movement",
                commit=movement.get("moved_by"),
                text=(f"code moved here by {moved_by[:8] if moved_by != '?' else '?'} "
                      f"from {movement.get('source_path')}; originally introduced "
                      f"by {origin[:8] if origin != '?' else '?'} "
                      f"({movement.get('origin_path')})"),
                weight=weight_for("code_movement"),
                reasons=["movement evidence: git rename metadata and/or "
                         "symbol-level continuity across the move commit"],
                is_counter=False)]

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


def _build_standalone_movement(repo: Repository, memo: AnalysisMemo,
                               target: Target, revision: str,
                               blame_lines) -> Optional[dict]:
    """Movement evidence for a standalone (WHY/HISTORY/RISK) analysis.

    Two cases:
    1. git's blame followed a rename: the blame `filename` field holds
       the ORIGIN path and the blamed commit is the original introducer.
       A bounded movement-chain walk finds which commit MOVED the code.
    2. blame credited the CURRENT path (git's similarity detection
       missed a partial move): find_origin checks whether the blamed
       commit's parent had the same symbol elsewhere; on a confirmed
       match the mover is the blamed commit and the true origin is
       blamed from the source range.

    Returns a Movement-style dict, or None (no movement established -
    a genuine introduction stays an introduction).
    """
    if not blame_lines:
        return None
    origin_paths: dict = {}
    for bl in blame_lines:
        if bl.filename and bl.filename != target.file:
            origin_paths.setdefault(bl.commit, bl.filename)
    if origin_paths:
        # Case 1: blame followed the rename - origin is a FACT. The chain
        # walk surfaces WHICH commit(s) moved it (spec 2D/19: trace the
        # whole chain, not just the last move).
        origin_commit, origin_path = next(iter(origin_paths.items()))
        from .history import movement_chain
        chain = movement_chain(repo, target.file, revision=revision)
        moved_by = None
        mtype = "CODE_MOVEMENT"
        public_chain = []
        for ev in chain:
            if ev["kind"] == "rename" and ev["new_path"] == target.file:
                if moved_by is None:
                    moved_by = ev["commit"]
                    mtype = "RENAME"
            if ev["kind"] == "create" and ev["new_path"] == target.file:
                if moved_by is None:
                    moved_by = ev["commit"]
            public_chain.append({"commit": ev["commit"],
                                 "old_path": ev["old_path"],
                                 "new_path": ev["new_path"]})
        # The immediate source of the last move (the full chain stays in
        # `chain` for the multi-hop trace).
        immediate = chain[0]["old_path"] if chain else origin_path
        return {
            "type": mtype,
            "source_path": immediate,
            "source_symbol": None,
            "dest_path": target.file,
            "dest_symbol": None,
            "moved_by": moved_by,
            "origin": origin_commit,
            "origin_path": origin_path,
            "confidence": "HIGH",
            "signals": ["git blame rename follow (origin path from blame)",
                         "movement chain walk"] + (
                            ["git rename metadata"] if mtype == "RENAME" else []),
            "chain": public_chain,
        }
    # Case 2: blame credited the current path - partial-move correction.
    from collections import Counter
    from .symbols import find_origin
    common = Counter(bl.commit for bl in blame_lines).most_common(1)[0][0]
    mv = find_origin(repo, memo, common, revision, target)
    if mv is None:
        return None
    # Origin commit: blame the source symbol's range at the mover's parent.
    parent = mv.get("_parent")
    start = mv.get("_source_start")
    end = mv.get("_source_end")
    src = mv.get("source_path")
    if parent and start and src:
        try:
            from .history import blame_target
            origin_lines = blame_target(
                repo, Target(file=src, start_line=start, end_line=end),
                revision=parent)
            if origin_lines:
                mv["origin"] = origin_lines[0].commit
        except GitError:
            pass
    for drop in ("_parent", "_source_start", "_source_end"):
        mv.pop(drop, None)
    return mv
