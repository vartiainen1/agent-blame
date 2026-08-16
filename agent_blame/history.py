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

from .git import GitError, git_lines, git_output, try_git_output
from .models import BlameLine, CommitDiff, CommitInfo, Target
from .repository import Repository

_COMMIT_FORMAT = "%H%x01%an%x01%ae%x01%aI%x01%s%x01%b%x01%P"
_FIELDS = ["sha", "author", "author_email", "author_date", "subject", "body", "parents"]

# Metadata is fetched in ONE `git log` call per file (N+1 avoidance): the
# format above plus %x00 as a record terminator. Field separation inside
# a record uses \x01, so git object content cannot break the parse; the
# record terminator is NUL, which cannot appear in git object content.
_COMMIT_FORMAT_NUL = _COMMIT_FORMAT + "%x00"


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

    Returns up to `max_count` commits, metadata batched into ONE `git log`
    call (N+1 avoidance: no per-commit subprocess). On a shallow repo this
    returns only the history available locally - the caller is expected to
    detect and report that (LIMITED HISTORY).
    """
    args = ["log", f"-{max_count}"]
    if follow:
        args.append("--follow")
    args += [f"--format={_COMMIT_FORMAT_NUL}", "--", file]

    raw = git_output(args, cwd=repo.root)
    out: List[CommitInfo] = []
    for record in raw.split("\x00"):
        record = record.strip()  # git appends \n after each %x00 terminator
        if not record:
            continue
        fields = record.split("\x01")
        if len(fields) < 7:
            continue
        d = dict(zip(_FIELDS, fields))
        out.append(CommitInfo(
            sha=d["sha"],
            subject=d["subject"],
            body=d["body"],
            author=d["author"],
            author_email=d["author_email"],
            author_date=d["author_date"],
            is_merge=bool(d["parents"].strip().count(" ")),
        ))
    return out


def commit_info(repo: Repository, sha: str) -> Optional[CommitInfo]:
    """Fetch metadata for one commit, or None if it cannot be resolved.

    Used for single-commit lookups (e.g. HEAD). Bulk listings go through
    file_commits, which batches the metadata into one git call.
    """
    raw = try_git_output(
        ["log", "-1", f"--format={_COMMIT_FORMAT}", sha], cwd=repo.root)
    if raw is None:
        return None
    fields = raw.split("\x01")
    if len(fields) < 7:
        return None
    d = dict(zip(_FIELDS, fields))
    return CommitInfo(
        sha=d["sha"],
        subject=d["subject"],
        body=d["body"],
        author=d["author"],
        author_email=d["author_email"],
        author_date=d["author_date"],
        is_merge=bool(d["parents"].strip().count(" ")),
    )


def commit_files(repo: Repository, sha: str) -> List[str]:
    """List files changed by a commit (name-status, -z for safe parsing).

    Called only for the FEW commits that need same-commit-file facts (the
    introducing commits), never for every commit in a file's history.
    """
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

    Kept for single-commit callers. Bulk counter-evidence goes through
    file_diff_stats (one git call per file instead of one per commit);
    the raw `diff` text here is never consumed by the analysis - only the
    added/removed counts are.
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


def file_diff_stats(repo: Repository, file: str) -> Dict[str, Tuple[int, int]]:
    """Per-commit added/removed counts for `file` in ONE git call.

    Uses `git log --numstat`: git already computes the counts we need for
    regression/removal counter-evidence, so we never fetch N individual
    diffs (the old N+1). Format: each commit is `sha\0` followed by one
    `added\tremoved\tpath` line per file in that commit's diff; a commit
    may contribute multiple lines (multi-file commits).

    Returns {sha: (added, removed)}. Note: counts can differ by ±1 from
    show-based counting on files whose line endings were normalized
    (git counts a missing trailing newline differently) - documented
    limitation, immaterial to the 0/5/ratio thresholds used here.
    """
    args = ["log", "--numstat", "--format=%H%x00", "--", file]
    try:
        raw = git_output(args, cwd=repo.root)
    except GitError:
        return {}
    out: Dict[str, Tuple[int, int]] = {}
    cur: Optional[str] = None
    for record in raw.split("\x00"):
        for line in record.split("\n"):
            line = line.strip()
            if not line:
                continue
            # git appends \n after each %x00 terminator, so a sha may carry
            # a leading newline, and multi-file commits append numstat
            # lines after the sha. Match on a clean 40-hex sha line.
            if len(line) == 40 and all(c in "0123456789abcdef" for c in line):
                cur = line
                out.setdefault(cur, (0, 0))
                continue
            parts = line.split("\t")
            if cur is not None and len(parts) >= 2 \
                    and parts[0].isdigit() and parts[1].isdigit():
                a, r = out[cur]
                out[cur] = (a + int(parts[0]), r + int(parts[1]))
    return out


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
