"""agent-blame CLI.

Usage (spec section 30 + Phase 2A):
  agent-blame <file>:<line>            WHY mode (default)
  agent-blame <file>:<start>-<end>     WHY mode with a range
  agent-blame --history <target>       HISTORY mode
  agent-blame --risk <target>          RISK mode
  agent-blame --diff                   DIFF mode: historical context for the
                                       current working-tree changes
  agent-blame --diff --staged          DIFF mode for staged changes only
  agent-blame --commit <rev>           COMMIT mode: historical context for
                                       one commit (sha/abbrev/HEAD/HEAD~1)
  agent-blame --json <target>          machine-readable JSON
  agent-blame --verbose <target>       verbose terminal output

Runs from anywhere inside (or pointing at) a git repository.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .analyzer import analyze
from .diff import analyze_diff
from .models import Target
from .output import (render_commit_terminal, render_diff_terminal,
                     render_json, render_terminal, sanitize)
from .repository import discover_repository, resolve_repo_path
from .target import TargetError, parse_target


_QUICK_START = """\
Quick start (run from inside a git repository):

  agent-blame src/auth/session.py:142     why does this line exist?
  agent-blame --diff                      what history explains my current changes?
  agent-blame --commit d037a21            why does the code this commit changed exist?

agent-blame aggregates evidence git keeps scattered: introducing commits,
later modifications, movement, callers, risk, and regression/revert history.
It is not a prettier `git blame` - it answers WHY, not just WHO.
"""


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent-blame",
        description=(
            "Deterministic Git archaeology: why this code exists, how it "
            "evolved, and what historical evidence matters before changing "
            "or removing it. No LLM, no network - the repository is the "
            "source of truth."
        ),
        epilog=_QUICK_START,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("target", nargs="?", default=None,
                   help="WHY: <file>:<line> or <file>:<start>-<end> - "
                        "why does this code exist?")
    p.add_argument("--history", action="store_true",
                   help="HOW: ranked historical timeline - how did this code "
                        "evolve?")
    p.add_argument("--risk", action="store_true",
                   help="RISK: historical change/removal risk analysis - what "
                        "should I know before changing/removing it?")
    p.add_argument("--diff", action="store_true",
                   help="DIFF: historical context for your current "
                        "working-tree changes")
    p.add_argument("--commit", metavar="REV", default=None,
                   help="COMMIT: historical context for one commit - why does "
                        "the code it changed exist? (sha, abbrev, HEAD, "
                        "HEAD~1, ...)")
    p.add_argument("--staged", action="store_true",
                   help="with --diff: analyze staged changes (git diff --cached)")
    p.add_argument("--json", action="store_true",
                   help="machine-readable JSON output (stable schema)")
    p.add_argument("--verbose", action="store_true",
                   help="verbose output: per-evidence weights and reasons")
    p.add_argument("--cwd", default=None,
                   help="repository or subdirectory to analyze (default: cwd)")
    p.add_argument("--version", action="version", version=f"agent-blame {__version__}")
    return p


def _resolve_mode(args) -> str:
    if args.commit:
        if args.diff or args.history or args.risk or args.target:
            raise TargetError("--commit cannot be combined with --diff, "
                              "--history, --risk or a target")
        return "commit"
    if args.staged and not args.diff:
        raise TargetError("--staged only applies to --diff")
    if args.diff and (args.history or args.risk):
        raise TargetError("--diff cannot be combined with --history or --risk")
    if args.history and args.risk:
        raise TargetError("--history and --risk are mutually exclusive")
    if args.diff:
        return "diff"
    if args.history:
        return "history"
    if args.risk:
        return "risk"
    return "why"


def main(argv=None) -> int:
    """CLI entry point. Returns an exit code (never raises to the user)."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # non-console stdout; leave it alone

    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        mode = _resolve_mode(args)
    except TargetError as e:
        print(f"agent-blame: error: {sanitize(str(e))}", file=sys.stderr)
        return 2

    if mode == "diff":
        return _run_diff(args)

    if mode == "commit":
        return _run_commit(args)

    if args.target is None:
        parser.print_help()
        return 0

    try:
        target = parse_target(args.target)
    except TargetError as e:
        print(f"agent-blame: error: {sanitize(str(e))}", file=sys.stderr)
        return 2

    start = os.path.abspath(args.cwd) if args.cwd else os.getcwd()
    repo = discover_repository(start)
    if repo is None:
        print(
            "agent-blame: error: not inside a git repository "
            f"(looked up from {sanitize(start)})",
            file=sys.stderr,
        )
        return 1

    target = Target(
        file=resolve_repo_path(repo, target.file),
        start_line=target.start_line,
        end_line=target.end_line,
    )
    if not target.file:
        print("agent-blame: error: empty file path after normalization",
              file=sys.stderr)
        return 2

    result = analyze(repo, target, mode=mode)

    if args.json:
        print(render_json(result), end="")
    else:
        print(render_terminal(result, verbose=args.verbose), end="")
    return 0


def _run_diff(args) -> int:
    """DIFF mode: analyze the working-tree (or staged) changes."""
    start = os.path.abspath(args.cwd) if args.cwd else os.getcwd()
    repo = discover_repository(start)
    if repo is None:
        print(
            "agent-blame: error: not inside a git repository "
            f"(looked up from {sanitize(start)})",
            file=sys.stderr,
        )
        return 1

    result = analyze_diff(repo, staged=args.staged)

    if args.json:
        print(render_json(result), end="")
    else:
        print(render_diff_terminal(result, verbose=args.verbose), end="")
    return 0


def _run_commit(args) -> int:
    """COMMIT mode: analyze the historical context of one commit.

    The revision argument is treated as untrusted input: values starting
    with "-" are rejected outright so they can never be interpreted as
    git options (argv-based git calls would otherwise pass them through).
    """
    rev = args.commit
    if rev.startswith("-"):
        print("agent-blame: error: commit revision cannot start with '-'",
              file=sys.stderr)
        return 2

    start = os.path.abspath(args.cwd) if args.cwd else os.getcwd()
    repo = discover_repository(start)
    if repo is None:
        print(
            "agent-blame: error: not inside a git repository "
            f"(looked up from {sanitize(start)})",
            file=sys.stderr,
        )
        return 1

    from .commit import CommitError, analyze_commit
    try:
        result = analyze_commit(repo, rev)
    except CommitError as e:
        print(f"agent-blame: error: {sanitize(str(e))}", file=sys.stderr)
        return 2

    if args.json:
        print(render_json(result), end="")
    else:
        print(render_commit_terminal(result, verbose=args.verbose), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
