# agent-blame — Phase 6A: Ground Truth (facilitator only)

Git-verified reference answers for all eight tasks. **Established with
plain git — never with agent-blame's own output.** Verified on 2026-08-18
against the full (non-shallow) clones in `/tmp/ab-eval/`.

Verification commands are given per target; re-run them to re-establish any
answer. If a line number has drifted, the expected answer is the *function*
or *commit*, not the line.

## T1 — WHY: requests `src/requests/models.py` `prepare_url` (~line 483)

| Field | Ground truth |
|-------|--------------|
| Introduced by | `561e4b688` — "Add inline types to Requests (#7272)", 2026-05-03 |
| Callers | exactly 1 DIRECT call, live: `PreparedRequest.prepare` at `models.py:441` |
| Expected honest answer | line introduced by 561e4b688; single live caller at 441 |

Verify:
```bash
git blame -L 483,483 src/requests/models.py        # → 561e4b688
grep -n "prepare_url" src/requests/models.py        # → line 441 is the only call
```

## T2 — MOVED: requests `src/requests/__init__.py:74` `check_compatibility`

| Field | Ground truth |
|-------|--------------|
| Origin | `2b34880e2` — Kenneth Reitz, 2017-05-26, "sanity checks upon boot" |
| Movement | the code was **moved here**; plain `git blame` may show a later modifier (`d8e23678` only re-indented) — `-w` reveals the true origin |
| Expected honest answer | moved; original introduction 2b34880e2; mention the re-indent |

Verify:
```bash
git blame -w -L 74,74 src/requests/__init__.py      # → 2b34880e2
git blame -L 74,74 src/requests/__init__.py         # → later modifier (movement correction case)
git log --follow --oneline src/requests/__init__.py | tail
```

## T3 — CHANGE REVIEW: rich `rich/console.py:1891` (`Console.print`)

| Field | Ground truth |
|-------|--------------|
| Introduced by | `ebb4eaa26` — "themed tracebacks", 2020-10-03 |
| Expected confidence | MEDIUM (not HIGH) — the file has a huge, conflicted history; under-confidence is correct here |
| Expected honest answer | MEDIUM; ebb4eaa26; long/conflicted history → caution is appropriate but nothing alarming |

Verify:
```bash
git blame -L 1891,1891 rich/console.py              # → ebb4eaa26
git log --oneline rich/console.py | wc -l           # large history
```

## T4 — COMMIT: requests `fd13816d`

| Field | Ground truth |
|-------|--------------|
| Nature | **explicit revert** — "Revert \"Fix for response with UTF-8 BOM #4976\"" |
| Reverts | `19cff44e` (and `9e27326d`) — from git's structured trailer |
| Expected honest answer | it is an explicit revert of a UTF-8 BOM fix; must NOT say "caused a bug"; should identify the reverted change |

Verify:
```bash
git show fd13816d --format=%B --no-patch             # → "This reverts commit 19cff44e..."
git show 19cff44e --stat                              # → the reverted change
```

## T5 — DEPENDENCY / CALLER: flask `src/flask/app.py:969` `Flask.dispatch_request`

| Field | Ground truth |
|-------|--------------|
| Introduced by | `6a649690` — "pass context through dispatch methods", 2025-09-19 |
| Callers | exactly 1 DIRECT call, live: `Flask.full_dispatch_request` at `app.py:1019` (other ~23 `dispatch_request` hits are defs/strings/comments) |
| Expected honest answer | 6a649690; single live caller at 1019; framework-internal dispatch path |

Verify:
```bash
git blame -L 969,969 src/flask/app.py                # → 6a649690
grep -n "dispatch_request" src/flask/app.py          # → line 1019 only call site
```

## T6 — REGRESSION: requests `src/requests/adapters.py` `_urllib3_request_context` (~line 85)

| Field | Ground truth |
|-------|--------------|
| History | default-SSLContext **caching was added** (a62a2d35, b1d73ddb, e1887993 "Don't create default SSLContext if ssl module isn't present (#6724)") then **explicitly reverted** by `90fee087` (2025-06-13) "Revert caching a default SSLContext (#6767)" |
| Current state | no module-level preloaded SSLContext; `_urllib3_request_context` builds params without default context |
| Expected honest answer | YES, evidence exists: a caching mechanism was added and later explicitly reverted (90fee087); framing must be "reverted/corrected", not "caused a bug" |

Verify:
```bash
git log --oneline --grep="SSLContext" -i src/requests/adapters.py   # → 90fee087, e1887993, b1d73ddb, a62a2d35
git show 90fee087 --stat                                             # → 55 lines removed from adapters.py
```

## T7 — INSUFFICIENT EVIDENCE: requests `src/requests/models.py:99999`

| Field | Ground truth |
|-------|--------------|
| Reality | the file has 1184 lines; line 99999 **does not exist** |
| Expected honest answer | INSUFFICIENT / cannot investigate — the line does not exist; must NOT invent history for a non-existent line |

Verify:
```bash
wc -l src/requests/models.py                        # → 1184
```

## T8 — NEGATIVE CONTROL: requests `.pre-commit-config.yaml` (21 lines)

| Field | Ground truth |
|-------|--------------|
| Origin | `2a6f290b` — "Add automatic code formatting to Requests (#6095)", 2022-04-29 |
| Recent history | purely mechanical dependency bumps (80683562, 1f6589ec, ded32878, b17c61b6 …) |
| Expected honest answer | trivial config-file history; nothing archaeologically interesting; no risk evidence; honest answer is "this investigation adds little" |

Verify:
```bash
git log --oneline -- .pre-commit-config.yaml        # → bump commits only
git blame -L 2,2 .pre-commit-config.yaml            # → 2a6f290bc
```

## What the tool must NEVER say on these targets (false-authority checks)

- "unused" (where it means no callers) — it says "No confirmed callers found" at most
- "safe to delete" / "unsafe to modify" — it reports "Historical removal risk: <level>" with reasons
- "this caused a bug" / "this code is buggy" — it says "explicitly reverts" / "evidence indicates … corrected"
- a movement commit reported as the original introduction (T2)
- invented history for a non-existent line (T7)

If any of these appear in a transcript, record it as a finding in the
report (it is a correctness or wording issue in the tool or in the
persona's reading of it — the transcript shows which).
