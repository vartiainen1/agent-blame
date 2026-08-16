"""Evidence discovery.

Turns the raw historical facts (graph, blame, commits, diffs) into scored
evidence items and counter-evidence. Everything here is derived from
observable repository data; no intent is guessed. Weights live in
ranking.py so the scoring model is one place and fully documented.

The heavy git lookups (commit metadata, per-file diffs) are memoized by
the caller via `commit_map` / `diff_memo` so the pipeline fetches each
fact at most once (analyzer.py owns the memos).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from .graph import HistoricalGraph, _is_test_path
from .history import commit_info
from .models import EvidenceItem, Target
from .ranking import weight_for
from .repository import Repository

# Words that hint a commit fixed a regression / bug. Kept small and
# documented; message text is only a WEAK signal (see ranking.py).
_FIX_HINTS = re.compile(
    r"\b(fix|fixes|fixed|bug|regression|crash|race|deadlock|hang|"
    r"security|vuln|vulnerability|exploit|fail|broken|correct)\b",
    re.IGNORECASE,
)

_REVERT_RE = re.compile(r"^\s*[Rr]evert\b")
_REVERT_REF = re.compile(r"This reverts commit ([0-9a-f]{7,40})")

# A later commit that removed at least this many lines (with few additions)
# is treated as a possible REPLACEMENT/supersession. Kept small so the
# signal is reachable in real and fixture-sized files alike; documented as
# a weak heuristic, never proof.
_REPLACEMENT_MIN_REMOVED = 5


def _classify_commit_message(subject: str, body: str) -> List[str]:
    """Deterministic classification of a commit message into signal kinds.

    Returns a list of kinds, e.g. ["revert"], ["fix"]. This is a WEAK
    signal - message text alone never decides a conclusion.
    """
    kinds: List[str] = []
    text = f"{subject}\n{body}"
    if _REVERT_RE.match(subject) or _REVERT_REF.search(text):
        kinds.append("revert")
    if _FIX_HINTS.search(text):
        kinds.append("fix")
    return kinds


def collect_evidence(repo: Repository, target: Target,
                     graph: HistoricalGraph,
                     introducing: List[str],
                     later: List[str],
                     commit_map: Optional[Dict[str, object]] = None,
                     diff_memo: Optional[Dict[Tuple[str, str], object]] = None,
                     stats: Optional[Dict[str, Tuple[int, int]]] = None,
                     ) -> List[EvidenceItem]:
    """Collect scored evidence items for the target.

    Each item carries its weight and the reasons for that weight, so the
    final score is explainable (spec section 8). `commit_map`, `diff_memo`
    and `stats` are optional memo structures owned by the caller to avoid
    re-fetching the same git facts (stats = {sha: (added, removed)} in one
    batched git call).
    """
    evidence: List[EvidenceItem] = []
    file = target.file

    def subj_body(sha: str) -> tuple:
        if commit_map is not None:
            ci = commit_map.get(sha)
            if ci is not None:
                return ci.subject, ci.body
        ci = commit_info(repo, sha)
        return (ci.subject, ci.body) if ci else ("", "")

    # --- Introducing commits (direct line introduction) ----------------
    for sha in introducing:
        subject, body = subj_body(sha)
        kinds = _classify_commit_message(subject, body)
        reasons = ["direct line introduction via git blame"]
        item = EvidenceItem(
            kind="introduced_by",
            commit=sha,
            text=f"lines {target.start_line}-{target.end_line} introduced by "
                 f"{sha[:8]}: {subject}",
            weight=weight_for("introduced_by"),
            reasons=reasons,
        )
        evidence.append(item)

        # Same-commit tests strengthen the introducing-commit story.
        tests = _same_commit_tests(graph, sha)
        if tests:
            evidence.append(EvidenceItem(
                kind="same_commit_test",
                commit=sha,
                text=f"commit {sha[:8]} added test file(s): {', '.join(tests)}",
                weight=weight_for("test"),
                reasons=["test introduced together with the code"],
            ))
        if "fix" in kinds:
            evidence.append(EvidenceItem(
                kind="fix_related",
                commit=sha,
                text=f"introducing commit {sha[:8]} message references a fix/regression",
                weight=weight_for("related_fix"),
                reasons=["commit message references fix/regression (weak signal)"],
            ))
        # The introducing commit itself being a revert is counter-evidence:
        # the current line was restored by a revert of a removal.
        if "revert" in kinds:
            evidence.append(EvidenceItem(
                kind="revert",
                commit=sha,
                text=f"introducing commit {sha[:8]} is a revert: {subject}",
                weight=weight_for("revert"),
                reasons=["current lines restored by an explicit revert"],
                is_counter=True,
            ))

    # --- Later modifications (how the code evolved) ---------------------
    for sha in later:
        subject, body = subj_body(sha)
        if not subject and not body:
            continue
        kinds = _classify_commit_message(subject, body)
        is_revert = "revert" in kinds

        if is_revert:
            evidence.append(EvidenceItem(
                kind="revert",
                commit=sha,
                text=f"commit {sha[:8]} reverts prior behavior: {subject}",
                weight=weight_for("revert"),
                reasons=["explicit revert of earlier behavior"],
                is_counter=True,
            ))
        else:
            evidence.append(EvidenceItem(
                kind="modified_by",
                commit=sha,
                text=f"later commit {sha[:8]} modified the file: {subject}",
                weight=weight_for("modified_by"),
                reasons=["later modification of the target file"],
            ))
            if "fix" in kinds:
                evidence.append(EvidenceItem(
                    kind="fix_related",
                    commit=sha,
                    text=f"later commit {sha[:8]} references a fix/regression: {subject}",
                    weight=weight_for("related_fix"),
                    reasons=["later commit message references fix/regression (weak signal)"],
                ))

    # --- Current tests referencing this module (related tests) ----------
    # A test file present at HEAD whose path contains the module base name
    # (e.g. test_retry.py for app/retry.py) exercises this code. This is
    # evidence the behavior is still covered - independent of which commit
    # added the test, so it also works when the test was added in a commit
    # that did not touch the target file.
    stem = file.rsplit("/", 1)[-1]
    base = stem.rsplit(".", 1)[0] if "." in stem else stem
    current_tests = _current_test_files_for(repo, base)
    if current_tests:
        evidence.append(EvidenceItem(
            kind="related_test",
            commit=None,
            text=f"current test file(s) reference this module: {', '.join(current_tests)}",
            weight=weight_for("test"),
            reasons=["test file named after this module exists at HEAD"],
        ))

    # --- Counter-evidence: deletion of the target file's lines ----------
    counter = _detect_deletion_counterevidence(repo, target, later, diff_memo,
                                               stats=stats)
    evidence.extend(counter)

    return dedupe_evidence(evidence)


def _current_test_files_for(repo: Repository, base: str) -> List[str]:
    """Test files present at HEAD whose path contains the module base name.

    Uses git ls-tree (targeted, no content scan) and filters deterministically.
    """
    from .git import try_git_output
    if not base:
        return []
    raw = try_git_output(["ls-tree", "-r", "--name-only", "HEAD"], cwd=repo.root)
    if raw is None:
        return []
    hits = [
        p for p in raw.splitlines()
        if _is_test_path(p) and base.lower() in p.lower()
    ]
    return sorted(hits)


def _same_commit_tests(graph: HistoricalGraph, commit_sha: str) -> List[str]:
    """Test files introduced in the same commit as the target's introducer."""
    tests: Set[str] = set()
    prefix = f"commit:{commit_sha}"
    for (frm, to, rel) in graph.edges:
        if frm == prefix and rel == "tests":
            node = graph.nodes.get(to)
            if node and node.get("type") == "test":
                tests.add(node.get("path", ""))
    return sorted(tests)


def _get_diff(repo: Repository, sha: str, file: str,
              diff_memo: Optional[Dict[Tuple[str, str], object]]):
    """Fetch a per-file diff, memoized when the caller provides a memo."""
    key = (sha, file)
    if diff_memo is not None:
        if key not in diff_memo:
            diff_memo[key] = commit_diff_for_file(repo, sha, file)
        return diff_memo[key]
    return commit_diff_for_file(repo, sha, file)


def _detect_deletion_counterevidence(repo: Repository, target: Target,
                                     later: List[str],
                                     diff_memo=None,
                                     stats: Optional[Dict[str, Tuple[int, int]]] = None,
                                     ) -> List[EvidenceItem]:
    """Find commits that deleted lines from the target file.

    A later commit that removes lines is counter-evidence: the code may
    have been superseded or the behavior changed. This is intentionally
    conservative and approximate: it counts ANY removal in this file, not
    precisely the target range (line numbers drift across history, so
    exact range mapping is not reliable - documented limitation). To avoid
    one weak signal being emitted per commit, the finding is AGGREGATED
    into a single counter-evidence item.

    Uses the batched per-commit stats map when provided (one git call per
    file); falls back to per-commit diffs for direct callers.
    """
    deleters = []
    for sha in later:
        if stats is not None:
            removed = (stats.get(sha) or (0, 0))[1]
        else:
            diff = _get_diff(repo, sha, target.file, diff_memo)
            removed = diff.removed_lines if diff is not None else 0
        if removed > 0:
            deleters.append(sha)
    if not deleters:
        return []
    return [EvidenceItem(
        kind="deleted_lines",
        commit=None,
        text=f"{len(deleters)} later commit(s) removed lines from {target.file}",
        weight=weight_for("deleted_lines"),
        reasons=["later commits delete lines in this file (approximate range "
                 "mapping - documented limitation)"],
        is_counter=True,
    )]


def detect_counterevidence(repo: Repository, target: Target,
                           introducing: List[str],
                           later: List[str],
                           commit_map: Optional[Dict[str, object]] = None,
                           diff_memo: Optional[Dict[Tuple[str, str], object]] = None,
                           stats: Optional[Dict[str, Tuple[int, int]]] = None,
                           ) -> List[EvidenceItem]:
    """Standalone counter-evidence pass (reverts + replacement).

    Reverts are also detected inside collect_evidence; this pass runs
    again so the counter-evidence list is complete even if a caller only
    uses this function. Replacement is reported honestly as POSSIBLE
    supersession, never as fact.
    """
    out: List[EvidenceItem] = []

    # Reverts: message-based.
    for sha in later:
        if commit_map is not None:
            ci = commit_map.get(sha)
        else:
            ci = commit_info(repo, sha)
        if ci is None:
            continue
        kinds = _classify_commit_message(ci.subject, ci.body)
        if "revert" in kinds:
            out.append(EvidenceItem(
                kind="revert",
                commit=sha,
                text=f"commit {sha[:8]} is a revert: {ci.subject}",
                weight=weight_for("revert"),
                reasons=["explicit revert detected from commit message"],
                is_counter=True,
            ))

    # Replacement: a later commit that largely rewrote/removed the file is
    # a hint the implementation was superseded (weak signal).
    for sha in later:
        if stats is not None:
            added, removed = stats.get(sha) or (0, 0)
        else:
            diff = _get_diff(repo, sha, target.file, diff_memo)
            if diff is None:
                continue
            added, removed = diff.added_lines, diff.removed_lines
        if (removed >= _REPLACEMENT_MIN_REMOVED and
                added < removed * 0.3):
            out.append(EvidenceItem(
                kind="replacement",
                commit=sha,
                text=f"commit {sha[:8]} largely rewrote/removed {target.file} "
                     f"({removed} lines removed)",
                weight=weight_for("replacement"),
                reasons=["large deletion in one later commit suggests "
                         "supersession (weak signal)"],
                is_counter=True,
            ))
    return dedupe_evidence(out)


def dedupe_evidence(items: List[EvidenceItem]) -> List[EvidenceItem]:
    """Deduplicate evidence on (kind, commit), preserving first occurrence."""
    seen = set()
    out = []
    for it in items:
        key = (it.kind, it.commit)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
