# Phase 3 — Product Validation, Adversarial Testing & Accuracy Review

This is the permanent record of the Phase 3 evaluation (feature-frozen). It
answers the product question: **is agent-blame actually useful and
trustworthy for real developers?** The machine-readable dataset is
`eval_dataset.json`; this document is the analysis, the ground-truth
verification, and the classification.

**Baseline at phase start:** 259 tests green, all features (WHY / HISTORY /
RISK / --diff / --commit / callers / movement / regression) present.

**Baseline at phase end:** 270 tests green. Three genuine bugs found and
fixed (one of them confidence-destroying), two performance problems fixed,
one noise source eliminated, one commit-mode bug fixed.

---

## 1. Repositories evaluated

All read-only analysis targets (never modified, never committed to).

| Repo | Type | Size / history | Why selected |
|---|---|---|---|
| `requests` | mature Python HTTP library | 6,490 commits, 2010–2026, one large `src/` move (2023), long-lived files, several explicit reverts | old + refactored + renames + reverts + real tests |
| `flask` | mature Python web framework | 5,555 commits, 2010–2026, `src/` move, framework/dynamic usage | heavy refactoring, long-lived core (`app.py`, `helpers.py`) |
| `rich` | large Python terminal library | 4,460 commits, 2019–2026, heavily iterated | frequent fixes, many small commits, heavy modification |
| `Freebuff` | the workspace tool itself | ~1,000 commits, Python, no reverts | dogfooding on the project that spawned agent-blame |

## 2. Real-world questions tested (19 rows in eval_dataset.json)

WHY / HISTORY / RISK on `requests.models.prepare_url`, `Session.request`,
`BaseAdapter.send`, `requests.__init__`; WHY on flask `dispatch_request`,
`url_for`, `__init__`; WHY/RISK on rich `Console.print`, `Table.add_row`,
`Text.append`; `--commit` on a real revert (`fd13816d`), the `src/` move
(`d63e94f5`), flask `HEAD~50`, rich `HEAD~100`; live `--diff` on a modified
`prepare_url`.

## 3. Genuine bugs discovered and fixed

### 3.1 Chronology bug (confidence-destroying) — FIXED
**Symptom:** every real-repo target returned `CONTRADICTORY` confidence and
false `EXPLICIT_REVERT` findings citing 2013–2019 reverts against 2026 code.
**Root cause:** `build_graph` put *all* commits touching the file (except
the introducers) into `later`, with no chronology check. Six old
`explicit_revert` items at −0.25 each zeroed the score.
**Fix:** `later` is now strictly newer than the newest introducing commit;
EXPLICIT_REVERT resolution is confined to the analyzed lineage.
**Verified:** requests line 483 goes CONTRADICTORY → HIGH (0.85) with 0
regressions; eval harness shows zero CONTRADICTORY across 19 rows.
**Regression test:** `TestChronologyOldRevert` (pre-introducer revert →
no EXPLICIT_REVERT, not CONTRADICTORY).

### 3.2 `replacement` counter-evidence stacking — FIXED
**Symptom:** refactor-heavy files (flask/rich) emitted one `replacement`
item (−0.20) per later commit → score zeroed.
**Fix:** aggregate into ONE `replacement` item per target (deleted_lines
merged); the file-level supersession signal scans full history.
**Verified:** flask/rich MEDIUM (appropriate for heavily modified files),
no CONTRADICTORY.

### 3.3 revert + corrective_change double-count — FIXED
**Symptom:** the same commit (rich `19349e38`) counted as both `revert`
(−0.25) and `corrective_change` (−0.10).
**Fix:** the analyzer dedupe now also drops the message-based revert item
when the same commit produced a CORRECTIVE_CHANGE finding.
**Verified:** single item per commit on rich.

### 3.4 Pure-rename commit mode dropped movement — FIXED
**Symptom:** `--commit` on a git-confirmed R100 rename (requests `src/`
move: 18 renames) reported **no movement block** (`mv=None` on all).
**Fix:** the pure-rename branch now attaches the movement (origin from the
group blame, mover = the rename commit) instead of `continue`-ing past it.
**Verified:** all 18 renames carry movement; spot-check of one origin
matches `git blame` ground truth exactly.
**Regression test:** `TestRenameCommit.test_pure_rename_carries_movement`.

### 3.5 Pre-introducer fix-language noise — FIXED
**Symptom:** a 2019 "Fix …" commit was cited as a `POSSIBLE_REGRESSION_FIX`
against code introduced in 2026 (a sequence claim chronology cannot
support).
**Fix:** fix-language findings are suppressed when the fix predates the
introducer — with one legitimate exception: when an *introducing* commit
explicitly reverts that fix (then the fix IS the subject of the lineage,
e.g. the --diff fix+revert fixture).
**Verified:** chronology fixture clean; the diff fixture still surfaces its
LIKELY_REGRESSION_FIX.

### 3.6 Trivial revert-subject noise (flask copyright revert) — FIXED
**Symptom:** flask's 2018 `revert copyright year …` commit (1 removed / 1
added docstring line) fired CORRECTIVE_CHANGE against `dispatch_request`
and `__init__.py:24`.
**Fix:** CORRECTIVE_CHANGE now requires verified symbol overlap **or**
strictly corrective shape (`removed > added`) — the same discriminator the
fix-language path already had.
**Verified:** flask `app.py:969` regressions 3 → 0; `__init__.py:24` 1 → 0.
**Regression test:** `TestTrivialRevertSubject`.

### 3.7 Performance N+1 — FIXED
**Symptom (measured):** `--commit d63e94f5` (requests `src/` move) took
**49 s, 1,693 git subprocesses** — `commit_files` 922× unmemoized,
per-symbol range blames 272×.
**Fixes (measured):**
- `commit_files_cached` shared memo (922 → 1 call per unique sha)
- one batched `git log --no-walk --name-status --stdin` for ~800 distinct
  origin shas (merge commits excluded → exact per-sha fallback, verified
  byte-identical)
- whole-file `blame_file_map` for movement origins (272 range blames → 1)
- `subj_body` commit_map backfill (120 missed lookups → 0)
**Result:** 49 s → **12.5 s**, 1,693 → 568 git calls. Normal commits
0.5–8 s.
**Regression tests:** batch-parser unit tests (single/multi/rename/
sha-looking path/malformed) + SHA-integrity test (batch == per-sha).

## 4. Ground-truth verification (manual, against git)

| Claim | Ground truth | Verdict |
|---|---|---|
| requests `models.py:483` introduced by `561e4b68` (inline types, 2026) | `git blame` credits 561e4b68 | ✅ |
| `--commit fd13816d` = EXPLICIT_REVERT of `19cff44e` | trailer says `This reverts commit 19cff44e…` | ✅ |
| `__init__.py:74` moved by `d63e94f5` (src/ move), origin `2b34880e` | R100 rename confirmed; 2b34880e is the whitespace-insensitive origin (d8e23678 only re-indented) | ✅ |
| 43 callers of `BaseAdapter.send` — all POSSIBLE/TEXTUAL, 0 DIRECT | real calls are `adapter.send()` / `r.connection.send()` through unresolved locals → conservative downgrade is CORRECT (false claim would be worse) | ✅ |
| flask copyright revert NOT a regression | 1/1 docstring edit, no symbol overlap | ✅ |
| diff on `prepare_url` → symbol resolved, 10 callers, HIGH | worktree edit of the def line | ✅ |

## 5. False-positive / false-high-confidence findings

- **False HIGH-confidence claims:** **zero** after the fixes. The only
  remaining high-confidence claim type (EXPLICIT_REVERT) requires the
  structured git trailer.
- **False regressions:** zero on all 19 real-repo rows (was 12+ before the
  chronology fix).
- **CONTRADICTORY confidence:** zero on all rows (was 16/16 on requests
  alone before the fixes).

## 6. Feature value scores (1–10, honest)

| Feature | Acc | Use | Uniq | Expl | Perf | FP-risk | Notes |
|---|---|---|---|---|---|---|---|
| WHY | 9 | 9 | 8 | 9 | 9 | 1 | the headline: "where did this come from" |
| HISTORY | 8 | 7 | 6 | 9 | 8 | 1 | good evolution view; the 2013-era chain display is verbose |
| RISK | 8 | 8 | 8 | 8 | 9 | 2 | never claims safe/unsafe; reasons always visible |
| --diff | 9 | 9 | 9 | 9 | 8 | 1 | pre-commit context; noise control works |
| --commit | 9 | 8 | 7 | 9 | 8 | 1 | revert/merge/rename handled honestly |
| callers | 8 | 8 | 8 | 8 | 7 | 1 | conservative by design; 43 POSSIBLE + 0 DIRECT is honest |
| movement | 9 | 8 | 9 | 8 | 8 | 1 | introduction-vs-move separation is the killer property |
| regression | 7 | 7 | 7 | 8 | 8 | 3 | useful on revert-heavy repos; quiet where it should be |

**Killer feature (best evidence-based value):** **WHY with movement
correction** — "this code was moved here by X, originally introduced by Y"
is the statement a developer can immediately trust and act on, and it is
the one thing a raw `git blame` gets dangerously wrong.

**Weakest feature:** **regression detection**. Most real repos (requests,
flask, rich) have very few explicit reverts and most "fix" commits fail the
overlap tests (correctly!). It adds real value on revert-heavy histories
but contributes the most complexity per finding. Recommendation: keep it,
document it as best-effort; do not let its absence of findings read as "no
regressions ever".

## 7. MVP readiness classification

**C. USEFUL MVP** — developers can realistically benefit today, with one
caveat.

Evidence for:
- Correct origins on all ground-truth checks
- No false HIGH-confidence claims, no fabricated intent
- INSUFFICIENT/UNSUPPORTED reported correctly rather than guessed
- Performance is fine on real repos (0.5–13 s; pathological case fixed)
- Security surface is small and audited (argv-only git, no shell, no
  execution, sanitized output)

Caveat: "No confirmed callers found" and quiet regression output must not
be read as "no callers / no regressions ever" — the wording already
distinguishes this, but the README should say it explicitly (it does; see
documentation review).

Not yet B/stronger because: single-language symbol support (Python only),
caller resolution is deliberately conservative (misses valid calls through
unresolved locals), and regression detection is necessarily quiet on
revert-free repos.

## 8. Documentation / CLI review

- README documents what it does **and** does not prove (no safety
  guarantee, historical evidence only), supported language (Python for
  symbol/caller/movement analysis), shallow/merge behavior, confidence and
  risk semantics. Matches observed behavior. ✅
- CLI output separates FACTS (✓) / INFERENCES (·) / EVIDENCE /
  COUNTER-EVIDENCE / CALLERS / MOVEMENT / REGRESSIONS / RISK — a developer
  can see why the tool reached its conclusion. ✅
- Verbosity: 24 evidence lines on a well-trodden function is a lot, but
  the first two lines (Confidence + introducing fact) answer the question;
  evidence is the justification. Acceptable; not changed in the freeze.

## 9. Security audit (re-run)

- No `shell=True`, no `os.system`, no `eval`/`exec` of repository content
  (the only `eval`/`getattr`/`__import__` matches are AST pattern
  recognition in symbols.py — recognized as dynamic, never executed).
- All git calls argv-based with `--` for paths; `-z` parsing; malformed
  output handled defensively (verified by batch-parser tests + SHA-integrity).
- Source parsed with `ast.parse` only. No imports of project modules, no
  test execution, no hooks, no network.
- Terminal/JSON sanitization verified (ANSI/BEL stripped; JSON control-char
  free).

## 10. Performance measurements (final)

| Target | Mode | Time |
|---|---|---|
| requests models.py:483 | WHY/HISTORY/RISK | 0.6–0.9 s |
| requests `--commit d63e94f5` (src/ move, 18 renames, ~800 origin shas) | commit | 12.5 s (was 49 s) |
| requests `--commit fd13816d` (revert) | commit | 2.0 s |
| flask app.py:969 | WHY | 1.2 s |
| flask `--commit HEAD~50` | commit | 6.2 s |
| rich console.py:1891 | WHY | 1.2 s |

## 11. Final test count

**270 tests green** (was 259 at phase start; +9 chronology/parser/pure-rename
regressions, +2 trivial-revert noise gate — one analyzer test retargeted to
a genuinely later-modified line).

## 12. Errors logged (log-before-fix workflow)

Six Phase 3 entries in `freebuff-errors.txt`, all FIXED, audit green
(173 pins PASS): chronology bug, replacement stacking, revert+
corrective double-count, perf N+1, pre-introducer fix noise, trivial-revert
noise.

## 13. Final statement

**Yes — agent-blame is ready for real developer use as an MVP.** It is not
ready to *prove* anything: it is a historical-evidence tool, and the output
never claims more than the repository supports. The Phase 3 finding that
matters most is that the fixes *removed* authority the tool did not
deserve (CONTRADICTORY everywhere, reverts cited against unrelated code)
and left the claims that remain verifiable against git. Trust, not
impressiveness, is the product.
