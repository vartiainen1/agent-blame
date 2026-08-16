"""Output: terminal-safe rendering + JSON serialization.

SECURITY (spec section 21): repository data is untrusted. Commit messages,
filenames, authors, branches may contain ANSI escapes and control
characters. `sanitize()` strips everything that could affect the terminal:

- CSI sequences (ESC [ ... letter) including clear-screen, cursor moves
- OSC sequences (ESC ] ... BEL/ST)
- lone ESC bytes and all C0 control characters except \\n and \\t

We sanitize at the OUTPUT boundary only; raw facts stay intact for JSON.
JSON output additionally goes through json.dumps (which escapes control
chars by default), so it is safe for consumers regardless.
"""

from __future__ import annotations

import json
import re

from .models import AnalysisResult, DiffResult

# CSI: ESC [ params... final-byte (letters/@-~). Handles clear, cursor,
# color, erase - anything a terminal would interpret.
_CSI_RE = re.compile(r"\x1b\[[0-9;:?<>]*[@-~]")
# OSC: ESC ] ... terminated by BEL or ESC \ (ST).
_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
# Remaining C0 controls except \n = 0x0a and \t = 0x09, plus C1 0x7f-0x9f.
# 0x0b-0x1f covers \r (0x0d), \x1b (ESC) and everything else.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def sanitize(text: str) -> str:
    """Strip terminal-control sequences and control chars from untrusted text.

    Keeps \\n and \\t so multiline output still formats correctly.
    """
    if not text:
        return ""
    s = _CSI_RE.sub("", text)
    s = _OSC_RE.sub("", s)
    s = _CTRL_RE.sub("", s)
    return s


def _b(text: str) -> str:
    """Render a section header. Plain text - no ANSI styling.

    Deliberately no escape sequences at all: the output contract is that
    NOTHING the tool prints may contain terminal control characters, so
    a malicious repository cannot hide its own codes among ours.
    """
    return sanitize(text)


def _kv(label: str, value: str) -> str:
    return f"  {label}: {sanitize(value)}"


def render_terminal(result: AnalysisResult, verbose: bool = False) -> str:
    """Render an AnalysisResult as human-readable terminal output.

    Every string from the repository passes through sanitize() before
    being printed.
    """
    mode = result.mode
    target = result.target
    t = target.file
    lines = target.start_line if target.start_line == target.end_line \
        else f"{target.start_line}-{target.end_line}"

    if mode == "history":
        title = "HISTORY"
    elif mode == "risk":
        title = "CHANGE / REMOVAL ANALYSIS"
    else:
        title = "WHY DOES THIS CODE EXIST?"

    out = [f"{_b(title)}", ""]
    out.append(_kv("Target", f"{sanitize(t)}:{lines}"))
    out.append("")

    # --- Confidence -----------------------------------------------------
    conf = result.confidence
    out.append(_b("Confidence"))
    out.append(_kv("Level", conf.level))
    out.append(_kv("Score", f"{conf.score:.2f}"))
    for r in conf.reasons:
        out.append(f"    - {sanitize(r)}")
    out.append("")

    # --- Facts ----------------------------------------------------------
    if result.facts:
        out.append(_b("Facts"))
        for f in result.facts:
            text = f.get("text")
            if text is None:
                text = f"line {f.get('line')} introduced by {f.get('commit', '')[:8]}"
            out.append(f"  ✓ {sanitize(text)}")
        out.append("")

    # --- Inferences -----------------------------------------------------
    if result.inferences:
        out.append(_b("Inferences"))
        for inf in result.inferences:
            out.append(f"  · {sanitize(inf['text'])}")
            if verbose:
                out.append(f"      (confidence: {inf['confidence']})")
        out.append("")

    # --- Evidence -------------------------------------------------------
    if result.evidence:
        out.append(_b("Evidence"))
        for e in result.evidence:
            mark = "✗" if e["is_counter"] else "✓"
            out.append(f"  {mark} {sanitize(e['text'])}")
            if verbose:
                out.append(f"      weight {e['weight']:+.2f}  [{e['kind']}]")
                for r in e.get("reasons", []):
                    out.append(f"      - {sanitize(r)}")
        out.append("")

    # --- Counter-evidence ----------------------------------------------
    if result.counter_evidence:
        out.append(_b("Counter-evidence"))
        for e in result.counter_evidence:
            out.append(f"  ✗ {sanitize(e['text'])}")
        out.append("")

    # --- Historical chain -----------------------------------------------
    if result.history:
        out.append(_b("Historical chain"))
        for h in result.history:
            out.append(
                f"  {sanitize(h['sha'][:8])}  {sanitize(h['date'])}  "
                f"{sanitize(h['subject'])}"
            )
        out.append("")

    # --- Risk ------------------------------------------------------------
    risk = result.risk
    out.append(_b("Historical removal risk"))
    out.append(_kv("Level", risk.level))
    for r in risk.reasons:
        out.append(f"    - {sanitize(r)}")
    out.append("")
    out.append("Note: this is historical evidence, not a safety guarantee. "
               "The developer makes the final decision.")

    if result.warnings:
        out.append("")
        out.append(_b("Warnings"))
        for w in result.warnings:
            out.append(f"  ! {sanitize(w)}")

    return "\n".join(out) + "\n"


def render_diff_terminal(result: DiffResult, verbose: bool = False) -> str:
    """Render a --diff result as human-readable terminal output.

    Each changed region is rendered once (hunks with identical evidence
    were already merged by the analyzer), so a large diff does not produce
    a wall of duplicate explanations. Every repository string passes
    through sanitize().
    """
    scope = "STAGED" if result.scope == "staged" else "WORKING TREE"
    out = [f"{_b('DIFF ANALYSIS')}  ({scope} changes vs HEAD)", ""]

    if not result.files:
        out.append("  No changes to analyze.")
        for w in result.warnings:
            out.append(f"  ! {sanitize(w)}")
        return "\n".join(out) + "\n"

    for f in result.files:
        status_name = {"A": "added", "D": "deleted", "M": "modified",
                       "R": "renamed", "C": "copied"}.get(f.status, f.status)
        header = f"{sanitize(f.path)}  ({status_name}"
        if f.old_path and f.status in ("R", "C"):
            header += f" from {sanitize(f.old_path)}"
        header += ")"
        out.append(_b(header))
        out.append("")

        for g in f.groups:
            if g.new_file:
                out.append("  New file - no historical evidence available "
                           f"({g.added_lines} line(s) added).")
                _render_group_changes(out, g, verbose)
                out.append("")
                continue

            a = g.analysis
            conf = a.get("confidence", {})
            risk = a.get("risk", {})

            # Ranges covered by this group (one per merged hunk).
            ranges_txt = []
            for r in g.ranges:
                old = r.get("old")
                new = r.get("new")
                if old:
                    if old["start"] == old["end"]:
                        ranges_txt.append(f"line {old['start']}")
                    else:
                        ranges_txt.append(f"lines {old['start']}-{old['end']}")
                elif new:
                    if new["start"] == new["end"]:
                        ranges_txt.append(f"new line {new['start']}")
                    else:
                        ranges_txt.append(f"new lines {new['start']}-{new['end']}")
            if ranges_txt:
                out.append(f"  Changed: {', '.join(ranges_txt)}")
            else:
                out.append("  No textual changes (binary or pure rename).")
            _render_group_changes(out, g, verbose)

            # Historical context: the introducing commit(s) from blame facts.
            intro = [f for f in a.get("facts", []) if f.get("kind") == "blame"]
            if intro:
                out.append(_b("  Historical context"))
                # Cap per-line facts: a whole deleted file could blame 100s
                # of lines; the distinct introducing commits matter more.
                shown = set()
                rendered = []
                for fct in intro:
                    key = fct.get("commit", "")
                    if key in shown:
                        continue
                    shown.add(key)
                    rendered.append(fct)
                for fct in rendered[:10]:
                    out.append(f"    • {sanitize(fct.get('text', ''))}")
                if len(rendered) > 10:
                    out.append(f"    ... {len(rendered) - 10} more introducing "
                               f"commit(s)")
                out.append("")

            # Inferences (purpose etc.) - the "why" distilled.
            infs = a.get("inferences", [])
            if infs:
                out.append(_b("  Why (inferred)"))
                for inf in infs:
                    out.append(f"    · {sanitize(inf['text'])}")
                out.append("")

            # Evidence bullets. Per-commit kinds (modified_by / fix_related)
            # are AGGREGATED into one line per kind: a file touched by 80
            # commits must not print 80 near-identical bullets (the spec's
            # noise-control contract). Distinct kinds stay individual.
            ev = a.get("evidence", [])
            if ev:
                out.append(_b("  Related evidence"))
                _render_evidence_aggregated(out, ev, verbose)
                out.append("")
            else:
                out.append(_b("  Related evidence"))
                out.append("    None found.")
                out.append("")

            cev = a.get("counter_evidence", [])
            out.append(_b("  Counter-evidence"))
            if cev:
                # Counter-evidence is already aggregated by the engine
                # (one item per kind); render each item once.
                for e in cev:
                    out.append(f"    ✗ {sanitize(e['text'])}")
            else:
                out.append("    None found.")
            out.append("")

            out.append(_kv("Historical change risk", risk.get("level", "UNKNOWN")))
            for r in risk.get("reasons", []):
                out.append(f"      - {sanitize(r)}")
            out.append(_kv("Confidence", conf.get("level", "INSUFFICIENT")))
            out.append("")

            for w in a.get("warnings", []):
                out.append(f"  ! {sanitize(w)}")
            out.append("")

        out.append("─" * 60)
        out.append("")

    if result.warnings:
        out.append(_b("Warnings"))
        for w in result.warnings:
            out.append(f"  ! {sanitize(w)}")
        out.append("")

    out.append("Note: this is historical evidence, not a safety guarantee. "
               "The developer makes the final decision.")
    return "\n".join(out) + "\n"


def _render_evidence_aggregated(out: list, ev: list, verbose: bool) -> None:
    """Render evidence bullets, collapsing per-commit kinds into counts.

    `modified_by` and `fix_related` are emitted once per later commit by
    the engine; for a long-lived file that is dozens of near-identical
    bullets. Collapse each kind into a single line with a commit count
    (the JSON output keeps the full per-commit list for machines).
    """
    counts: dict = {}     # kind -> list of texts
    singles: list = []    # kinds shown individually (introduced_by, tests)
    for e in ev:
        kind = e["kind"]
        if kind in ("modified_by", "fix_related", "related_fix"):
            counts.setdefault(kind, []).append(e["text"])
        else:
            singles.append(e)
    for e in singles:
        out.append(f"    ✓ {sanitize(e['text'])}")
        if verbose:
            out.append(f"        weight {e['weight']:+.2f}  [{e['kind']}]")
    for kind in ("modified_by", "fix_related", "related_fix"):
        items = counts.get(kind)
        if not items:
            continue
        if len(items) == 1:
            out.append(f"    ✓ {sanitize(items[0])}")
        else:
            text = sanitize(items[0])
            if kind == "modified_by":
                label = f"{len(items)} later commits modified this file"
            else:
                label = f"{len(items)} later commits reference a fix/regression"
            out.append(f"    ✓ {label} (e.g. {text[:90]}{'...' if len(text) > 90 else ''})")
        if verbose:
            out.append(f"        ({len(items)} item(s), aggregated)")


def _render_group_changes(out: list, g, verbose: bool) -> None:
    """Render the changed lines of a group (sanitized, + / - prefixed)."""
    if not g.changes:
        return
    lines = []
    for c in g.changes:
        mark = "+" if c["side"] == "new" else "-"
        lines.append(f"    {mark} {c['line']:>4}  {sanitize(c['text'])}")
    if len(lines) <= 20:
        out.extend(lines)
    else:
        out.extend(lines[:10])
        out.append(f"    ... {len(lines) - 10} more changed line(s) "
                   f"(use --json for the full list)")


def render_json(result) -> str:
    """Serialize the full structured result as JSON (UTF-8, escaped).

    Works for both AnalysisResult and DiffResult (anything with a
    `to_dict()`). Values pass through sanitize() first: json.dumps escapes
    C0 control characters but NOT C1 (0x80-0x9f) or DEL (0x7f), so a
    malicious commit message could otherwise embed a raw CSI byte (0x9b)
    in the JSON that a terminal would interpret when the JSON is printed.
    """
    return json.dumps(_sanitize_dict(result.to_dict()),
                      ensure_ascii=False, indent=2) + "\n"


def _sanitize_dict(d: dict) -> dict:
    """Recursively sanitize string values in a dict (for safe JSON output)."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = _sanitize_dict(v)
        elif isinstance(v, list):
            out[k] = [_sanitize_dict(x) if isinstance(x, dict)
                      else sanitize(x) if isinstance(x, str) else x
                      for x in v]
        elif isinstance(v, str):
            out[k] = sanitize(v)
        else:
            out[k] = v
    return out
