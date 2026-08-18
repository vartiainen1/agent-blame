# agent-blame — Phase 6A: Task Sheet (persona-facing)

Eight realistic repository-investigation tasks. Tasks are written without
any hint about what agent-blame can do, and without telling the persona
which commands to use. The correct approach is whatever the persona
naturally chooses with its available tooling.

Each task ends with: "Report your findings and your confidence
(HIGH / MEDIUM / LOW / INSUFFICIENT)." The persona decides when it has
enough evidence.

---

## TASK 1 — WHY

**Repository:** `requests` (Python HTTP library, `src/requests/`)

You have inherited the `requests` library. You are about to modify a
function you have never seen, and you want to understand why it exists
before touching it.

**Target:** `src/requests/models.py` — the function `prepare_url` inside
`PreparedRequest` (it starts around line 483).

**Question:** Where did this code come from, and what should you know about
its history before changing it?

---

## TASK 2 — MOVED CODE

**Repository:** `requests`

In `src/requests/__init__.py`, around line 74, there is a
`check_compatibility` function that runs "sanity checks upon boot". A
colleague claims the project has always had this check there.

**Question:** Was this code originally introduced in `__init__.py`, or was
it moved there from somewhere else? If it moved, where did it actually come
from? How confident are you?

---

## TASK 3 — CHANGE REVIEW

**Repository:** `rich` (terminal formatting library, `rich/console.py`)

A colleague has prepared a small change to `rich/console.py`: inside the
method around line 1891 they add a `# NOTE: verify kwargs are forwarded`
comment. The change is already applied to the working tree.

**Question:** Before this change is submitted, what does the historical
context of the code being changed have to say? Who depends on it, what
happened to it before, and is there any history that suggests caution?

(You are reviewing the change — you do not need to modify anything.)

---

## TASK 4 — COMMIT INVESTIGATION

**Repository:** `requests`

A colleague points you at commit `fd13816d` — subject: `Revert "Fix for
response with UTF-8 BOM #4976"`. It looks unusual.

**Question:** What did this commit change, and what historical context
explains it? Why might it matter?

---

## TASK 5 — DEPENDENCY / CALLER RISK

**Repository:** `flask` (Python web framework, `src/flask/app.py`)

You need to modify the request-dispatch path of Flask. The function
`dispatch_request` in `src/flask/app.py` (around line 969) is registered
and called by the framework itself.

**Question:** What code currently depends on this function, and are there
historical reasons to be cautious before changing it?

---

## TASK 6 — REGRESSION / FIX HISTORY

**Repository:** `requests`

In `src/requests/adapters.py`, around line 85, there is a function
`_urllib3_request_context` that builds connection/SSL parameters. You are
told the SSL handling in this area "has a complicated past".

**Question:** Determine whether there is historical evidence that this area
previously had a problem or was subsequently corrected. What exactly
happened, and how confident are you?

---

## TASK 7 — INSUFFICIENT EVIDENCE

**Repository:** `requests`

You are asked to investigate `src/requests/models.py` at line 99999 — a
line number you were told "is where something important lives".

**Question:** Investigate this target and explain what is there and its
history. If you cannot establish the facts, say so plainly and say why.

---

## TASK 8 — NEGATIVE CONTROL (ADVERSARIAL)

**Repository:** `requests`

You are asked to explain the history of `.pre-commit-config.yaml`, a small
21-line configuration file at the repository root (a colleague is
considering removing it and wants to know if it matters).

**Question:** Where did this file come from, and does its history contain
anything that should affect the decision? Be honest about whether this
investigation is actually worth anyone's time.

---

## Facilitator note (not shown to personas)

| Task | Mode under test | Ground truth reference |
|------|-----------------|------------------------|
| 1 | WHY | `AI_GROUND_TRUTH.md` §T1 |
| 2 | WHY + movement | §T2 |
| 3 | --diff / change review | §T3 |
| 4 | --commit | §T4 |
| 5 | WHY/RISK + callers | §T5 |
| 6 | regression detection | §T6 |
| 7 | insufficient-evidence honesty | §T7 |
| 8 | negative control | §T8 |
