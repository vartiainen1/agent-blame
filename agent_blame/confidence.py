"""Confidence scoring.

Levels (spec section 15): HIGH / MEDIUM / LOW / CONTRADICTORY /
INSUFFICIENT.

The score is a deterministic, explainable weighted sum of the available
repository evidence - NOT a statistical probability (we say so in the docs
and in the JSON). Rules:

  - Supporting evidence is summed first and capped at 1.0; counter-evidence
    (negative weights) is then SUBTRACTED from that cap. This guarantees
    counter-evidence always lowers the score - it cannot be hidden by an
    arbitrarily large pile of supporting items.
  - No evidence at all -> INSUFFICIENT.
  - A direct revert of the introducing commit -> CONTRADICTORY.
  - Any revert in the file's history caps the level at MEDIUM: an explicit
    revert means the "why does this exist" story is murky, so HIGH would
    be overclaiming.
  - Net-negative evidence (replacement outweighs support) -> CONTRADICTORY.
"""

from __future__ import annotations

from typing import List

from .models import Confidence, EvidenceItem

# Level thresholds on the clamped weighted sum.
_HIGH = 0.60
_MEDIUM = 0.35
_LOW = 0.10


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_confidence(evidence: List[EvidenceItem]) -> Confidence:
    """Compute confidence from the evidence list.

    See module docstring for the scoring rules.
    """
    if not evidence:
        return Confidence("INSUFFICIENT", 0.0, reasons=["no historical evidence found"])

    support = sum(e.weight for e in evidence if e.weight > 0)
    counter = sum(e.weight for e in evidence if e.weight < 0)
    # Cap SUPPORT first, then subtract counter-evidence: negatives always
    # reduce the visible score (fixes the old clamp-after-sum which let
    # counter-evidence become invisible once support exceeded 1.0).
    score = _clamp(min(support, 1.0) + counter)

    introducers = {e.commit for e in evidence if e.kind == "introduced_by"}
    reverts = [e for e in evidence if e.is_counter and e.kind == "revert"]

    # 1. Direct revert of an introducer is a hard contradiction.
    if any(e.commit in introducers for e in reverts):
        return Confidence(
            "CONTRADICTORY", score,
            reasons=["a later commit explicitly reverts the introducing commit"],
        )

    # 2. Strong net-negative evidence (e.g. replacement dominates).
    if score < 0.05 and support > 0 and counter < 0:
        return Confidence(
            "CONTRADICTORY", score,
            reasons=["counter-evidence outweighs supporting evidence "
                     "(replacement/supersession detected)"],
        )

    # 3. Level from the score.
    if score >= _HIGH:
        level = "HIGH"
    elif score >= _MEDIUM:
        level = "MEDIUM"
    elif score >= _LOW:
        level = "LOW"
    else:
        return Confidence(
            "INSUFFICIENT", score,
            reasons=["available evidence is too weak to support an inference"],
        )

    # 4. Any revert in the file's history caps at MEDIUM: the story is
    #    murky, HIGH would overclaim.
    if reverts and level == "HIGH":
        level = "MEDIUM"

    reasons = _level_reasons(evidence, level)
    return Confidence(level, score, reasons)


def _level_reasons(evidence: List[EvidenceItem], level: str) -> List[str]:
    """Human-readable reasons behind the level."""
    pos = [e for e in evidence if not e.is_counter]
    neg = [e for e in evidence if e.is_counter]
    reasons = [
        f"{len(pos)} supporting evidence item(s)",
    ]
    if neg:
        reasons.append(f"{len(neg)} counter-evidence item(s)")
    return reasons
