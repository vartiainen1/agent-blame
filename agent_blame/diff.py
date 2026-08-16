"""Diff mode (--diff): historical context for the developer's current changes.

Pipeline (spec Phase 2A):

    git diff (or --cached)
      -> name-status -z  (NUL-safe file metadata: status, paths, renames)
      -> per-file unified diff (hunks, old/new line numbers, changed lines)
      -> group hunks by historical-evidence signature
      -> existing analysis pipeline per group (blame -> graph -> evidence
         -> confidence -> risk), reusing one shared AnalysisMemo so git
         facts are fetched once per run, not once per hunk

Noise control: a large diff does NOT produce one explanation per changed
line. Hunks are the natural unit; hunks whose analysis results are
identical (same introducing commits, same evidence, same confidence/risk)
are merged into one group with all their ranges - \"these N changed lines
share the same historical context\".

Honesty rules (same as the rest of the tool):
  - added lines have no history: never fabricated - the surrounding
    context (nearest old-side lines) is analyzed instead and the
    limitation is stated explicitly
  - deleted lines are analyzed against the previous revision (HEAD)
  - a brand-new file has no base version: reported as new, no analysis
  - binary files: reported, not parsed

Security: all diff invocations use --no-ext-diff --no-textconv so
repository-controlled attributes/config (external diff drivers, textconv
filters) can never execute code. Paths are passed as argv, never shell.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .analyzer import AnalysisMemo, analyze
from .git import GitError, git_output
from .history import file_exists_at_head
from .models import (AnalysisResult, Confidence, DiffChange, DiffFile,
                     DiffGroup, DiffResult, Target)
from .repository import Repository

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_NAME_STATUS_RE = re.compile(r"^([AMD RTCUB])(\d*)")

# Statuses we fully analyze.
_ANALYZABLE = ("A", "D", "M", "R", "C")


def _scope_args(staged: bool) -> List[str]:
    return ["--cached"] if staged else []


def _parse_name_status(raw: str) -> List[dict]:
    """Parse `git diff --name-status -z` output into {status, path, old_path}.

    -z output is NUL-separated (never quoted): status token, path, and for
    renames/copies the old path. Works identically for worktree/staged
    diffs and commit diffs (`git diff <parent> <sha>`) - the format is the
    same.
    """
    files: List[dict] = []
    tokens = raw.split("\x00")
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok:
            i += 1
            continue
        m = _NAME_STATUS_RE.match(tok)
        if not m:
            i += 1
            continue
        status = m.group(1)
        path = tokens[i + 1] if i + 1 < len(tokens) else ""
        old_path = None
        if status in ("R", "C"):
            old_path = path
            path = tokens[i + 2] if i + 2 < len(tokens) else ""
            i += 3
        else:
            i += 2
        if path:
            files.append({"status": status, "path": path, "old_path": old_path})
    return files


def collect_changed_files(repo: Repository, staged: bool = False,
                          revs: Optional[List[str]] = None) -> List[dict]:
    """NUL-safe file metadata: status + paths from `git diff --name-status -z`.

    Returns a list of dicts: {status, path, old_path}. Renames (R/C) carry
    the previous path so the two-path diff form can be used for hunks.
    Untracked files are listed separately by the caller (git diff ignores
    them entirely).

    `revs` switches the source from the working tree / index to a commit
    pair `[parent, sha]` (used by commit mode); when given it replaces the
    --cached scope selection entirely.
    """
    scope = _scope_args(staged) if revs is None else list(revs)
    args = ["diff", *scope, "-M", "--no-ext-diff",
            "--no-textconv", "--no-color", "--name-status", "-z"]
    raw = git_output(args, cwd=repo.root)
    return _parse_name_status(raw)


def list_untracked(repo: Repository) -> List[str]:
    """Untracked files (git diff never shows them; report honestly)."""
    try:
        raw = git_output(["ls-files", "--others", "--exclude-standard", "-z"],
                         cwd=repo.root)
    except GitError:
        return []
    return [p for p in raw.split("\x00") if p]


def _raw_diff_for_file(repo: Repository, staged: bool, status: str, path: str,
                       old_path: Optional[str],
                       revs: Optional[List[str]] = None) -> str:
    """The unified diff text for one file (fetched once, parsed twice).

    For renames both paths are passed so git emits the rename form with
    hunks; for everything else the single path is enough. `staged` selects
    the same scope as the top-level name-status call; `revs` (a commit
    pair) replaces it for commit mode, matching the top-level name-status
    call exactly.
    """
    scope = _scope_args(staged) if revs is None else list(revs)
    pathspec = [old_path, path] if status in ("R", "C") else [path]
    args = ["diff", *scope, "-M", "--no-ext-diff",
            "--no-textconv", "--no-color", "--", *pathspec]
    return git_output(args, cwd=repo.root)


def _parse_hunks(raw: str) -> List[dict]:
    """Parse unified diff text into hunk dicts.

    Each hunk: {old_start, old_count, new_start, new_count, old_changed,
    new_changed} where the *_changed lists are the CHANGED line numbers on
    each side (context lines excluded). Returns [] for binary files (no
    hunks - git emits "Binary files ... differ" with no @@ headers).
    """
    hunks: List[dict] = []
    lines = raw.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i]
        m = _HUNK_RE.match(line)
        if not m:
            i += 1
            continue
        old_start = int(m.group(1))
        old_count = int(m.group(2)) if m.group(2) else 1
        new_start = int(m.group(3))
        new_count = int(m.group(4)) if m.group(4) else 1

        old_cur = old_start
        new_cur = new_start
        old_changed: List[int] = []
        new_changed: List[int] = []

        i += 1
        while i < len(lines) and not _HUNK_RE.match(lines[i]) \
                and not lines[i].startswith("diff --git "):
            ln = lines[i]
            if ln.startswith("+") and not ln.startswith("+++"):
                new_changed.append(new_cur)
                new_cur += 1
            elif ln.startswith("-") and not ln.startswith("---"):
                old_changed.append(old_cur)
                old_cur += 1
            elif ln.startswith(" "):
                old_cur += 1
                new_cur += 1
            # "\ No newline at end of file" lines carry no counter change.
            i += 1

        hunks.append({
            "old_start": old_start, "old_count": old_count,
            "new_start": new_start, "new_count": new_count,
            "old_changed": old_changed, "new_changed": new_changed,
        })
    return hunks


def _classify_changes(old_changed: List[int], new_changed: List[int],
                      old_body: Dict[int, str], new_body: Dict[int, str],
                      old_start: int, new_start: int) -> Tuple[List[DiffChange], int, int]:
    """Pair old/new changed lines into add/del/mod DiffChange items.

    Within a hunk, a removed old line followed by an added new line is a
    modification (the line was replaced); an unmatched old line is a
    deletion; an unmatched new line is an addition. Counts are returned
    so the group can report how many lines were added/deleted.
    """
    changes: List[DiffChange] = []
    added = 0
    deleted = 0
    # Pair sequentially: the k-th old changed line pairs with the k-th new
    # changed line when both exist (git's own -/+ pairing inside a hunk).
    n = max(len(old_changed), len(new_changed))
    for k in range(n):
        has_old = k < len(old_changed)
        has_new = k < len(new_changed)
        if has_old and has_new:
            changes.append(DiffChange(
                side="old", line=old_changed[k], type="mod",
                text=old_body.get(old_changed[k], "")))
            changes.append(DiffChange(
                side="new", line=new_changed[k], type="mod",
                text=new_body.get(new_changed[k], "")))
            added += 1
            deleted += 1
        elif has_old:
            changes.append(DiffChange(
                side="old", line=old_changed[k], type="del",
                text=old_body.get(old_changed[k], "")))
            deleted += 1
        else:
            changes.append(DiffChange(
                side="new", line=new_changed[k], type="add",
                text=new_body.get(new_changed[k], "")))
            added += 1
    return changes, added, deleted


def _hunk_bodies(raw: str) -> Dict[str, Dict[int, str]]:
    """Split hunk body lines into old-side and new-side content maps.

    Returns (old_lines, new_lines): line number -> content, built by
    walking the +/- lines of every hunk with running counters. Used to
    attach the actual changed text to DiffChange items.
    """
    old_map: Dict[int, str] = {}
    new_map: Dict[int, str] = {}
    old_cur = new_cur = None
    for line in raw.splitlines():
        m = _HUNK_RE.match(line)
        if m:
            old_cur = int(m.group(1))
            new_cur = int(m.group(3))
            continue
        if old_cur is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            new_map[new_cur] = line[1:]
            new_cur += 1
        elif line.startswith("-") and not line.startswith("---"):
            old_map[old_cur] = line[1:]
            old_cur += 1
        elif line.startswith(" "):
            old_cur += 1
            new_cur += 1
    return old_map, new_map


def _analyze_region(repo: Repository, memo: AnalysisMemo,
                    path: str, old_path: Optional[str],
                    old_start: int, old_end: int,
                    revision: str = "HEAD", mode: str = "diff",
                    change_map: Optional[dict] = None) -> AnalysisResult:
    """Run the existing pipeline on one changed region.

    The target is the OLD side (previous revision) of the change: blame
    against `revision` gives the introducing commit of the behavior being
    modified or deleted. `old_path` is the path the file had at that
    revision when it was renamed (blame must run against the old name).
    Diff mode blames HEAD; commit mode passes the target commit's parent.
    `change_map` ({path: status}) lets caller analysis mark callers that
    this change deletes/modifies.
    """
    head_path = old_path or path
    target = Target(file=head_path, start_line=old_start, end_line=old_end)
    return analyze(repo, target, mode=mode, memo=memo, revision=revision,
                   change_map=change_map)


def analyze_diff(repo: Repository, staged: bool = False,
                 memo: AnalysisMemo = None) -> DiffResult:
    """Analyze the working-tree (git diff) or staged (git diff --cached) changes."""
    if memo is None:
        memo = AnalysisMemo()

    scope = "staged" if staged else "worktree"
    warnings: List[str] = list(repo.warnings)
    if repo.shallow:
        warnings.append(
            "LIMITED HISTORY: this repository appears to be a shallow clone; "
            "the original introduction may not be available locally."
        )
    result = DiffResult(scope=scope, repository=repo.to_dict(),
                        warnings=warnings)

    try:
        file_meta = collect_changed_files(repo, staged=staged)
    except GitError as e:
        warnings.append(f"could not read the diff: {str(e)}")
        return result

    # Untracked files are invisible to git diff - report them as new
    # files with no historical evidence (never fabricated).
    if not staged:
        untracked = list_untracked(repo)
        for u in sorted(untracked):
            result.files.append(DiffFile(
                path=u, status="?", old_path=None,
                groups=[DiffGroup(
                    ranges=[{"old": None, "new": None}],
                    changes=[], added_lines=0, deleted_lines=0,
                    new_file=True,
                    analysis=AnalysisResult(
                        target=Target(file=u, start_line=1, end_line=1),
                        mode="diff", repository=repo.to_dict(),
                        confidence=_INSUFFICIENT(
                            "untracked file - no base version, no historical "
                            "evidence"),
                        warnings=["untracked file: stage it to include it in "
                                  "a future diff"]).to_dict(),
                )],
            ))

    change_map = {m["path"]: m["status"] for m in file_meta}

    for meta in file_meta:
        status = meta["status"]
        path = meta["path"]
        old_path = meta["old_path"]

        if status not in _ANALYZABLE:
            warnings.append(f"unsupported diff status {status!r} for {path}")
            continue

        try:
            raw = _raw_diff_for_file(repo, staged, status, path, old_path)
        except GitError as e:
            warnings.append(f"could not read diff for {path}: {str(e)}")
            continue
        hunks = _parse_hunks(raw)

        diff_file = DiffFile(path=path, status=status, old_path=old_path)

        if not hunks:
            # Binary file, or a pure rename with no content change.
            exists = file_exists_at_head(repo, old_path or path)
            if status == "D" and exists:
                # Deleted binary file: no hunks to parse, nothing to show.
                diff_file.groups.append(DiffGroup(
                    ranges=[], changes=[], added_lines=0, deleted_lines=0,
                    analysis=AnalysisResult(
                        target=Target(file=old_path or path, start_line=1, end_line=1),
                        mode="diff",
                        repository=repo.to_dict(),
                        confidence=_INSUFFICIENT()).to_dict(),
                ))
                warnings.append(f"{path}: binary or no textual changes")
            elif status == "R":
                diff_file.groups.append(DiffGroup(
                    ranges=[], changes=[], added_lines=0, deleted_lines=0,
                    analysis=AnalysisResult(
                        target=Target(file=path, start_line=1, end_line=1),
                        mode="diff",
                        repository=repo.to_dict(),
                        confidence=_INSUFFICIENT()).to_dict(),
                ))
            else:
                warnings.append(f"{path}: binary file - content not analyzed")
            result.files.append(diff_file)
            continue

        old_map, new_map = _hunk_bodies(raw)
        # New-file detection is a property of the FILE, not each hunk.
        is_new = (status == "A" and not file_exists_at_head(repo, path))

        # --- Build one candidate group per hunk -------------------------
        groups: List[DiffGroup] = []
        for h in hunks:
            changes, added, deleted = _classify_changes(
                h["old_changed"], h["new_changed"], old_map, new_map,
                h["old_start"], h["new_start"])
            old_changed = h["old_changed"]
            if is_new:
                groups.append(DiffGroup(
                    ranges=[{"old": None, "new": {"start": h["new_start"],
                                                  "end": h["new_start"] + h["new_count"] - 1}}],
                    changes=[c.to_dict() for c in changes],
                    added_lines=added, deleted_lines=deleted,
                    new_file=True,
                    analysis=AnalysisResult(
                        target=Target(file=path, start_line=1, end_line=1),
                        mode="diff", repository=repo.to_dict(),
                        confidence=_INSUFFICIENT(
                            "new file - no base version, no historical evidence"),
                        warnings=["new file: no historical evidence available"]).to_dict(),
                ))
                continue

            # Choose the region to analyze:
            #  - changed old lines -> analyze them (deleted/modified code)
            #  - no old lines (pure addition) -> analyze the surrounding
            #    context: the old-side range of this hunk (context lines
            #    still exist at HEAD)
            if old_changed:
                old_start = min(old_changed)
                old_end = max(old_changed)
            else:
                # Pure addition: the hunk's old count covers context lines.
                old_start = h["old_start"]
                old_end = h["old_start"] + h["old_count"] - 1
                if h["old_count"] == 0:
                    # No old side at all (e.g. addition before any line).
                    groups.append(DiffGroup(
                        ranges=[{"old": None,
                                 "new": {"start": h["new_start"],
                                         "end": h["new_start"] + h["new_count"] - 1}}],
                        changes=[c.to_dict() for c in changes],
                        added_lines=added, deleted_lines=deleted,
                        new_file=False,
                        analysis=AnalysisResult(
                            target=Target(file=path, start_line=1, end_line=1),
                            mode="diff", repository=repo.to_dict(),
                            confidence=_INSUFFICIENT(
                                "added lines have no previous version to analyze"),
                            warnings=["added lines: no historical evidence; "
                                      "the surrounding context was not part of "
                                      "this hunk"]).to_dict(),
                    ))
                    continue

            try:
                aresult = _analyze_region(repo, memo, path, old_path,
                                          old_start, old_end,
                                          change_map=change_map)
            except GitError as e:
                warnings.append(f"could not analyze {path}:{old_start}-{old_end}: {str(e)}")
                continue

            groups.append(DiffGroup(
                ranges=[{"old": {"start": old_start, "end": old_end},
                         "new": {"start": h["new_start"],
                                 "end": h["new_start"] + h["new_count"] - 1}}],
                changes=[c.to_dict() for c in changes],
                added_lines=added, deleted_lines=deleted,
                analysis=aresult.to_dict(),
            ))

        # --- Merge hunks with identical evidence (noise control) --------
        merged: List[DiffGroup] = []
        for g in groups:
            sig = _analysis_signature(g)
            for existing in merged:
                if _analysis_signature(existing) == sig:
                    # Same evidence: merge ranges + changes into this group.
                    existing.ranges.extend(g.ranges)
                    existing.changes.extend(g.changes)
                    existing.added_lines += g.added_lines
                    existing.deleted_lines += g.deleted_lines
                    break
            else:
                merged.append(g)

        diff_file.groups = merged
        result.files.append(diff_file)

    return result


def _analysis_signature(g: DiffGroup) -> Tuple:
    """Signature of a group's analysis dict, for merging identical hunks."""
    a = g.analysis
    introducers = tuple(sorted({f.get("commit", "") for f in a.get("facts", [])
                                if f.get("kind") == "blame"}))
    evidence = tuple(sorted((e["kind"], e.get("commit") or "")
                            for e in a.get("evidence", [])))
    counter = tuple(sorted((e["kind"], e.get("commit") or "")
                           for e in a.get("counter_evidence", [])))
    return (g.new_file, introducers, evidence, counter,
            a.get("confidence", {}).get("level"),
            a.get("risk", {}).get("level"))


def _INSUFFICIENT(reason: str = "no historical evidence") -> Confidence:
    return Confidence("INSUFFICIENT", 0.0, reasons=[reason])
