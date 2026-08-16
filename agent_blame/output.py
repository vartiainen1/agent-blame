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

from .models import AnalysisResult

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


def render_json(result: AnalysisResult) -> str:
    """Serialize the full structured result as JSON (UTF-8, escaped).

    Values pass through sanitize() first: json.dumps escapes C0 control
    characters but NOT C1 (0x80-0x9f) or DEL (0x7f), so a malicious
    commit message could otherwise embed a raw CSI byte (0x9b) in the
    JSON that a terminal would interpret when the JSON is printed.
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
