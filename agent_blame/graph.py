"""Historical relationship graph (targeted, not whole-repository).

The graph is built by expanding outward from the requested code along
relationships we can derive deterministically from git data:

    Code
     -> introducing commit (via blame)
     -> commits touching the file (via git log --follow)
     -> same-commit tests / related files (via the introducing diff)

We deliberately do NOT construct the entire repository graph (spec section
6). Expansion is targeted: only commits, files and relationships that are
reachable from the target are materialized.

The graph is a plain dict-of-dicts so it stays JSON-friendly and
deterministic (all iteration is sorted).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .history import blame_target, commit_files, file_commits
from .models import CommitInfo, Target
from .repository import Repository

# Relationship kinds we can derive deterministically (spec section 6).
REL_INTRODUCED_BY = "introduced_by"
REL_MODIFIED_BY = "modified_by"
REL_TOUCHES = "touches"
REL_TESTS = "tests"
REL_REVERTED_BY = "reverted_by"
REL_RENAMED_TO = "renamed_to"

# Test-file detection. Word-boundary aware: "test" must be a whole token
# separated by non-alphanumerics (or a prefix/suffix on the basename), so
# files like latest.py / contest.py / attest.py are NOT classified as
# tests (the naive substring "test" matches them all).
_TEST_TOKEN = re.compile(r"(^|[\W_])(test|tests|spec)([\W_]|$)", re.IGNORECASE)


@dataclass
class HistoricalGraph:
    """A small, targeted graph around a target.

    nodes: dict key -> node dict {type, ...}
    edges: list of (from_key, to_key, relation)
    """

    nodes: Dict[str, dict] = field(default_factory=dict)
    edges: List[tuple] = field(default_factory=list)

    def add_node(self, key: str, kind: str, **attrs) -> None:
        self.nodes.setdefault(key, {"type": kind, **attrs})

    def add_edge(self, frm: str, to: str, relation: str) -> None:
        edge = (frm, to, relation)
        if edge not in self.edges:
            self.edges.append(edge)

    def to_dict(self) -> dict:
        return {
            "nodes": self.nodes,
            "edges": sorted(self.edges, key=lambda e: (e[0], e[1], e[2])),
        }


def _is_test_path(path: str) -> bool:
    """Heuristic: is this path a test file? Conservative and deterministic.

    Matches conventional test file names only:
      - basename starts with test_ / ends with _test / is test, tests, spec
      - a "test"/"tests"/"spec" token delimited by separators or case
        boundaries (e.g. tests/..., foo.test.py, FooSpec.go)
    A name like "latest.py" does NOT match (naive substring would).
    """
    base = path.rsplit("/", 1)[-1].lower()
    stem, _, ext = base.rpartition(".")
    if stem in ("test", "tests", "spec"):
        return True
    if stem.startswith("test_") or stem.endswith("_test") or stem.endswith("_spec"):
        return True
    return bool(_TEST_TOKEN.search(base))


def build_graph(repo: Repository, target: Target,
                blame_lines=None,
                commits: Optional[List[CommitInfo]] = None) -> HistoricalGraph:
    """Build the targeted historical graph for a target.

    `commits` may be pre-fetched by the caller (analyzer fetches once and
    reuses) to avoid re-running `git log` for every stage.

    Returns (graph, introducing_commits, later_commits):
      introducing_commits: commits blamed for introducing the target lines
      later_commits:       commits touching the file, excluding introducers
    """
    g = HistoricalGraph()
    file_key = f"file:{target.file}"
    g.add_node(file_key, "file", path=target.file)

    introducing: Set[str] = set()

    # 1. Blame the target range -> introducing commits per line.
    if blame_lines is None:
        blame_lines = blame_target(repo, target)
    for bl in blame_lines:
        introducing.add(bl.commit)
        line_key = f"line:{target.file}:{bl.line_no}"
        g.add_node(line_key, "line", file=target.file, line=bl.line_no)
        g.add_edge(line_key, f"commit:{bl.commit}", REL_INTRODUCED_BY)
        g.add_edge(file_key, f"commit:{bl.commit}", REL_TOUCHES)

    # 2. All commits touching the file (follow renames), newest first.
    if commits is None:
        commits = file_commits(repo, target.file)
    for ci in commits:
        ckey = f"commit:{ci.sha}"
        g.add_node(ckey, "commit", sha=ci.sha, subject=ci.subject,
                   author_date=ci.author_date)
        g.add_edge(file_key, ckey, REL_TOUCHES)
        if ci.sha in introducing:
            continue  # introducers already linked via blame
        g.add_edge(ckey, file_key, REL_MODIFIED_BY)

    # 3. Same-commit tests: files in the introducing commits' diffs that
    #    look like tests. Edge file -> test.
    for sha in introducing:
        files = commit_files(repo, sha)
        for f in files:
            if _is_test_path(f):
                tkey = f"test:{f}"
                g.add_node(tkey, "test", path=f)
                g.add_edge(file_key, tkey, REL_TESTS)
                g.add_edge(f"commit:{sha}", tkey, REL_TESTS)

    later = [ci.sha for ci in commits if ci.sha not in introducing]
    return g, sorted(introducing), later
