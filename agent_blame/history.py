"""History extraction.

Turns the repository's raw git data into structured facts about a target:
- `git blame` per line (introducing commits)
- commit metadata (subject/body/author/date/files)
- commit diffs restricted to a file
- the commit list for a file, following renames where possible

Everything here is FACT extraction: direct, observable repository
information. Inference happens later, in evidence.py / confidence.py.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from .git import git_lines, try_git_output
from .models import BlameLine, CommitDiff, CommitInfo, Target
from .repository import Repository

_COMMIT_FORMAT = "%H%x01%an%x01%ae%x01%aI%x01%s%x01%b%x01%P"
_FIELDS = ["sha", "author", "author_email", "author_date", "subject", "body", "parents"]


def blame_target(repo: Repository, target: Target) -> List[BlameLine]:
    """Run `git blame` on the target line range, return per-line facts.

    Uses --line-porcelain (stable machine format) with -w so whitespace
    moves do not count as introductions. Returns [] when the file does not
    exist at HEAD (caller decides how to handle that).
    """
    file = target.file
    lines = git_lines(
        [
            "blame", "--line-porcelain", "-w",
            "-L", f"{target.start_line},{target.end_line}",
            "HEAD", "--", file,
        ],
        cwd=repo.root,
    )
    return _parse_porcelain_blame(lines)


def _parse_porcelain_blame(lines: List[str]) -> List[BlameLine]:
    """Parse `git blame --line-porcelain` output.

    Format per blamed line:
        <sha> <orig_line> <final_line> [<num_lines>]
        author <name>
        author-mail <email>
        author-time <unix ts>
        author-tz <tz>
        summary <subject>
        [other fields...]
        \t<content>

    We collect the fields we need; content lines start with a tab.
    """
    result: List[BlameLine] = []
    current: Dict[str, str] = {}
    current_line: Optional[int] = None

    for line in lines:
        if line.startswith("\t"):
            # content line: finalize the current entry
            if current_line is not None and current.get("sha"):
                result.append(BlameLine(
                    line_no=current_line,
                    commit=current["sha"],
                    summary=current.get("summary", ""),
                    author=current.get("author", ""),
                    author_time=current.get("author_date", ""),
                ))
            current = {}
            current_line = None
            continue

        if re.match(r"^[0-9a-f]{40,64} \d+ \d+", line):
            parts = line.split()
            current_line = int(parts[2])
            current = {"sha": parts[0]}
            continue

        key, _, value = line.partition(" ")
        if key in ("author", "summary"):
            current[key] = value
        elif key == "author-time":
            # Convert unix timestamp to ISO-8601 for stable, sortable dates.
            try:
                ts = int(value)
                current["author_date"] = _iso_from_epoch(ts)
            except ValueError:
                current["author_date"] = value

    # Flush any trailing entry (blame output should end with a content
    # line, but be defensive about boundary conditions - rule 7).
    if current_line is not None and current.get("sha"):
        already = any(b.line_no == current_line for b in result)
        if not already:
            result.append(BlameLine(
                line_no=current_line,
                commit=current["sha"],
                summary=current.get("summary", ""),
                author=current.get("author", ""),
                author_time=current.get("author_date", ""),
            ))
    return result


def _iso_from_epoch(ts: int) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def file_commits(repo: Repository, file: str,
                 follow: bool = True, max_count: int = 200) -> List[CommitInfo]:
    """List commits touching `file`, newest first, following renames.

    Returns up to `max_count` commits. On a shallow repo this returns only
    the history available locally - the caller is expected to detect and
    report that (LIMITED HISTORY).
    """
    args = ["log", f"-{max_count}"]
    if follow:
        args.append("--follow")
    args += ["--format=%H", "--", file]

    shas = git_lines(args, cwd=repo.root)
    out: List[CommitInfo] = []
    for sha in shas:
        sha = sha.strip()
        if not sha:
            continue
        info = commit_info(repo, sha)
        if info is not None:
            out.append(info)
    return out


def commit_info(repo: Repository, sha: str) -> Optional[CommitInfo]:
    """Fetch metadata for one commit, or None if it cannot be resolved."""
    raw = try_git_output(
        ["log", "-1", f"--format={_COMMIT_FORMAT}", sha], cwd=repo.root)
    if raw is None:
        return None
    fields = raw.split("\x01")
    if len(fields) < 7:
        return None
    d = dict(zip(_FIELDS, fields))
    files = commit_files(repo, sha)
    return CommitInfo(
        sha=d["sha"],
        subject=d["subject"],
        body=d["body"],
        author=d["author"],
        author_email=d["author_email"],
        author_date=d["author_date"],
        files_changed=files,
        is_merge=bool(d["parents"].strip().count(" ")),
    )


def commit_files(repo: Repository, sha: str) -> List[str]:
    """List files changed by a commit (name-status, -z for safe parsing)."""
    raw = try_git_output(
        ["show", "--name-status", "--format=", "-z", sha], cwd=repo.root)
    if raw is None:
        return []
    files: List[str] = []
    tokens = raw.split("\x00")
    # name-status -z emits: <status>\0<path>\0[<oldpath>\0 for R/C]
    i = 0
    while i < len(tokens):
        token = tokens[i].strip()
        if not token:
            i += 1
            continue
        status = token[0]
        if status in ("R", "C") and i + 2 < len(tokens):
            files.append(tokens[i + 2])
            i += 3
        else:
            if i + 1 < len(tokens):
                files.append(tokens[i + 1])
            i += 2
    return [f for f in files if f]


def commit_diff_for_file(repo: Repository, sha: str, file: str) -> Optional[CommitDiff]:
    """The diff of `sha` restricted to `file` (or None if untouched/unavailable).

    Uses the merge-diff form for merge commits (git show handles it), and
    counts added/removed lines from the unified diff for later use by
    regression/removal detection.
    """
    raw = try_git_output(["show", "--format=", sha, "--", file], cwd=repo.root)
    if raw is None:
        return None
    added = removed = 0
    for line in raw.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return CommitDiff(sha=sha, file=file, diff=raw,
                      added_lines=added, removed_lines=removed)


def file_exists_at_head(repo: Repository, file: str) -> bool:
    """True if `file` exists at HEAD."""
    return try_git_output(["cat-file", "-e", f"HEAD:{file}"], cwd=repo.root) is not None


def head_commit(repo: Repository) -> Optional[CommitInfo]:
    """Metadata for HEAD, or None on an unborn repository."""
    if not repo.head:
        return None
    return commit_info(repo, repo.head)


def current_file_lines(repo: Repository, file: str) -> Optional[List[str]]:
    """The current content of `file` at HEAD, or None if missing."""
    raw = try_git_output(["show", f"HEAD:{file}"], cwd=repo.root)
    if raw is None:
        return None
    return raw.splitlines()
