"""Phase 3 evaluation harness: run agent-blame across real repos and
record a structured dataset (repository, target, mode, runtime, result
summary, key signals). Read-only against the target repos.

Usage: python _eval_phase3.py [--out out.json]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

AB = os.path.dirname(os.path.abspath(__file__))
_TMP = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), "ab-eval")
REPOS = {
    "requests": os.path.join(_TMP, "requests"),
    "flask": os.path.join(_TMP, "flask"),
    "rich": os.path.join(_TMP, "rich"),
}

TARGETS = {
    "requests": [
        # WHY on the classic prepare_url (types rewrite 2023)
        ("src/requests/models.py:483", "why"),
        ("src/requests/models.py:483", "history"),
        ("src/requests/models.py:483", "risk"),
        # A function with many callers
        ("src/requests/sessions.py:324", "why"),   # Session.request
        # send() in adapters
        ("src/requests/adapters.py:128", "why"),
        # A rarely-touched, long-lived line: version
        ("src/requests/__init__.py:74", "why"),
        # --commit on a known revert commit
        ("--commit fd13816d", "commit"),
        # --commit on the src/ move
        ("--commit d63e94f5", "commit"),
    ],
    "flask": [
        ("src/flask/app.py:969", "why"),       # dispatch_request
        ("src/flask/app.py:969", "history"),
        ("src/flask/app.py:969", "risk"),
        ("src/flask/helpers.py:580", "why"),   # url_for
        ("src/flask/__init__.py:24", "why"),
        ("--commit HEAD~50", "commit"),
    ],
    "rich": [
        ("rich/console.py:1891", "why"),       # Console.print
        ("rich/console.py:1891", "risk"),
        ("rich/table.py:502", "why"),          # Table.add_row
        ("rich/text.py:231", "why"),           # Text.append
        ("--commit HEAD~100", "commit"),
    ],
}


def run_ab(repo_dir: str, target: str, mode: str, timeout: int = 120):
    """Run agent-blame, return (rc, json_dict or None, seconds, stderr)."""
    args = [sys.executable, "-m", "agent_blame"]
    if mode == "commit":
        args += ["--commit", target.split(" ", 1)[1] if " " in target else target]
        args += ["--json"]
    else:
        args.append(target)
        args.append("--json")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = AB
    t0 = time.time()
    try:
        proc = subprocess.run(args, cwd=repo_dir, capture_output=True,
                              text=True, env=env, timeout=timeout,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return "TIMEOUT", None, time.time() - t0, ""
    dt = time.time() - t0
    if mode == "commit":
        # commit mode: no --json flag in this harness - reuse the json
        # renderer via the library instead
        return proc.returncode, None, dt, proc.stderr[-500:]
    if proc.returncode != 0:
        return proc.returncode, None, dt, proc.stderr[-500:]
    try:
        return proc.returncode, json.loads(proc.stdout), dt, ""
    except json.JSONDecodeError:
        return proc.returncode, None, dt, proc.stdout[-500:]


def summarize(d: dict) -> dict:
    if d is None:
        return {"error": True}
    conf = d.get("confidence", {})
    risk = d.get("risk", {})
    return {
        "confidence": conf.get("level"),
        "confidence_score": conf.get("score"),
        "risk": risk.get("level"),
        "risk_reasons": len(risk.get("reasons", [])),
        "n_facts": len(d.get("facts", [])),
        "n_evidence": len(d.get("evidence", [])),
        "n_counter": len(d.get("counter_evidence", [])),
        "n_callers": len(d.get("callers", [])),
        "n_regressions": len(d.get("regressions", [])),
        "movement": (d.get("movement") or {}).get("type"),
        "movement_origin": (d.get("movement") or {}).get("origin"),
        "movement_moved_by": (d.get("movement") or {}).get("moved_by"),
        "symbol": (d.get("symbol") or {}).get("name"),
        "evidence_kinds": sorted({e["kind"] for e in d.get("evidence", [])}),
        "counter_kinds": sorted({e["kind"] for e in d.get("counter_evidence", [])}),
        "regression_types": [r["type"] for r in d.get("regressions", [])],
        "caller_first": [(c["symbol"], c["relationship"], c["status"])
                         for c in d.get("callers", [])[:3]],
    }


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "eval_dataset.json"
    dataset = {"repos": {}, "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
    for repo, targets in TARGETS.items():
        repo_dir = REPOS[repo]
        if not os.path.isdir(repo_dir):
            print(f"skip {repo}: missing {repo_dir}")
            continue
        rows = []
        for target, mode in targets:
            rc, data, dt, err = run_ab(repo_dir, target, mode)
            row = {
                "repo": repo, "target": target, "mode": mode,
                "rc": rc, "seconds": round(dt, 2),
                "summary": summarize(data),
            }
            if err:
                row["stderr"] = err
            rows.append(row)
            print(f"{repo:10s} {mode:8s} {target:40s} rc={rc} {dt:5.1f}s "
                  f"{row['summary'].get('confidence')}")
        dataset["repos"][repo] = rows
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(dataset, fh, indent=2, ensure_ascii=False)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
