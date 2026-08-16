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

from .models import AnalysisResult, CommitResult, DiffResult

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


def _render_movement(out: list, mv: dict, indent: str = "  ") -> None:
    """Render a movement block (Phase 2D).

    The whole point: the mover is NEVER the introduction. The origin
    (where the code actually came from) is shown separately from the
    mover (which commit moved it), with the multi-hop chain when present.
    """
    mtype = mv.get("type", "UNKNOWN")
    conf = mv.get("confidence", "")
    out.append(_b(f"{indent}Movement: {mtype} ({conf})"))
    if mv.get("moved_by"):
        src = f" from {sanitize(mv['source_path'])}" if mv.get("source_path") else ""
        out.append(f"{indent}  Moved here by: {sanitize(mv['moved_by'])[:8]}{src}")
    elif mv.get("source_path"):
        out.append(f"{indent}  Source: {sanitize(mv['source_path'])}")
    if mv.get("origin"):
        op = f" ({sanitize(mv['origin_path'])}) " if mv.get("origin_path") else " "
        out.append(f"{indent}  Originally introduced by: "
                   f"{sanitize(mv['origin'])[:8]}{op}(not the mover)")
    elif mv.get("source_path"):
        out.append(f"{indent}  Original introduction: not traced")
    for ev in mv.get("chain") or []:
        out.append(f"{indent}  • {sanitize(ev['commit'])[:8]}: "
                   f"{sanitize(ev['old_path'] or '?')} -> "
                   f"{sanitize(ev['new_path'])}")
    for s in mv.get("signals") or []:
        out.append(f"{indent}  · {sanitize(s)}")
    out.append("")


def _render_regressions(out: list, regressions: list,
                        indent: str = "  ") -> None:
    """Render regression findings (Phase 2E) with careful, non-causal wording.

    The language contract: findings say "reverts" / "evidence indicates" /
    "possible ... sequence" - never "caused the bug" or "is buggy". A
    revert proves the change was reversed, not that it was wrong.
    """
    if not regressions:
        return
    out.append(_b(f"{indent}Historical regression evidence"))
    for r in regressions:
        rtype = r.get("type", "?")
        conf = r.get("confidence", "?")
        out.append(f"{indent}  • {rtype} ({conf})")
        exp = r.get("explanation")
        if exp:
            out.append(f"{indent}    {sanitize(exp)}")
        sigs = r.get("signals") or []
        for s in sigs[:5]:
            out.append(f"{indent}    · {sanitize(s)}")
    out.append("")


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

    # --- Regression detection (Phase 2E) -------------------------------
    _render_regressions(out, result.regressions, indent="")

    # --- Movement (Phase 2D) -------------------------------------------
    if result.movement:
        out.append(_b("Movement"))
        _render_movement(out, result.movement, indent="  ")

    # --- Callers (Phase 2C) --------------------------------------------
    if result.symbol is not None:
        out.append(_b("Callers"))
        if result.callers:
            _render_callers(out, result.callers, verbose, indent="  ")
        else:
            out.append("  No confirmed callers found.")
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
        if f.movement:
            _render_movement(out, f.movement, indent="  ")

        for g in f.groups:
            if g.new_file:
                out.append("  New file - no historical evidence available "
                           f"({g.added_lines} line(s) added).")
                if g.analysis.get("movement"):
                    _render_movement(out, g.analysis["movement"], indent="  ")
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
            if a.get("movement"):
                _render_movement(out, a["movement"], indent="  ")
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

            _render_regressions(out, a.get("regressions", []), indent="  ")

            if a.get("symbol") is not None:
                out.append(_b("  Callers"))
                if a.get("callers"):
                    _render_callers(out, a["callers"], verbose, indent="    ")
                else:
                    out.append("    No confirmed callers found.")
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


def render_commit_terminal(result: CommitResult, verbose: bool = False) -> str:
    """Render a --commit result as human-readable terminal output.

    One section per changed file; groups with identical evidence were
    already merged by the analyzer (same noise control as --diff). The
    before-state analysis (historical context, evidence, counter-evidence,
    confidence, risk) is rendered from each group's pipeline result; the
    after-state scan is shown separately and never mixed in. Every
    repository string passes through sanitize().
    """
    meta = result.commit
    out = [_b("COMMIT ANALYSIS"), ""]

    out.append(_kv("Commit", f"{meta.get('short', '')}  {meta.get('subject', '')}"))
    out.append(_kv("Author", meta.get("author", "")))
    out.append(_kv("Date", meta.get("date", "")))
    if meta.get("is_root"):
        out.append(_kv("Parents", "none - root commit"))
        out.append(_kv("Baseline", "none (no previous revision)"))
    else:
        parents = meta.get("parents", [])
        out.append(_kv("Parents", ", ".join(p[:8] for p in parents)
                       or "none"))
        out.append(_kv("Baseline", (result.parent or "")[:8]
                       + (" (first parent)" if meta.get("is_merge") else "")))
    if meta.get("revert_of"):
        out.append(_kv("Type", f"revert of {meta['revert_of'][:8]}"))
    out.append(_kv("Changed files", str(len(result.changes))))
    out.append("")

    if not result.changes:
        out.append("  No changes to analyze.")
        for w in result.warnings:
            out.append(f"  ! {sanitize(w)}")
        return "\n".join(out) + "\n"

    for c in result.changes:
        status_name = {"A": "added", "D": "deleted", "M": "modified",
                       "R": "renamed", "C": "copied"}.get(c.status, c.status)
        header = f"CHANGE  {sanitize(c.path)}  ({status_name}"
        if c.old_path and c.status in ("R", "C"):
            header += f" from {sanitize(c.old_path)}"
        header += ")"
        out.append(_b(header))
        if c.movement:
            _render_movement(out, c.movement, indent="  ")
        _render_regressions(out, c.regressions, indent="  ")

        for g in c.groups:
            if g.new_file:
                out.append("  New file in this commit - no prior history "
                           f"({g.added_lines} line(s) added).")
                if g.analysis.get("movement"):
                    _render_movement(out, g.analysis["movement"], indent="  ")
                for fct in g.analysis.get("facts", []):
                    out.append(f"  ✓ {sanitize(fct.get('text', ''))}")
                out.append("")
                continue

            a = g.analysis
            conf = a.get("confidence", {})
            risk = a.get("risk", {})

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
            if a.get("movement"):
                _render_movement(out, a["movement"], indent="  ")
            _render_group_changes(out, g, verbose)

            # Historical context: introducing commits of the PREVIOUS
            # behavior (blame ran against the baseline revision).
            intro = [f for f in a.get("facts", []) if f.get("kind") == "blame"]
            if intro:
                out.append(_b("  Historical context (before this commit)"))
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

            infs = a.get("inferences", [])
            if infs:
                out.append(_b("  Why (inferred)"))
                for inf in infs:
                    out.append(f"    · {sanitize(inf['text'])}")
                out.append("")

            ev = a.get("evidence", [])
            out.append(_b("  Related evidence"))
            if ev:
                _render_evidence_aggregated(out, ev, verbose)
            else:
                out.append("    None found.")
            out.append("")

            cev = a.get("counter_evidence", [])
            out.append(_b("  Counter-evidence"))
            if cev:
                for e in cev:
                    out.append(f"    ✗ {sanitize(e['text'])}")
            else:
                out.append("    None found.")
            out.append("")

            if a.get("symbol") is not None:
                out.append(_b("  Callers"))
                if a.get("callers"):
                    _render_callers(out, a["callers"], verbose, indent="    ")
                else:
                    out.append("    No confirmed callers found.")
                out.append("")

            out.append(_kv("Historical change risk", risk.get("level", "UNKNOWN")))
            for r in risk.get("reasons", []):
                out.append(f"      - {sanitize(r)}")
            out.append(_kv("Confidence", conf.get("level", "INSUFFICIENT")))
            out.append("")

            for w in a.get("warnings", []):
                out.append(f"  ! {sanitize(w)}")
            out.append("")

        # After-state scan: chronologically separate from the before-state
        # evidence above (later commits can show whether this change was
        # subsequently fixed, reverted or reworked).
        if c.after:
            out.append(_b("  After this commit"))
            out.append(f"    · {sanitize(c.after.get('summary', ''))}")
            _render_regressions(out, c.after.get("regressions", []),
                                indent="    ")
            if verbose:
                for lc in c.after.get("later_commits", []):
                    out.append(f"      {sanitize(lc['short'])}  "
                               f"{sanitize(lc['date'])}  "
                               f"{sanitize(lc['subject'])}")
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


def _render_callers(out: list, callers: list, verbose: bool,
                    indent: str = "  ") -> None:
    """Render caller entries, capped for the terminal (JSON keeps all).

    Resolved callers (DIRECT/ATTRIBUTE/IMPORT/POSSIBLE) are shown one per
    line with relationship + status + confidence; the aggregated
    TEXTUAL_MATCH / UNRESOLVED entries are shown as single informational
    lines (zero evidence weight - they never affect the score).
    """
    detailed = [c for c in callers
                if c["relationship"] in ("DIRECT_CALL", "ATTRIBUTE_CALL",
                                          "IMPORT_REFERENCE", "POSSIBLE_CALL")]
    info = [c for c in callers
            if c["relationship"] in ("TEXTUAL_MATCH", "UNRESOLVED")]

    for c in detailed[:10]:
        mark = "✓" if c["status"] == "LIVE" else "✗"
        out.append(f"{indent}{mark} {sanitize(c['symbol'])}  "
                   f"{c['relationship']}  {c['status']}  "
                   f"(confidence {c['confidence']})")
        if verbose and c.get("call_sites", 1) > 1:
            out.append(f"{indent}    {c['call_sites']} call site(s)")
    if len(detailed) > 10:
        out.append(f"{indent}... {len(detailed) - 10} more caller(s) "
                   f"(use --json for the full list)")
    if not detailed and not info:
        out.append(f"{indent}No confirmed callers found.")
    for c in info:
        out.append(f"{indent}! {sanitize(c['text'])}")


def render_json(result) -> str:
    """Serialize the full structured result as JSON (UTF-8, escaped).

    Works for AnalysisResult, DiffResult and CommitResult (anything with a
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
