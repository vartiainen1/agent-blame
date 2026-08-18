"""Phase 6C section 9: adversarial skeptic with Condition C description."""
import json
import sys
import urllib.request
import time
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from personas import PERSONAS

OLLAMA = "http://localhost:11434/api/generate"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcripts", "SKEPTIC_6C.jsonl")


def generate(model, prompt, max_tokens=1600):
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tokens},
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    p6 = PERSONAS["P6"]
    questions = (
        "Your job is to determine whether this tool deserves to exist as a "
        "separate developer tool.\n\n"
        "There is a tool called `agent-blame` on the PATH. It is a Git "
        "archaeology tool that combines introducing commits, later changes, "
        "code movement, callers, risk, and regression/revert evidence into a "
        "single historical analysis.\n\n"
        "You may run `agent-blame --help` and any git commands you want to "
        "evaluate it. Do NOT be told what to like - judge it on evidence.\n\n"
        "Answer these 10 questions plainly, with reasoning:\n\n"
        "1. What does this tool do that Git doesn't already do?\n"
        "2. Which feature is genuinely differentiated?\n"
        "3. Which features are unnecessary?\n"
        "4. Would you install it?\n"
        "5. Would you use it repeatedly?\n"
        "6. What would make you uninstall it?\n"
        "7. Is the aggregation valuable enough to justify another CLI?\n"
        "8. Is there a single killer workflow?\n"
        "9. Is the product essentially a wrapper around existing Git commands?\n"
        "10. What would you change if you were the product owner?"
    )
    prompt = p6["traits"] + "\n\n" + questions

    t0 = time.time()
    print(f"[skeptic] generating with {p6['model']} ...", flush=True)
    resp = generate(p6["model"], prompt)
    text = resp.get("response", "")
    dt = time.time() - t0
    print(f"[skeptic] done in {dt:.0f}s, {len(text)} chars", flush=True)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "meta", "session": "SKEPTIC_6C",
                            "model": p6["model"], "prompt": prompt}) + "\n")
        f.write(json.dumps({"kind": "response", "text": text}) + "\n")
    print(f"[skeptic] saved to {OUT}", flush=True)
    print("=" * 70)
    print(text[:4000])


if __name__ == "__main__":
    main()
