# agent-blame — Study Task Sheet

One task per participant. Your facilitator will tell you which task is
yours. Each task is a realistic maintenance scenario. Work through it with
**agent-blame**; you may also use normal `git` if you want.

There is no single correct way to do these tasks and no hidden expected
answer. Stop when you feel you have learned what you need — then tell the
facilitator.

> Prefer your own repository? If you would rather investigate code you
> actually work with, tell the facilitator and pick a function you find
> confusing there instead. The "Option B" line in each task tells you how
> to adapt.

---

## TASK 1 — Understand code history (WHY)

**Scenario:** You have inherited the `requests` library. You are about to
modify a function you have never seen, and you want to understand why it
exists before touching it.

**Target:** `src/requests/models.py`, around line 483 — the function
`prepare_url` in `PreparedRequest`.

**Question:** Where did this code come from, and what should you know about
its history before changing it?

*Option B (own repo):* pick any function you have never read and ask the
same question.

---

## TASK 2 — Moved code

**Scenario:** In `requests`, `src/requests/__init__.py` line 74 contains
`check_compatibility`, which runs "sanity checks upon boot". A colleague
claims the project has always had this check there.

**Question:** Was this code originally introduced in `__init__.py`, or was
it moved there from somewhere else? If it moved, where did it actually come
from?

*Option B (own repo):* find a function you suspect was moved (e.g. a file
that looks like a refactored copy of another) and determine its real
origin.

---

## TASK 3 — Change review (your own diff)

**Scenario:** You are about to submit a small change to `rich`'s console
module: in `rich/console.py`, inside `Console.print` (around line 1891),
make a small edit — for example, change a default parameter value or add a
`# TODO` comment on a line inside the method.

**Question:** Before you submit this change, what does the historical
context of the code you are changing have to say? Who depends on it, what
happened to it before, and is there any history that suggests caution?

When you are done investigating, you may undo your edit (the facilitator
can help restore the file) — the study only cares about the investigation.

*Option B (own repo):* make any small real change you are already working
on and investigate its historical context.

---

## TASK 4 — Dependency / risk before modifying

**Scenario:** You need to modify `flask`'s request-dispatch path. The
function `dispatch_request` in `src/flask/app.py` (around line 969) is
registered and called by the framework itself.

**Question:** What historical information should you know before changing
this function — where it came from, who calls it, and what evidence exists
that changing it deserves caution?

*Option B (own repo):* pick a function other code depends on and answer the
same question.

---

## TASK 5 — Commit investigation

**Scenario:** A colleague points you at commit `fd13816d` in `requests` —
subject: `Revert "Fix for response with UTF-8 BOM #4976"`. It looks
unusual.

**Question:** What did this commit change, and what historical context
explains it? Why might it matter?

*Option B (own repo):* pick a commit you consider suspicious or important
and investigate it the same way.

---

*Facilitator note: tasks map to the product's modes as — 1: WHY, 2: WHY +
movement, 3: --diff, 4: WHY/RISK + callers, 5: --commit. Do not tell the
participant which mode each task uses.*
