"""Data models for agent-blame.

Every meaningful conclusion carries the evidence that supports it. The
models below are the structured result contract: stable, documented, and
consumable by other tools via the JSON output (see output.py).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional

from . import __version__


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Target:
    """A file:line (or file:start-end) target inside the repository."""

    file: str                       # repo-relative path, forward slashes
    start_line: int                 # 1-based inclusive
    end_line: int                   # 1-based inclusive

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


# ---------------------------------------------------------------------------
# Git primitives (facts about the repository)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BlameLine:
    """One line of `git blame --line-porcelain` output for a target range."""

    line_no: int
    commit: str                     # full sha of the introducing commit
    summary: str                    # subject of that commit (raw, unsanitized)
    author: str                     # author name (raw)
    author_time: str                # ISO-8601 author date
    filename: Optional[str] = None  # ORIGIN path when git's rename detection
                                    # followed a rename; None when the line
                                    # was introduced at its current path


@dataclass(frozen=True)
class CommitInfo:
    """Metadata + file-level diff summary for a single commit."""

    sha: str
    subject: str
    body: str
    author: str
    author_email: str
    author_date: str                # ISO-8601
    parents: List[str] = field(default_factory=list)  # full shas
    is_merge: bool = False          # more than one parent

    def to_dict(self) -> dict:
        return {
            "sha": self.sha,
            "subject": self.subject,
            "body": self.body,
            "author": self.author,
            "author_email": self.author_email,
            "author_date": self.author_date,
            "parents": self.parents,
            "is_merge": self.is_merge,
        }


@dataclass(frozen=True)
class CommitDiff:
    """The diff of one commit restricted to one file (for analysis)."""

    sha: str
    file: str
    diff: str                       # raw unified diff text (unsanitized)
    added_lines: int = 0
    removed_lines: int = 0


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceItem:
    """A single piece of historical evidence relevant to the target.

    `kind` is the machine-readable evidence class (e.g. "introduction",
    "same_commit_test", "later_modification", "revert", ...). `weight` is
    the deterministic contribution to the evidence score. `reasons` are
    human-readable explanations of why this evidence ranked the way it did.
    """

    kind: str
    commit: Optional[str] = None
    text: str = ""
    weight: float = 0.0
    reasons: List[str] = field(default_factory=list)
    is_counter: bool = False        # True -> this evidence weakens the story

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Inference:
    """A conclusion derived from one or more evidence items (never a fact)."""

    text: str
    evidence_kinds: List[str] = field(default_factory=list)
    confidence: str = "LOW"         # how strongly the supporting evidence
                                    # supports this specific inference

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Aggregated results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Confidence:
    """How strongly the available repository evidence supports the analysis.

    Levels: HIGH / MEDIUM / LOW / CONTRADICTORY / INSUFFICIENT.
    """

    level: str
    score: float                    # 0.0 - 1.0, deterministic, explainable
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "score": round(self.score, 4),
            "reasons": self.reasons,
        }


@dataclass(frozen=True)
class Risk:
    """Historical change/removal risk. NOT a safety guarantee.

    Levels: LOW / MEDIUM / HIGH / UNKNOWN. Signals are evidence-based;
    the developer makes the final decision.
    """

    level: str
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"level": self.level, "reasons": self.reasons}


# ---------------------------------------------------------------------------
# Symbol / caller relationships (Phase 2C)
# ---------------------------------------------------------------------------
#
# Movement evidence (Phase 2D) uses plain dicts, not a dataclass - see
# movement.py for the schema (type / source_path / source_symbol /
# dest_path / dest_symbol / moved_by / origin / origin_path / confidence /
# signals / chain). The one rule that matters: `origin` (the true
# introducer) and `moved_by` (the mover) are ALWAYS kept separate.

@dataclass(frozen=True)
class Symbol:
    """A definition (function/method/class) in a source file.

    `name` is the QUALIFIED name (e.g. "retry", "Server.handle",
    "outer.inner") so two files can never collide on a bare display name.
    The stable identity is `path:name` plus the source range.
    """

    path: str                       # repo-relative, forward slashes
    name: str                       # qualified symbol name
    kind: str                       # "function" | "method" | "class" | "module"
    start_line: int                 # 1-based inclusive
    end_line: int                   # 1-based inclusive
    parent: Optional[str] = None    # qualified name of the enclosing symbol

    def qualname(self) -> str:
        return f"{self.path}:{self.name}"

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "name": self.name,
            "kind": self.kind,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


@dataclass(frozen=True)
class CallerRef:
    """One caller relationship found for a target symbol.

    `relationship` is the classification (DIRECT_CALL / ATTRIBUTE_CALL /
    IMPORT_REFERENCE / POSSIBLE_CALL / TEXTUAL_MATCH / UNRESOLVED). Only
    the strongest categories ever affect confidence or risk; TEXTUAL_MATCH
    and UNRESOLVED are reported for transparency with zero evidence weight.
    `status` reflects the analyzed revision: LIVE, or DELETED/MODIFIED by
    the analyzed change (diff/commit mode).
    """

    symbol: str                     # caller identity "path:qualname"
    path: str                       # caller file path
    name: str                       # caller symbol name (unqualified)
    line: int                       # first call-site line
    call_sites: int = 1             # number of call sites in the caller
    relationship: str = "UNRESOLVED"
    status: str = "LIVE"
    confidence: str = "LOW"
    text: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "path": self.path,
            "name": self.name,
            "line": self.line,
            "call_sites": self.call_sites,
            "relationship": self.relationship,
            "status": self.status,
            "confidence": self.confidence,
            "text": self.text,
        }


# ---------------------------------------------------------------------------
# Regression detection (Phase 2E)
# ---------------------------------------------------------------------------
#
# Regression findings are EVIDENCE of a historical correction pattern, never
# proof of causation. The type ladder (strongest first):
#
#   EXPLICIT_REVERT          - structured "This reverts commit <sha>" trailer
#                              pointing at a commit related to the target
#   LIKELY_REGRESSION_FIX    - fix language + strong overlap (introducer
#                              reference, or corrective shape AND tests)
#   POSSIBLE_REGRESSION_FIX  - fix language + one weak overlap signal
#   CORRECTIVE_CHANGE        - "Revert"-subject without a trailer, touching
#                              the target file
#   NO_REGRESSION_EVIDENCE   - everything else (never emitted as a finding)
#
# The relationship field describes HOW the corrective commit overlaps the
# target: DIRECT_RANGE_OVERLAP / SYMBOL_OVERLAP / FILE_OVERLAP /
# TEST_EVIDENCE / MESSAGE_REFERENCE / NO_OVERLAP. Correlation is never
# presented as causation: the explanation text says "reverts" / "evidence
# indicates", never "caused the bug".

@dataclass(frozen=True)
class RegressionEvidence:
    """A structured historical regression/fix finding.

    `type` is the classification (see module docstring ladder).
    `original_commit` is the commit whose behavior the corrective commit
    appears to address; `fix_commit` is the corrective commit itself;
    `reverted_commit` is the commit named by an explicit revert trailer.
    `relationship` says how the corrective commit overlaps the target.
    `signals` lists the deterministic signals that drove the decision;
    `explanation` is the carefully-worded human text (never causal).
    """

    type: str
    confidence: str                 # HIGH / MEDIUM / LOW
    relationship: str               # overlap level (see module docstring)
    original_commit: Optional[str] = None
    fix_commit: Optional[str] = None
    reverted_commit: Optional[str] = None
    target_path: str = ""
    target_symbol: Optional[str] = None
    signals: List[str] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "confidence": self.confidence,
            "relationship": self.relationship,
            "original_commit": self.original_commit,
            "fix_commit": self.fix_commit,
            "reverted_commit": self.reverted_commit,
            "target_path": self.target_path,
            "target_symbol": self.target_symbol,
            "signals": self.signals,
            "explanation": self.explanation,
        }


# ---------------------------------------------------------------------------
# Diff mode (--diff)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DiffChange:
    """One changed line inside a diff hunk.

    `side` says which file version the line belongs to: "old" (the HEAD/
    base version) or "new" (the working-tree/staged version). `type` is
    "add" (only on the new side), "del" (only on the old side), or "mod"
    (a paired old/new line that git treats as a modification).
    """

    side: str                       # "old" | "new"
    line: int                       # 1-based line number on that side
    type: str                       # "add" | "del" | "mod"
    text: str                       # raw line content (unsanitized)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DiffRange:
    """A contiguous line range on one side of a hunk."""

    start: int
    end: int

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end}


@dataclass
class DiffGroup:
    """One analyzed region of a changed file.

    A group is one or more hunks whose historical analysis is identical;
    the analyzer merges hunks with the same evidence signature so a large
    diff does not produce dozens of duplicate explanations.

    `ranges` lists the old/new line ranges covered (one per merged hunk);
    `analysis` is the full pipeline AnalysisResult for the region.
    """

    ranges: List[dict] = field(default_factory=list)      # DiffRange dicts
    changes: List[dict] = field(default_factory=list)     # DiffChange dicts
    added_lines: int = 0
    deleted_lines: int = 0
    analysis: dict = field(default_factory=dict)          # AnalysisResult dict
    new_file: bool = False     # True: brand-new file, no base version

    def to_dict(self) -> dict:
        return {
            "ranges": self.ranges,
            "changes": self.changes,
            "added_lines": self.added_lines,
            "deleted_lines": self.deleted_lines,
            "new_file": self.new_file,
            "analysis": self.analysis,
        }


@dataclass
class DiffFile:
    """One changed file in the diff, with its analyzed groups."""

    path: str                       # repo-relative path in the NEW tree
    status: str                     # "A" | "D" | "M" | "R" | "?" (untracked)
    old_path: Optional[str] = None  # previous path for renames/deletes
    groups: List[DiffGroup] = field(default_factory=list)
    movement: Optional[dict] = None  # Movement dict (Phase 2D), or None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "status": self.status,
            "old_path": self.old_path,
            "groups": [g.to_dict() for g in self.groups],
            "movement": self.movement,
        }


@dataclass
class DiffResult:
    """The full structured result of a --diff run."""

    scope: str                      # "worktree" (git diff) | "staged" (--cached)
    repository: dict = field(default_factory=dict)
    files: List[DiffFile] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tool": "agent-blame",
            "version": __version__,
            "mode": "diff",
            "scope": self.scope,
            "repository": self.repository,
            "files": [f.to_dict() for f in self.files],
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Commit mode (--commit)
# ---------------------------------------------------------------------------

@dataclass
class CommitChange:
    """One file changed by the analyzed commit.

    `groups` reuses the DiffGroup structure from --diff (one analyzed
    region per merged hunk group, with the full before-state pipeline
    result in `analysis`). `after` holds the bounded scan of commits that
    touched this file AFTER the target commit (chronologically separate
    from the before-state analysis - never mixed into its evidence).
    """

    path: str                       # path in the target commit's tree
    status: str                     # "A" | "D" | "M" | "R" | "C"
    old_path: Optional[str] = None  # previous path for renames
    groups: List[DiffGroup] = field(default_factory=list)
    after: dict = field(default_factory=dict)  # later-history scan
    movement: Optional[dict] = None  # Movement dict (Phase 2D), or None
    regressions: List[dict] = field(default_factory=list)  # RegressionEvidence dicts (Phase 2E)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "status": self.status,
            "old_path": self.old_path,
            "groups": [g.to_dict() for g in self.groups],
            "after": self.after,
            "movement": self.movement,
            "regressions": self.regressions,
        }


@dataclass
class CommitResult:
    """The full structured result of a --commit run.

    `commit` is the metadata section (sha, parents, author, date, subject,
    body, is_merge, is_root, revert_of). `parent` is the baseline used for
    the before-state analysis (first parent for merges, None for the root
    commit). `changes` is the per-file analysis; each group's `analysis`
    carries its own evidence/confidence/risk.
    """

    sha: str
    commit: dict = field(default_factory=dict)
    parent: Optional[str] = None
    changes: List[CommitChange] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tool": "agent-blame",
            "version": __version__,
            "mode": "commit",
            "commit": self.commit,
            "parent": self.parent,
            "changes": [c.to_dict() for c in self.changes],
            "warnings": self.warnings,
        }


@dataclass
class AnalysisResult:
    """The full structured result of an agent-blame investigation."""

    target: Target
    mode: str                       # "why" | "history" | "risk" | "diff"
    repository: dict = field(default_factory=dict)
    confidence: Confidence = field(default_factory=lambda: Confidence("INSUFFICIENT", 0.0))
    facts: List[dict] = field(default_factory=list)
    inferences: List[dict] = field(default_factory=list)
    evidence: List[dict] = field(default_factory=list)
    counter_evidence: List[dict] = field(default_factory=list)
    callers: List[dict] = field(default_factory=list)   # CallerRef dicts
    symbol: Optional[dict] = None      # resolved target Symbol dict, or None
    movement: Optional[dict] = None    # Movement dict (Phase 2D), or None
    regressions: List[dict] = field(default_factory=list)  # RegressionEvidence dicts (Phase 2E)
    history: List[dict] = field(default_factory=list)
    risk: Risk = field(default_factory=lambda: Risk("UNKNOWN", []))
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tool": "agent-blame",
            "version": __version__,
            "target": self.target.to_dict(),
            "mode": self.mode,
            "repository": self.repository,
            "confidence": self.confidence.to_dict(),
            "facts": self.facts,
            "inferences": self.inferences,
            "evidence": self.evidence,
            "counter_evidence": self.counter_evidence,
            "regressions": self.regressions,
            "callers": self.callers,
            "symbol": self.symbol,
            "movement": self.movement,
            "history": self.history,
            "risk": self.risk.to_dict(),
            "warnings": self.warnings,
        }
