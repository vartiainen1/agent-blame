"""Historical change/removal risk analysis.

Answers: "what historical evidence should I consider before changing or
removing this?" (spec section 11). The result is a LEVEL plus REASONS -
never an absolute claim like "safe to delete". The developer makes the
final decision.

Signals (deterministic, evidence-derived):

  HIGH-risk signals:
    - previous revert of this behavior
    - regression/fix history around the target
    - strong test coverage (tests introduced with the code)
    - frequent modifications
    - replacement/supersession uncertainty (deleted lines)

  LOW-risk signals:
    - original purpose clearly superseded (replacement detected)
    - no current callers / tests

UNKNOWN when the repository offers no usable history (shallow clone, no
commits, file never touched in available history).
"""

from __future__ import annotations

from typing import List

from .models import EvidenceItem, Risk

_HIGH_COUNT = 2


def _level_for(high_signals: int, low_signals: int, has_history: bool) -> str:
    if not has_history:
        return "UNKNOWN"
    if high_signals >= _HIGH_COUNT:
        return "HIGH"
    if high_signals == 1:
        return "MEDIUM"
    # No high signals: either genuinely low risk or insufficient evidence.
    if low_signals > 0:
        return "LOW"
    return "UNKNOWN"


def analyze_risk(evidence: List[EvidenceItem], has_history: bool) -> Risk:
    """Compute historical removal risk from the evidence list."""
    kinds = {e.kind for e in evidence}

    high_reasons: List[str] = []
    low_reasons: List[str] = []

    if "revert" in kinds:
        reverts = [e for e in evidence if e.kind == "revert"]
        high_reasons.append(
            f"previous revert of this behavior ({len(reverts)} revert commit(s))"
        )
    if "fix_related" in kinds:
        fixes = [e for e in evidence if e.kind == "fix_related"]
        high_reasons.append(
            f"regression/fix history around this code ({len(fixes)} fix-related commit(s))"
        )
    if "related_test" in kinds:
        high_reasons.append(
            "tests referencing this code were added or modified in later commits"
        )
    if "same_commit_test" in kinds:
        high_reasons.append("tests were introduced together with this code "
                            "(behavior is exercised)")
    if "modified_by" in kinds:
        mods = [e for e in evidence if e.kind == "modified_by"]
        if len(mods) >= 3:
            high_reasons.append(f"frequently modified ({len(mods)} later modifications)")
    if "live_caller" in kinds:
        callers = [e for e in evidence if e.kind == "live_caller"]
        high_reasons.append(
            f"{len(callers)} confirmed live caller(s) depend on this code"
        )

    if "replacement" in kinds:
        low_reasons.append("replacement/superseding implementation detected")
    if "deleted_lines" in kinds:
        low_reasons.append("lines in this file were removed by later commits "
                           "(behavior may have been superseded)")

    high = len(high_reasons)
    low = len(low_reasons)
    level = _level_for(high, low, has_history)

    reasons = high_reasons + low_reasons
    if level == "UNKNOWN" and has_history and not reasons:
        reasons = ["no strong historical signals found in available history"]
    return Risk(level=level, reasons=reasons)
