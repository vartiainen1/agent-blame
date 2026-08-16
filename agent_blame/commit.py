"""Commit mode (--commit): historical context for a specific commit.

Answers: "what did this commit change, and what historical context explains
those changes?" (spec Phase 2B). The target-selection dimension is a
commit instead of a working-tree diff; the underlying analysis engine is
the SAME one used by WHY / HISTORY / RISK / DIFF modes.

Pipeline:

    resolve commit
      -> baseline = first parent (merges) | none (root commit)
      -> git diff <baseline> <sha> --name-status -z  (NUL-safe metadata)
      -> per-file unified diff hunks
      -> BEFORE-state analysis per group: the existing pipeline run
         against the BASELINE revision, so blame attributes the previous
         behavior to the commits that introduced IT - the target commit
         can never be mis-attributed as the origin of its own change
         (chronology: before/target/after are kept strictly separate)
      -> AFTER-state scan: bounded `git log <sha>..HEAD` per file, shown
         as its own section, never mixed into the before-state evidence

Honesty rules carried over from --diff:
  - added files: no base version -> NEW FILE, no fabricated history
  - deleted files: analyzed against the baseline revision
  - binary files: reported, not parsed
  - merge commits: first-parent baseline, documented as a limitation
  - root commit: no previous revision, reported as such

Security: all git invocations go through the safe argv wrapper (no shell),
revision strings are passed as argv elements, and the CLI rejects revision
arguments that start with "-" so they can never become git options.
"""

from __future__ import annotations

from typing import List, Optional

from .analyzer import AnalysisMemo
from .diff import (_ANALYZABLE, _INSUFFICIENT, _analysis_signature,
                   _analyze_region, _classify_changes, _hunk_bodies,
                   _parse_hunks, _parse_name_status, _raw_diff_for_file,
                   collect_changed_files)
from .evidence import _REVERT_REF, _classify_commit_message
from .graph import _is_test_path
from .git import GitError, git_output, try_git_output
from .history import commit_info, file_exists_at, later_commits_after
from .models import (AnalysisResult, CommitChange, CommitResult, DiffGroup,
                     Target)
from .movement import (boundary_movements, group_movement,
                       intersecting_movement, moved_symbol_group,
                       public_movement, rename_movement)
from .repository import Repository


class CommitError(Exception):
    """Raised when the requested commit cannot be resolved or analyzed."""


def resolve_commit(repo: Repository, rev: str):
    """Fetch metadata for a revision-ish argument (sha, abbrev, HEAD, HEAD~1)."""
    ci = commit_info(repo, rev)
    if ci is None:
        raise CommitError(f"could not resolve commit {rev!r}")
    return ci


def _revert_ref(ci) -> Optional[str]:
    """The commit this commit reverts, per its message (deterministic).

    git does not store revert relationships structurally, so the strongest
    deterministic signal is the standard "This reverts commit <sha>"
    trailer (git's own `git revert` writes it). The historical
    significance is then confirmed INDEPENDENTLY by blame: the reverted
    commit is attributed as the origin of the previous behavior in the
    before-state analysis. We never infer a revert from the word "revert"
    alone - only the structured sha reference counts.
    """
    m = _REVERT_REF.search(f"{ci.subject}\n{ci.body}")
    return m.group(1) if m else None


def _root_file_meta(repo: Repository, sha: str) -> List[dict]:
    """File metadata for the root commit (no parent -> git show, not diff)."""
    raw = git_output(
        ["show", "--name-status", "-z", "--format=", "-M",
         "--no-ext-diff", "--no-textconv", sha],
        cwd=repo.root,
    )
    return _parse_name_status(raw)


def _root_raw_diff(repo: Repository, sha: str, pathspec: List[str]) -> str:
    """Unified diff text for one file of the root commit."""
    args = ["show", "--format=", "-M", "--no-ext-diff", "--no-textconv",
            sha, "--", *pathspec]
    return git_output(args, cwd=repo.root)


def _build_after(repo: Repository, sha: str, path: str,
                 memo: AnalysisMemo = None,
                 max_count: int = 30) -> dict:
    """Bounded scan of commits that touched `path` AFTER `sha`.

    Returns a dict (empty when there is no later history, e.g. the target
    is HEAD). Each later commit is classified (revert / fix) with the SAME
    message classifier the evidence engine uses, so "after" facts speak
    the same vocabulary. This is intentionally separate from the
    before-state evidence - later history must never retroactively alter
    the confidence of "what introduced the previous behavior".

    Phase 2E: later commits are ALSO classified into structured regression
    findings, with the analyzed commit itself as the reference point: a
    later commit that explicitly reverts THIS commit is an EXPLICIT_REVERT
    (the analyzed change was reversed); a later fix-language commit with
    overlap becomes LIKELY/POSSIBLE_REGRESSION_FIX. `memo` shares the
    commit/stats caches so this costs no extra git calls beyond the scan
    itself.
    """
    if memo is None:
        from .analyzer import AnalysisMemo
        memo = AnalysisMemo()
    commits = later_commits_after(repo, sha, path, max_count=max_count)
    if not commits:
        return {}
    for c in commits:
        memo.commit_map.setdefault(c.sha, c)
    later: List[dict] = []
    reverts = fixes = 0
    for c in commits:
        kinds = _classify_commit_message(c.subject, c.body)
        later.append({
            "sha": c.sha,
            "short": c.sha[:8],
            "date": c.author_date,
            "subject": c.subject,
            "kinds": kinds,
        })
        if "revert" in kinds:
            reverts += 1
        elif "fix" in kinds:
            fixes += 1

    # Regression classification (Phase 2E): the analyzed commit is the
    # reference; the after-commits are the corrective candidates.
    regressions: List[dict] = []
    try:
        from .models import Target as _T
        from .regression import detect_regressions
        stats = memo.file_stats(repo, path, revision="HEAD")
        findings = detect_regressions(
            repo, memo, _T(file=path, start_line=1, end_line=1),
            introducing=[sha],
            later=[c.sha for c in commits],
            stats=stats,
        )
        regressions = [f.to_dict() for f in findings]
    except Exception:
        regressions = []

    summary = (f"{len(later)} later commit(s) touched this file "
               f"after this commit")
    extra = []
    if reverts:
        extra.append(f"{reverts} revert(s)")
    if fixes:
        extra.append(f"{fixes} fix/regression-related")
    if regressions:
        extra.append(f"{len(regressions)} regression finding(s)")
    if extra:
        summary += f" ({', '.join(extra)})"
    return {
        "later_commits": later,
        "count": len(later),
        "reverts": reverts,
        "fixes": fixes,
        "regressions": regressions,
        "summary": summary,
    }


def _file_text_line_count(repo: Repository, revision: str, path: str,
                          max_bytes: int = 2 * 1024 * 1024) -> Optional[int]:
    """Line count of `path` at `revision`, or None if unavailable/too big.

    Used to pick the whole-file analysis range for pure renames. The byte
    size is checked FIRST (one cheap git call) so an enormous or binary
    blob is never streamed just to count lines.
    """
    size = try_git_output(["cat-file", "-s", f"{revision}:{path}"],
                          cwd=repo.root)
    if size is None:
        return None
    try:
        n = int(size.strip())
    except ValueError:
        return None
    if n > max_bytes:
        return None
    raw = try_git_output(["show", f"{revision}:{path}"], cwd=repo.root)
    if raw is None:
        return None
    return len(raw.splitlines())


def _new_file_group(repo: Repository, path: str, h: dict, changes: list,
                    added: int, deleted: int, sha: str,
                    tests_added: List[str]) -> DiffGroup:
    """A group for a file added by the commit: no base version, honest.

    The commit itself and the tests introduced with it are reported as
    FACTS (direct, observable), while the confidence stays INSUFFICIENT -
    there is no previous implementation whose history could be analyzed.
    """
    facts: List[dict] = []
    if tests_added:
        facts.append({
            "kind": "same_commit_test",
            "commit": sha,
            "text": f"commit also added test file(s): {', '.join(tests_added)}",
        })
    return DiffGroup(
        ranges=[{"old": None,
                 "new": {"start": h["new_start"],
                         "end": h["new_start"] + h["new_count"] - 1}}],
        changes=[c.to_dict() for c in changes],
        added_lines=added, deleted_lines=deleted,
        new_file=True,
        analysis=AnalysisResult(
            target=Target(file=path, start_line=1, end_line=1),
            mode="commit", repository=repo.to_dict(),
            confidence=_INSUFFICIENT(
                "new file - no base version, no historical evidence"),
            facts=facts,
            warnings=["new file: no historical evidence available"]).to_dict(),
    )


def analyze_commit(repo: Repository, rev: str,
                   memo: AnalysisMemo = None) -> CommitResult:
    """Analyze the historical context of one commit (see module docstring)."""
    if memo is None:
        memo = AnalysisMemo()
    ci = resolve_commit(repo, rev)

    parents = ci.parents
    is_root = not parents
    is_merge = len(parents) > 1
    baseline = parents[0] if parents else None

    warnings: List[str] = list(repo.warnings)
    if repo.shallow:
        warnings.append(
            "LIMITED HISTORY: this repository appears to be a shallow clone; "
            "the original introduction may not be available locally."
        )
    if is_root:
        warnings.append(
            "root commit: no previous revision exists for historical "
            "comparison"
        )
    if is_merge:
        warnings.append(
            "merge commit: first parent used as the baseline; full merge "
            "interpretation is a documented limitation"
        )

    result = CommitResult(
        sha=ci.sha,
        commit={
            "sha": ci.sha,
            "short": ci.sha[:8],
            "parents": parents,
            "author": ci.author,
            "date": ci.author_date,
            "subject": ci.subject,
            "body": ci.body,
            "is_merge": is_merge,
            "is_root": is_root,
            "revert_of": _revert_ref(ci),
        },
        parent=baseline,
        warnings=warnings,
    )

    try:
        if is_root:
            file_meta = _root_file_meta(repo, ci.sha)
        else:
            file_meta = collect_changed_files(repo, revs=[baseline, ci.sha])
    except GitError as e:
        warnings.append(f"could not read the commit diff: {e}")
        return result

    tests_added = sorted(m["path"] for m in file_meta
                         if _is_test_path(m["path"]))
    change_map = {m["path"]: m["status"] for m in file_meta}

    # --- Movement (Phase 2D): which of this commit's changes are MOVES?
    # Symbol-level continuity between baseline and commit, restricted to
    # the changed paths (a move's source and destination are both in the
    # change by definition, so the scan is proportional to the change
    # size). A confirmed move is classified, never re-reported as an
    # introduction: added ranges belonging to a moved symbol are analyzed
    # against the SOURCE at the baseline instead of "no previous version".
    rename_map = {m["path"]: m["old_path"] for m in file_meta
                  if m["status"] in ("R", "C") and m["old_path"]}
    boundary_mv: Dict[str, List[dict]] = {}
    if baseline is not None and not is_merge:
        before_paths = sorted({m.get("old_path") or m["path"]
                               for m in file_meta
                               if m["status"] in ("A", "M", "R", "C", "D")})
        after_paths = sorted({m["path"] for m in file_meta
                              if m["status"] in ("A", "M", "R", "C")})
        if before_paths and after_paths:
            try:
                before = memo.py_sources_limited(repo, baseline, before_paths)
                after = memo.py_sources_limited(repo, ci.sha, after_paths)
                boundary_mv = boundary_movements(
                    repo, memo, before, after, rename_map, revision=baseline)
            except GitError:
                boundary_mv = {}

    for meta in file_meta:
        status = meta["status"]
        path = meta["path"]
        old_path = meta["old_path"]

        if status not in _ANALYZABLE:
            warnings.append(f"unsupported diff status {status!r} for {path}")
            continue

        try:
            if is_root:
                raw = _root_raw_diff(repo, ci.sha, [path])
            else:
                raw = _raw_diff_for_file(repo, False, status, path, old_path,
                                         revs=[baseline, ci.sha])
        except GitError as e:
            warnings.append(f"could not read diff for {path}: {e}")
            continue
        hunks = _parse_hunks(raw)

        change = CommitChange(path=path, status=status, old_path=old_path)
        change.after = _build_after(repo, ci.sha, path, memo=memo)

        if not hunks:
            if status == "R" and baseline is not None:
                # Pure rename (no content change): the spec wants the
                # history of the MOVED code, so analyze the whole old file
                # against the baseline. Binary/oversized renames are
                # guarded by the line-count probe and fall through.
                n = _file_text_line_count(repo, baseline, old_path or path)
                if n:
                    try:
                        aresult = _analyze_region(repo, memo, path, old_path,
                                                  1, n, revision=baseline,
                                                  mode="commit",
                                                  change_map=change_map)
                    except GitError as e:
                        warnings.append(f"could not analyze {path}: {e}")
                        aresult = None
                    if aresult is not None:
                        change.groups.append(DiffGroup(
                            ranges=[{"old": {"start": 1, "end": n},
                                     "new": {"start": 1, "end": n}}],
                            changes=[], added_lines=0, deleted_lines=0,
                            analysis=aresult.to_dict(),
                        ))
                        result.changes.append(change)
                        continue
            # Binary file, or an unanalyzable rename.
            change.groups.append(DiffGroup(
                ranges=[], changes=[], added_lines=0, deleted_lines=0,
                analysis=AnalysisResult(
                    target=Target(file=path, start_line=1, end_line=1),
                    mode="commit",
                    repository=repo.to_dict(),
                    confidence=_INSUFFICIENT()).to_dict(),
            ))
            warnings.append(f"{path}: binary or no textual changes")
            result.changes.append(change)
            continue

        old_map, new_map = _hunk_bodies(raw)
        # New-file detection is a property of the FILE, not each hunk.
        is_new = status == "A" and (baseline is None
                                    or not file_exists_at(repo, baseline, path))

        groups: List[DiffGroup] = []
        file_mvs = boundary_mv.get(path, [])
        for h in hunks:
            changes, added, deleted = _classify_changes(
                h["old_changed"], h["new_changed"], old_map, new_map,
                h["old_start"], h["new_start"])
            old_changed = h["old_changed"]

            # Moved symbol in this hunk's NEW range: analyze the SOURCE
            # at the baseline instead of reporting "no previous version".
            # The mover is never the introduction (Phase 2D core rule).
            # Moved-symbol handling applies to ADDED ranges only (no old
            # side at the destination): a hunk with genuine old-side
            # changes keeps the normal modification/deletion analysis.
            mv = None
            if not old_changed:
                mv = intersecting_movement(
                    file_mvs, h["new_start"],
                    h["new_start"] + h["new_count"] - 1)
                if mv is not None:
                    m_group = moved_symbol_group(
                        repo, memo, path, mv, h, changes, ci.sha, baseline,
                        mode="commit", change_map=change_map)
                    if m_group is not None:
                        groups.append(m_group)
                        continue

            if is_new:
                groups.append(_new_file_group(repo, path, h, changes, added,
                                              deleted, ci.sha, tests_added))
                continue

            # Choose the region to analyze on the OLD side (the previous
            # behavior being modified or deleted by this commit).
            if old_changed:
                old_start = min(old_changed)
                old_end = max(old_changed)
            else:
                old_start = h["old_start"]
                old_end = h["old_start"] + h["old_count"] - 1
                if h["old_count"] == 0:
                    groups.append(DiffGroup(
                        ranges=[{"old": None,
                                 "new": {"start": h["new_start"],
                                         "end": h["new_start"] + h["new_count"] - 1}}],
                        changes=[c.to_dict() for c in changes],
                        added_lines=added, deleted_lines=deleted,
                        analysis=AnalysisResult(
                            target=Target(file=path, start_line=1, end_line=1),
                            mode="commit", repository=repo.to_dict(),
                            confidence=_INSUFFICIENT(
                                "added lines have no previous version to analyze"),
                            warnings=["added lines: no historical evidence; "
                                      "the surrounding context was not part "
                                      "of this hunk"]).to_dict(),
                    ))
                    continue

            try:
                aresult = _analyze_region(repo, memo, path, old_path,
                                          old_start, old_end,
                                          revision=baseline, mode="commit",
                                          change_map=change_map)
            except GitError as e:
                warnings.append(f"could not analyze {path}:{old_start}-"
                                f"{old_end}: {e}")
                continue

            groups.append(DiffGroup(
                ranges=[{"old": {"start": old_start, "end": old_end},
                         "new": {"start": h["new_start"],
                                 "end": h["new_start"] + h["new_count"] - 1}}],
                changes=[c.to_dict() for c in changes],
                added_lines=added, deleted_lines=deleted,
                analysis=aresult.to_dict(),
            ))

        # Merge hunks with identical evidence (same noise control as diff).
        merged: List[DiffGroup] = []
        for g in groups:
            sig = _analysis_signature(g)
            for existing in merged:
                if _analysis_signature(existing) == sig:
                    existing.ranges.extend(g.ranges)
                    existing.changes.extend(g.changes)
                    existing.added_lines += g.added_lines
                    existing.deleted_lines += g.deleted_lines
                    break
            else:
                merged.append(g)

        change.groups = merged

        # Per-change movement (Phase 2D): strongest signal first - a
        # symbol-level move is more specific than the file-level rename.
        if file_mvs:
            change.movement = public_movement(
                group_movement(path, file_mvs[0], ci.sha))
        elif status == "R" and old_path:
            mv = rename_movement(old_path, path, _analysis_origin(change))
            mv["moved_by"] = ci.sha
            change.movement = mv

        # Phase 2E: if the analyzed commit ITSELF is a revert, surface the
        # relationship per change (the reverted commit touched this file).
        _attach_self_revert(repo, memo, ci, change, path, old_path)
        result.changes.append(change)

    return result


def _analysis_origin(change: CommitChange) -> Optional[str]:
    """The introducing commit of the analyzed code, from the first blame
    fact of the change's groups (used for pure-rename origin)."""
    for g in change.groups:
        for f in g.analysis.get("facts", []):
            if f.get("kind") == "blame":
                return f.get("commit")
    return None


def _attach_self_revert(repo: Repository, memo, ci, change: CommitChange,
                        path: str, old_path: Optional[str]) -> None:
    """Phase 2E: classify a revert commit's relationship to one change.

    When the analyzed commit is itself a revert (structured trailer), the
    reverted commit is the historical reference point: the current change
    RESTORES the behavior the reverted commit had removed. Relationship is
    DIRECT_RANGE_OVERLAP when the before-state analysis blames the
    reverted commit as the origin of the previous lines; FILE_OVERLAP when
    it merely touched this file. Never claims the reverted commit "caused
    a bug" - only that it was explicitly reverted.
    """
    try:
        from .history import commit_files as _cf
        revert_of = _revert_ref(ci)
        if not revert_of:
            return
        rfiles = _cf(repo, revert_of)
        if path not in rfiles and not (old_path and old_path in rfiles):
            return  # reverted commit unrelated to this change's file
        origin = _analysis_origin(change)
        direct = False
        if origin is not None:
            # The trailer may cite an abbreviated sha; match by prefix.
            direct = (origin == revert_of
                      or origin.startswith(revert_of)
                      or revert_of.startswith(origin[:7]))
        change.regressions.append({
            "type": "EXPLICIT_REVERT",
            "confidence": "HIGH" if direct else "MEDIUM",
            "relationship": "DIRECT_RANGE_OVERLAP" if direct
            else "FILE_OVERLAP",
            "original_commit": revert_of,
            "fix_commit": ci.sha,
            "reverted_commit": revert_of,
            "target_path": path,
            "target_symbol": None,
            "signals": ["git_revert_relationship",
                         "reverted_file_overlap"]
            + (["reverted_commit_is_origin"] if direct else []),
            "explanation": (
                f"this commit explicitly reverts {revert_of[:8]}, "
                f"which changed {path}" + (
                    "; the reverted commit is blamed as the origin of "
                    "the previous behavior" if direct else "")),
        })
    except Exception:
        pass  # never let revert bookkeeping crash the analysis
