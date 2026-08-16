"""Test fixture: build miniature git repositories with KNOWN histories.

Every fixture records the exact commits and line content so tests can
assert on the ALGORITHM's conclusion, not just that the command ran
(spec section 25: "Test whether the algorithm reaches the correct
historical conclusion").

Security note: fixture repos intentionally contain hostile content
(malicious commit messages, control characters) to exercise the output
sanitization layer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Optional


class GitFixture:
    """A disposable git repository with a scripted history."""

    def __init__(self, author: str = "Fixture Author",
                 email: str = "fixture@example.com"):
        self._tmp = tempfile.mkdtemp(prefix="agent_blame_fixture_")
        self.root = self._tmp
        self._run("init", "-q", "-b", "main")
        self._run("config", "user.name", author)
        self._run("config", "user.email", email)
        self._run("config", "commit.gpgsign", "false")

    # -- git plumbing -----------------------------------------------------

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            ["git", "-C", self.root, *args],
            capture_output=True, text=True, check=False,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)!r} failed: {proc.stderr.strip()}")
        return proc

    def _out(self, *args: str) -> str:
        return self._run(*args).stdout.strip()

    # -- scripted history --------------------------------------------------

    def write(self, path: str, content: str) -> None:
        full = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(full) or self.root, exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)

    def commit(self, message: str, files: Optional[Dict[str, str]] = None,
               when: Optional[str] = None) -> str:
        """Stage the given files (or everything), commit, return the sha."""
        if files is not None:
            for path, content in files.items():
                self.write(path, content)
            self._run("add", "--", *files.keys())
        else:
            self._run("add", "-A")
        env = os.environ.copy()
        if when:
            env["GIT_AUTHOR_DATE"] = when
            env["GIT_COMMITTER_DATE"] = when
        proc = subprocess.run(
            ["git", "-C", self.root, "commit", "-q", "-m", message],
            capture_output=True, text=True, check=False, env=env,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"commit failed: {proc.stderr.strip()}")
        return self._out("rev-parse", "HEAD")

    def rm(self, path: str, message: str) -> str:
        self._run("rm", "-q", path)
        return self.commit(message)

    def mv(self, src: str, dst: str, message: str) -> str:
        # git mv does not create the destination directory itself.
        dst_dir = os.path.dirname(dst)
        if dst_dir:
            os.makedirs(os.path.join(self.root, dst_dir), exist_ok=True)
        self._run("mv", src, dst)
        return self.commit(message)

    def clone_shallow(self) -> "GitFixture":
        """Clone this repo shallowly into a sibling dir, return the clone."""
        target = tempfile.mkdtemp(prefix="agent_blame_shallow_")
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", f"file://{self.root}", target],
            check=True, capture_output=True, text=True,
        )
        clone = GitFixture.__new__(GitFixture)
        clone._tmp = target
        clone.root = target
        return clone

    # -- helpers ------------------------------------------------------------

    @property
    def head(self) -> str:
        return self._out("rev-parse", "HEAD")

    def cat(self, path: str) -> str:
        with open(os.path.join(self.root, path), encoding="utf-8") as fh:
            return fh.read()

    def cleanup(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Scripted histories (spec section 25 / 26)
# ---------------------------------------------------------------------------

def make_introduction_fixture() -> GitFixture:
    """1. Simple introduction: one commit adds a file with a purpose."""
    f = GitFixture()
    f.commit("Add rate-limit handling", {
        "app/retry.py": (
            "import time\n"
            "def retry(fn, n=7):\n"
            "    time.sleep(13)\n"
            "    return fn()\n"
        ),
    })
    return f


def make_evolution_fixture() -> GitFixture:
    """2+3. Introduction, then modification, then a regression test.

    History:
      A: "Add rate-limit handling"           (introduces app/retry.py)
      B: "Fix retry timing for 429s"         (modifies the sleep line)
      C: "Add 429 regression test"           (adds tests/test_retry.py)
    """
    f = GitFixture()
    f.commit("Add rate-limit handling", {
        "app/retry.py": "import time\ndef retry(fn, n=7):\n    time.sleep(13)\n    return fn()\n",
    }, when="2023-02-12T10:00:00+00:00")
    f.commit("Fix retry timing for 429s", {
        "app/retry.py": "import time\ndef retry(fn, n=7):\n    time.sleep(7)\n    return fn()\n",
    }, when="2023-03-04T10:00:00+00:00")
    f.commit("Add 429 regression test", {
        "tests/test_retry.py": "def test_429_backoff():\n    assert True\n",
    }, when="2023-03-05T10:00:00+00:00")
    return f


def make_revert_fixture() -> GitFixture:
    """6. Revert: behavior introduced, then reverted by a later commit."""
    f = GitFixture()
    f.commit("Add retry logic", {
        "app/retry.py": "def retry(fn):\n    return fn()\n",
    })
    f.commit("Remove retry logic", {
        "app/retry.py": "",
    })
    f.commit('Revert "Remove retry logic"', {
        "app/retry.py": "def retry(fn):\n    return fn()\n",
    })
    return f


def make_adversarial_fixture() -> GitFixture:
    """26. Adversarial history: misleading security commit + supersession.

    Commit A says "Fix security issue" but changes an unrelated file.
    Commit B introduces the actual code.
    Commit C removes it. Commit D adds a replacement.
    A simplistic algorithm must NOT credit A's message for B's code.
    """
    f = GitFixture()
    f.commit("Fix security issue", {
        "README.md": "hardened docs\n",
    })
    f.commit("Add legacy cache", {
        "src/legacy/cache.py": (
            "class Cache:\n"
            "    def get(self, k):\n"
            "        return None\n"
        ),
    })
    f.commit("Remove legacy cache", {
        "src/legacy/cache.py": "",
    })
    f.commit("Add new cache", {
        "src/cache.py": (
            "class Cache:\n"
            "    def get(self, k):\n"
            "        return None\n"
        ),
    })
    return f


def make_malicious_message_fixture() -> GitFixture:
    """18. Malicious commit message: ANSI escape sequences.

    The message tries to clear the screen / move the cursor. Output must
    render safely (no control chars leak).
    """
    f = GitFixture()
    evil = "Add feature \x1b[2J\x1b[H\rmalicious \x1b]0;EVIL\x07payload"
    f.commit(evil, {"src/evil.py": "x = 1\n"})
    return f


def make_unicode_fixture() -> GitFixture:
    """20. Unicode paths + content."""
    f = GitFixture()
    f.commit("Add unicode file", {
        "src/émoji/ünïcode.py": "# ünïcode comment\nvalue = 'héllo'\n",
    })
    return f


def make_shallow_fixture() -> GitFixture:
    """14. Shallow clone: history truncated at depth 1."""
    f = GitFixture()
    f.commit("Add deep file", {"src/deep.py": "x = 1\n"})
    f.commit("Modify deep file", {"src/deep.py": "x = 2\n"})
    return f.clone_shallow()


def make_rename_fixture() -> GitFixture:
    """4. Rename: file moved, history should follow it."""
    f = GitFixture()
    f.commit("Add auth module", {
        "src/auth.py": "def login():\n    return True\n",
    })
    f.commit("Fix auth bug", {
        "src/auth.py": "def login():\n    return False\n",
    })
    f.mv("src/auth.py", "src/security/session.py", "Move auth to security")
    return f


def make_deleted_file_fixture() -> GitFixture:
    """13. Deleted file: target was removed from the tree."""
    f = GitFixture()
    f.commit("Add parser", {"src/parser.py": "def parse(s):\n    return s\n"})
    f.rm("src/parser.py", "Remove parser")
    return f


def make_replacement_fixture() -> GitFixture:
    """11. Replacement implementation: old cache removed, new one added IN PLACE.

    History (the file EXISTS at HEAD - the current code superseded the old):
      A: "Add legacy cache"     (introduces src/cache.py, 8 lines)
      B: "Remove legacy cache"  (deletes the whole file - 8 lines removed)
      C: "Add new cache"        (re-adds src/cache.py with new 5-line impl)
    Analyzing src/cache.py:1 blames commit C; B's wholesale deletion must
    surface as replacement counter-evidence and reduce confidence.
    """
    f = GitFixture()
    f.commit("Add legacy cache", {
        "src/cache.py": (
            "class Cache:\n"
            "    def __init__(self):\n"
            "        self._data = {}\n"
            "    def get(self, k):\n"
            "        return self._data.get(k)\n"
            "    def set(self, k, v):\n"
            "        self._data[k] = v\n"
            "    def clear(self):\n"
            "        self._data.clear()\n"
            "    def size(self):\n"
            "        return len(self._data)\n"
        ),
    })
    f.rm("src/cache.py", "Remove legacy cache")
    f.commit("Add new cache", {
        "src/cache.py": (
            "class Cache:\n"
            "    def __init__(self):\n"
            "        self._data = {}\n"
            "    def get(self, k):\n"
            "        return self._data.get(k)\n"
        ),
    })
    return f


def make_merge_fixture() -> GitFixture:
    """7. Merge: a merge commit exists in the file's history.

    Feature modifies line 2, main modifies line 3 of the SAME base file -
    disjoint hunks, so the 3-way merge is clean and a merge commit is
    created (--no-ff).
    """
    f = GitFixture()
    f.commit("Add module", {
        "src/mod.py": "x = 1\nz = 2\nw = 3\nv = 4\nu = 5\nt = 6\n",
    })
    f._run("checkout", "-q", "-b", "feature")
    f.commit("Feature change", {
        "src/mod.py": "x = 1\nz = 99\nw = 3\nv = 4\nu = 5\nt = 6\n",
    })
    f._run("checkout", "-q", "main")
    f.commit("Main change", {
        "src/mod.py": "x = 1\nz = 2\nw = 3\nv = 4\nu = 5\nt = 99\n",
    })
    f._run("merge", "-q", "--no-ff", "feature", "-m", "Merge feature")
    return f


def make_detached_head_fixture() -> GitFixture:
    """Detached HEAD: no branch checked out."""
    f = GitFixture()
    f.commit("Add file", {"src/detached.py": "z = 1\n"})
    f.commit("Modify", {"src/detached.py": "z = 2\n"})
    f._run("checkout", "-q", "HEAD~1")  # detached
    return f
