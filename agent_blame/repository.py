"""Repository discovery.

Finds the git repository a target belongs to and reports basic facts about
it (root, current head, whether it is a shallow clone). All discovery uses
the safe git wrapper - no shell, no interpolation of repository content.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from .git import try_git_output


@dataclass(frozen=True)
class Repository:
    root: str
    head: str                       # full sha of HEAD (or "" if unborn)
    shallow: bool
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "root": self.root,
            "head": self.head,
            "shallow": self.shallow,
        }
        if self.warnings:
            d["warnings"] = self.warnings
        return d


def _find_git_root(start_dir: str) -> Optional[str]:
    """Walk up from start_dir looking for a .git directory or file."""
    current = os.path.abspath(start_dir)
    while True:
        git_path = os.path.join(current, ".git")
        if os.path.isdir(git_path) or os.path.isfile(git_path):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def discover_repository(start_dir: str) -> Optional[Repository]:
    """Discover the repository containing start_dir (or None if not in one).

    Uses `git rev-parse` from the discovered root so worktrees/submodules
    are handled by git itself rather than by our .git sniffing.
    """
    root = _find_git_root(start_dir)
    if root is None:
        return None

    warnings: List[str] = []

    # HEAD sha - may fail on a fresh repo with no commits yet.
    head = ""
    head_out = try_git_output(["rev-parse", "HEAD"], cwd=root)
    if head_out:
        head = head_out.strip()
    else:
        warnings.append("Repository has no commits yet (unborn HEAD).")

    shallow = False
    shallow_out = try_git_output(["rev-parse", "--is-shallow-repository"], cwd=root)
    if shallow_out and shallow_out.strip() == "true":
        shallow = True

    return Repository(root=root, head=head, shallow=shallow, warnings=warnings)


def resolve_repo_path(repo: Repository, rel_path: str) -> str:
    """Normalize a target path to repo-relative forward-slash form.

    Strips a leading "./" (or absolute-style leading "/") but preserves
    leading DOTfiles (e.g. ".gitignore") - lstrip("./") would eat the dot.
    """
    norm = rel_path.replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    norm = norm.lstrip("/")
    # Refuse paths that would escape the repository root.
    parts = [p for p in norm.split("/") if p not in ("", ".", "..")]
    return "/".join(parts)
