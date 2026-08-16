"""agent-blame CLI.

Usage (spec section 30 + Phase 2A):
  agent-blame <file>:<line>            WHY mode (default)
  agent-blame <file>:<start>-<end>     WHY mode with a range
  agent-blame --history <target>       HISTORY mode
  agent-blame --risk <target>          RISK mode
  agent-blame --diff                   DIFF mode: historical context for the
                                       current working-tree changes
  agent-blame --diff --staged          DIFF mode for staged changes only
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
from .output import render_diff_terminal, render_json, render_terminal, sanitize
from .repository import discover_repository, resolve_repo_path
from .target import TargetError, parse_target


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent-blame",
        description=(
            "Deterministic Git archaeology: why this code exists, how it "
            "evolved, and what historical evidence matters before changing "
            "or removing it. No LLM, no network - the repository is the "
            "source of truth."
        ),
    )
    p.add_argument("target", nargs="?", default=None,
                   help="<file>:<line> or <file>:<start>-<end>")
    p.add_argument("--history", action="store_true",
                   help="show the ranked historical timeline for the target")
    p.add_argument("--risk", action="store_true",
                   help="historical change/removal risk analysis")
    p.add_argument("--diff", action="store_true",
                   help="DIFF mode: analyze the current working-tree changes")
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


if __name__ == "__main__":
    sys.exit(main())
