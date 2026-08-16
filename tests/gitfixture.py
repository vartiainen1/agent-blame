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


# ---------------------------------------------------------------------------
# Phase 2A: --diff fixtures (working-tree / staged changes on top of a
# KNOWN history, so tests can assert the analysis of the change itself)
# ---------------------------------------------------------------------------

def _diff_fx() -> GitFixture:
    """Shared history: a retry module with a known introducing commit.

    History:
      A: "Add rate-limit handling"  (introduces src/retry.py)
      B: "Fix retry timing for 429s" (modifies the sleep line + adds test)
      C: "Add retry regression test" (adds tests/test_retry.py)
    """
    f = GitFixture()
    f.commit("Add rate-limit handling", {
        "src/retry.py": (
            "def retry(fn, n=7):\n"
            "    import time\n"
            "    time.sleep(13)\n"
            "    return fn()\n"
        ),
    })
    f.commit("Fix retry timing for 429s", {
        "src/retry.py": (
            "def retry(fn, n=7):\n"
            "    import time\n"
            "    time.sleep(7)\n"
            "    return fn()\n"
        ),
    })
    f.commit("Add retry regression test", {
        "tests/test_retry.py": "def test_429_backoff():\n    assert True\n",
    })
    return f


def make_diff_modify_fixture() -> GitFixture:
    """Diff fixture: one historically meaningful line modified.

    Working tree changes line 3 of src/retry.py (time.sleep(7) -> 5): the
    line was introduced by commit B ("Fix retry timing for 429s"), so the
    --diff analysis must credit B, not A.
    """
    f = _diff_fx()
    f.write("src/retry.py", (
        "def retry(fn, n=7):\n"
        "    import time\n"
        "    time.sleep(5)\n"
        "    return fn()\n"
    ))
    return f


def make_diff_add_fixture() -> GitFixture:
    """Diff fixture: a completely new line added (no previous line history).

    Adds a new logging line at the end of src/retry.py. The added line has
    no direct historical evidence - the analyzer must say so, not fabricate
    an introducing commit for it, and must analyze the surrounding context.
    """
    f = _diff_fx()
    f.write("src/retry.py", (
        "def retry(fn, n=7):\n"
        "    import time\n"
        "    time.sleep(7)\n"
        "    return fn()\n"
        "    print('retrying')\n"
    ))
    return f


def make_diff_new_file_fixture() -> GitFixture:
    """Diff fixture: a brand-new file (untracked in the worktree)."""
    f = _diff_fx()
    f.write("src/backoff.py", "def backoff():\n    return 1\n")
    return f


def make_diff_staged_fixture() -> GitFixture:
    """Diff fixture: staged changes (git add) only.

    The working tree is CLEAN (nothing unstaged); only the index differs
    from HEAD. `--diff` (worktree) sees nothing; `--diff --staged` sees
    the modification of the historically meaningful line.
    """
    f = _diff_fx()
    f.write("src/retry.py", (
        "def retry(fn, n=7):\n"
        "    import time\n"
        "    time.sleep(3)\n"
        "    return fn()\n"
    ))
    f._run("add", "--", "src/retry.py")
    return f


def make_diff_deleted_fixture() -> GitFixture:
    """Diff fixture: a historically meaningful file deleted (unstaged).

    src/retry.py (introduced by commit A, later fixed) is deleted from the
    working tree without being staged. The analysis must target the
    PREVIOUS revision and surface the full history + risk of removing it.
    """
    f = _diff_fx()
    os.remove(os.path.join(f.root, "src/retry.py"))
    return f


def make_diff_rename_fixture() -> GitFixture:
    """Diff fixture: a file renamed with a content change (staged).

    The rename is staged (git mv), so it only appears with --staged. The
    content change inside the renamed file is a modification of the
    historically meaningful line.
    """
    f = _diff_fx()
    f._run("mv", "src/retry.py", "src/session.py")
    f.write("src/session.py", (
        "def retry(fn, n=7):\n"
        "    import time\n"
        "    time.sleep(5)\n"
        "    return fn()\n"
    ))
    # Stage both the rename and the content change so --staged sees a
    # rename-with-modification (the realistic review scenario).
    f._run("add", "-A")
    return f


def make_diff_malicious_fixture() -> GitFixture:
    """Diff fixture: malicious content in the changed lines.

    The modified line contains ANSI/control sequences. The terminal output
    must render safely (sanitized), and JSON must stay clean.
    """
    f = _diff_fx()
    f.write("src/retry.py", (
        "def retry(fn, n=7):\n"
        "    import time\n"
        "    time.sleep(7)  # \x1b[2J\x1b[H evil\n"
        "    return fn()\n"
    ))
    return f


def make_diff_unicode_fixture() -> GitFixture:
    """Diff fixture: a modified file with a Unicode path."""
    f = GitFixture()
    f.commit("Add unicode module", {
        "src/ünïcode/mod.py": "value = 1\n",
    })
    f.write("src/ünïcode/mod.py", "value = 2\n")
    return f


def make_diff_revert_fixture() -> GitFixture:
    """Diff fixture: reverting a historically reverted line.

    History: line introduced, removed, restored by revert. The working
    tree then modifies that reverted line again - the analysis must
    surface the revert history (counter-evidence / risk) for the region.
    """
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
    f.write("app/retry.py", "def retry(fn, n=3):\n    return fn()\n")
    return f


def make_diff_empty_fixture() -> GitFixture:
    """Diff fixture: no changes at all (clean working tree + index)."""
    return _diff_fx()


def make_diff_multi_hunk_fixture() -> GitFixture:
    """Diff fixture: several changed regions sharing one introducing commit.

    src/multi.py introduced by ONE commit with several independent lines;
    the working tree modifies multiple regions. All changed lines share
    the same introducing commit and evidence - the analyzer must produce
    ONE group (aggregated), not one explanation per changed line.
    """
    f = GitFixture()
    f.commit("Add multi module", {
        "src/multi.py": (
            "alpha = 1\n"
            "beta = 2\n"
            "gamma = 3\n"
            "delta = 4\n"
            "epsilon = 5\n"
            "zeta = 6\n"
            "eta = 7\n"
            "theta = 8\n"
            "iota = 9\n"
            "kappa = 10\n"
        ),
    })
    f.write("src/multi.py", (
        "alpha = 100\n"
        "beta = 2\n"
        "gamma = 300\n"
        "delta = 4\n"
        "epsilon = 500\n"
        "zeta = 6\n"
        "eta = 700\n"
        "theta = 8\n"
        "iota = 900\n"
        "kappa = 10\n"
    ))
    return f


def make_diff_whitespace_fixture() -> GitFixture:
    """Diff fixture: whitespace-only change to a historically meaningful line.

    The content is semantically identical but the whitespace differs, so
    git reports a modification. The analysis should still credit the
    introducing commit (blame uses -w, so whitespace-only hunks attribute
    to the original introducer).
    """
    f = _diff_fx()
    f.write("src/retry.py", (
        "def retry(fn, n=7):\n"
        "    import time\n"
        "    time.sleep(7)   \n"
        "    return fn()\n"
    ))
    return f


# ---------------------------------------------------------------------------
# Phase 2B: --commit fixtures. Each records the exact shas in `f.shas` so
# tests can assert chronology (the analyzed commit must never be credited
# as the origin of the behavior it changes).
# ---------------------------------------------------------------------------

def make_commit_evolution_fixture() -> GitFixture:
    """Commit fixture: A introduces, B fixes, C adds a regression test.

    Analyzing B must attribute the line B changes to A (the introducer of
    the PREVIOUS behavior) and never to B itself; the after-scan must show
    C as a later commit touching the file.
    """
    f = GitFixture()
    a = f.commit("Add rate-limit handling", {
        "src/retry.py": (
            "def retry(fn, n=7):\n"
            "    import time\n"
            "    time.sleep(13)\n"
            "    return fn()\n"
        ),
    })
    b = f.commit("Fix retry timing for 429s", {
        "src/retry.py": (
            "def retry(fn, n=7):\n"
            "    import time\n"
            "    time.sleep(7)\n"
            "    return fn()\n"
        ),
    })
    c = f.commit("Add retry regression test", {
        "tests/test_retry.py": "def test_429_backoff():\n    assert True\n",
    })
    f.shas = {"A": a, "B": b, "C": c}
    return f


def make_commit_revert_fixture() -> GitFixture:
    """Commit fixture: A introduces, B changes, C reverts B (standard trailer).

    Analyzing C (spec section 21) must:
      - expose revert_of == B (deterministic message reference)
      - attribute the previous behavior to B, never to C
      - not contain C anywhere in the before-state facts/history
    """
    f = GitFixture()
    a = f.commit("Add retry logic", {
        "app/retry.py": "def retry(fn):\n    return fn()\n",
    })
    b = f.commit("Add timeout to retry", {
        "app/retry.py": "def retry(fn, timeout=5):\n    return fn()\n",
    })
    c = f.commit(
        'Revert "Add timeout to retry"\n\nThis reverts commit ' + b + ".",
        {"app/retry.py": "def retry(fn):\n    return fn()\n"},
    )
    f.shas = {"A": a, "B": b, "C": c}
    return f


def make_commit_root_fixture() -> GitFixture:
    """Commit fixture: the repository's root commit (no parent)."""
    f = GitFixture()
    a = f.commit("Initial commit", {
        "README.md": "# hi\n",
        "src/init.py": "x = 1\n",
    })
    f.shas = {"A": a}
    return f


def make_commit_add_fixture() -> GitFixture:
    """Commit fixture: B adds a brand-new file (no base version)."""
    f = GitFixture()
    a = f.commit("Add module", {"src/mod.py": "m = 1\n"})
    b = f.commit("Add tests", {"tests/test_mod.py": "def test_m():\n    assert True\n"})
    f.shas = {"A": a, "B": b}
    return f


def make_commit_delete_fixture() -> GitFixture:
    """Commit fixture: B deletes a file with known history."""
    f = GitFixture()
    a = f.commit("Add parser", {"src/parser.py": "def parse(s):\n    return s\n"})
    b = f.rm("src/parser.py", "Remove parser")
    f.shas = {"A": a, "B": b}
    return f


def make_commit_rename_fixture() -> GitFixture:
    """Commit fixture: C renames src/auth.py -> src/security/session.py.

    The analysis must follow the history through the pre-rename path.
    """
    f = GitFixture()
    a = f.commit("Add auth module", {"src/auth.py": "def login():\n    return True\n"})
    b = f.commit("Fix auth bug", {"src/auth.py": "def login():\n    return False\n"})
    c = f.mv("src/auth.py", "src/security/session.py", "Move auth to security")
    f.shas = {"A": a, "B": b, "C": c}
    return f


def make_commit_multi_fixture() -> GitFixture:
    """Commit fixture: B changes TWO files; one has multiple hunks sharing
    the same introducing commit (must merge into one group)."""
    f = GitFixture()
    a = f.commit("Add modules", {
        "src/multi.py": (
            "alpha = 1\nbeta = 2\ngamma = 3\ndelta = 4\nepsilon = 5\n"
            "zeta = 6\neta = 7\ntheta = 8\niota = 9\nkappa = 10\n"
        ),
        "src/other.py": "x = 1\n",
    })
    b = f.commit("Wire modules together", {
        "src/multi.py": (
            "alpha = 100\nbeta = 2\ngamma = 300\ndelta = 4\nepsilon = 500\n"
            "zeta = 6\neta = 700\ntheta = 8\niota = 900\nkappa = 10\n"
        ),
        "src/other.py": "x = 1\nimport multi\n",
    })
    f.shas = {"A": a, "B": b}
    return f


def make_commit_binary_fixture() -> GitFixture:
    """Commit fixture: B adds a binary file (content must not be parsed)."""
    f = GitFixture()
    a = f.commit("Add module", {"src/mod.py": "m = 1\n"})
    with open(os.path.join(f.root, "src/data.bin"), "wb") as fh:
        fh.write(b"\x00\x01\x02\xffBINARY\x00")
    f._run("add", "--", "src/data.bin")
    b = f.commit("Add binary blob")
    f.shas = {"A": a, "B": b}
    return f


def make_commit_unicode_fixture() -> GitFixture:
    """Commit fixture: B modifies a file with a Unicode path."""
    f = GitFixture()
    a = f.commit("Add unicode module", {"src/ünïcode/mod.py": "value = 1\n"})
    b = f.commit("Fix unicode module", {"src/ünïcode/mod.py": "value = 2\n"})
    f.shas = {"A": a, "B": b}
    return f


def make_commit_reverted_later_fixture() -> GitFixture:
    """Commit fixture: A adds, B changes, C changes again, D reverts C.

    Analyzing C: the AFTER-scan must surface D as a later revert of this
    change (contradictory signal), while C itself stays out of the
    before-state facts.
    """
    f = GitFixture()
    a = f.commit("Add retry logic", {
        "app/retry.py": "def retry(fn):\n    return fn()\n",
    })
    b = f.commit("Add timeout", {
        "app/retry.py": "def retry(fn, timeout=5):\n    return fn()\n",
    })
    c = f.commit("Fix timeout to 10", {
        "app/retry.py": "def retry(fn, timeout=10):\n    return fn()\n",
    })
    d = f.commit(
        'Revert "Fix timeout to 10"\n\nThis reverts commit ' + c + ".",
        {"app/retry.py": "def retry(fn, timeout=5):\n    return fn()\n"},
    )
    f.shas = {"A": a, "B": b, "C": c, "D": d}
    return f


def make_commit_malicious_fixture() -> GitFixture:
    """Commit fixture: B's message carries ANSI/control sequences.

    Terminal and JSON output must stay clean (sanitized) for --commit too.
    """
    f = GitFixture()
    a = f.commit("Add module", {"src/mod.py": "m = 1\n"})
    evil = "Fix thing \x1b[2J\x1b[H\r oops \x1b]0;EVIL\x07payload"
    b = f.commit(evil, {"src/mod.py": "m = 2\n"})
    f.shas = {"A": a, "B": b}
    return f


# ---------------------------------------------------------------------------
# Phase 2C: caller/symbol fixtures. Each has a KNOWN structure so tests can
# assert exact relationship classifications (DIRECT_CALL vs POSSIBLE_CALL vs
# TEXTUAL_MATCH) - the false-positive guarantees are the point of this phase.
# ---------------------------------------------------------------------------

def _caller_auth() -> dict:
    """The canonical target module used by most caller fixtures."""
    return {"src/auth.py": "def authenticate():\n    return True\n"}


def _caller_server() -> dict:
    """A file that imports and calls authenticate() from auth."""
    return {
        "src/server.py": (
            "from auth import authenticate\n"
            "\n"
            "def handle_request():\n"
            "    authenticate()\n"
        ),
    }


def make_caller_simple_fixture() -> GitFixture:
    """1. Simple direct caller: handle_request -> authenticate()."""
    f = GitFixture()
    a = f.commit("Add auth module", _caller_auth())
    b = f.commit("Add request handler", _caller_server())
    f.shas = {"A": a, "B": b}
    return f


def make_caller_multiple_fixture() -> GitFixture:
    """2. Multiple callers across two files."""
    f = GitFixture()
    a = f.commit("Add auth module", _caller_auth())
    b = f.commit("Add handlers", {
        ** _caller_server(),
        "src/worker.py": (
            "from auth import authenticate\n"
            "\n"
            "def run_job():\n"
            "    authenticate()\n"
        ),
    })
    f.shas = {"A": a, "B": b}
    return f


def make_caller_method_fixture() -> GitFixture:
    """3+4. Method target: instance call (POSSIBLE) + class call (DIRECT)."""
    f = GitFixture()
    f.commit("Add auth class", {
        "src/auth.py": (
            "class Auth:\n"
            "    def check(self):\n"
            "        return True\n"
        ),
        "src/server.py": (
            "from auth import Auth\n"
            "\n"
            "def handle():\n"
            "    a = Auth()\n"
            "    a.check()\n"
            "    return Auth.check(a)\n"
        ),
    })
    return f


def make_caller_aliased_fixture() -> GitFixture:
    """6. Aliased import: `from auth import authenticate as auth_fn`."""
    f = GitFixture()
    f.commit("Add auth", {
        ** _caller_auth(),
        "src/a1.py": (
            "from auth import authenticate as auth_fn\n"
            "\n"
            "def go():\n"
            "    auth_fn()\n"
        ),
    })
    return f


def make_caller_attribute_fixture() -> GitFixture:
    """7. Attribute call: `import auth; auth.authenticate()`."""
    f = GitFixture()
    f.commit("Add auth", {
        ** _caller_auth(),
        "src/a2.py": (
            "import auth\n"
            "\n"
            "def go():\n"
            "    auth.authenticate()\n"
        ),
    })
    return f


def make_caller_nested_fixture() -> GitFixture:
    """8. Nested function: outer() calls inner()."""
    f = GitFixture()
    f.commit("Add nested", {
        "src/nest.py": (
            "def outer():\n"
            "    def inner():\n"
            "        return 1\n"
            "    return inner()\n"
        ),
    })
    return f


def make_caller_deleted_fixture() -> GitFixture:
    """9. Deleted caller: a commit removes the caller file."""
    f = GitFixture()
    a = f.commit("Add auth module", _caller_auth())
    b = f.commit("Add request handler", _caller_server())
    c = f.rm("src/server.py", "Remove request handler")
    f.shas = {"A": a, "B": b, "C": c}
    return f


def make_caller_history_fixture() -> GitFixture:
    """10. Caller introduced later: caller exists only after commit B."""
    f = GitFixture()
    a = f.commit("Add auth module", _caller_auth())
    b = f.commit("Add request handler", _caller_server())
    f.shas = {"A": a, "B": b}
    return f


def make_caller_removed_fixture() -> GitFixture:
    """11. Caller removed later: commit C drops the call from server.py."""
    f = GitFixture()
    a = f.commit("Add auth module", _caller_auth())
    b = f.commit("Add request handler", _caller_server())
    c = f.commit("Drop auth usage", {
        "src/server.py": (
            "def handle_request():\n"
            "    return None\n"
        ),
    })
    f.shas = {"A": a, "B": b, "C": c}
    return f


def make_caller_none_fixture() -> GitFixture:
    """12. No callers: the symbol is referenced nowhere."""
    f = GitFixture()
    f.commit("Add auth module", _caller_auth())
    return f


def make_caller_ambiguous_fixture() -> GitFixture:
    """13. Ambiguous caller: bare name call with NO import - must NOT be
    claimed as a confirmed caller (POSSIBLE_CALL at most)."""
    f = GitFixture()
    f.commit("Add auth", {
        ** _caller_auth(),
        "src/worker.py": (
            "def run():\n"
            "    authenticate()\n"
        ),
    })
    return f


def make_caller_same_name_fixture() -> GitFixture:
    """14+17. Same symbol name in two modules: only the matching module's
    import/usage may be credited as a caller of each."""
    f = GitFixture()
    f.commit("Add modules", {
        "src/mod_a.py": "def authenticate():\n    return 1\n",
        "src/mod_b.py": "def authenticate():\n    return 2\n",
        "src/use_a.py": (
            "from mod_a import authenticate\n"
            "\n"
            "def go():\n"
            "    authenticate()\n"
        ),
    })
    return f


def make_caller_false_positive_fixture() -> GitFixture:
    """15. Comment/string false positives: `text = "authenticate()"`,
    `# authenticate()`, and `def authenticate_other` must NOT be callers."""
    f = GitFixture()
    f.commit("Add auth", {
        ** _caller_auth(),
        "src/tricks.py": (
            'text = "authenticate()"\n'
            "# authenticate()\n"
            "def authenticate_other():\n"
            "    return 1\n"
        ),
    })
    return f


def make_caller_unicode_fixture() -> GitFixture:
    """16. Unicode path: caller in a Unicode-named directory."""
    f = GitFixture()
    f.commit("Add auth", {
        ** _caller_auth(),
        "src/ünïcode/handler.py": (
            "from auth import authenticate\n"
            "\n"
            "def go():\n"
            "    authenticate()\n"
        ),
    })
    return f


def make_caller_unsupported_fixture() -> GitFixture:
    """17. Unsupported language: no symbol analysis, honest absence."""
    f = GitFixture()
    f.commit("Add js", {
        "src/app.js": "function authenticate() { return 1; }\n",
        "src/main.js": "authenticate();\n",
    })
    return f


def make_caller_malicious_fixture() -> GitFixture:
    """21. Malicious source content (ANSI in strings) + a real caller."""
    f = GitFixture()
    f.commit("Add auth", {
        "src/auth.py": "def authenticate():\n    return '\x1b[2J\x1b[H evil'\n",
        "src/caller.py": (
            "from auth import authenticate\n"
            "\n"
            "def go():\n"
            "    authenticate()\n"
        ),
    })
    return f


def make_caller_large_fixture(n_files: int = 120) -> GitFixture:
    """22. Large repository: N python files, ONE real caller."""
    f = GitFixture()
    files = {"src/auth.py": "def authenticate():\n    return True\n"}
    for i in range(n_files):
        files[f"src/mod_{i:03d}.py"] = f"def fn_{i}():\n    return {i}\n"
    files["src/use_auth.py"] = (
        "from auth import authenticate\n"
        "\n"
        "def go():\n"
        "    authenticate()\n"
    )
    f.commit("Add many modules", files)
    return f


def make_caller_diff_fixture() -> GitFixture:
    """19. --diff integration: the worktree modifies authenticate()."""
    f = make_caller_simple_fixture()
    f.write("src/auth.py", "def authenticate(force=False):\n    return True\n")
    return f


def make_caller_modify_commit_fixture() -> GitFixture:
    """20. --commit integration: commit C modifies authenticate(); its
    before-state analysis must still find the LIVE caller from B."""
    f = GitFixture()
    a = f.commit("Add auth module", _caller_auth())
    b = f.commit("Add request handler", _caller_server())
    c = f.commit("Add force flag", {
        "src/auth.py": "def authenticate(force=False):\n    return True\n",
    })
    f.shas = {"A": a, "B": b, "C": c}
    return f


# ---------------------------------------------------------------------------
# Phase 2D: code-movement / rename fixtures. Each has a KNOWN movement
# chain so tests can assert the central property of the phase:
#
#     MOVEMENT must never be reported as INTRODUCTION.
#
# The fixtures deliberately include the cases git's own similarity
# detection gets wrong (partial moves) - those are the ones that would
# otherwise blame the MOVE commit as the origin.
# ---------------------------------------------------------------------------

def make_movement_pure_rename_fixture() -> GitFixture:
    """1+2. Pure file rename, then a modification after the rename.

    A: "Add foo in old.py"        (introduces old.py)
    B: "Rename to new.py"         (git mv - 100% similarity, blame follows)
    C: "Modify foo"               (changes the body after the move)
    """
    f = GitFixture()
    a = f.commit("Add foo in old.py", {
        "old.py": "def foo():\n    return 1\n",
    })
    b = f.mv("old.py", "new.py", "Rename to new.py")
    c = f.commit("Modify foo", {
        "new.py": "def foo():\n    return 2\n",
    })
    f.shas = {"A": a, "B": b, "C": c}
    return f


def make_movement_partial_fixture() -> GitFixture:
    """3. PARTIAL move (the dangerous case): foo moves out of old.py while
    bar stays - git's similarity threshold misses the move entirely.

    A: "Add foo and bar in old.py"   (old.py has foo + bar)
    B: "Move foo to new.py"          (new.py gets foo; old.py keeps bar)

    git blame on new.py credits B (the MOVER). Phase 2D must correct this
    to: moved by B, originally introduced by A (the mandatory spec 2D/23
    property: agent-blame new.py:<line> must NOT report "introduced by B").
    """
    f = GitFixture()
    a = f.commit("Add foo and bar in old.py", {
        "old.py": "def foo():\n    return 1\n\ndef bar():\n    return 2\n",
    })
    b = f.commit("Move foo to new.py", {
        "old.py": "def bar():\n    return 2\n",
        "new.py": "def foo():\n    return 1\n",
    })
    f.shas = {"A": a, "B": b}
    return f


def make_movement_modified_fixture() -> GitFixture:
    """4. Moved AND modified: the moved body differs (return 2 vs 1)."""
    f = GitFixture()
    a = f.commit("Add foo and bar in old.py", {
        "old.py": "def foo():\n    return 1\n\ndef bar():\n    return 2\n",
    })
    b = f.commit("Move and tweak foo", {
        "old.py": "def bar():\n    return 2\n",
        "new.py": "def foo():\n    return 2\n",
    })
    f.shas = {"A": a, "B": b}
    return f


def make_movement_multiple_fixture() -> GitFixture:
    """10. MULTIPLE sequential moves: old.py -> middle.py -> new.py.

    The chain must trace through BOTH moves back to A (bounded walk).
    """
    f = GitFixture()
    a = f.commit("Add foo in old.py", {"old.py": "def foo():\n    return 1\n"})
    b = f.mv("old.py", "middle.py", "Move to middle.py")
    c = f.mv("middle.py", "new.py", "Move to new.py")
    f.shas = {"A": a, "B": b, "C": c}
    return f


def make_movement_copy_fixture() -> GitFixture:
    """9. COPY: new.py gets foo while old.py KEEPS it - never a move."""
    f = GitFixture()
    a = f.commit("Add foo in old.py", {"old.py": "def foo():\n    return 1\n"})
    b = f.commit("Copy foo to new.py", {
        "old.py": "def foo():\n    return 1\n",
        "new.py": "def foo():\n    return 1\n",
    })
    f.shas = {"A": a, "B": b}
    return f


def make_movement_ambiguous_fixture() -> GitFixture:
    """17. AMBIGUOUS: two identical same-name symbols at different paths;
    both deleted, one identical copy appears elsewhere. The origin cannot
    be pinned to one - POSSIBLE_MOVEMENT / AMBIGUOUS, never a confident
    claim of a specific origin."""
    f = GitFixture()
    a = f.commit("Add duplicate runners", {
        "mod_a.py": "def run():\n    return 1\n",
        "mod_b.py": "def run():\n    return 1\n",
    })
    import os as _os
    _os.remove(_os.path.join(f.root, "mod_a.py"))
    _os.remove(_os.path.join(f.root, "mod_b.py"))
    f.write("new.py", "def run():\n    return 1\n")
    b = f.commit("Move a run() to new.py")  # add -A: deletes + new file
    f.shas = {"A": a, "B": b}
    return f


def make_movement_same_name_fixture() -> GitFixture:
    """7. Same-name unrelated symbols: two `run()` definitions with
    DIFFERENT bodies; the move must pick the structurally identical one."""
    f = GitFixture()
    a = f.commit("Add runners", {
        "mod_a.py": "def run():\n    return 999\n",
        "old.py": "def run():\n    return 1\n",
    })
    b = f.commit("Move run to new.py", {
        "new.py": "def run():\n    return 1\n",
    })
    f.shas = {"A": a, "B": b}
    return f


def make_movement_unicode_fixture() -> GitFixture:
    """16. Unicode paths: a file with a Unicode name moved to another
    Unicode path."""
    f = GitFixture()
    a = f.commit("Add unicode module", {
        "src/ünïcode/old.py": "def foo():\n    return 1\n",
    })
    b = f.mv("src/ünïcode/old.py", "src/émoji/new.py",
             "Move to unicode path")
    f.shas = {"A": a, "B": b}
    return f


def make_movement_unsupported_fixture() -> GitFixture:
    """19. Unsupported language: a .js file moved - no symbol claim."""
    f = GitFixture()
    a = f.commit("Add js module", {"old.js": "function foo() { return 1; }\n"})
    b = f.mv("old.js", "new.js", "Rename js file")
    f.shas = {"A": a, "B": b}
    return f


def make_movement_malicious_fixture() -> GitFixture:
    """18. Malicious content inside moved code (ANSI in a string) - the
    analysis must not crash and output must stay sanitized. The source is
    genuinely removed (a real move), so the move is confirmed."""
    f = GitFixture()
    a = f.commit("Add foo", {"old.py": "def foo():\n    return '\x1b[2J\x1b[H evil'\n"})
    import os as _os
    _os.remove(_os.path.join(f.root, "old.py"))
    f.write("new.py", "def foo():\n    return '\x1b[2J\x1b[H evil'\n")
    b = f.commit("Move foo")   # add -A stages the deletion + the new file
    f.shas = {"A": a, "B": b}
    return f


def make_movement_diff_fixture() -> GitFixture:
    """20. --diff integration: worktree rename (old.py deleted from the
    tree, new.py untracked with the moved content)."""
    f = GitFixture()
    a = f.commit("Add foo and bar", {
        "old.py": "def foo():\n    return 1\n\ndef bar():\n    return 2\n",
    })
    import os as _os
    _os.remove(_os.path.join(f.root, "old.py"))
    f.write("new.py", "def foo():\n    return 1\n")
    f.shas = {"A": a}
    return f


def make_movement_commit_fixture() -> GitFixture:
    """21. --commit integration: B is the partial-move commit itself."""
    f = GitFixture()
    a = f.commit("Add foo and bar in old.py", {
        "old.py": "def foo():\n    return 1\n\ndef bar():\n    return 2\n",
    })
    b = f.commit("Move foo to new.py", {
        "old.py": "def bar():\n    return 2\n",
        "new.py": "def foo():\n    return 1\n",
    })
    f.shas = {"A": a, "B": b}
    return f


# ---------------------------------------------------------------------------
# Phase 2E: regression-detection fixtures. Each records the exact shas so
# tests can assert the CLASSIFICATION (EXPLICIT_REVERT / LIKELY /
# POSSIBLE / CORRECTIVE_CHANGE / none) and the careful, non-causal wording.
# ---------------------------------------------------------------------------

def _retry_with(sleep_value: str) -> str:
    return ("import time\n"
            "def retry(fn, n=7):\n"
            f"    time.sleep({sleep_value})\n"
            "    return fn()\n")


def make_regression_revert_sequence_fixture() -> GitFixture:
    """1. A introduces, B modifies, C reverts B (structured trailer), D
    modifies again. Standalone WHY on D's lines must find C's revert of B
    (EXPLICIT_REVERT, FILE_OVERLAP) and B's fix+test (POSSIBLE)."""
    f = GitFixture()
    a = f.commit("Add retry with sleep 13", {
        "app/retry.py": _retry_with(13),
    }, when="2023-01-01T10:00:00+00:00")
    b = f.commit("Fix retry timing for 429s", {
        "app/retry.py": _retry_with(7),
        "tests/test_retry.py": "def test_429_backoff():\n    assert True\n",
    }, when="2023-02-01T10:00:00+00:00")
    c = f.commit(
        'Revert "Fix retry timing for 429s"\n\nThis reverts commit ' + b + ".",
        {"app/retry.py": _retry_with(13)},
        when="2023-03-01T10:00:00+00:00")
    d = f.commit("Make retry configurable", {
        "app/retry.py": (
            "import time\ndef retry(fn, n=7, delay=13):\n"
            "    time.sleep(delay)\n    return fn()\n"
        ),
    }, when="2023-04-01T10:00:00+00:00")
    f.shas = {"A": a, "B": b, "C": c, "D": d}
    return f


def make_regression_fix_sequence_fixture() -> GitFixture:
    """5. A introduces, B fixes with corrective shape + tests (LIKELY)."""
    f = GitFixture()
    a = f.commit("Add retry with sleep 13", {
        "app/retry.py": _retry_with(13),
    })
    b = f.commit("Fix retry timing for 429s", {
        "app/retry.py": _retry_with(7),
        "tests/test_retry.py": "def test_429_backoff():\n    assert True\n",
    })
    f.shas = {"A": a, "B": b}
    return f


def make_regression_no_false_positive_fixture() -> GitFixture:
    """6. Property tests: "fix" language with NO overlap must produce
    nothing; a revert of an UNRELATED file must produce nothing.

    A introduces retry.py + README. B says "Fix README typo" but only
    touches README (no overlap with retry.py). C reverts B (trailer) -
    again only README. Analyzing retry.py must find NO regression
    findings (Properties 5/6 + revert of unrelated file).
    """
    f = GitFixture()
    a = f.commit("Add retry logic", {
        "app/retry.py": _retry_with(13),
        "README.md": "# project\n",
    })
    b = f.commit("Fix README typo", {
        "README.md": "# project (fixed)\n",
    })
    c = f.commit(
        'Revert "Fix README typo"\n\nThis reverts commit ' + b + ".",
        {"README.md": "# project\n"},
    )
    f.shas = {"A": a, "B": b, "C": c}
    return f


def make_regression_corrective_fixture() -> GitFixture:
    """9. A "Revert ..." subject WITHOUT a trailer touching the file:
    CORRECTIVE_CHANGE (weakened - cannot link to a specific commit).

    B says "Revert retry changes" and modifies the sleep value; C then
    modifies the line again. Analyzing C's line: B is a LATER commit with
    a revert subject but no structured trailer -> CORRECTIVE_CHANGE.
    """
    f = GitFixture()
    a = f.commit("Add retry logic", {
        "app/retry.py": _retry_with(13),
    })
    b = f.commit("Revert retry changes", {
        "app/retry.py": _retry_with(7),
    })
    c = f.commit("Add configurable delay", {
        "app/retry.py": (
            "import time\ndef retry(fn, n=7, delay=13):\n"
            "    time.sleep(delay)\n    return fn()\n"
        ),
    })
    f.shas = {"A": a, "B": b, "C": c}
    return f


def make_regression_moved_then_fixed_fixture() -> GitFixture:
    """8. Regression followed by movement: A introduces foo, B moves it,
    C fixes it. Property 3: the fix sequence must preserve symbol identity
    through the move (the finding names the ORIGINAL introducer A)."""
    f = GitFixture()
    a = f.commit("Add foo with bug", {
        "old.py": "def foo():\n    return 1\n",
    })
    b = f.mv("old.py", "new.py", "Move foo to new.py")
    c = f.commit("Fix foo bug", {
        "new.py": "def foo():\n    return 2\n",
    })
    f.shas = {"A": a, "B": b, "C": c}
    return f


def make_regression_commit_revert_fixture() -> GitFixture:
    """22. --commit integration: analyzing C (the revert commit) must
    classify it as EXPLICIT_REVERT with the reverted commit B as origin."""
    f = GitFixture()
    a = f.commit("Add retry logic", {
        "app/retry.py": "def retry(fn):\n    return fn()\n",
    })
    b = f.commit("Add timeout to retry", {
        "app/retry.py": "def retry(fn, timeout=5):\n    return fn()\n",
    })
    c = f.commit(
        'Revert "Add timeout to retry"\n\nThis reverts commit ' + b + ".",
        {"app/retry.py": "def retry(fn):\n    return fn()\n"},
    )
    f.shas = {"A": a, "B": b, "C": c}
    return f


def make_regression_commit_after_revert_fixture() -> GitFixture:
    """24. --commit integration: analyzing C when D later reverts C - the
    AFTER-scan must classify D as EXPLICIT_REVERT of this commit."""
    f = GitFixture()
    a = f.commit("Add retry logic", {
        "app/retry.py": "def retry(fn):\n    return fn()\n",
    })
    b = f.commit("Add timeout", {
        "app/retry.py": "def retry(fn, timeout=5):\n    return fn()\n",
    })
    c = f.commit("Fix timeout to 10", {
        "app/retry.py": "def retry(fn, timeout=10):\n    return fn()\n",
    })
    d = f.commit(
        'Revert "Fix timeout to 10"\n\nThis reverts commit ' + c + ".",
        {"app/retry.py": "def retry(fn, timeout=5):\n    return fn()\n"},
    )
    f.shas = {"A": a, "B": b, "C": c, "D": d}
    return f


def make_regression_malicious_fixture() -> GitFixture:
    """19. Malicious commit message with fix/revert words + ANSI escapes -
    must not crash and must not be misclassified by the escape junk. B's
    only change to retry.py is a comment OUTSIDE any symbol (no overlap)."""
    f = GitFixture()
    a = f.commit("Add retry logic", {
        "app/retry.py": _retry_with(13),
    })
    evil = "fix \x1b[2J\x1b[H\r\x1b]0;EVIL\x07this is not a real fix"
    b = f.commit(evil, {
        "app/retry.py": "# \x1b[2J comment\n" + _retry_with(13),
    })
    f.shas = {"A": a, "B": b}
    return f


def make_regression_unicode_fixture() -> GitFixture:
    """18. Unicode path with a fix sequence."""
    f = GitFixture()
    a = f.commit("Add unicode module", {
        "src/ünïcode/retry.py": _retry_with(13),
    })
    b = f.commit("Fix retry timing", {
        "src/ünïcode/retry.py": _retry_with(7),
        "tests/test_retry.py": "def test_429():\n    assert True\n",
    })
    f.shas = {"A": a, "B": b}
    return f


def make_regression_multiple_fixes_fixture() -> GitFixture:
    """11. Multiple sequential fixes: A introduces, B fixes, C fixes again
    - multiple POSSIBLE/LIKELY findings, deterministic ordering."""
    f = GitFixture()
    a = f.commit("Add retry with sleep 13", {
        "app/retry.py": _retry_with(13),
    })
    b = f.commit("Fix retry timing for 429s", {
        "app/retry.py": _retry_with(7),
    })
    c = f.commit("Fix retry for 503s too", {
        "app/retry.py": _retry_with(5),
        "tests/test_retry.py": "def test_503():\n    assert True\n",
    })
    f.shas = {"A": a, "B": b, "C": c}
    return f


def make_regression_same_symbol_refactor_fixture() -> GitFixture:
    """10. Contradictory evidence: A modifies foo, B modifies foo again
    but is a REFACTOR (no fix language, no removal) - must NOT become a
    regression (Property 4 / 14 counter-evidence)."""
    f = GitFixture()
    a = f.commit("Add foo", {
        "app/foo.py": "def foo():\n    return 1\n",
    })
    b = f.commit("Refactor foo", {
        "app/foo.py": "def foo():\n    return 2\n",
    })
    f.shas = {"A": a, "B": b}
    return f


def make_regression_shallow_fixture() -> GitFixture:
    """16. Shallow repository: history truncated - regression detection
    must not invent findings from missing history."""
    f = GitFixture()
    f.commit("Add retry with sleep 13", {"app/retry.py": _retry_with(13)})
    f.commit("Fix retry timing", {"app/retry.py": _retry_with(7)})
    return f.clone_shallow()


def make_regression_diff_fixture() -> GitFixture:
    """23. --diff integration: the changed line's history contains a fix+
    revert sequence; the diff analysis must surface the regression finding.

    The worktree edits the sleep line (line 3, unchanged at HEAD after the
    revert) so the old-side analysis blames a stable introducer and the
    fix+revert commits appear in the later history."""
    f = GitFixture()
    a = f.commit("Add retry with sleep 13", {
        "app/retry.py": _retry_with(13),
    })
    b = f.commit("Fix retry timing for 429s", {
        "app/retry.py": _retry_with(7),
        "tests/test_retry.py": "def test_429_backoff():\n    assert True\n",
    })
    c = f.commit(
        'Revert "Fix retry timing for 429s"\n\nThis reverts commit ' + b + ".",
        {"app/retry.py": _retry_with(13)},
    )
    # The worktree changes line 3 (sleep 13 at HEAD) - the old side keeps
    # the historical context (fix B + revert C) intact.
    f.write("app/retry.py",
            "import time\ndef retry(fn, n=7, delay=13):\n"
            "    time.sleep(delay)\n    return fn()\n")
    f.shas = {"A": a, "B": b, "C": c}
    return f


def make_regression_deterministic_fixture() -> GitFixture:
    """28. Deterministic repeated execution: the same analysis twice must
    produce byte-identical regression findings."""
    f = GitFixture()
    a = f.commit("Add retry with sleep 13", {
        "app/retry.py": _retry_with(13),
    })
    b = f.commit("Fix retry timing for 429s", {
        "app/retry.py": _retry_with(7),
        "tests/test_retry.py": "def test_429_backoff():\n    assert True\n",
    })
    c = f.commit(
        'Revert "Fix retry timing for 429s"\n\nThis reverts commit ' + b + ".",
        {"app/retry.py": _retry_with(13)},
    )
    d = f.commit("Make retry configurable", {
        "app/retry.py": (
            "import time\ndef retry(fn, n=7, delay=13):\n"
            "    time.sleep(delay)\n    return fn()\n"
        ),
    })
    f.shas = {"A": a, "B": b, "C": c, "D": d}
    return f
