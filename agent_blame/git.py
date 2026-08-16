"""Safe Git abstraction.

Security contract (spec sections 20/21/23):
- Git is always invoked with argument arrays; shell=True is never used.
- Repository-supplied strings (paths, refs, arguments) are passed as argv
  elements, never interpolated into a shell command.
- Every invocation has a timeout so a hanging repository cannot hang us.
- Output is decoded as UTF-8 with errors='replace' - the repository is
  untrusted input and must never be able to crash us via encoding.
- Control characters are stripped only at OUTPUT time (output.py), so the
  raw facts stay intact for analysis while the terminal/JSON stays safe.
"""

from __future__ import annotations

import subprocess
from typing import List, Optional, Tuple


class GitError(Exception):
    """Raised when a git invocation fails (non-zero exit or timeout)."""

    def __init__(self, message: str, args: Optional[List[str]] = None,
                 exit_code: Optional[int] = None, stderr: str = ""):
        super().__init__(message)
        self.args_list = args
        self.exit_code = exit_code
        self.stderr = stderr

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.exit_code is not None:
            parts.append(f"(exit {self.exit_code})")
        if self.stderr:
            parts.append(f"git: {self.stderr.strip()}")
        return " ".join(parts)


# Default timeout for git commands. History-heavy commands can be slow on
# large repositories; callers may pass a larger timeout explicitly.
DEFAULT_TIMEOUT = 60


def run_git(args: List[str], cwd: Optional[str] = None,
            timeout: int = DEFAULT_TIMEOUT,
            check: bool = True) -> Tuple[str, str, int]:
    """Run a git command safely.

    Args are passed as an argv list (never shell). Returns
    (stdout, stderr, exit_code). When `check` is True, a non-zero exit
    raises GitError with a clean message (no raw tracebacks).
    """
    if not args or args[0] != "git":
        args = ["git", *args]
    try:
        proc = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise GitError(
            f"git command timed out after {timeout}s: {' '.join(args)}",
            args=args,
        )
    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise GitError(
            f"git command failed: {' '.join(args)}",
            args=args,
            exit_code=proc.returncode,
            stderr=stderr,
        )
    return stdout, stderr, proc.returncode


def git_output(args: List[str], cwd: Optional[str] = None,
               timeout: int = DEFAULT_TIMEOUT) -> str:
    """Run git and return stdout (raising GitError on failure)."""
    stdout, _stderr, _rc = run_git(args, cwd=cwd, timeout=timeout, check=True)
    return stdout


def git_lines(args: List[str], cwd: Optional[str] = None,
              timeout: int = DEFAULT_TIMEOUT) -> List[str]:
    """Run git and return stdout split into lines (trailing newline kept)."""
    out = git_output(args, cwd=cwd, timeout=timeout)
    if not out:
        return []
    return out.splitlines()


def try_git_output(args: List[str], cwd: Optional[str] = None,
                   timeout: int = DEFAULT_TIMEOUT) -> Optional[str]:
    """Run git, returning None on failure instead of raising.

    Used for probes where absence is a legitimate answer (e.g. "does this
    file exist at HEAD?").
    """
    try:
        return git_output(args, cwd=cwd, timeout=timeout)
    except GitError:
        return None
