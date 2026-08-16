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
                 max_count: int = 30) -> dict:
    """Bounded scan of commits that touched `path` AFTER `sha`.

    Returns a dict (empty when there is no later history, e.g. the target
    is HEAD). Each later commit is classified (revert / fix) with the SAME
    message classifier the evidence engine uses, so "after" facts speak
    the same vocabulary. This is intentionally separate from the
    before-state evidence - later history must never retroactively alter
    the confidence of "what introduced the previous behavior".
    """
    commits = later_commits_after(repo, sha, path, max_count=max_count)
    if not commits:
        return {}
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
    summary = (f"{len(later)} later commit(s) touched this file "
               f"after this commit")
    extra = []
    if reverts:
        extra.append(f"{reverts} revert(s)")
    if fixes:
        extra.append(f"{fixes} fix/regression-related")
    if extra:
        summary += f" ({', '.join(extra)})"
    return {
        "later_commits": later,
        "count": len(later),
        "reverts": reverts,
        "fixes": fixes,
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
        change.after = _build_after(repo, ci.sha, path)

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
                                                  mode="commit")
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
        for h in hunks:
            changes, added, deleted = _classify_changes(
                h["old_changed"], h["new_changed"], old_map, new_map,
                h["old_start"], h["new_start"])
            old_changed = h["old_changed"]

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
                                          revision=baseline, mode="commit")
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
        result.changes.append(change)

    return result
