"""Regression detection (Phase 2E).

Identifies HISTORICAL REGRESSION PATTERNS: a later commit that appears to
fix or revert behavior introduced (or modified) by an earlier commit. The
central rule is CORRELATION IS NOT PROOF OF CAUSATION: the findings say
"commit C explicitly reverts B" or "evidence indicates C corrected
behavior introduced by B" - never "B caused the bug".

This is one more evidence layer inside the existing pipeline, not a second
engine. It consumes facts the analyzer already fetched (introducing
commits from blame, later commits touching the file, per-commit numstat,
commit metadata from the shared memo) and produces:

  1. a list of RegressionEvidence findings (structured, deterministic)
  2. EvidenceItems that flow through the existing ranking / confidence /
     risk machinery

Classification ladder (strongest first):

  EXPLICIT_REVERT
      The commit message contains the structured git trailer
      "This reverts commit <sha>" (git revert writes it). This is the
      strongest regression-related signal - but it proves the change was
      REVERTED, not that it contained a bug. HIGH when the reverted
      commit is the target's introducer; MEDIUM when it merely touched
      the target file; skipped entirely when it is unrelated.

  LIKELY_REGRESSION_FIX
      Fix/regression language (weak hint) PLUS a strong overlap signal:
      the message explicitly references an introducing commit, or the
      commit both removed code (corrective shape) AND changed tests.

  POSSIBLE_REGRESSION_FIX
      Fix language PLUS one weak overlap signal (corrective shape or test
      changes). LOW confidence - reported, never decisive.

  CORRECTIVE_CHANGE
      A "Revert ..." subject WITHOUT a structured trailer, touching the
      target file. Weakened because without the trailer we cannot link it
      deterministically to a specific commit (spec 2E/4: do not infer a
      revert from the word "revert" when no stronger evidence exists).

  NO_REGRESSION_EVIDENCE
      Everything else - including fix language with NO overlap (Property
      6: the word "fix" alone must never establish a regression) and
      reverts of unrelated files (Property: revert of unrelated file).

Evidence kinds emitted (weights in ranking.py, documented heuristics):
  explicit_revert       -0.25  counter (replaces the weak message-based
                                "revert" item for the same commit)
  regression_fix        +0.15  supporting (LIKELY)
  possible_regression_fix +0.05 supporting (POSSIBLE)
  corrective_change     -0.10  counter (weak correction signal)
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from .evidence import _REVERT_REF, _classify_commit_message
from .graph import _is_test_path
from .history import commit_files
from .models import EvidenceItem, RegressionEvidence, Target
from .ranking import weight_for
from .repository import Repository

# How many fix-language later commits we examine per target (bounded scan:
# each one costs commit_files + stats lookups; fix language is already a
# rare pre-filter, and the cap keeps pathological histories cheap).
_MAX_FIX_CANDIDATES = 5

# Corrective shape requires a STRICT NET REMOVAL (removed > added): a
# single-line edit (1 removed / 1 added) is not corrective on its own, so
# "Fix naming" style renames never count. Documented as a heuristic,
# never proof.
_CORRECTIVE_MIN_REMOVED = 1


def _resolve_sha(candidate: str, full_shas: Set[str]) -> Optional[str]:
    """Resolve a possibly-abbreviated sha against a set of full shas.

    The revert trailer may cite "This reverts commit 81f3a2c" (7 chars)
    while the analysis holds full 40-char shas. Returns the full sha on
    an exact or unique-prefix match, else None (unrelated commit).
    """
    if candidate in full_shas:
        return candidate
    if len(candidate) >= 7 and len(candidate) < 40:
        matches = [s for s in full_shas if s.startswith(candidate)]
        if len(matches) == 1:
            return matches[0]
    return None


def _introducer_reference(text: str, introducing: List[str]) -> Optional[str]:
    """An introducing commit sha cited in a commit message, if any.

    Deterministic: looks for full or abbreviated (>= 7 hex) shas of the
    introducing commits in the message text. A message that says
    "fixes regression from 81f3a2" is strong evidence the commit
    concerns that introducer's behavior - but still evidence, not proof.
    """
    for sha in introducing:
        if sha in text:
            return sha
        short = sha[:7]
        if re.search(rf"\b{short}\b", text):
            return sha
    return None


def _commit_files_cached(repo: Repository, memo, sha: str) -> List[str]:
    """commit_files(sha) with a per-run memo (avoids repeat git calls)."""
    cache = getattr(memo, "_regression_files", None)
    if cache is None:
        cache = memo._regression_files = {}
    if sha not in cache:
        cache[sha] = commit_files(repo, sha)
    return cache[sha]


def _test_evidence(files: List[str], target_file: str) -> Optional[str]:
    """A test file in `files` that plausibly covers the target module.

    Matches on the module base name (e.g. tests/test_retry.py for
    app/retry.py) so an unrelated test change is not credited. Returns
    the first matching test path, or None.
    """
    stem = target_file.rsplit("/", 1)[-1]
    base = stem.rsplit(".", 1)[0] if "." in stem else stem
    if not base:
        return None
    for p in sorted(files):
        if _is_test_path(p) and base.lower() in p.lower():
            return p
    return None


def _symbol_overlap(repo: Repository, memo, sha: str, target_file: str,
                    symbol_name: Optional[str]) -> bool:
    """Did commit `sha` change lines inside the target symbol?

    The discriminator that keeps "fix to an unrelated symbol" out of the
    findings (Property 4): a later fix commit touching the same FILE but a
    different symbol must not become a regression for the target. We
    compare in the commit's PARENT coordinate space:

      - the commit's diff to the file (old-side changed line numbers)
      - symbols extracted from the file content at the commit's parent

    Line numbers never drift because both sides are pinned to the parent.
    Returns True only on a verified intersection. Cost is bounded: only
    fix-language candidates reach here, and the diff + parent content are
    memoized (one git call each, shared across targets in a run).
    """
    if not symbol_name:
        return False
    ci = memo.commit_map.get(sha)
    if ci is None or not ci.parents:
        return False
    parent = ci.parents[0]
    try:
        diff = memo.diff_memo.get((sha, target_file))
        if diff is None:
            from .history import commit_diff_for_file
            diff = commit_diff_for_file(repo, sha, target_file)
            if diff is not None:
                memo.diff_memo[(sha, target_file)] = diff
        if diff is None:
            return False
        from .diff import _parse_hunks  # shared NUL-safe hunk parser
        changed = set()
        for h in _parse_hunks(diff.diff):
            changed.update(h.get("old_changed", []))
        if not changed:
            return False
        content = memo.py_sources_limited(repo, parent, [target_file])
        src = content.get(target_file)
        if src is None:
            return False
        syms = memo.file_symbols(parent, target_file, src)
        for s in syms:
            if s.name == symbol_name and any(
                    s.start_line <= ln <= s.end_line for ln in changed):
                return True
    except Exception:
        return False
    return False


def _classify_later_commit(repo: Repository, memo, sha: str, text: str,
                           kinds: List[str], introducing: List[str],
                           touching: Set[str],
                           target_file: str,
                           stats: Optional[Dict[str, tuple]],
                           symbol_name: Optional[str] = None,
                           has_symbol: bool = False) -> Optional[RegressionEvidence]:
    """Classify one later commit into a regression finding (or None)."""
    # --- EXPLICIT_REVERT: structured trailer ---------------------------
    m = _REVERT_REF.search(text)
    if m:
        reverted = m.group(1)
        full = memo.commit_map.get(reverted)
        # Normalize to the full sha when we have it in the memo; otherwise
        # resolve the (possibly abbreviated) trailer sha against the file's
        # commit history.
        reverted_full = full.sha if full else reverted
        resolved = _resolve_sha(reverted_full, {*introducing, *touching})
        if resolved is None:
            # Revert of an unrelated commit: NOT a regression for this
            # target (Property: revert of unrelated file).
            return None
        reverted_full = resolved
        if reverted_full in introducing:
            return RegressionEvidence(
                type="EXPLICIT_REVERT", confidence="HIGH",
                relationship="DIRECT_RANGE_OVERLAP",
                original_commit=reverted_full,
                fix_commit=sha, reverted_commit=reverted_full,
                target_path=target_file,
                signals=["git_revert_relationship",
                         "reverted_commit_is_introducer"],
                explanation=(f"commit {sha[:8]} explicitly reverts {reverted[:8]}, "
                             f"which introduced the analyzed behavior"),
            )
        # Related at the file level? The reverted commit also touched this
        # file (it is in the file's commit history = introducers + later).
        return RegressionEvidence(
            type="EXPLICIT_REVERT", confidence="MEDIUM",
            relationship="FILE_OVERLAP",
            original_commit=reverted_full,
            fix_commit=sha, reverted_commit=reverted_full,
            target_path=target_file,
            signals=["git_revert_relationship"],
            explanation=(f"commit {sha[:8]} explicitly reverts {reverted[:8]}, "
                         f"which also modified this file"),
        )

    # --- Fix language ---------------------------------------------------
    if "fix" not in kinds:
        # A plain "Revert ..." subject without a trailer is a weak
        # correction signal, but only if it touches the target file (all
        # `later` commits do by construction).
        if "revert" in kinds:
            return RegressionEvidence(
                type="CORRECTIVE_CHANGE", confidence="LOW",
                relationship="FILE_OVERLAP",
                fix_commit=sha, target_path=target_file,
                signals=["revert_subject_without_trailer"],
                explanation=(f"commit {sha[:8]} has a revert subject but no "
                             f"structured revert reference; correction "
                             f"relationship cannot be confirmed"),
            )
        return None

    # Fix language present - gather overlap signals (fix words alone never
    # establish a regression; Property 6).
    signals: List[str] = ["fix_language"]

    ref = _introducer_reference(text, introducing)
    if ref:
        signals.append("references_introducer")

    corrective = False
    if stats is not None:
        added, removed = stats.get(sha) or (0, 0)
        if removed >= _CORRECTIVE_MIN_REMOVED and removed > added:
            corrective = True
            signals.append("corrective_shape")

    test_path = None
    try:
        files = _commit_files_cached(repo, memo, sha)
        test_path = _test_evidence(files, target_file)
    except Exception:
        files = []
        test_path = None
    if test_path:
        signals.append(f"test_evidence:{test_path}")

    # Verified symbol overlap (parent-coordinate comparison). When the
    # target resolved to a symbol, this is the discriminator that keeps an
    # unrelated-symbol fix out of the findings (Property 4).
    sym = _symbol_overlap(repo, memo, sha, target_file, symbol_name)
    if sym:
        signals.append("symbol_overlap")

    # Strong overlap: explicit introducer reference, OR verified symbol
    # overlap combined with a second independent signal (corrective shape
    # or test changes).
    if ref:
        return RegressionEvidence(
            type="LIKELY_REGRESSION_FIX", confidence="MEDIUM",
            relationship="MESSAGE_REFERENCE",
            original_commit=ref, fix_commit=sha,
            target_path=target_file,
            signals=signals,
            explanation=(f"evidence indicates commit {sha[:8]} corrected "
                         f"behavior introduced by {ref[:8]}"),
        )
    if sym and (corrective or test_path):
        return RegressionEvidence(
            type="LIKELY_REGRESSION_FIX", confidence="MEDIUM",
            relationship="SYMBOL_OVERLAP",
            original_commit=introducing[0] if introducing else None,
            fix_commit=sha, target_path=target_file,
            signals=signals,
            explanation=(f"evidence indicates commit {sha[:8]} corrected "
                         f"behavior in {target_file} (changes overlap the "
                         f"analyzed symbol)"),
        )

    # Weak overlap: verified symbol overlap alone, or file-level signals
    # (test evidence / corrective shape) when the target has NO resolved
    # symbol (non-Python or unresolved target - file-level overlap is the
    # honest limit there). When a symbol IS resolved but the fix did NOT
    # touch it, nothing is emitted (Property 4).
    if sym:
        return RegressionEvidence(
            type="POSSIBLE_REGRESSION_FIX", confidence="LOW",
            relationship="SYMBOL_OVERLAP",
            original_commit=introducing[0] if introducing else None,
            fix_commit=sha, target_path=target_file,
            signals=signals,
            explanation=(f"possible regression/fix sequence involving "
                         f"commit {sha[:8]} and the analyzed symbol; overlap "
                         f"evidence is limited"),
        )
    if not has_symbol and (corrective or test_path):
        return RegressionEvidence(
            type="POSSIBLE_REGRESSION_FIX", confidence="LOW",
            relationship="TEST_EVIDENCE" if test_path else "FILE_OVERLAP",
            original_commit=introducing[0] if introducing else None,
            fix_commit=sha, target_path=target_file,
            signals=signals,
            explanation=(f"possible regression/fix sequence involving "
                         f"commit {sha[:8]} and {target_file}; overlap "
                         f"evidence is limited (file-level only)"),
        )

    # Fix language with NO overlap: never a regression on its own.
    return None


def detect_regressions(repo: Repository, memo,
                       target: Target,
                       introducing: List[str],
                       later: List[str],
                       stats: Optional[Dict[str, tuple]] = None,
                       symbol_name: Optional[str] = None,
                       has_symbol: bool = False,
                       ) -> List[RegressionEvidence]:
    """Detect regression patterns among the later commits touching a file.

    `introducing`: blame-introduced commits for the target lines.
    `later`: commits touching the file after, excluding introducers
             (newest first, from the shared pipeline).
    `stats`: {sha: (added, removed)} per-commit numstat for the file.
    `symbol_name`: qualified name of the target's resolved symbol, when
        the target line sits inside a Python symbol (Phase 2C). Used for
        verified symbol overlap - the Property 4 discriminator.
    `has_symbol`: whether the target resolved to a symbol at all. When
        True and the fix did NOT touch that symbol, file-level overlap is
        NOT enough (unrelated-symbol fixes stay out). When False (non-
        Python / unresolved), file-level signals are the honest limit.

    Returns findings sorted deterministically (strongest type first,
    then by commit). Empty list == NO_REGRESSION_EVIDENCE.
    """
    findings: List[RegressionEvidence] = []
    fix_candidates = 0
    touching: Set[str] = {*introducing, *later}

    for sha in later:
        ci = memo.commit_map.get(sha)
        if ci is None:
            continue
        text = f"{ci.subject}\n{ci.body}"
        kinds = _classify_commit_message(ci.subject, ci.body)

        # Reverts (structured or subject-only) are always examined - the
        # trailer check is free and reverts are rare.
        if "revert" in kinds:
            finding = _classify_later_commit(
                repo, memo, sha, text, kinds, introducing, touching,
                target.file, stats, symbol_name=symbol_name,
                has_symbol=has_symbol)
            if finding is not None:
                findings.append(finding)
            continue

        # Fix-language commits: bounded examination (commit_files +
        # stats lookups are the only git work, and only these candidates).
        if "fix" in kinds:
            if fix_candidates >= _MAX_FIX_CANDIDATES:
                continue
            fix_candidates += 1
            finding = _classify_later_commit(
                repo, memo, sha, text, kinds, introducing, touching,
                target.file, stats, symbol_name=symbol_name,
                has_symbol=has_symbol)
            if finding is not None:
                findings.append(finding)

    _TYPE_ORDER = {"EXPLICIT_REVERT": 0, "LIKELY_REGRESSION_FIX": 1,
                   "POSSIBLE_REGRESSION_FIX": 2, "CORRECTIVE_CHANGE": 3}
    findings.sort(key=lambda f: (_TYPE_ORDER.get(f.type, 9),
                                 f.fix_commit or f.reverted_commit or ""))
    return findings


def regressions_to_evidence(findings: List[RegressionEvidence],
                            ) -> List[EvidenceItem]:
    """Convert regression findings into scored evidence items.

    EXPLICIT_REVERT replaces the weak message-based "revert" item for the
    same commit (the caller removes those); the other kinds add their own
    items through the normal pipeline.
    """
    out: List[EvidenceItem] = []
    for f in findings:
        if f.type == "EXPLICIT_REVERT":
            out.append(EvidenceItem(
                kind="explicit_revert",
                commit=f.reverted_commit,
                text=f.explanation,
                weight=weight_for("explicit_revert"),
                reasons=[f"git revert trailer references {f.reverted_commit[:8]}"],
                is_counter=True,
            ))
        elif f.type == "LIKELY_REGRESSION_FIX":
            out.append(EvidenceItem(
                kind="regression_fix",
                commit=f.fix_commit,
                text=f.explanation,
                weight=weight_for("regression_fix"),
                reasons=["fix language plus overlapping corrective/test "
                         "evidence (heuristic, not proof)"],
            ))
        elif f.type == "POSSIBLE_REGRESSION_FIX":
            out.append(EvidenceItem(
                kind="possible_regression_fix",
                commit=f.fix_commit,
                text=f.explanation,
                weight=weight_for("possible_regression_fix"),
                reasons=["fix language with a single weak overlap signal "
                         "(heuristic, not proof)"],
            ))
        elif f.type == "CORRECTIVE_CHANGE":
            out.append(EvidenceItem(
                kind="corrective_change",
                commit=f.fix_commit,
                text=f.explanation,
                weight=weight_for("corrective_change"),
                reasons=["revert subject without a structured reference "
                         "(weak correction signal)"],
                is_counter=True,
            ))
    return out
