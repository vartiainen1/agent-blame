"""Run all Phase 6A sessions in matrix order, skipping completed ones.

Sessions are independent and resumable: a session is skipped if its
transcript ends with a meta line. Re-run this script after any interruption
to continue.

Usage: python run_all.py [--max-commands N] [--max-minutes M]
"""

import argparse
import subprocess
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from personas import SESSION_MATRIX  # noqa: E402
from run_session import session_complete  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-commands", type=int, default=40)
    ap.add_argument("--max-minutes", type=int, default=10)
    args = ap.parse_args()

    total = len(SESSION_MATRIX)
    done = 0
    for task, persona, stype in SESSION_MATRIX:
        sid = f"S{task}_{persona}_{stype}"
        if session_complete(sid):
            done += 1
            print(f"[{done}/{total}] {sid}: already complete")
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
                "--max-commands", str(args.max_commands),
                "--max-minutes", str(args.max_minutes),
            ],
            cwd=HERE,
        )
        dt = time.time() - t0
        if r.returncode != 0:
            print(f"[{sid}] FAILED rc={r.returncode} after {dt:.0f}s", flush=True)
            sys.exit(1)
        print(f"[{sid}] done in {dt:.0f}s", flush=True)
        done += 1

    print(f"all {total} sessions processed")


if __name__ == "__main__":
    main()
