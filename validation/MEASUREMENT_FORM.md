# agent-blame — Measurement Form (one per participant)

Fill in one copy of this form per session, during and immediately after the
session. Everything below the "Participant" header is per-participant. At
the end, use §12 (Report assembly) to build the final report.

---

## Participant

| Field | Value |
|-------|-------|
| Participant ID (anonymized, e.g. P1) | |
| Background (git expert / normal dev / rarely investigates / legacy-code maintainer) | |
| Years of professional experience | |
| Date / time | |
| Repository used (requests / flask / rich / own) | |
| Task assigned (1–5) | |
| Total session duration | |

---

## 1. Command log (record in order, with times)

| Time | Command (agent-blame or git, exactly as typed) | Result / notes |
|------|-----------------------------------------------|----------------|
| 0:00 | (first command) | |
| | | |
| | | |
| | | |

First command the participant ran (before any help): ____________

First *successful* agent-blame command: ____________
Time from session start to first useful result: ________

---

## 2. Observation fields

| Observation | Record |
|-------------|--------|
| First command (before any help) | |
| Did they read `--help`? What did they look for in it? | |
| Which output sections did they visibly read? (WHY / Facts / Inferences / Evidence / Counter-evidence / Callers / Movement / Regressions / Risk / Historical chain) | |
| Which sections did they skip? | |
| Where did they hesitate / misunderstand? (quote) | |
| Did they run manual git afterward? Which commands, and what did they verify? | |
| Did they notice, without prompting: movement? callers? regression/revert? risk? `--diff`? `--commit`? `--json`? | |
| Did the facilitator have to help? When and how much? (minimum help only) | |
| Time to answer (they say "done" or stop) | |
| Did they run agent-blame again voluntarily after the first answer? | |

---

## 3. Trust calibration (up to 3 conclusions the participant relied on)

| # | The claim (verbatim, incl. which section) | Participant confidence (H/M/L) | Ground truth (git command + result, verified by facilitator) | Correct? | Confidence appropriate? |
|---|------------------------------------------|-------------------------------|--------------------------------------------------------------|----------|--------------------------|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

**HIGH confidence + wrong result = the most serious finding. Flag it
immediately if it occurs.**

---

## 4. Wording comprehension (ask in the participant's own words; do not lead)

| Concept | What the participant said it means | Intended meaning | Match? |
|---------|-----------------------------------|------------------|--------|
| "Historical removal risk: HIGH" | | history suggests caution before changing; NOT "unsafe"/"don't change"/"will break" | |
| "INSUFFICIENT EVIDENCE" | | repository evidence can't support a stronger conclusion; NOT "nothing happened"/"no history" | |
| last modifier vs original origin | | `git blame` shows last modifier; the tool tries to trace the original introduction, correcting for moves | |

---

## 5. Time / effort comparison (if the task had a manual-git phase too)

| Question | Manual git (observed) | agent-blame (observed) |
|----------|----------------------|------------------------|
| Commands needed | | |
| Wall-clock time | | |
| Investigation effort (classification/digging required) | | |

Note the honest expectation: agent-blame is usually *not* faster per
command than a known `git` command. Its value is knowing which commands to
run and combining the results. Record what actually happened; do not try to
make either side look better.

---

## 6. Post-session questionnaire (record verbatim)

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
11. Did it save you time? (compared to what?)
12. Would you use it again?
13. What would you expect agent-blame to do that it currently does not?
14. Would you install it in a real project?
15. Would you recommend it to another developer?
16. **What would you have done without agent-blame?** (exact commands /
    manual steps they would have run)

---

## 7. Product-market signal (tick what applies; verbatim quote for each)

- [ ] VERY STRONG — ran agent-blame again voluntarily
- [ ] STRONG — asked to install it / "would join my workflow" / used it to
      answer a question they would otherwise dig for manually
- [ ] MEDIUM — useful but wants UX changes
- [ ] WEAK — "interesting"
- [ ] NEGATIVE — "normal git is easier" / no recurring use case

Quotes:

---

## 8. Product scorecard (1–10, with evidence per score)

| Dimension | Score | Evidence (observation) |
|-----------|-------|------------------------|
| Usefulness | | |
| Ease of use | | |
| Accuracy | | |
| Trustworthiness | | |
| Time saved / investigation effort | | |
| Explainability | | |
| Distinctiveness | | |
| Reuse intent | | |
| Recommendation intent | | |

## 9. Feature scorecard (1–10, with evidence per score)

| Feature | Used? | Usefulness | Comprehension | Accuracy | User reaction | Saves investigation effort? |
|---------|-------|-----------|---------------|----------|---------------|-----------------------------|
| WHY | | | | | | |
| HISTORY | | | | | | |
| RISK | | | | | | |
| --diff | | | | | | |
| --commit | | | | | | |
| CALLERS | | | | | | |
| MOVEMENT | | | | | | |
| REGRESSION | | | | | | |

Killer use case (what the participant independently called useful):
Weakest use case (least used / most misunderstood):

---

## 10. Bugs / confusion / feature requests (record everything)

| # | What happened (verbatim) | Classification (BUG / UX / DOC / PERF / MISSING FEATURE / PERSONAL PREFERENCE) | Priority (MUST FIX / HIGH-VALUE / NICE TO HAVE / OUT OF SCOPE) | Action (record only — never fix mid-study) |
|---|--------------------------|-------------------------------------------------------------------------------|----------------------------------------------------------------|--------------------------------------------|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

---

## 11. After the study (facilitator only)

Correctness bugs discovered (esp. HIGH-confidence + wrong): follow the
project workflow after the study — log the error in the Freebuff error log,
write a regression test, fix, run the full suite, re-verify against the
real repo, commit through the AREA gate. Never silently patch.

---

## 12. Report assembly (36-section final report template)

Produce one combined report covering all participants. Required sections:

1. Executive summary
2. Number of real participants
3. Participant backgrounds
4. Repositories used
5. Tasks used
6. First-use behavior
7. Discoverability results
8. Commands naturally used
9. Time-to-answer
10. Manual Git comparison
11. Investigation-effort comparison
12. Most-used features
13. Least-used features
14. Developer feedback
15. Real quotes (verbatim, anonymized)
16. Major UX problems
17. Correctness problems
18. Trust calibration
19. False-authority findings (esp. HIGH confidence + wrong)
20. Feature scorecard (aggregate of §9)
21. Killer use case
22. Weakest use case
23. Requested features
24. Features deliberately rejected (and why — spec: don't overbuild)
25. Bugs fixed (workflow applied after the study)
26. Regression tests added
27. Final test count
28. Security status
29. Performance status
30. Documentation status
31. Overall product score
32. Final MVP classification (A–E, evidence-based)
33. Whether developers would reuse it
34. Whether developers would recommend it
35. Whether continued development is justified
36. Recommended next steps

Honesty rules: no fabricated quotes or counts. If the study has not run,
the report's first line is: **"Real human validation remains outstanding."**
The final classification must rest on this study's observations.
