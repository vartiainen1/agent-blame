"""Parsing of `file:line` and `file:start-end` targets.

Windows note: the workspace runs on Windows where a path like
`C:\\repo\\src\\auth.py:142` contains a colon before the line number. We
split on the LAST colon (which separates the line spec from the path), so
drive letters and paths with colons keep working.
"""

from __future__ import annotations

import re

from .models import Target

_LINE_SPEC = re.compile(r"^(\d+)(?:-(\d+))?$")


class TargetError(Exception):
    """Raised for malformed or invalid targets - a clean usage error."""


def parse_target(spec: str) -> Target:
    """Parse `file:line` or `file:start-end` into a Target.

    Raises TargetError with a clean message on bad input (never a raw
    traceback).
    """
    if not spec or not spec.strip():
        raise TargetError("empty target; expected <file>:<line> or <file>:<start>-<end>")

    spec = spec.strip()

    # Split on the last colon: everything before is the path, after is the
    # line spec. This keeps Windows drive letters (C:\\...) working.
    if ":" not in spec:
        raise TargetError(
            f"target {spec!r} has no line number; expected <file>:<line> "
            f"e.g. src/auth/session.py:142"
        )
    path, _, line_part = spec.rpartition(":")
    path = path.strip()
    line_part = line_part.strip()

    if not path:
        raise TargetError(f"target {spec!r} has an empty file path")

    m = _LINE_SPEC.match(line_part)
    if not m:
        raise TargetError(
            f"bad line spec {line_part!r}; expected <line> or <start>-<end>"
        )

    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else start

    if start < 1:
        raise TargetError("line numbers are 1-based; got start=%d" % start)
    if end < start:
        raise TargetError(f"invalid range {start}-{end}: end before start")

    return Target(file=path, start_line=start, end_line=end)
