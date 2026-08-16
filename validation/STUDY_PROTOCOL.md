# agent-blame — Real-Developer Validation Study: Protocol

> **STATUS: NOT YET RUN.** This is the executable protocol for a real
> 5-developer study. It has been prepared and verified (installation paths,
> reference targets, measurement forms), but **no human participants have
> taken part yet**. Do not present any results as real until a facilitator
> has run this protocol with actual participants and filled in
> `MEASUREMENT_FORM.md` for each session.

Audience of this document: the **facilitator** (the person running the
study). Participants receive only `PARTICIPANT_QUICKSTART.md` and their
assigned task from `TASK_SHEET.md`.

Goal: determine whether real developers understand, trust, and would reuse
agent-blame — using observed behavior, not polite enthusiasm.

---

## 1. What is being validated

agent-blame is a local Git-archaeology tool. It answers questions like:

- Where did this code come from, and why does it exist?
- Was this code moved here from somewhere else?
- Who calls this code?
- What should I know from history before changing it?
- Was this change later reverted or corrected?

It does **not** prove code safety. It reports historical evidence and says
`INSUFFICIENT EVIDENCE` when it does not know. The study tests whether
developers understand and value exactly that.

The tool's own honest positioning (do not hide this from participants if
they ask):

- It is **not faster than a known `git blame` command** — it is a
  **discovery + aggregation layer** (knowing which commands to run,
  combining evidence, tracing movement, finding callers).
- It never claims "unused", "safe", or "this caused a bug".

## 2. Participants (guidelines, not quotas)

Aim for **5 developers, 30–45 minutes each**. Backgrounds to look for:

| # | Background | Why |
|---|-----------|-----|
| 1 | Git expert (uses `git blame`/`git log` regularly) | hardest audience; checks wall-clock trade-off |
| 2 | Normal professional developer | mainstream usability |
| 3 | Normal professional developer | repetition check (avoid overfitting to one dev) |
| 4 | Developer who rarely investigates Git history | discoverability + jargon test |
| 5 | Developer who maintains unfamiliar/legacy code | the core use case (meeting unknown code) |

Any mix is acceptable; record each participant's actual background. Do not
use people who built agent-blame or who have seen its internals.

## 3. Materials you need

1. This folder:
   - `PARTICIPANT_QUICKSTART.md` — give to each participant.
   - `TASK_SHEET.md` — assign one task per participant.
   - `MEASUREMENT_FORM.md` — one copy per participant; fill in during and
     after the session.
   - `REFERENCE_TARGETS.md` — your ground-truth reference (keep it with
     you, do not hand it to participants).
2. A machine with Python 3.9+ and git, with agent-blame installed (see
   section 4).
3. Clones of the study repositories (see section 5). Read-only; the tool
   never writes to them.
4. A stopwatch or phone timer.

## 4. Environment setup (do this before any session)

Install agent-blame once on the study machine:

```bash
git clone <your agent-blame repo URL or copy the folder>
cd agent-blame
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -e .
agent-blame --version   # must print agent-blame 0.1.0
agent-blame --help      # must print usage
```

If `pip install -e .` fails (e.g. no network for build tools), the
no-install fallback works too — agent-blame is stdlib-only:

```bash
# Windows (Git Bash):
PYTHONPATH=/path/to/agent-blame python -m agent_blame --version
# PowerShell:
$env:PYTHONPATH = "C:\path\to\agent-blame"; python -m agent_blame --version
```

**Self-check (2 minutes, before the first participant):** run the
environment-validation commands in `REFERENCE_TARGETS.md` §0. If the tool
does not produce the expected confidence/answer on those targets, do not
start the study until it does — the study would be testing a broken build.

## 5. Study repositories

Participants need repositories they do **not** know well (that is the
point). Recommended (the reference targets were verified against current
upstream `main` of these):

```bash
git clone https://github.com/psf/requests.git   # ~50 MB
git clone https://github.com/pallets/flask.git
git clone https://github.com/Textualize/rich.git
```

Participants may instead use **their own repository** or one they know —
natural usage is more valuable than uniformity. If they use their own repo,
skip the line-number reference targets for trust calibration and instead
verify their conclusions with `git blame`/`git show` on the spot (section
9.3 covers this).

Note: the tool itself never touches the network; cloning is just to obtain
the repositories. Do **not** use shallow clones for the reference targets —
shallow history changes the tool's output (`LIMITED HISTORY` warnings) and
would invalidate the ground truth.

## 6. Session flow (30–45 minutes total)

| Phase | Time | What happens |
|-------|------|--------------|
| A. Intro | 3 min | Read the participant the intro script (§7). Give them `PARTICIPANT_QUICKSTART.md` and their task. **Do not explain the features or which commands to use.** |
| B. Task | 15–20 min | Participant works the task. You observe silently and record (§9). Intervene only if truly stuck — record the exact point of confusion first (§7, "If stuck"). |
| C. Trust calibration | 5–10 min | For up to 3 conclusions the participant relied on, run the trust-calibration exchange (§9.3). |
| D. Debrief | 10 min | Post-session questionnaire (§10). Ask "What would you have done without agent-blame?" last. |

Total per participant: **30–45 minutes**. Schedule a 15-minute gap between
sessions to finish writing up the observation form.

## 7. Intro script (read verbatim — no extra hints)

> "You're evaluating a developer tool called agent-blame. It investigates
> git history. I'm going to give you a maintenance task and this tool, and
> I want to see how you use it. There are no wrong answers — if something
> is confusing or useless, that is exactly what I want to know.
>
> You can run the tool however you like. `agent-blame --help` shows you
> what it can do. You may also use git normally if you want — that is part
> of the comparison.
>
> I'll be taking notes while you work. I won't help unless you're really
> stuck, and I won't tell you what the tool is supposed to do. When you've
> found an answer — or you feel you've gone as far as you can — tell me and
> we'll talk about what you found."

### If stuck

Record the exact moment and what they tried. Then give the **minimum** help
to continue, e.g. "the tool takes a `file:line` target — try
`agent-blame --help`" — and record that you helped. Never say "try the
callers section" or "use --diff" — that would be marketing, not observation.

## 8. Task assignment

Assign tasks from `TASK_SHEET.md`. Cover the range across the five
participants (all 5 tasks if possible; at minimum tasks 1, 3, and 4 —
WHY/history, change review, dependency/risk — are the core use cases).
Hand the participant their task's page only. The task sheet states the
question but never the command to use.

## 9. What to observe and record (during the task)

Fill in one `MEASUREMENT_FORM.md` per participant. Record, for each
participant:

1. **First command** they run (before any help): e.g. `agent-blame --help`,
   `git log`, `agent-blame file.py:1`.
2. **First successful agent-blame command** and how long until it produced
   a useful result.
3. **Every command** they run (agent-blame and git), in order, with a
   timestamp — this is the raw evidence for "time to answer" and "manual
   git vs agent-blame".
4. **Which sections of the output they read vs skip** — note what the
   output shows (WHY/Evidence/Callers/Movement/Regressions/Risk) and which
   parts they visibly engage with.
5. **Where they hesitate or misunderstand** — quote what they say.
6. **Whether they verify the result manually** (`git blame`, `git show`,
   `git log`) — and what they verify.
7. **Whether they notice, without prompting:** movement ("was this code
   moved here?"), callers, regression/revert history, risk, `--diff`,
   `--commit`, `--json`.
8. **Time to answer** — the moment they say "I've got an answer" or stop.
9. Whether they hit `--help` at all, and what they looked for in it.

### 9.3 Trust calibration (phase C)

For up to 3 conclusions the participant relied on:

1. Ask: "How confident are you that this result is correct?" (high /
   medium / low).
2. Independently verify with git yourself (see `REFERENCE_TARGETS.md` for
   the exact commands) or together with the participant.
3. Record: participant confidence vs actual correctness. **Pay special
   attention to HIGH confidence + wrong result** — that is the most serious
   failure mode. If it happens, record the exact claim and the ground
   truth, and report it immediately (section 12).

Also, if the session covers it, ask the participant to put these in their
own words (do not lead):

- What does "Historical removal risk: HIGH" mean to you?
  (Intended: "history suggests caution before changing this". NOT "the
  code is unsafe" / "do not change it" / "it will break".)
- What does "INSUFFICIENT EVIDENCE" mean to you?
  (Intended: "the repository evidence cannot support a stronger
  conclusion". NOT "nothing happened" / "no history exists".)
- The difference between "last person who changed this line" and "where
  this code originally came from".

## 10. Debrief — post-session questionnaire (phase D)

Ask every question; let the participant answer freely before you follow up.
Record verbatim answers on the measurement form. Do not ask in a way that
leads toward positive answers.

1. What do you think agent-blame does?
2. What did you expect it to tell you?
3. Did it answer your question?
4. What information was most useful?
5. What information was confusing?
6. Did anything appear unnecessary?
7. Did you trust the result? Why / why not?
8. Was there anything you would have verified manually?
9. Did the output change your understanding of the code?
10. Did it change what you would do next?
11. Did it save you time? (Follow up: compared to what?)
12. Would you use it again?
13. What would you expect agent-blame to do that it currently does not?
14. Would you install it in a real project?
15. Would you recommend it to another developer?
16. **What would you have done without agent-blame?** (the most important
    question — record exactly which git commands or manual steps they would
    have run)

## 11. After all sessions — analysis and scorecards

Use the filled measurement forms to produce the report (see
`MEASUREMENT_FORM.md` §"Report assembly" for the exact 36-section output
template). The scorecards must be **evidence-based**: for every score,
write the observation that justifies it. Classify the product:

| Class | Meaning |
|-------|---------|
| A | NOT READY — fundamental correctness problems |
| B | TECHNICALLY SOLID, LIMITED VALUE — correct but not compelling |
| C | USEFUL MVP — developers can realistically benefit today |
| D | STRONG MVP — clear recurring use cases + trustworthy output |
| E | READY FOR BROADER RELEASE |

Also identify, from observed behavior (not from this protocol's opinions):

- the **killer use case** (what developers independently call useful),
- the **weakest use case** (least used / most misunderstood),
- the **product-market signal** (see §12),
- requested features, each classified MUST FIX / HIGH-VALUE /
  NICE TO HAVE / OUT OF SCOPE (do not build any of them during the study).

## 12. Product-market signal guide (how to read the observations)

| Signal | Meaning |
|--------|---------|
| VERY STRONG | developer runs agent-blame again voluntarily, without being asked |
| STRONG | asks to install it / says it would join their workflow / uses it to answer a question they would otherwise dig for manually |
| MEDIUM | "useful, but I'd change the UX" |
| WEAK | "interesting" (polite) |
| NEGATIVE | "normal git is easier" / can't find a recurring use case |

Repeated patterns matter more than any single participant. If several
developers independently use WHY + movement, that is significant. If
several independently ignore regression detection, that is also
significant.

## 13. Bugs and feedback handling during the study

- Record every bug, confusion point, and feature request on the measurement
  form with the participant's words.
- Classify each: BUG / UX PROBLEM / DOCUMENTATION PROBLEM / PERFORMANCE
  PROBLEM / MISSING FEATURE / PERSONAL PREFERENCE.
- **Do not fix anything mid-study** (that would change what later
  participants are testing). Note it, finish the study, then decide.
- If a **correctness bug** is confirmed (especially HIGH confidence +
  wrong result), follow the project workflow afterwards: log the error in
  the Freebuff error log, write a regression test, fix, run the full suite,
  re-verify against the real repo, commit through the AREA gate.
- Feature requests are recorded, classified, and **not** built unless they
  are MUST FIX (blocking the study) or repeated by multiple independent
  participants.

## 14. Honesty rules for the report

- **Do not fabricate anything.** No invented quotes, participant counts,
  survey responses, or preferences. If the study has not happened yet, the
  report says: "Real human validation remains outstanding."
- Keep the Phase 4 simulated sessions labeled as simulations — they are
  not this study.
- The final classification must be based on this study's observed behavior,
  not on the Phase 3/4 evaluations.
- Report both good and bad findings. Negative feedback is the valuable half.

## 15. Checklist before you start

- [ ] agent-blame installed and `--help`/`--version` work on the study machine
- [ ] environment self-check passed (`REFERENCE_TARGETS.md` §0)
- [ ] study repos cloned (requests, flask, rich) or participant-repo plan agreed
- [ ] copies of `PARTICIPANT_QUICKSTART.md` and `TASK_SHEET.md` printed
- [ ] one blank `MEASUREMENT_FORM.md` per participant
- [ ] `REFERENCE_TARGETS.md` in your hands (not the participant's)
- [ ] timer available
- [ ] informed consent: tell the participant you are recording observations
      and that they can stop any time; anonymize names in the report
