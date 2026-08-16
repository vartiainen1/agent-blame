"""Evidence ranking weights.

The scoring model is a single documented table (spec section 8). Every
weight is deterministic, and every scored evidence item explains its own
reasons, so the final score is auditable:

    Evidence score: 0.91
      + direct introduction      (introduced_by,     0.30)
      + same-commit test         (test,              0.20)
      + later modification       (modified_by,       0.18)
      + regression relationship  (related_fix,       0.15)
      + ...                      (temporal,          0.03)

Counter-evidence kinds carry NEGATIVE weights: they reduce the confidence
score instead of inflating it.
"""

from __future__ import annotations

from typing import Dict

# Evidence kind -> base weight. Kept as a flat table so the whole scoring
# model is visible in one place and trivially testable.
WEIGHTS: Dict[str, float] = {
    # Very strong: direct, verifiable relationships to the target lines.
    "introduced_by": 0.30,     # git blame says this commit introduced the line
    "revert": -0.25,           # a later commit explicitly reverts behavior

    # Strong: same-commit tests and direct modifications.
    "same_commit_test": 0.20,  # test introduced together with the code
    "modified_by": 0.18,       # later commit modified the target file
    "related_fix": 0.15,       # commit message references fix/regression (weak)

    # Caller relationships (Phase 2C). AST-confirmed direct callers are
    # strong evidence the symbol is depended upon; a caller that lives in a
    # test file is weaker (see symbols.py). Possible callers are weak.
    "live_caller": 0.20,       # AST-confirmed DIRECT_CALL / ATTRIBUTE_CALL
    "import_reference": 0.10,  # module/symbol imported elsewhere
    "possible_caller": 0.05,   # name matches but resolution is ambiguous

    # Movement (Phase 2D). A confirmed move means the code has DEEPER
    # history than its current file suggests - the mover is never the
    # introduction. Small weight: it enriches context, it does not by
    # itself decide confidence or risk.
    "code_movement": 0.10,     # code moved here from another path

    # Regression detection (Phase 2E). A structured revert is counter-
    # evidence (the story is murky); a fix pattern with overlap is
    # supporting (the behavior has a corrective history). All documented
    # heuristics - correlation is never presented as causation.
    "explicit_revert": -0.25,   # structured "This reverts commit <sha>"
    "regression_fix": 0.15,     # fix language + strong overlap (LIKELY)
    "possible_regression_fix": 0.05,  # fix language + weak overlap
    "corrective_change": -0.10, # revert subject without a trailer

    # Medium: same-file relationships.
    "same_file": 0.10,

    # Weak: circumstantial signals - never decisive on their own.
    "deleted_lines": -0.15,    # later commit removed lines in this file
    "replacement": -0.20,      # later commit largely rewrote/removed the file
    "temporal": 0.03,          # temporal proximity to the introduction
}

# Aliases used by evidence.py (kind -> weight key).
_KIND_ALIASES: Dict[str, str] = {
    "test": "same_commit_test",
    "fix_related": "related_fix",
    "deleted_test": "deleted_lines",  # placeholder, see evidence.py
}


def weight_for(kind: str) -> float:
    """Weight for an evidence kind, resolving aliases."""
    key = _KIND_ALIASES.get(kind, kind)
    return WEIGHTS.get(key, 0.0)


def rank_evidence(items) -> list:
    """Sort evidence by weight descending, stable (tie -> insertion order).

    Counter-evidence (negative weight) naturally sinks to the bottom.
    """
    return sorted(items, key=lambda e: e.weight, reverse=True)
