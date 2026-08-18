"""Phase 6A session harness: run one baseline/treatment persona session.

Talks to a local ollama server, runs an agentic loop where the persona
proposes bash commands (fenced blocks) and the harness executes them and
returns output, until the persona emits `FINAL ANSWER:` or a budget is
exhausted. Writes a JSONL transcript + meta JSON to transcripts/.

Usage:
    python run_session.py --task T1 --persona P4 --type baseline [--session-id S01]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from personas import (  # noqa: E402
    BASELINE_ENV,
    CAPABILITY_ENV,
    GUIDED_TREATMENT_ENV,
    PERSONAS,
    POST_QUESTIONS,
    REPO_PATHS,
    SESSION_MATRIX,
    SYSTEM_SHELL,
    TASKS,
    TREATMENT_ENV,
)

OLLAMA_URL = "http://localhost:11434/api/chat"
SHIM_DIR = "/tmp/ab-eval/bin"
# Git Bash's real bash (the Windows System32 "bash" is a broken WSL stub).
GIT_BASH = "C:\\Program Files\\Git\\usr\\bin\\bash.exe"
TRANSCRIPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcripts")

# Commands that modify state or hit the network - never allowed in a session.
BLOCKED_PATTERNS = [
    r"\bgit\s+(commit|checkout|reset|clean|push|pull|fetch|clone|merge|rebase|stash)\b",
    r"\brm\b",
    r"\bmv\b",
    r"\bcp\b",
    r"\bmkdir\b",
    r"\btouch\b",
    r"\bcurl\b",
    r"\bwget\b",
    r"\bchmod\b",
    r"\bsudo\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bkill\b",
    r"\bpkill\b",
    r"^\s*>\s*",
    r">>\s*",
    r"\bpython\b[^\n]*\b(open\([^)]*['\"]w|write\(|remove\(|os\.remove|shutil)",
]
BLOCKED_RE = re.compile("|".join(BLOCKED_PATTERNS))

MAX_OUTPUT_CHARS = 3000


def call_ollama(model, messages, timeout=420):
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.6, "num_predict": 4000},
        }
    ).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    return data["message"]["content"]


def extract_commands(text):
    """Return all commands in a response, in order.

    Handles multiple fenced bash blocks per response (qwen3-coder emits
    full agent trajectories in one completion) plus CMD:/$ prefixed lines.
    """
    cmds = re.findall(r"```(?:bash|sh|shell)?\s*\n(.*?)```", text, re.DOTALL)
    if not cmds:
        cmds = re.findall(r"(?m)^CMD:\s*(.+)$", text)
    if not cmds:
        cmds = re.findall(r"(?m)^\$\s+(.+)$", text)
    return [c.strip() for c in cmds if c.strip()]


def is_blocked(command):
    return bool(BLOCKED_RE.search(command))


def win_path(p):
    """Convert a Git Bash POSIX path to a Windows path (cygpath)."""
    try:
        r = subprocess.run(["cygpath", "-w", p], capture_output=True, timeout=20)
        if r.returncode == 0:
            return r.stdout.decode("utf-8", errors="replace").strip()
    except Exception:  # noqa: BLE001
        pass
    return p


def run_command(command, cwd, treatment):
    env = dict(os.environ)
    if treatment:
        env["PATH"] = SHIM_DIR + os.pathsep + env.get("PATH", "")
    t0 = time.time()
    try:
        proc = subprocess.run(
            [GIT_BASH, "-lc", command],
            cwd=win_path(cwd),
            capture_output=True,
            timeout=120,
            env=env,
        )
        # Decode with utf-8 errors=replace: command output may contain
        # arbitrary bytes (e.g. filenames in other encodings); text=True
        # would use the locale codec (cp1252 on Windows) and crash the
        # reader thread on non-decodable bytes.
        out = proc.stdout.decode("utf-8", errors="replace") + proc.stderr.decode("utf-8", errors="replace")
        dur = time.time() - t0
    except subprocess.TimeoutExpired:
        return "[TIMEOUT after 120s]", 120.0
    except Exception as exc:  # noqa: BLE001
        return f"[ERROR] {exc}", time.time() - t0
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + "\n...[output truncated]..."
    return out, dur


def transcript_path(session_id):
    return os.path.join(TRANSCRIPT_DIR, f"{session_id}.jsonl")


def session_complete(session_id):
    path = transcript_path(session_id)
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as fh:
        last = None
        for last in fh:
            pass
    if not last:
        return False
    try:
        return json.loads(last).get("kind") == "meta"
    except Exception:  # noqa: BLE001
        return False


def append_transcript(session_id, line):
    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
    with open(transcript_path(session_id), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def reset_transcript(session_id):
    """Delete a stale/incomplete transcript so a re-run starts clean.

    A session is only ever considered complete when its last line is a meta
    line (see session_complete). Anything else is a partial run from a killed
    process; appending a fresh run to it would interleave two sessions.
    """
    path = transcript_path(session_id)
    if os.path.exists(path):
        os.remove(path)


def apply_patch(patch_path, repo):
    wcwd = win_path(repo)
    subprocess.run(
        ["git", "apply", "--check", patch_path], cwd=wcwd, capture_output=True, check=True
    )
    subprocess.run(["git", "apply", patch_path], cwd=wcwd, capture_output=True, check=True)


def restore_repo(repo):
    wcwd = win_path(repo)
    subprocess.run(["git", "checkout", "--", "."], cwd=wcwd, capture_output=True)
    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=wcwd, capture_output=True
    ).stdout.decode("utf-8", errors="replace").strip()
    return out == ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, choices=list(TASKS.keys()))
    ap.add_argument("--persona", required=True, choices=list(PERSONAS.keys()))
    ap.add_argument("--type", required=True, choices=["baseline", "treatment", "guided", "capability"])
    ap.add_argument("--session-id", default=None)
    ap.add_argument("--max-commands", type=int, default=40)
    ap.add_argument("--max-minutes", type=int, default=10)
    args = ap.parse_args()

    if (args.task, args.persona, args.type) not in SESSION_MATRIX:
        print(f"WARN: ({args.task},{args.persona},{args.type}) not in SESSION_MATRIX")

    session_id = args.session_id or f"{args.task}_{args.persona}_{args.type}_S{int(time.time())}"

    if session_complete(session_id):
        print(f"session {session_id}: already complete, skipping")
        return

    # A partial transcript from a previously killed run must not be appended to.
    reset_transcript(session_id)

    task = TASKS[args.task]
    persona = PERSONAS[args.persona]
    repo = REPO_PATHS[task["repo"]]
    treatment = args.type in ("treatment", "guided", "capability")
    env = (
        CAPABILITY_ENV
        if args.type == "capability"
        else GUIDED_TREATMENT_ENV
        if args.type == "guided"
        else TREATMENT_ENV
        if treatment
        else BASELINE_ENV
    )
    # Post-investigation questions apply to conditions where agent-blame
    # exists (B: treatment, C: capability) but NOT to git-only baseline.
    ask_post = args.type in ("treatment", "capability")

    sys_prompt = SYSTEM_SHELL.format(
        NAME=persona["name"], TRAITS=persona["traits"], ENV=env
    )
    task_text = (
        f"You are in the repository root of `{task['repo']}` ({task['repo_desc']}).\n\n"
        f"## Task\n{task['text']}"
    )

    # T3: apply the prepared diff to the working tree (restore first = idempotent).
    patch = None
    if args.task == "T3":
        patch = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "patches", "rich_console_note.diff"
        )
        restore_repo(repo)
        apply_patch(patch, repo)
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=win_path(repo), capture_output=True
        ).stdout.decode("utf-8", errors="replace").strip()
        if not dirty:
            print("ERROR: T3 patch did not dirty the tree; aborting.")
            sys.exit(1)

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": task_text},
    ]
    for line in (
        {"turn": 0, "kind": "meta", "content": {
            "session_id": session_id, "task": args.task, "persona": args.persona,
            "persona_name": persona["name"], "model": persona["model"],
            "type": args.type, "repo": task["repo"], "target": task["text"].splitlines()[1][:60],
        }, "ts": time.time()},
        {"turn": 0, "kind": "system_prompt", "content": sys_prompt, "ts": time.time()},
        {"turn": 0, "kind": "task", "content": task_text, "ts": time.time()},
    ):
        append_transcript(session_id, line)

    start = time.time()
    final_answer = None
    error = None
    nudge_count = 0
    cmd_count = 0
    git_count = 0
    ab_count = 0
    blocked_count = 0
    turn = 1

    def rec(kind, content):
        append_transcript(session_id, {"turn": turn, "kind": kind, "content": content, "ts": time.time()})

    try:
        while True:
            if time.time() - start > args.max_minutes * 60:
                rec("system", "[BUDGET] wall-clock budget exceeded")
                break
            if cmd_count >= args.max_commands:
                rec("system", "[BUDGET] command budget exceeded")
                break

            try:
                resp = call_ollama(persona["model"], messages)
            except Exception as exc:  # noqa: BLE001
                error = f"ollama error: {exc}"
                rec("error", error)
                break

            rec("assistant", resp)

            commands = extract_commands(resp)
            has_final = "FINAL ANSWER" in resp.upper()

            if not commands:
                if has_final:
                    final_answer = resp
                    break
                nudge_count += 1
                if nudge_count > 2:
                    error = "model stopped emitting commands without FINAL ANSWER"
                    rec("error", error)
                    break
                nudge = (
                    "Your last response did not contain a runnable command or a "
                    "FINAL ANSWER. If you want to run a command, output ONLY fenced "
                    "bash blocks like:\n```bash\ngit log --oneline -5\n```\n"
                    "If you are done, start your response with 'FINAL ANSWER:'."
                )
                messages.append({"role": "assistant", "content": resp})
                messages.append({"role": "user", "content": nudge})
                rec("nudge", nudge)
                turn += 1
                continue

            # Execute all commands the model proposed in this response, in order.
            outputs = []
            for command in commands:
                cmd_count += 1
                if cmd_count > args.max_commands:
                    rec("system", "[BUDGET] command budget exceeded")
                    break
                if re.search(r"\bgit\s", command):
                    git_count += 1
                if "agent-blame" in command:
                    ab_count += 1
                rec("command", command)
                if is_blocked(command):
                    blocked_count += 1
                    out = "[BLOCKED] that command would modify the repository or network state; not executed in this read-only session."
                else:
                    out, _dur = run_command(command, repo, treatment)
                rec("output", out)
                outputs.append(f"$ {command}\n{out}")

            messages.append({"role": "assistant", "content": resp})
            messages.append(
                {"role": "user", "content": "## Command output\n\n" + "\n\n".join(outputs)}
            )
            turn += 1
    finally:
        if patch is not None:
            ok = restore_repo(repo)
            rec("system", f"[T3 restore] tree clean: {ok}")

    # Phase 6C section 7: post-investigation questions for the conditions
    # where agent-blame exists (B: treatment, C: capability). Not asked of
    # git-only baseline. Non-leading; the agent answers from its own
    # investigation.
    post_answers = None
    if ask_post and not error:
        try:
            post_msgs = messages + [{"role": "user", "content": (
                "A few follow-up questions about your investigation. Answer "
                "each briefly and honestly:\n"
                + "\n".join(f"{i+1}. {q}" for i, q in enumerate(POST_QUESTIONS))
            )}]
            post_answers = call_ollama(persona["model"], post_msgs)
            rec("post_questions", POST_QUESTIONS)
            rec("post_answers", post_answers)
        except Exception as exc:  # noqa: BLE001
            rec("post_error", f"post-investigation questions failed: {exc}")

    wall = time.time() - start
    meta = {
        "session_id": session_id,
        "task": args.task,
        "persona": args.persona,
        "persona_name": persona["name"],
        "model": persona["model"],
        "type": args.type,
        "repo": task["repo"],
        "wall_seconds": round(wall, 1),
        "command_count": cmd_count,
        "git_count": git_count,
        "agentblame_count": ab_count,
        "blocked_count": blocked_count,
        "nudge_count": nudge_count,
        "final_answer": final_answer is not None,
        "error": error,
        "task_text": task["text"],
    }
    append_transcript(session_id, {"turn": turn, "kind": "meta", "content": meta, "ts": time.time()})
    path = transcript_path(session_id)
    print(f"session {session_id}: wall={wall:.0f}s cmds={cmd_count} git={git_count} ab={ab_count} final={final_answer is not None} err={error}")
    print(f"transcript: {path}")


if __name__ == "__main__":
    main()
