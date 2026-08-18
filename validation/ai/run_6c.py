"""Phase 6C launcher: Conditions B (agent-blame unexplained) and C (neutral
capability description) on tasks T1/T2/T4/T5/T6/T7, current committed version.

Condition A (git only) reuses the Phase 6A baseline transcripts - identical
methodology (git-only env, agent-blame never mentioned), documented in the
report. Condition B and C are run fresh here, with post-investigation
questions (phase 6C section 7).

Run: python run_6c.py [--only B|C]
"""

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# (task, persona, condition) - personas match Phase 6A for these tasks.
MATRIX = [
    ("T1", "P1", "B"),
    ("T2", "P3", "B"),
    ("T4", "P2", "B"),
    ("T5", "P1", "B"),
    ("T6", "P3", "B"),
    ("T7", "P5", "B"),
    ("T1", "P1", "C"),
    ("T2", "P3", "C"),
    ("T4", "P2", "C"),
    ("T5", "P1", "C"),
    ("T6", "P3", "C"),
    ("T7", "P5", "C"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["B", "C"], default=None)
    args = ap.parse_args()

    total = len(MATRIX)
    done = 0
    for task, persona, cond in MATRIX:
        if args.only and cond != args.only:
            continue
        stype = "treatment" if cond == "B" else "capability"
        sid = f"ST{task[1]}_{persona}_6C_{cond}"
        # Skip if already complete (resumable).
        import run_session  # noqa: E402
        if run_session.session_complete(sid):
            done += 1
            print(f"[{done}/{total}] {sid}: already complete", flush=True)
            continue
        print(f"[{done + 1}/{total}] {sid}: starting...", flush=True)
        t0 = time.time()
        r = subprocess.run(
            [
                sys.executable,
                os.path.join(HERE, "run_session.py"),
                "--task", task,
                "--persona", persona,
                "--type", stype,
                "--session-id", sid,
                "--max-commands", "40",
                "--max-minutes", "10",
            ],
            cwd=HERE,
        )
        dt = time.time() - t0
        if r.returncode != 0:
            print(f"[{sid}] FAILED rc={r.returncode} after {dt:.0f}s", flush=True)
            sys.exit(1)
        print(f"[{sid}] done in {dt:.0f}s", flush=True)
        done += 1
    print("phase 6C sessions processed")


if __name__ == "__main__":
    main()
