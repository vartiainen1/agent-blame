"""Phase 4 external-developer validation harness (simulated).

Runs the closest feasible equivalent of a human-participant study in an
environment with no external developers:

  1. DISCOVERABILITY battery  - every mode a fresh user must find from
     `--help` alone; natural guesses and common mistakes recorded with rc
     and first output lines.
  2. PERSONA sessions         - three simulated developer personas (git
     expert, normal professional, rarely-investigates) walking realistic
     tasks (A-E) using only --help/README knowledge. Command sequences are
     actually executed; observations are recorded.
  3. TIME-TO-ANSWER           - for representative questions, run the exact
     manual-git investigation a competent developer would perform and time
     it, then time the single agent-blame command for the same question.
  4. TRUST CALIBRATION        - for each question record agent-blame's
     confidence and the git-verified ground truth so confidence can be
     audited (over/under-confidence).

Target repos are treated as read-only. The --diff task runs in a scratch
clone under the temp dir, never in a real repository.

Usage: python _validate_phase4.py [--out validation_dataset.json]
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

AB = os.path.dirname(os.path.abspath(__file__))
_TMP = os.path.join(tempfile.gettempdir(), "ab-eval")
REPOS = {
    "requests": os.path.join(_TMP, "requests"),
    "flask": os.path.join(_TMP, "flask"),
    "rich": os.path.join(_TMP, "rich"),
}
FREEBUFF = os.path.join(
    os.path.dirname(AB), "Freebuff"
)  # sibling workspace repo (dogfood)


def ab_args(*extra: str) -> list:
    return [sys.executable, "-m", "agent_blame", *extra]


def run(cmd: list, cwd: str, timeout: int = 180) -> tuple:
    """Run a command; return (rc, stdout, stderr, seconds)."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = AB
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, env=env,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        return p.returncode, p.stdout, p.stderr, time.time() - t0
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "", "", time.time() - t0


def run_ab(repo: str, args: list, timeout: int = 180) -> dict:
    rc, out, err, dt = run(ab_args(*args), REPOS[repo], timeout)
    rec = {"repo": repo, "args": args, "rc": rc, "seconds": round(dt, 2)}
    if rc == 0 and args and "--json" in args:
        try:
            rec["json"] = json.loads(out)
        except json.JSONDecodeError:
            rec["json_parse_error"] = out[:300]
    rec["stdout_head"] = out[:400]
    if err.strip():
        rec["stderr"] = err[:300]
    return rec


# --------------------------------------------------------------------------
# 1. DISCOVERABILITY BATTERY
# --------------------------------------------------------------------------

DISCOVERABILITY = [
    # (label, args, repo)  -- commands a fresh user would naturally try
    ("help", ["--help"], "requests"),
    ("version", ["--version"], "requests"),
    ("why file:line", ["src/requests/models.py:483"], "requests"),
    ("why range", ["src/requests/models.py:480-486"], "requests"),
    ("history", ["--history", "src/requests/models.py:483"], "requests"),
    ("risk", ["--risk", "src/requests/models.py:483"], "requests"),
    ("json", ["--json", "src/requests/models.py:483"], "requests"),
    ("diff", ["--diff"], "requests"),
    ("diff staged", ["--diff", "--staged"], "requests"),
    ("commit sha", ["--commit", "fd13816d"], "requests"),
    ("commit HEAD", ["--commit", "HEAD"], "requests"),
    # natural mistakes / edge inputs
    ("bare file", ["src/requests/models.py"], "requests"),
    ("no args", [], "requests"),
    ("bad line", ["src/requests/models.py:99999"], "requests"),
    ("bad rev", ["--commit", "deadbeef"], "requests"),
    ("dash rev", ["--commit", "--help"], "requests"),
    ("not a repo", ["foo.py:1"], tempfile.gettempdir()),
    ("unknown flag", ["--frobnicate"], "requests"),
    ("missing file", ["nope/nothere.py:1"], "requests"),
]

# --------------------------------------------------------------------------
# 2. PERSONA SESSIONS  (simulated; command sequences actually executed)
# --------------------------------------------------------------------------

PERSONAS = {
    "p1_git_expert": {
        "profile": ("experienced Git user; fluent in blame/log/show; "
                    "likely to verify tool claims with git"),
        "task": "B - before modifying code",
        "brief": ("You need to change Session.request in requests. Before "
                  "changing it, find out what historical information you "
                  "should know: who calls it, whether it moved, previous "
                  "changes, regressions, risk."),
        "target": "src/requests/sessions.py:324",
        "repo": "requests",
        "manual_probe": [
            ["git", "blame", "-L", "324,324", "src/requests/sessions.py"],
            ["git", "log", "--oneline", "-5", "--", "src/requests/sessions.py"],
        ],
        "ab_commands": [
            ["src/requests/sessions.py:324"],
            ["--risk", "src/requests/sessions.py:324"],
            ["--json", "src/requests/sessions.py:324"],
        ],
    },
    "p2_normal_dev": {
        "profile": ("normal professional developer; knows git basics "
                    "(commit/push/pull), rarely digs history"),
        "task": "A - why does this code exist",
        "brief": ("You found dispatch_request in an unfamiliar codebase. "
                  "Determine where it came from and why it exists."),
        "target": "src/flask/app.py:969",
        "repo": "flask",
        "manual_probe": [
            ["git", "blame", "-L", "969,969", "src/flask/app.py"],
            ["git", "log", "--oneline", "-5", "--", "src/flask/app.py"],
        ],
        "ab_commands": [
            ["src/flask/app.py:969"],
            ["--history", "src/flask/app.py:969"],
        ],
    },
    "p3_rarely_investigates": {
        "profile": ("developer who almost never investigates git history; "
                    "uses git only for commit/push"),
        "task": "E - unfamiliar code",
        "brief": ("You inherited this repository. Pick one confusing "
                  "function and investigate it."),
        "target": "rich/console.py:1891",
        "repo": "rich",
        "manual_probe": [
            ["git", "blame", "-L", "1891,1891", "rich/console.py"],
        ],
        "ab_commands": [
            ["rich/console.py:1891"],
        ],
    },
}

# --------------------------------------------------------------------------
# 3. TIME-TO-ANSWER  (manual git archaeology vs agent-blame)
# --------------------------------------------------------------------------

TIME_QUESTIONS = [
    {
        "q": "Where did this code come from (origin + why)?",
        "repo": "requests",
        "target": "src/requests/models.py:483",
        "manual": [
            ["git", "blame", "-L", "483,483", "src/requests/models.py"],
            ["git", "show", "--stat", "--format=%h %s %ad", "561e4b68"],
            ["git", "log", "--oneline", "-3", "--", "src/requests/models.py"],
        ],
        "ab": ["src/requests/models.py:483"],
    },
    {
        "q": "Who calls this function?",
        "repo": "requests",
        "target": "src/requests/models.py:483",
        "manual": [
            ["git", "grep", "-n", "prepare_url", "HEAD", "--", "src/"],
            ["git", "grep", "-n", "prepare_url", "HEAD", "--", "tests/"],
        ],
        "ab": ["--json", "src/requests/models.py:483"],
    },
    {
        "q": "Was this code moved here, or introduced here?",
        "repo": "requests",
        "target": "src/requests/__init__.py:74",
        "manual": [
            ["git", "log", "--follow", "--oneline", "-5", "--", "src/requests/__init__.py"],
            ["git", "log", "--follow", "--diff-filter=R", "--oneline", "--", "src/requests/__init__.py"],
        ],
        "ab": ["src/requests/__init__.py:74"],
    },
    {
        "q": "What did this commit change and why?",
        "repo": "requests",
        "target": "fd13816d",
        "manual": [
            ["git", "show", "--stat", "--format=%h %s%n%b", "fd13816d"],
            ["git", "show", "fd13816d", "--", "requests/models.py"],
        ],
        "ab": ["--commit", "fd13816d"],
    },
    {
        "q": "What should I know before modifying this?",
        "repo": "flask",
        "target": "src/flask/app.py:969",
        "manual": [
            ["git", "blame", "-L", "969,969", "src/flask/app.py"],
            ["git", "log", "--oneline", "-10", "--", "src/flask/app.py"],
            ["git", "log", "--oneline", "--all", "--grep=revert", "--", "src/flask/app.py"],
        ],
        "ab": ["--risk", "src/flask/app.py:969"],
    },
]

# --------------------------------------------------------------------------
# 4. TRUST CALIBRATION TARGETS
# --------------------------------------------------------------------------

TRUST_TARGETS = [
    # (repo, target/args, expected truth, confidence expectation)
    ("requests", ["--json", "src/requests/models.py:483"], "HIGH", "introduced by 561e4b68 (types rewrite)"),
    ("requests", ["--commit", "fd13816d", "--json"], "MEDIUM+", "explicit revert of 19cff44e"),
    ("requests", ["--json", "src/requests/__init__.py:74"], "HIGH", "origin 2b34880e via -w blame (d8e23678 only re-indented)"),
    ("requests", ["--json", "src/requests/models.py:99999"], "INSUFFICIENT", "line does not exist -> honest INSUFFICIENT"),
    ("flask", ["--json", "src/flask/app.py:969"], "MEDIUM+", "dispatch_request long-lived, framework-registered"),
    ("rich", ["--json", "rich/console.py:1891"], "MEDIUM+", "Console.print, huge change history"),
]

# Classification burden: raw git grep hit counts for a caller question, to
# quantify the manual review effort agent-blame's classifier replaces.
GREP_CALLER_PROBE = [
    ("requests", "prepare_url", ["src/", "tests/"]),
    ("flask", "dispatch_request", ["src/", "tests/"]),
]


def time_manual(repo: str, cmds: list) -> tuple:
    """Run a manual investigation; return (total_seconds, per_cmd)."""
    per = []
    total = 0.0
    for c in cmds:
        rc, out, err, dt = run(c, REPOS[repo])
        per.append({"cmd": c, "rc": rc, "seconds": round(dt, 2),
                    "out_len": len(out), "out_head": out[:120]})
        total += dt
    return round(total, 2), per


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "validation_dataset.json"
    dataset = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "note": "SIMULATED validation - no external human participants available in this environment. Command sequences are executed for real; persona observations are reconstructed from actual output."}

    # 1. discoverability
    print("== discoverability ==")
    disc = []
    for label, args, repo in DISCOVERABILITY:
        if repo == tempfile.gettempdir():
            rc, out, err, dt = run(ab_args(*args), tempfile.gettempdir(), 60)
            rec = {"repo": "not-a-repo", "args": args, "rc": rc,
                   "seconds": round(dt, 2), "stdout_head": out[:400]}
            if err.strip():
                rec["stderr"] = err[:300]
        else:
            rec = run_ab(repo, args, timeout=60)
        rec["label"] = label
        disc.append(rec)
        print(f"  {label:22s} rc={rec['rc']} {rec['seconds']:5.1f}s")
    dataset["discoverability"] = disc

    # 2. personas
    print("== personas ==")
    personas = {}
    for pid, spec in PERSONAS.items():
        rec = {"profile": spec["profile"], "task": spec["task"],
               "brief": spec["brief"], "target": spec["target"],
               "repo": spec["repo"], "manual_probe": [],
               "ab_runs": []}
        for c in spec["manual_probe"]:
            rc, out, err, dt = run(c, REPOS[spec["repo"]])
            rec["manual_probe"].append({"cmd": c, "rc": rc,
                                        "seconds": round(dt, 2),
                                        "out_head": out[:200]})
        for args in spec["ab_commands"]:
            rec["ab_runs"].append(run_ab(spec["repo"], args))
        personas[pid] = rec
        print(f"  {pid} rc_ab={[r['rc'] for r in rec['ab_runs']]}")
    dataset["personas"] = personas

    # 3. time-to-answer
    print("== time-to-answer ==")
    times = []
    total_manual_cmds = 0
    total_manual_sec = 0.0
    total_ab_sec = 0.0
    for q in TIME_QUESTIONS:
        m_total, m_per = time_manual(q["repo"], q["manual"])
        ab = run_ab(q["repo"], q["ab"])
        times.append({"question": q["q"], "repo": q["repo"],
                      "target": q["target"],
                      "manual_seconds": m_total, "manual_commands": m_per,
                      "ab_seconds": ab["seconds"], "ab_rc": ab["rc"]})
        total_manual_cmds += len(q["manual"])
        total_manual_sec += m_total
        total_ab_sec += ab["seconds"]
        print(f"  {q['q'][:44]:46s} manual={m_total:5.1f}s({len(q['manual'])}cmds) ab={ab['seconds']:5.1f}s")
    times.append({"question": "TOTAL: full 5-question investigation",
                  "manual_commands_count": total_manual_cmds,
                  "manual_seconds": round(total_manual_sec, 2),
                  "ab_commands_count": len(TIME_QUESTIONS),
                  "ab_seconds": round(total_ab_sec, 2)})
    print(f"  TOTAL manual={total_manual_sec:5.1f}s/{total_manual_cmds}cmds  ab={total_ab_sec:5.1f}s/{len(TIME_QUESTIONS)}cmds")
    dataset["time_to_answer"] = times

    # 3b. grep classification burden (raw hits a developer must review)
    print("== grep burden ==")
    grep_burden = []
    for repo, symbol, paths in GREP_CALLER_PROBE:
        total = 0
        per = []
        for p in paths:
            rc, out, err, dt = run(["git", "grep", "-n", symbol, "HEAD", "--", p], REPOS[repo])
            n = len([l for l in out.splitlines() if l.strip()])
            total += n
            per.append({"path": p, "hits": n})
        grep_burden.append({"repo": repo, "symbol": symbol,
                            "per_path": per, "total_hits": total})
        print(f"  {repo:9s} {symbol:20s} {total} raw hits")
    dataset["grep_burden"] = grep_burden

    # 4. trust calibration
    print("== trust calibration ==")
    trust = []
    for repo, args, expect_conf, truth in TRUST_TARGETS:
        rec = run_ab(repo, args)
        conf = None
        extra = {}
        j = rec.get("json")
        if j:
            if j.get("mode") == "commit":
                # commit JSON keeps confidence per-change (inside groups)
                levels = []
                for ch in j.get("changes", []):
                    for g in ch.get("groups", []):
                        a = g.get("analysis") or {}
                        c = a.get("confidence") or {}
                        if c.get("level"):
                            levels.append(c["level"])
                conf = levels
                extra["revert_of"] = j.get("commit", {}).get("revert_of")
                extra["subject"] = j.get("commit", {}).get("subject")
            else:
                conf = j.get("confidence", {}).get("level")
        trust.append({"repo": repo, "args": args,
                      "expected_confidence": expect_conf,
                      "ground_truth": truth,
                      "got_confidence": conf,
                      "extra": extra,
                      "rc": rec["rc"]})
        print(f"  {repo:9s} {args} -> {conf} {extra}")
    dataset["trust_calibration"] = trust

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(dataset, fh, indent=2, ensure_ascii=False)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
