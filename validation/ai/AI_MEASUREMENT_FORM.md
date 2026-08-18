# agent-blame — Phase 6A: Measurement Form (per session)

One form per session, completed from the transcript in
`transcripts/<session_id>.jsonl`. Every score must cite transcript
evidence (command numbers / verbatim quotes). Raw transcripts are the
source of truth; this form is the summary.

## Session identity

| Field | Value |
|-------|-------|
| Session ID | |
| Task (T1–T8) | |
| Persona | |
| Model | |
| Baseline / Treatment | |
| Ordering (which condition ran first) | |
| Repository / target | |
| Wall-clock duration | |
| Command count (total) | |
| Git command count | |
| Agent-blame command count (treatment only) | |
| First command | |
| Did the persona consult --help (treatment) or git help? | |

## Conclusions

| Field | Record |
|-------|--------|
| Final conclusion (verbatim from FINAL ANSWER) | |
| Confidence stated | |
| Ground-truth match (A. Correctness) | |
| Important evidence missed (B. Completeness) | |
| Claims traceable to evidence (C. Evidence quality) | |
| Unsupported confident claims (D. False-confidence) | |
| Investigation effort (E) — commands needed, digging | |
| Discoverability (F) — features found unaided | |
| Decision usefulness (G) | |
| Redundancy (H) — restated a trivial git command | |
| Invented evidence? (quote) | |
| Mistakes / false assumptions / corrections | |

## Trust-calibration notes

- Any HIGH-confidence claim that was wrong? (quote + ground truth)
- Any wording confusion (risk ≠ unsafe, no-caller ≠ unused, insufficient
  ≠ nothing, movement origin ≠ last modifier)?

## Feature discovery (treatment only)

Which of these did the persona find unaided (transcript command numbers):

- [ ] `--help` / `agent-blame` at all
- [ ] WHY / HISTORY
- [ ] RISK
- [ ] CALLERS
- [ ] MOVEMENT
- [ ] REGRESSION / revert
- [ ] `--diff`
- [ ] `--commit`
- [ ] `--json`

## Raw evidence discovered (list)

- commits identified:
- callers identified:
- movement identified:
- regressions/reverts identified:
- risk identified:
