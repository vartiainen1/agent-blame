"""Phase 6A persona/task configuration for the agent-blame AI validation.

Text mirrors validation/ai/AI_PERSONAS.md and AI_TASKS.md (single source
of truth for the harness).
"""

# --- environment blocks -----------------------------------------------------

BASELINE_ENV = (
    "Use normal repository tooling: git, grep, find, and standard shell "
    "utilities. Use whatever you would normally use to investigate a "
    "repository."
)

TREATMENT_ENV = (
    "A tool called `agent-blame` is available on your PATH. It is a "
    "git-related tool. Use it or not - your choice. Run "
    "`agent-blame --help` to see what it does. You may also use normal "
    "repository tooling (git, grep, find, shell utilities) as you normally "
    "would."
)

# Guided round: the tool's OWN help text is provided up front (the tool
# speaking for itself, not the facilitator claiming what it is good at).
# This isolates DISCOVERABILITY (natural round) from VALUE (guided round):
# if the treatment fails even with the tool's own docs in front of the
# agent, that is a value finding, not a syntax/discoverability failure.
GUIDED_TREATMENT_ENV = (
    "A tool called `agent-blame` is available on your PATH. Its own "
    "documentation (from `agent-blame --help`) is:\n\n"
    "```\n"
    "usage: agent-blame [-h] [--history] [--risk] [--diff] [--commit REV]\n"
    "                   [--staged] [--json] [--verbose] [--cwd CWD] [--version]\n"
    "                   [target]\n"
    "\n"
    "Deterministic Git archaeology: why this code exists, how it evolved, and what\n"
    "historical evidence matters before changing or removing it. No LLM, no network\n"
    "- the repository is the source of truth.\n"
    "\n"
    "positional arguments:\n"
    "  target        <file>:<line> or <file>:<start>-<end>\n"
    "\n"
    "options:\n"
    "  -h, --help    show this help message and exit\n"
    "  --history     show the ranked historical timeline for the target\n"
    "  --risk        historical change/removal risk analysis\n"
    "  --diff        DIFF mode: analyze the current working-tree changes\n"
    "  --commit REV  COMMIT mode: analyze a specific commit (sha, abbrev, HEAD,\n"
    "                HEAD~1, ...)\n"
    "  --staged      with --diff: analyze staged changes (git diff --cached)\n"
    "  --json        machine-readable JSON output (stable schema)\n"
    "  --verbose     verbose output: per-evidence weights and reasons\n"
    "  --cwd CWD     repository or subdirectory to analyze (default: cwd)\n"
    "  --version     show program's version number and exit\n"
    "```\n\n"
    "You may use it or not - your choice. You may also use normal repository "
    "tooling (git, grep, find, shell utilities) as you normally would."
)

# --- personas ---------------------------------------------------------------

PERSONAS = {
    "P1": {
        "name": "Git Expert",
        "model": "qwen3-coder:30b-agent",
        "traits": (
            "You are an expert in Git history and archaeology. You know "
            "`git blame`, `git log`, `git show`, `git diff`, `git rev-list` "
            "and reflog tricks inside out. You are skeptical of tools that "
            "merely wrap git - you prefer raw git unless something clearly "
            "adds value, and you verify any tool's claims against git "
            "before trusting them."
        ),
    },
    "P2": {
        "name": "Senior Developer",
        "model": "qwen3-coder:30b",
        "traits": (
            "You maintain unfamiliar production repositories. You value "
            "correctness and evidence over speed. You are careful and "
            "methodical, and you verify important claims before acting on "
            "them. You have strong general git skills but are not a "
            "git-archaeology specialist."
        ),
    },
    "P3": {
        "name": "Maintenance Developer",
        "model": "qwen3-coder:30b-robust",
        "traits": (
            "You frequently investigate old code before modifying it. You "
            "are particularly concerned with historical context and "
            "regressions - \"has this area been problematic before?\" is a "
            "question you ask constantly. You want to know why code exists "
            "before you touch it."
        ),
    },
    "P4": {
        "name": "Less Git-Experienced Developer",
        "model": "qwen2.5-coder:14b",
        "traits": (
            "You are comfortable writing code but not an expert in Git "
            "archaeology. You know basic `git add` / `git commit` / "
            "`git push` but rarely use `git log`, `git blame`, or "
            "`git show`. You prefer simple commands and clear, readable "
            "output. You may not know the best git command for a question - "
            "that is fine; do your best with what you know."
        ),
    },
    "P5": {
        "name": "Code Reviewer",
        "model": "qwen3-coder:30b-agent",
        "traits": (
            "You investigate changes before approving them. You care about "
            "callers, risk, history, and unintended consequences. You "
            "review pull requests professionally: you want to know who and "
            "what a change affects, whether similar changes have caused "
            "problems before, and whether the change is safe in historical "
            "context."
        ),
    },
    "P6": {
        "name": "Adversarial Skeptic",
        "model": "qwen3-coder:30b",
        "traits": (
            "You explicitly attempt to prove that extra tooling is "
            "unnecessary. You assume an experienced developer can "
            "accomplish everything with standard git. You look aggressively "
            "for false value, redundant output, misleading conclusions, and "
            "unnecessary complexity. You prefer the simplest possible git "
            "commands and are highly suspicious of any tool that claims to "
            "add insight. You will say so plainly when a tool adds nothing."
        ),
    },
}

SYSTEM_SHELL = """You are {NAME}. {TRAITS}

You are working in a large, unfamiliar codebase. You have been given an
investigation task. You interact with a bash shell. To run a command,
respond with exactly one fenced bash block:

```bash
<command>
```

The command is executed and its output is returned to you. You may run as
many commands as you need, one per turn. {ENV}

When you have enough evidence, respond with a section starting with
`FINAL ANSWER:` - state your conclusion, your confidence
(HIGH / MEDIUM / LOW / INSUFFICIENT), and the evidence you based it on.

Rules: this is a read-only investigation. Never modify the repository
(no `git commit`, `git checkout`, `git reset`, `git clean`, no file
edits, no `rm`). Investigation commands only."""

# --- tasks ------------------------------------------------------------------

TASKS = {
    "T1": {
        "repo": "requests",
        "repo_desc": "the `requests` Python HTTP library",
        "text": """You have inherited the `requests` library. You are about to modify a
function you have never seen, and you want to understand why it exists
before touching it.

**Target:** `src/requests/models.py` - the function `prepare_url` inside
`PreparedRequest` (it starts around line 483).

**Question:** Where did this code come from, and what should you know about
its history before changing it?

Report your findings and your confidence (HIGH / MEDIUM / LOW /
INSUFFICIENT).""",
    },
    "T2": {
        "repo": "requests",
        "repo_desc": "the `requests` Python HTTP library",
        "text": """In `src/requests/__init__.py`, around line 74, there is a
`check_compatibility` function that runs "sanity checks upon boot". A
colleague claims the project has always had this check there.

**Question:** Was this code originally introduced in `__init__.py`, or was
it moved there from somewhere else? If it moved, where did it actually come
from? How confident are you?

Report your findings and your confidence (HIGH / MEDIUM / LOW /
INSUFFICIENT).""",
    },
    "T3": {
        "repo": "rich",
        "repo_desc": "the `rich` terminal formatting library",
        "text": """A colleague has prepared a small change to `rich/console.py`: inside the
method around line 1891 they add a `# NOTE: verify kwargs are forwarded`
comment. The change is already applied to the working tree.

**Question:** Before this change is submitted, what does the historical
context of the code being changed have to say? Who depends on it, what
happened to it before, and is there any history that suggests caution?

(You are reviewing the change - you do not need to modify anything.)

Report your findings and your confidence (HIGH / MEDIUM / LOW /
INSUFFICIENT).""",
    },
    "T4": {
        "repo": "requests",
        "repo_desc": "the `requests` Python HTTP library",
        "text": """A colleague points you at commit `fd13816d` - subject: `Revert "Fix for
response with UTF-8 BOM #4976"`. It looks unusual.

**Question:** What did this commit change, and what historical context
explains it? Why might it matter?

Report your findings and your confidence (HIGH / MEDIUM / LOW /
INSUFFICIENT).""",
    },
    "T5": {
        "repo": "flask",
        "repo_desc": "the `flask` Python web framework",
        "text": """You need to modify the request-dispatch path of Flask. The function
`dispatch_request` in `src/flask/app.py` (around line 969) is registered
and called by the framework itself.

**Question:** What code currently depends on this function, and are there
historical reasons to be cautious before changing it?

Report your findings and your confidence (HIGH / MEDIUM / LOW /
INSUFFICIENT).""",
    },
    "T6": {
        "repo": "requests",
        "repo_desc": "the `requests` Python HTTP library",
        "text": """In `src/requests/adapters.py`, around line 85, there is a function
`_urllib3_request_context` that builds connection/SSL parameters. You are
told the SSL handling in this area "has a complicated past".

**Question:** Determine whether there is historical evidence that this area
previously had a problem or was subsequently corrected. What exactly
happened, and how confident are you?

Report your findings and your confidence (HIGH / MEDIUM / LOW /
INSUFFICIENT).""",
    },
    "T7": {
        "repo": "requests",
        "repo_desc": "the `requests` Python HTTP library",
        "text": """You are asked to investigate `src/requests/models.py` at line 99999 - a
line number you were told "is where something important lives".

**Question:** Investigate this target and explain what is there and its
history. If you cannot establish the facts, say so plainly and say why.

Report your findings and your confidence (HIGH / MEDIUM / LOW /
INSUFFICIENT).""",
    },
    "T8": {
        "repo": "requests",
        "repo_desc": "the `requests` Python HTTP library",
        "text": """You are asked to explain the history of `.pre-commit-config.yaml`, a small
21-line configuration file at the repository root (a colleague is
considering removing it and wants to know if it matters).

**Question:** Where did this file come from, and does its history contain
anything that should affect the decision? Be honest about whether this
investigation is actually worth anyone's time.

Report your findings and your confidence (HIGH / MEDIUM / LOW /
INSUFFICIENT).""",
    },
}

REPO_PATHS = {
    "requests": "/tmp/ab-eval/requests",
    "flask": "/tmp/ab-eval/flask",
    "rich": "/tmp/ab-eval/rich",
}

# Session matrix: (task, persona, session_type) in run order.
SESSION_MATRIX = [
    ("T1", "P4", "baseline"),
    ("T1", "P4", "treatment"),
    ("T1", "P1", "baseline"),
    ("T1", "P1", "treatment"),
    ("T2", "P3", "baseline"),
    ("T2", "P3", "treatment"),
    ("T3", "P5", "baseline"),
    ("T3", "P5", "treatment"),
    ("T4", "P2", "baseline"),
    ("T4", "P2", "treatment"),
    ("T5", "P1", "baseline"),
    ("T5", "P1", "treatment"),
    ("T6", "P3", "baseline"),
    ("T6", "P3", "treatment"),
    ("T7", "P5", "baseline"),
    ("T7", "P5", "treatment"),
    ("T8", "P6", "baseline"),
    ("T8", "P6", "treatment"),
    # Guided round: same tasks/personas, tool's own --help docs provided.
    ("T1", "P1", "guided"),
    ("T2", "P3", "guided"),
    ("T3", "P5", "guided"),
    ("T4", "P2", "guided"),
    ("T5", "P1", "guided"),
    ("T6", "P3", "guided"),
    ("T7", "P5", "guided"),
    ("T8", "P6", "guided"),
]
