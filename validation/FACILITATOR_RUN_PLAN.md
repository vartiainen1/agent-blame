# agent-blame — Facilitator Run Plan (real 5-developer study)

**Prepared:** 2026-08-19
**Status:** NOT YET RUN — this plan is the facilitator's day-of checklist.
**Package verified:** all six reference targets reproduce with agent-blame
0.1.0 on the current study clones (see §10 appendix for today's exact
values). No broken artifacts found; the protocol is executable as written.

The authoritative documents remain `STUDY_PROTOCOL.md` (procedure),
`PARTICIPANT_QUICKSTART.md`, `TASK_SHEET.md`, `MEASUREMENT_FORM.md`, and
`REFERENCE_TARGETS.md` (facilitator only). This plan is the condensed,
chronological version with the current machine state filled in.

---

## 1. Exact prerequisites for a facilitator

Before recruiting anyone:

1. **A study machine** with Python 3.9+ and git. (This machine qualifies:
   `C:\Users\vartiainen\Desktop\ai\llama-improvements\agent-blame\.venv`
   exists and `agent-blame` runs from it.)
2. **agent-blame installed and runnable as `agent-blame` on PATH.** On this
   machine the working install is the shim:
   ```bash
   # /tmp/ab-eval/bin/agent-blame  (already executable):
   export PATH=/tmp/ab-eval/bin:$PATH
   agent-blame --version    # -> agent-blame 0.1.0
   ```
   On any other machine, follow `STUDY_PROTOCOL.md` §4 (`pip install -e .`
   or the `PYTHONPATH python -m agent_blame` fallback).
3. **Study repositories, full clones (never shallow):**
   `/tmp/ab-eval/requests`, `/tmp/ab-eval/flask`, `/tmp/ab-eval/rich`
   (already cloned here; heads: requests `80683562` (2026-08-11), flask
   `2a8a38b0` (2026-08-11), rich `9d8f9a37` (2026-06-23)). They must be
   **clean** (`git status --porcelain` empty) before each session — the
   T3 participant edits `rich/console.py`, so restore it afterwards:
   `git -C /tmp/ab-eval/rich checkout -- rich/console.py`.
4. **Environment self-check passed** — run the commands in
   `REFERENCE_TARGETS.md` §0 (also listed in §10 here). If any expected
   answer does not reproduce, do not start the study.
5. **Printed materials** (one set per participant):
   - `PARTICIPANT_QUICKSTART.md`
   - the participant's single task page from `TASK_SHEET.md` (cut so the
     footer "Facilitator note: tasks map to the product's modes as — ..."
     is never handed over)
   - one blank `MEASUREMENT_FORM.md`
6. **Facilitator's own copy** of `REFERENCE_TARGETS.md` (never shown to
   participants).
7. **A timer** (phone stopwatch is fine) and a way to record command
   timestamps.
8. **Consent:** tell each participant that observations are being recorded,
   they can stop at any time, and the report anonymizes them
   (`STUDY_PROTOCOL.md` §15 checklist). A written one-page consent notice
   is recommended (§10, optional).

## 2. Exact files/scripts the facilitator needs

| File | Role | Give to participant? |
|------|------|----------------------|
| `validation/STUDY_PROTOCOL.md` | the procedure (this plan condenses it) | no |
| `validation/PARTICIPANT_QUICKSTART.md` | participant onboarding | **yes** |
| `validation/TASK_SHEET.md` | 5 tasks; hand only the assigned task's page | **yes (one page only)** |
| `validation/MEASUREMENT_FORM.md` | observation + questionnaire + 36-section report template | no (facilitator fills it) |
| `validation/REFERENCE_TARGETS.md` | ground truth + trust-calibration verification commands | no |
| `validation/FACILITATOR_RUN_PLAN.md` | this plan | no |

**No scripts need to be run.** Sessions are manual: participant types
commands, facilitator observes. The only commands the facilitator ever
runs are the trust-calibration git verifications (§7) and the T3 restore.
(`validation/ai/*` is the separate AI-validation harness — **not** part of
the human study; ignore it here.)

## 3. Recruiting / onboarding the five participants

1. **Recruit 5 developers** matching the §2 backgrounds, ideally one each:
   git expert, normal developer ×2, rarely-investigates developer, and a
   legacy/unfamiliar-code maintainer. Anyone who built agent-blame or saw
   its internals is excluded.
2. **Consent + schedule:** explain observation/recording + anonymization;
   schedule 30–45 min per session with a **15-minute gap** between
   sessions (write-up time). Suggest ≥3 participants per day max, or two
   half-days.
3. **Prepare the session room:** repos clean, materials printed, timer on
   the desk, `REFERENCE_TARGETS.md` open on the facilitator's side.
4. **Session start:** read the §7 intro script verbatim, hand over
   `PARTICIPANT_QUICKSTART.md` + the task page, start the timer.
5. **After each session:** fill the measurement form immediately (verbatim
   quotes while fresh); run the T3 restore if applicable; verify the repo
   is clean before the next participant.

## 4. What the participant receives before each task

Exactly two documents, and nothing else:

1. `PARTICIPANT_QUICKSTART.md` — what the tool is, how to run it, the
   ground rules ("no correct command sequence", "confusion is a finding").
2. **Their single task page** from `TASK_SHEET.md` — the scenario, the
   target, the question, and the "Option B (own repo)" line if they prefer
   their own code.

They must **not** receive: `REFERENCE_TARGETS.md`, the task-sheet footer
(mode mapping), the measurement form, the protocol, or any hint about
which feature/mode the task exercises.

## 5. What the facilitator may / may not explain

**May (and must):** the verbatim §7 intro script; that `agent-blame --help`
shows what the tool can do; that normal git is allowed; the minimum-help
interventions when genuinely stuck — the protocol's example: "the tool
takes a `file:line` target — try `agent-blame --help`".

**May not:** name any feature or command for the task ("try the callers
section", "use `--diff`", "the answer is the movement section"); explain
what the tool is "supposed" to do; lead the debrief questions; suggest
which output sections matter. Every help given must be recorded on the
form ("Facilitator had to help — when and how much").

## 6. Exact task sequence and timing

**Task-to-participant assignment** (cover the core three at minimum; all
five if possible):

| Participant background | Suggested task | Mode exercised (do NOT tell them) |
|-----------------------|----------------|-----------------------------------|
| 1. Git expert | T1 WHY (`models.py:483`) | WHY |
| 2. Normal dev | T3 change review (`rich/console.py`) | `--diff` |
| 3. Normal dev | T4 risk/callers (`flask app.py:969`) | WHY/RISK + callers |
| 4. Rarely investigates | T2 moved code (`requests __init__.py`) | WHY + movement |
| 5. Legacy-code maintainer | T5 commit (`fd13816d`) | `--commit` |

**Per-session timeline (30–45 min):**

| Phase | Time | Action |
|-------|------|--------|
| A. Intro | 3 min | Read §7 script verbatim; hand over quickstart + task page; start timer |
| B. Task | 15–20 min | Observe silently; log every command + timestamp; intervene only if truly stuck (record the intervention) |
| C. Trust calibration | 5–10 min | For up to 3 conclusions the participant relied on: confidence (H/M/L) → verify with the exact git commands in `REFERENCE_TARGETS.md` → record match |
| D. Debrief | 10 min | The 16-question questionnaire (§10 of the protocol); ask "What would you have done without agent-blame?" **last**; record verbatim |
| — | 15 min | Write up the form; restore the tree if T3; clean the repo |

**Full study:** 5 sessions ≈ 4–5 hours including gaps. Do not run more
than ~3 sessions back-to-back.

## 7. Observations / results that must be recorded

For **each** participant, one `MEASUREMENT_FORM.md`:

- Participant metadata (anonymized ID, background, years, date, repo, task,
  total duration).
- **Full command log with timestamps** (agent-blame AND git, in order).
- First command (before any help); first successful agent-blame command;
  time to first useful result; time to answer.
- Which output sections they visibly read vs skipped (WHY/Facts/
  Inferences/Evidence/Counter-evidence/Callers/Movement/Regressions/Risk/
  Historical chain).
- Hesitations/misunderstandings (verbatim quotes); whether they verified
  with manual git, and what.
- Which features they noticed without prompting (movement/callers/
  regression/risk/`--diff`/`--commit`/`--json`).
- Whether they re-ran agent-blame voluntarily after the first answer.
- **Trust calibration:** up to 3 claims — verbatim claim, participant
  confidence (H/M/L), facilitator's git verification, correct?, confidence
  appropriate?. HIGH confidence + wrong = immediate flag.
- Wording comprehension: "Historical removal risk: HIGH", "INSUFFICIENT
  EVIDENCE", last-modifier vs origin.
- The 16 verbatim questionnaire answers.
- Product-market signal tick (VERY STRONG → NEGATIVE) with quotes.
- Scorecards (§8/§9 of the form): 9 product dimensions + 8 features, each
  **with the observation that justifies the score**.
- Bugs/confusion/feature requests table with classification and priority
  (record only — never fix mid-study).

## 8. What constitutes a successful study run

All of the following:

1. **5 real, distinct participants** (or the agreed minimum), none of whom
   built the tool.
2. Every session followed the §6 flow; **every measurement form is fully
   filled** — including the command log, trust calibration, and the 16
   verbatim answers.
3. **At least one ground-truth conclusion per participant was verified**
   against git (trust calibration), so the accuracy findings are real.
4. The environment self-check passed on study day (targets reproduced).
5. **No unlogged correctness problem:** any HIGH-confidence + wrong result
   (or tool bug) is recorded and reported immediately; nothing is hidden.
6. The report is honest: real quotes and counts only; the Phase 4 AI
   simulations stay labeled as simulations; negative findings are reported
   as prominently as positive ones.
7. The final report follows the 36-section template in `MEASUREMENT_FORM.md`
   §12 and ends with an **evidence-based A–E classification** — not the
   prior provisional classification repeated.

## 9. Summarizing results against USEFUL MVP (C), provisional

- The current classification is **USEFUL MVP (C), PROVISIONAL** — it rests
  on AI simulation (Phases 3/4/6), not real developers. The study's job is
  to replace "provisional" with an evidence-based verdict.
- Use the §11 ladder: **A** NOT READY → **B** TECHNICALLY SOLID, LIMITED
  VALUE → **C** USEFUL MVP → **D** STRONG MVP → **E** READY FOR BROADER
  RELEASE. Apply it from the observed behavior only:
  - Evidence for C/D: developers independently reuse the tool, trust the
    output after verification, and cite a recurring use case (the §12
    signal guide: STRONG/VERY STRONG patterns).
  - Evidence for B: correct but "normal git is easier" (NEGATIVE) or no
    recurring use case.
  - Evidence for A: a confirmed correctness bug, especially HIGH-confidence
    + wrong.
- Report the killer use case, the weakest use case, and the product-market
  signal with the observations behind each. Requested features are
  classified MUST FIX / HIGH-VALUE / NICE TO HAVE / OUT OF SCOPE and **not
  built during the study**.
- The report's first line stays honest: if the study has not run, "Real
  human validation remains outstanding." If it has run, that line becomes
  the real participant count.

## 10. Verified state + missing materials / ambiguities (2026-08-19)

**Ground truth re-verified today against the current clones** (the
reference file says "verified 2026-08-17"; here is today's state):

| Target | Command | Expected (today) | Verified? |
|--------|---------|------------------|-----------|
| §0 self-check | `agent-blame --version` | agent-blame 0.1.0 | ✅ |
| T1 | `agent-blame src/requests/models.py:483` | HIGH; introduced by `561e4b68`; 1 caller at line 441 | ✅ |
| T2 | `agent-blame src/requests/__init__.py:74` | HIGH; moved here by `d63e94f5`; origin `2b34880e` "sanity checks upon boot" | ✅ |
| T3 | `agent-blame --commit fd13816d` | `revert_of` = `19cff44e` (explicit revert) | ✅ |
| T4 | `agent-blame src/flask/app.py:969` | HIGH; `6a649690`; 1 DIRECT_CALL at 1019 (`full_dispatch_request`) | ✅ |
| T5 | `agent-blame rich/console.py:1891` | MEDIUM (0.40); `ebb4eaa2` "themed tracebacks" | ✅ |
| T6 | `agent-blame src/requests/models.py:99999` | INSUFFICIENT (file has 1184 lines) | ✅ |

**Items identified (none block the study; smallest fixes proposed):**

1. **T2 line drift — documentation note only.** The `check_compatibility`
   **def** moved from line 74 to **line 60** (upstream "Add inline types"
   commits). Line 74 is still *inside the function body* and the tool's
   expected output (movement + origin `2b34880e`) still reproduces there,
   so the target is valid as written. Proposed (one-line, facilitator-only):
   add a note to `REFERENCE_TARGETS.md` §1 T2 — "def is now at line 60
   (blamed to the 2026 annotation commit `561e4b68`); the reference line
   74 is inside the body and reproduces the movement answer" — so a
   facilitator isn't confused if a participant lands on the def.
2. **Consent form (optional).** The protocol covers consent verbally in the
   §15 checklist. A one-page written observation/consent notice is
   recommended for real participants; propose adding
   `validation/CONSENT_NOTICE.md` (a copy to keep, a copy to sign).
3. **Task-sheet footer leakage (handling note).** `TASK_SHEET.md`'s footer
   maps tasks→modes. The protocol already says hand only the task's page;
   this plan makes it explicit: print/cut per-task, never hand the whole
   file.
4. **Repo freshness on study day.** The clones at `/tmp/ab-eval` are
   current as of 2026-08-11 (requests) / 2026-08-11 (flask) / 2026-06-23
   (rich) and today's targets reproduce. Upstream moves between now and
   the study date will drift line numbers — re-run the §10 table on study
   day and adjust per the reference file's own drift clause (re-locate the
   function; the expected answer is the function, not the line).

**Explicitly out of scope:** nothing in this plan changes the product,
the protocol's procedure, the prompts, or the evaluation. The study is
evidence collection only.
