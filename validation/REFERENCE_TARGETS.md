# agent-blame — Reference Targets & Ground Truth (facilitator only)

**Do not hand this document to participants.** It contains the expected
answers. Use it for (a) environment self-check before the study starts and
(b) trust calibration during sessions — verify the participant's
conclusions against git yourself.

All targets were verified on **2026-08-17** against current upstream
`main` of each repository (full clones, not shallow). If a target line has
drifted since (repos move), the expected answer is the *function*, not the
exact line number — re-locate it with `git blame`/`git show` and adjust.

## 0. Environment self-check (run before the first participant)

```bash
agent-blame --version              # expect: agent-blame 0.1.0
agent-blame --help                 # expect: usage listing all modes
cd requests && agent-blame src/requests/models.py:483
#    expect: Confidence HIGH, "line 483 introduced by 561e4b68"
```

If any of these fail, the install is broken — do not start the study.

## 1. Trust-calibration targets (expected answers + how to verify)

### T1 — requests `src/requests/models.py:483` (`PreparedRequest.prepare_url`)

| Field | Value |
|-------|-------|
| Expected | Confidence HIGH; introduced by `561e4b68` ("Add inline types to Requests (#7272)") |
| Verify | `git blame -L 483,483 src/requests/models.py` → `561e4b68` |
| Callers | exactly 1 DIRECT_CALL, LIVE: `src/requests/models.py:441` (`PreparedRequest.prepare`) |
| Verify callers | `grep -n "prepare_url" src/requests/models.py` → line 441 is the only call |

### T2 — requests `src/requests/__init__.py:74` (`check_compatibility` — movement)

| Field | Value |
|-------|-------|
| Expected | Confidence HIGH; **moved here**, original introduction `2b34880e` ("sanity checks upon boot") |
| Verify | `git log --follow --oneline src/requests/__init__.py | tail` and `git blame -w -L 74,74 src/requests/__init__.py` → `2b34880e` (blame with `-w`; the intermediate `d8e23678` only re-indented) |
| Note | This is the movement-correction case: `git blame` without `-w` may show a later modifier; the true origin is 2b34880e. Do not teach this to the participant — the trust question is whether the tool's "origin" claim is correct. |

### T3 — requests `--commit fd13816d` (`Revert "Fix for response with UTF-8 BOM #4976"`)

| Field | Value |
|-------|-------|
| Expected | `revert_of` = `19cff44e` (explicit revert, from git's structured trailer); per-change confidence HIGH/MEDIUM |
| Verify | `git show fd13816d --format=fuller --no-patch` → trailer `This reverts commit 19cff44e...`; `git show 19cff44e --stat` → the reverted change |
| Note | This is the explicit-revert (regression) case. The tool must call it an explicit revert and must NOT say "caused a bug". |

### T4 — flask `src/flask/app.py:969` (`Flask.dispatch_request`)

| Field | Value |
|-------|-------|
| Expected | Confidence HIGH; introduced by `6a649690` ("pass context through dispatch methods") |
| Verify | `git blame -L 969,969 src/flask/app.py` → `6a649690` |
| Callers | exactly 1 DIRECT_CALL, LIVE: `src/flask/app.py:1019` (`Flask.full_dispatch_request`) |
| Verify callers | `grep -n "dispatch_request" src/flask/app.py` → line 1019 is the only call site (the other ~23 hits are defs/strings/comments) |

### T5 — rich `rich/console.py:1891` (`Console.print`)

| Field | Value |
|-------|-------|
| Expected | Confidence MEDIUM; introduced by `ebb4eaa2` ("themed tracebacks") |
| Verify | `git blame -L 1891,1891 rich/console.py` → `ebb4eaa2` |
| Note | MEDIUM (not HIGH) is expected — the file has a huge, conflicted history; appropriate under-confidence is the finding here, not a bug. |

### T6 — negative control — requests `src/requests/models.py:99999`

| Field | Value |
|-------|-------|
| Expected | Confidence INSUFFICIENT (line does not exist) — honest, no fabricated history |
| Verify | `wc -l src/requests/models.py` → well under 99999 |
| Note | Use this to test that participants do not read "INSUFFICIENT EVIDENCE" as "nothing happened / no history". |

## 2. What the tool should NEVER say on these targets (false-authority checks)

On T1–T5 the tool must not produce any of:

- "unused" (no callers) — it says "No confirmed callers found" at most
- "safe to delete" / "unsafe to modify" — it says "Historical removal risk: <level>" with reasons
- "this caused a bug" / "this code is buggy" — it says "explicitly reverts" / "evidence indicates ... corrected"
- a movement commit reported as the original introduction (T2)

If any of these appear, record it as a BUG on the measurement form and
report it immediately (the project workflow applies afterwards: log →
regression test → fix → full suite → re-verify → AREA commit).

## 3. If the participant uses their own repository

Skip T1–T6 and instead verify their conclusions live:

- introducer claim → `git blame -L <line>,<line> <file>`
- movement claim → `git log --follow --oneline <file>` + `git show <move commit>`
- caller claim → `grep -n "<name>" <file>` and inspect the call site
- revert claim → `git show <sha> --format=fuller --no-patch` (look for the trailer)
