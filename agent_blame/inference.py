"""Inference: derive the likely purpose of the target code from evidence.

Inference is NEVER a fact. It is a conclusion derived from multiple
evidence items, phrased as a suggestion backed by named evidence, and
suppressed entirely when the evidence cannot support it (spec sections
16/36: "insufficient evidence" over "I think it exists because...").
"""

from __future__ import annotations

from typing import List

from .models import EvidenceItem, Inference
from .ranking import weight_for

# Words that let us make a SAFE, evidence-backed inference about purpose.
# If the introducing commit's message matches one of these domains, we can
# say "the introducing commit references a security issue" - a statement
# about the message, not about the author's intent.
_DOMAIN_HINTS = [
    ("security", ("secur", "vuln", "exploit", "auth", "token", "permission",
                  "sanitize", "injection", "xss", "csrf", "encrypt", "crypto")),
    ("performance", ("perf", "slow", "latency", "timeout", "optimize",
                     "fast", "cache", "benchmark")),
    ("correctness", ("fix", "bug", "crash", "race", "deadlock", "hang",
                     "corrupt", "incorrect", "regression", "correct")),
    ("concurrency", ("race", "concurrent", "thread", "lock", "mutex",
                     "deadlock", "atomic")),
    ("compatibility", ("compat", "legacy", "backward", "migrat", "deprecat",
                       "old", "api v")),
]


def infer_purpose(evidence: List[EvidenceItem]) -> List[Inference]:
    """Derive likely-purpose inferences from introducing-commit evidence.

    Returns zero inferences when there is no introducing commit or when the
    introducing message gives no domain signal - the honest "I don't know".
    """
    introducers = [e for e in evidence if e.kind == "introduced_by"]
    if not introducers:
        return []

    inferences: List[Inference] = []
    for intro in introducers:
        text = intro.text
        lower = text.lower()
        matched = []
        for domain, hints in _DOMAIN_HINTS:
            if any(h in lower for h in hints):
                matched.append(domain)
        if not matched:
            continue
        domain = ", ".join(sorted(matched))
        inferences.append(Inference(
            text=(
                f"The introducing commit message references {domain}-related "
                f"concerns; the code may have been introduced to address that "
                f"area (evidence: {intro.commit[:8]})"
            ),
            evidence_kinds=[intro.kind],
            confidence=_inference_confidence(intro),
        ))
    return inferences


def _inference_confidence(intro: EvidenceItem) -> str:
    """Confidence of a single inference, from supporting evidence weight."""
    w = weight_for("introduced_by")
    if w >= 0.25:
        return "MEDIUM"
    return "LOW"


def infer_original_vs_current(evidence: List[EvidenceItem]) -> List[Inference]:
    """Distinguish ORIGINAL purpose from CURRENT relevance (spec section 10).

    When counter-evidence (replacement, deletions, reverts) exists, state
    honestly that the original reason may no longer apply.
    """
    counter = [e for e in evidence if e.is_counter]
    if not counter:
        return []

    kinds = {e.kind for e in counter}
    parts = []
    if "replacement" in kinds:
        parts.append("a replacement implementation was detected")
    if "deleted_lines" in kinds:
        parts.append("later commits removed lines from this file")
    if "revert" in kinds:
        parts.append("prior behavior was reverted")
    if not parts:
        return []

    return [Inference(
        text=(
            f"Original purpose may no longer apply: {', '.join(parts)}. "
            f"The current code may be retained for a different reason "
            f"(or may be superseded)."
        ),
        evidence_kinds=sorted(kinds),
        confidence="LOW",
    )]
