"""Movement classification for change boundaries (Phase 2D).

The one historical-analysis engine serves every mode; movement is one more
evidence layer. This module answers, for a BEFORE/AFTER boundary (a
commit's parent -> commit, or HEAD -> working tree / index):

    did code MOVE here, and if so, where did it originally come from?

Sources of movement evidence, in strength order:

  1. git rename metadata (`git diff -M`): a file-level R<score> entry is
     git-confirmed. The whole file moved - but its CONTENT may still have
     changed inside the rename, so symbol-level matching still runs for
     the analysis of specific added ranges.
  2. symbol-level continuity (Python AST + stdlib difflib): catches the
     partial moves git's similarity threshold misses - a symbol that
     disappeared from one file and appeared in another, structurally
     similar. This is the case that would otherwise blame the MOVE commit
     as the introduction.

Honesty rules (spec 2D):
  - a move is never an introduction: `moved_by` and `origin` are kept
    strictly separate
  - similarity is a heuristic, documented as such, never a probability
  - ambiguity (competing origins) degrades to POSSIBLE_MOVEMENT
  - a copy (source still exists) is NEVER reported as a move
  - unsupported languages produce no movement claim

Security: all git calls are argv-based; source content is parsed (AST) and
compared as data, never executed.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .git import GitError
from .history import blame_file_map
from .models import Target
from .symbols import match_moved_symbols


def _origin_for(repo, memo, mv: dict, revision: str) -> Optional[str]:
    """Blame the source symbol's range at `revision` -> the origin sha.

    `revision` is the BEFORE side of the boundary (the commit's parent for
    --commit, HEAD for --diff), so the origin is the commit that actually
    introduced the moved code - never the mover.

    Perf (Phase 3): the whole source file is blamed ONCE per (file,
    revision) via the memoized blame_file_map; a move commit with many
    moved symbols previously ran one `git blame` subprocess PER symbol
    (272 calls, ~14s, on requests' src/ move).
    """
    start = mv.get("_source_start")
    src = mv.get("source_path")
    if not (start and src):
        return None
    bl = blame_file_map(repo, memo, src, revision).get(start)
    return bl.commit if bl else None


def boundary_movements(repo, memo, before: Dict[str, str],
                       after: Dict[str, str],
                       rename_map: Optional[Dict[str, str]] = None,
                       revision: str = "HEAD",
                       ) -> Dict[str, List[dict]]:
    """Per-file movement dicts for a change boundary.

    `before`/`after` are content maps ({path: source text}) - the caller
    decides the boundary source (revision blobs, index, or worktree).
    `rename_map` maps git-confirmed new_path -> old_path (status R/C).

    Returns {dest_path: [movement dicts]} - ALL matched movements per
    file (a commit can move several symbols), with `origin` filled by
    blaming the source range at the BEFORE revision. The dicts keep
    private "_range" fields for hunk-intersection checks; call
    `public_movement()` before attaching to structured output.
    """
    rename_map = rename_map or {}
    raw = match_moved_symbols(repo, memo, before, after, rename_map)
    out: Dict[str, List[dict]] = {}
    for mv in raw:
        mv["origin"] = _origin_for(repo, memo, mv, revision)
        mv["origin_path"] = mv.get("source_path")
        path = mv["dest_path"]
        out.setdefault(path, []).append(mv)
    return out


def public_movement(mv: dict) -> dict:
    """Strip private matching fields (ranges) before structured output."""
    return {k: v for k, v in mv.items() if not k.startswith("_")}


def rename_movement(old_path: str, new_path: str, origin: Optional[str]) -> dict:
    """A git-confirmed file rename (status R): Movement dict."""
    return {
        "type": "RENAME",
        "source_path": old_path,
        "source_symbol": None,
        "dest_path": new_path,
        "dest_symbol": None,
        "moved_by": None,      # set by the caller (the analyzed change)
        "origin": origin,
        "origin_path": old_path,
        "confidence": "HIGH",
        "signals": ["git rename metadata (R<score>)"],
    }


def group_movement(dest_path: str, mv: dict, moved_by: Optional[str]) -> dict:
    """A movement dict for a GROUP's analysis (with the mover filled in)."""
    d = dict(mv)
    d["moved_by"] = moved_by
    d["dest_path"] = dest_path
    return d


def intersecting_movement(mvs: List[dict], start: int, end: int) -> Optional[dict]:
    """The moved symbol whose destination range overlaps [start, end]."""
    for mv in mvs:
        ds = mv.get("_dest_start")
        de = mv.get("_dest_end")
        if ds is None or de is None:
            continue
        if ds <= end and start <= de:
            return mv
    return None


def moved_symbol_group(repo, memo, dest_path: str, mv: dict, h: dict,
                       changes: list, moved_by: str, revision: str,
                       mode: str, change_map: Optional[dict] = None):
    """A DiffGroup for a moved symbol's added range: origin traced to the
    SOURCE at the BEFORE revision, movement attached.

    Without this, an added range inside a moved symbol would be reported
    as "no previous version" - the Phase 2D false-introduction trap. The
    analysis targets the source symbol's range at `revision` (baseline /
    HEAD), so the introducing commit is the true origin, never the mover.
    Returns None when the source cannot be analyzed.
    """
    from .analyzer import analyze  # lazy: avoids import cycle
    from .models import DiffGroup
    try:
        aresult = analyze(
            repo, Target(file=mv["source_path"],
                         start_line=mv["_source_start"],
                         end_line=mv["_source_end"]),
            mode=mode, memo=memo, revision=revision, change_map=change_map)
    except GitError:
        return None
    aresult.movement = public_movement(group_movement(dest_path, mv, moved_by))
    added = len([c for c in changes if c.type == "add"])
    return DiffGroup(
        ranges=[{"old": None,
                 "new": {"start": h["new_start"],
                         "end": h["new_start"] + h["new_count"] - 1}}],
        changes=[c.to_dict() for c in changes],
        added_lines=added, deleted_lines=0,
        analysis=aresult.to_dict(),
    )
