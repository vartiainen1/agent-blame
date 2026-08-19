"""Parsing of `file:line`, `file:start-end` and the Phase 6C target forms:
bare `file`, `file:function`, and a bare commit sha.

Windows note: the workspace runs on Windows where a path like
`C:\\repo\\src\\auth.py:142` contains a colon before the line number. We
split on the LAST colon (which separates the line spec from the path), so
drive letters and paths with colons keep working.

Form classification is PURE (no repository access): the CLI resolves the
forms against the repository (sha -> commit, function -> defining line,
bare file -> blame-able lines). `parse_target` keeps its original contract
(`file:line` only); the new forms are classified with `classify_target`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .models import Target

_LINE_SPEC = re.compile(r"^(\d+)(?:-(\d+))?$")

# A bare sha is 4-40 hex chars (git's accepted abbreviation range), with
# no path separator and no dot - so `deadbeef` is sha-shaped but
# `dead/beef` and `deadbeef.py` never are.
_SHA_RE = re.compile(r"^[0-9a-fA-F]{4,40}$")

# Function-name charset: Python identifiers plus dots for qualified names
# (Server.handle, outer.inner). ASCII only - matches the symbol matcher in
# symbols.py, which is the AST source of truth for resolution.
_FUNC_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


class TargetError(Exception):
    """Raised for malformed or invalid targets - a clean usage error."""


@dataclass(frozen=True)
class TargetSpec:
    """A raw target classified into one of the four supported forms.

    kind:
      "file_line"     -> <file>:<line> or <file>:<start>-<end>
      "file_function" -> <file>:<function-name> (qualified names allowed)
      "bare_file"     -> <file> with no line spec; the CLI resolves it to
                         the file's blame-able lines
      "sha"           -> a bare commit-ish sha; the CLI routes it to
                         COMMIT mode after verifying it resolves

    `path` holds the file part for the file forms, and the sha itself for
    kind="sha". `start_line`/`end_line` are filled only for "file_line".
    """

    kind: str
    path: str
    line_part: str = ""             # numeric line spec or function name
    start_line: int = 0
    end_line: int = 0


def is_sha_like(spec: str) -> bool:
    """A bare hex string of 4-40 chars (git's accepted abbrev range).

    Deliberately shape-only: whether it actually IS a commit is resolved
    against the repository by the caller, so a file that merely LOOKS like
    a sha is never hijacked (the sha check verifies before routing).
    """
    return bool(_SHA_RE.fullmatch(spec))


def classify_target(spec: str) -> TargetSpec:
    """Classify a raw target into its form, without touching the repo.

    Raises TargetError with a clean message on empty/garbage input. The
    last-colon split keeps Windows drive letters and colon-containing
    paths working exactly as before.
    """
    if not spec or not spec.strip():
        raise TargetError(
            "empty target; expected <file>:<line>, <file>:<function>, "
            "<file> or <sha>"
        )

    spec = spec.strip()

    if ":" not in spec:
        if is_sha_like(spec):
            return TargetSpec(kind="sha", path=spec)
        return TargetSpec(kind="bare_file", path=spec)

    path, _, line_part = spec.rpartition(":")
    path = path.strip()
    line_part = line_part.strip()

    if not path:
        raise TargetError(f"target {spec!r} has an empty file path")

    m = _LINE_SPEC.match(line_part)
    if m:
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        if start < 1:
            raise TargetError("line numbers are 1-based; got start=%d" % start)
        if end < start:
            raise TargetError(f"invalid range {start}-{end}: end before start")
        return TargetSpec(kind="file_line", path=path, line_part=line_part,
                          start_line=start, end_line=end)

    # A non-numeric line part is a function/method/class name; qualified
    # names (Server.handle) are allowed and resolved deterministically.
    if not _FUNC_RE.match(line_part):
        raise TargetError(
            f"bad target spec {line_part!r}; expected <line>, <start>-<end> "
            "or a function name"
        )
    return TargetSpec(kind="file_function", path=path, line_part=line_part)


def parse_target(spec: str) -> Target:
    """Parse `file:line` or `file:start-end` into a Target.

    Raises TargetError with a clean message on bad input (never a raw
    traceback). Contract unchanged: only the numeric forms parse here;
    the other forms are classified with `classify_target` (the CLI uses
    `classify_target` directly and resolves them against the repository).
    """
    cs = classify_target(spec)
    if cs.kind != "file_line":
        if cs.kind == "file_function":
            raise TargetError(
                f"bad line spec {cs.line_part!r}; expected <line> or "
                "<start>-<end>"
            )
        if cs.kind == "sha":
            raise TargetError(
                f"target {cs.path!r} looks like a commit sha; use "
                f"--commit {cs.path}"
            )
        raise TargetError(
            f"target {cs.path!r} needs a line number: add :LINE to ask why "
            f"that line exists, e.g. {cs.path!r}:1 (format: <file>:<line>, "
            f"e.g. src/auth/session.py:142)"
        )
    return Target(file=cs.path, start_line=cs.start_line, end_line=cs.end_line)
