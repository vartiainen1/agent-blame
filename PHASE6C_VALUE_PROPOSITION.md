# PHASE 6C — VALUE PROPOSITION / ADOPTION EXPERIMENT

**Date:** 2026-08-18
**Product under test:** `agent-blame` (deterministic Git archaeology CLI)
**Status:** COMPLETE — report of the adoption experiment
**Classification:** USEFUL MVP (C) — PROVISIONAL (unchanged)
**Real human validation:** NOT RUN (this remains true)

---

## 1. Objective

Answer the central question:

> **"When an AI developer understands what agent-blame does, does it independently conclude that agent-blame provides useful information that normal Git does not conveniently provide?"**

This is deliberately *not* the Phase 6A/6B question ("can the AI use agent-blame?" — we already know it can, 25/25 in the guided round). The question is *adoption*: would the agent **choose** to use it, and does it perceive differentiated value?

Phases 6A and 6B established:
- Natural discovery: **0/8** successful uses (6A), **0/3** after help-text improvements (6B)
- Guided use (tool's own `--help` provided): **25/25** usable calls with real value on archaeology tasks

Phase 6C isolates **perceived value** from **discoverability** by adding a third condition that tells the agent *what the tool is for* without telling it *how to use it*.

## 2. Hypotheses

| # | Hypothesis | Prediction if true |
|---|-----------|-------------------|
| H1 | The blocker is purely discoverability (agents don't know the tool exists or what it does) | Condition C (capability description) → agents choose agent-blame frequently |
| H2 | The blocker is perceived value (agents know the capability but consider git sufficient) | Condition C → agents still prefer git, or try agent-blame and conclude it adds nothing |
| H3 | The blocker is the invocation contract (agents try but fail to construct a valid call) | Condition C → agents attempt agent-blame but fail on syntax, then fall back to git |
| H4 | Value is real but niche (only some tasks/personas benefit) | Condition C → adoption only on specific tasks (e.g. movement/callers) or by specific personas |

Phase 6C was designed so the data distinguishes H1 (C succeeds), H2 (C fails to convert), H3 (C attempts but fails syntax), and H4 (mixed pattern).

## 3. Experimental conditions

| Condition | Tools given | agent-blame mentioned? | Usage guidance? |
|-----------|-------------|------------------------|-----------------|
| **A — Git only** | repo, task, git/file tools | **No** (never mentioned) | — |
| **B — Available, unexplained** | repo, task, git/file tools, agent-blame installed | Yes, one line: "A tool called agent-blame is available... Run `agent-blame --help` to see what it does" | No |
| **C — Capability description** | repo, task, git/file tools, agent-blame installed | Yes, neutral capability description (see below) | No — no command syntax, no "which feature applies", no superiority claim |

**Condition C description (verbatim, neutral):**

> "A tool called `agent-blame` is available on your PATH. It is a Git archaeology tool that combines introducing commits, later changes, code movement, callers, risk, and regression/revert evidence into a single historical analysis. You may use it or not - your choice. You may also use normal repository tooling (git, grep, find, shell utilities) as you normally would. Run `agent-blame --help` if you want its usage details."

Deliberately absent: the exact command syntax, which feature applies to which task, and any claim that agent-blame is *better* than git. The agent must decide.

**Task instruction (identical across conditions):** "Investigate this task and provide a trustworthy answer." — never "use agent-blame".

## 4. Personas

Same personas and models as Phase 6A (single source: `validation/ai/personas.py`):

| Persona | Model | Task |
|---------|-------|------|
| P1 Git Expert (skeptical of wrappers) | qwen3-coder:30b-agent | T1, T5 |
| P2 Senior Developer | qwen3-coder:30b | T4 |
| P3 Maintenance Developer (regression-aware) | qwen3-coder:30b-robust | T2, T6 |
| P5 Code Reviewer (callers/risk) | qwen3-coder:30b-agent | T7 |
| P6 Adversarial Skeptic | qwen3-coder:30b | §9 skeptic session |

## 5. Tasks

Six of the strongest Phase 6A tasks, identical ground truth (git-verified in Phase 6A):

| Task | Repo | Target | Ground truth |
|------|------|--------|--------------|
| T1 WHY | requests | `prepare_url` ~line 483 | introduced by `561e4b688`; caller `PreparedRequest.prepare` at 441 |
| T2 MOVED | requests | `check_compatibility` __init__.py:74 | moved here; origin `2b34880e2` (2017 "sanity checks upon boot"); `d8e23678` re-indent |
| T4 COMMIT | requests | revert commit `fd13816d` | revert of UTF-8 BOM fix #4976 |
| T5 CALLER | flask | `dispatch_request` app.py:969 | introduced by `6a649690`; exactly 1 live caller `full_dispatch_request` at 1019 |
| T6 REGRESSION | requests | `_urllib3_request_context` ~85 | SSLContext caching added (a62a2d35, b1d73ddb, e1887993) then **reverted** by `90fee087` |
| T7 INSUFFICIENT | requests | models.py line 99999 | does not exist (1184 lines); honest INSUFFICIENT answer expected |

T3 (prepared diff) and T8 (negative control) were excluded: T3's diff artifact is tied to the harness setup and T8 is the intentional no-value control already measured in 6A.

## 6. Raw results

### Session inventory (12 fresh sessions + 1 skeptic)

| Session | Cond | Task | Commands | agent-blame invocations | Successful? | Final answer |
|---------|------|------|----------|--------------------------|-------------|--------------|
| ST1_P1_6C_B | B | T1 | 40 | 1 (`--help`) | — | incomplete (budget) |
| ST1_P1_6C_C | C | T1 | 33 | 2 (`:prepare_url` ×2) | ❌ bad line spec | partial: function origin `366e8e849` (2012) via git, not the git-verified line origin `561e4b688` |
| ST2_P3_6C_B | B | T2 | 25 | 1 (invented `--file/--function`) | ❌ unknown flags | **correct**: moved, origin 2b34880e |
| ST2_P3_6C_C | C | T2 | 26 | 1 (invented `--file/--function`) | ❌ unknown flags | correct via git |
| ST4_P2_6C_B | B | T4 | 22 | 1 (`--help`) | — | correct (revert of BOM fix) |
| ST4_P2_6C_C | C | T4 | 27 | 1 (`fd13816d` bare sha) | ❌ needs :LINE | correct via git |
| ST5_P1_6C_B | B | T5 | 23 | 0 | — | correct via git (6a649690, caller 1019) |
| ST5_P1_6C_C | C | T5 | 28 | 6 → **3 valid** (`:969`, `--risk`, `--history`) | ✅✅✅ | correct via agent-blame (6a649690, caller 1019) |
| ST6_P3_6C_B | B | T6 | 40 | 0 (narrative only) | — | incomplete (shell noise, budget) |
| ST6_P3_6C_C | C | T6 | 20 | 3 (invented `--file/--line`) | ❌ unknown flags | correct via git (90fee087 revert) |
| ST7_P5_6C_B | B | T7 | 20 | 1 (`--help`) | — | correct (line 99999 does not exist) |
| ST7_P5_6C_C | C | T7 | 21 | 0 | — | correct via file tools |
| SKEPTIC_6C | C-desc | §9 | (read-only reasoning) | — | — | **rejects tool** (see §10) |

## 7. Tool-selection results

### Did the AI choose agent-blame?

| | Condition B (unexplained) | Condition C (capability) |
|---|---|---|
| Sessions that attempted agent-blame | 3/6 (2 `--help` only, 1 invalid) | **5/6** (real invocations) |
| Successful invocations | **0** | **3** (all in ST5) |
| Sessions with ≥1 successful use | **0/6** | **1/6 (ST5)** |
| First considered | — | ST5 tried `:function` then `--help` then bare file then `:969` |
| Inspected `--help` | 3 sessions | 1 session (ST5, mid-attempt) |
| Continued using after first result | — | ST5: yes (ran `--risk` and `--history` after the plain call succeeded) |

**What caused the choice (from transcripts):** In ST5_C the agent, after two failed syntax attempts, ran `--help`, read it, then successfully ran `app.py:969` and *kept going* — running `--risk` and `--history` on the same target. That is genuine adoption: the capability description motivated the attempt, and the tool's own help closed the syntax gap. ST5_C is the one clean case where the full chain (perceive value → attempt → read help → construct valid invocation → obtain evidence → continue using) completed end-to-end.

**Who chose git instead:** ST1_C read `--help`, tried `:prepare_url` (function name, not line), failed, and finished with git. ST2_C/ST6_C invented flags (`--file`, `--function`, `--line`, `--show-code`, `--all`) that do not exist — a git-flag-shaped guess — and finished with git. ST4_C tried a bare sha (reasonable for a commit task but the target contract requires `:LINE` or `--commit`), failed, finished with git. ST7_C never tried.

**Did any agent decide agent-blame was unnecessary?** ST5_B (git-only arm of the same persona/task) never considered it (it didn't know it existed) and completed with git — but its post-answers said it *would* be cautious about the tool. The skeptic (§10) explicitly decided it was unnecessary.

## 8. Differentiation results (post-investigation answers)

Asked after investigation: (1) what was difficult to obtain with other tools, (2) would you use agent-blame again, (3) what would replace it.

| Session | Difficult info | Use again? | Replacement if removed |
|---------|----------------|------------|------------------------|
| ST1_B | tracing exact origin (31d10c0b2 etc.) across history | **Yes** — "more structured archaeology than raw git" | git log --follow + blame |
| ST1_C | precise commit history/author attribution per line | **Yes** — "combines introduction, evolution, cross-references in a single analysis" | git log --follow -p, blame |
| ST2_B | original introduction of moved code | Mixed — "git was more effective for full context" | git log --grep/-S combos |
| ST2_C | full evolution + previous incarnations | **Yes** — "combines introducing commits, changes, movement, callers, regression" | git log, grep, show |
| ST4_B | *why* the BOM fix was reverted | **Yes** — "ranked timelines and risk analysis for WHY not WHO" | git log --follow, log --graph |
| ST4_C | commit's historical meaning | **Yes** | git log/show combos |
| ST5_B | signature evolution (6a649690) | **No/cautious** — "prefer raw git... unclear the tool adds value over standard git" | git log --follow, blame |
| ST5_C | **"the comprehensive historical chain and risk analysis... confidence score and clear risk assessment that would take much longer to construct manually"** | **Yes, definitely** — "answers WHY not WHO... much more efficient than manually cross-referencing" | git log/show/grep manual piecing |
| ST6_B | (session broken) | Cautious — "tool appears to have issues with the shell" | git commands |
| ST6_C | full blame analysis (introducing commits, revert patterns, risk) | **Yes** — "shows when, why, how related code evolved" | git log, grep, scripts |
| ST7_B | confirming a line doesn't exist | **Yes** — "specifically designed for code history/callers/context" | git log --follow, blame, grep, cloc |
| ST7_C | same as B | **Yes** | git + custom scripts |

**Pattern:** 9/11 usable sessions said they *would* use agent-blame again for historical investigations, citing aggregation of introducing commits + movement + callers + risk as the differentiating value. The notable dissents: ST2_B (git was sufficient for that task) and ST5_B (Git Expert, cautious, wants proof of added value). Note ST5_C and ST5_B are the *same persona on the same task* — the Git Expert who used agent-blame (C) endorsed it strongly, while the Git Expert who never saw it (B) was skeptical. That is the cleanest value signal in the study: **when the skeptic-of-wrappers persona actually used the tool, it became an advocate; when it only heard about it, it stayed skeptical.**

## 9. Feature-level results (per §8's differentiation questions)

| Feature | Did it demonstrate value? | Evidence |
|---------|--------------------------|----------|
| **WHY (`file:line`)** | ✅ Strong | ST5_C: `app.py:969` → HIGH 0.65, exact introducer 6a649690, 14 supporting + 2 counter items, historical chain. ST1_C found the *function* origin 366e8e849 (2012) via git after its failed agent-blame attempt — but missed the git-verified *line* origin 561e4b688, which agent-blame's line-level output surfaces (6A guided T1). |
| **MOVEMENT** | ✅ (from 6A guided) | Not re-measured cleanly in 6C — both ST2 arms found the movement via git. 6A's guided round showed agent-blame catches movement plain blame misses. |
| **CALLERS** | ✅ Strong | ST5_C: exactly 1 live DIRECT call (`full_dispatch_request` at 1019) — matches ground truth precisely, plus honest note that 4 files match the name only as text. The git-only ST5_B also found the caller but without the "text-only vs live" disambiguation. |
| **RISK** | ✅ | ST5_C `--risk` returned change/removal analysis; post-answers in 4 sessions explicitly cited risk analysis as valuable for "before I change this" decisions. |
| **REGRESSION** | ⚠️ Moderate | ST6_C found the exact revert chain (90fee087) — but via git; its agent-blame attempts failed on invented flags. Regression detection value is established by 6A's guided round (T6: 41→15 commands). |
| **DIFF (`--diff`)** | ⚠️ Not measured in 6C | T3 (diff task) excluded this round; 6A guided evidence stands. |
| **COMMIT (`--commit`)** | ⚠️ Partial | ST4_C tried a bare sha (not `--commit`) and failed the contract, finished via git. T4's answer was correct either way — commit archaeology was *not* where the tool earned its keep this round. |

**Honest net:** the tool earned its keep in 6C on **WHY + CALLERS + RISK** (one session, ST5, with 3 successful invocations that produced git-verified ground truth). MOVEMENT/REGRESSION/DIFF/COMMIT value rests on 6A's guided evidence, not on 6C's natural attempts.

## 10. Skeptical-agent findings (P6, Condition C description, 10 questions)

The Adversarial Skeptic (qwen3-coder:30b), given the neutral capability description and asked to judge whether the tool deserves to exist, **rejected it**:

1. **What does it do that Git doesn't?** — "None of the claimed features are genuinely differentiated": blame/log/show/grep/reflog cover them.
2. **Genuinely differentiated feature?** — "None."
3. **Unnecessary features?** — "All... aggregation... just bundles together what's already available."
4. **Would you install it?** — "No. The tool adds zero functional value over standard Git."
5. **Use it repeatedly?** — "No."
6. **Uninstall trigger?** — "If it actually saved me time... but it doesn't."
7. **Aggregation worth another CLI?** — "No... just combines existing tools into one interface that's harder to use."
8. **Killer workflow?** — "No."
9. **Wrapper?** — "Yes, absolutely. A thin wrapper."
10. **Product-owner change?** — "I'd remove it entirely... create something that actually does something Git can't."

**Fair reading:** the skeptic evaluated from the capability description + its own git knowledge, did not run a successful invocation, and concluded wrappers are redundant. This matches Phase 6B's skeptic. It is *adversarial by design*, so its rejection is the expected control — but it is still important evidence that **the value proposition does not survive a hostile read of the capability description alone**. The skeptic is exactly the developer who would need to *see* the aggregated output (as ST5_C did) to be convinced.

## 11. Killer-workflow analysis

Asked: does one use case stand out? Evidence:

- **"Why does this line exist?" — the strongest candidate.** The only session that completed a full successful agent-blame use (ST5_C) was a WHY/CALLER task, and the output was exact (introducer + single live caller + risk + chain). The post-answers repeatedly describe the tool's value as "WHY not WHO."
- **"What historical context matters before I change this?" — the runner-up.** Risk analysis was cited as valuable by 4 sessions; the Maintenance Developer and Code Reviewer personas (P3, P5) endorsed it.
- **"Where did this code come from after moving?" — plausible but unproven in 6C.** 6A's guided round showed it; 6C's natural attempts failed to invoke movement analysis.
- **"Has this area been fixed/reverted before?" — real but niche.** ST6_C found the revert via git; the tool would have done it faster (6A: 41→15 commands).

**Conclusion:** the evidence points to **WHY + CALLERS + RISK as the coherent killer workflow** — "before I change this line, show me why it exists, who calls it, and what happened to it before." It is the workflow where agent-blame's output was git-verified *and* where agents endorsed it. No evidence for COMMIT/DIFF as standalone killers. This is a *tentative* conclusion from one successful session; it does not prove human demand.

## 12. Negative findings

1. **Condition C did not fix invocation success.** 5/6 C sessions attempted agent-blame; **4/5 failed on the target contract** — function name instead of line (ST1), invented `--file/--function/--line/--show-code/--all` flags (ST2, ST6), bare sha (ST4). The capability description raised *attempts* but not *success*.
2. **Skeptic still rejects the tool outright** — "thin wrapper", "zero functional value", "I'd remove it entirely."
3. **Git-only arms frequently matched or beat the capability arms.** On T2/T4/T7 both arms produced correct answers; on T5 both arms found 6a649690 + caller 1019 — the tool was faster/cleaner but not uniquely correct. The tool's *unique* contributions (movement detection, live-vs-text caller disambiguation) were not required to answer any 6C task correctly.
4. **One capability session hallucinated that the tool "wasn't available"** (ST2_C post-answers) after its invalid invocation — evidence that a failed first attempt can *discourage* rather than prompt retry, even with the capability description present.
5. **Two baseline sessions burned the 40-command budget** (ST1_B, ST6_B) without producing clean final answers — effort variance between conditions is real but attributable to shell-noise failure modes, not to tool choice.
6. **Adoption was persona-dependent.** The skeptical Git Expert (P1) was the *only* persona to achieve successful adoption in C (ST5) — and the *only* persona to be openly skeptical in B (ST5_B). Strong disagreement between conditions of the same persona (Outcome E flavor).

## 13. Limitations

- **AI simulation, not human validation.** Per phase rules: "This does not establish human demand, willingness to install, willingness to pay, or real-world developer adoption." **REAL HUMAN VALIDATION = NOT RUN.**
- Small n: 12 sessions (6/condition), 1 successful agent-blame adoption. Single model family (qwen3-coder) for most personas.
- The 30b-agent models emit multi-command trajectories; the harness executes all commands in a response, which inflates command counts and can produce shell-noise failures (ST1_B, ST6_B).
- Post-answer endorsements may reflect the capability description priming ("combines... evidence") rather than actual experienced value — several endorsers never successfully ran the tool. Distinguish *reported* value (many) from *demonstrated* value (ST5 only).
- The skeptic reasoned without a successful invocation; a skeptic shown real output might differ (not tested — would be a future experiment).
- No product code was changed; the tool under test is the Phase 6B version.

## 14. Product interpretation

**Which hypothesis won?**

- **H3 (invocation contract) is the dominant blocker in 6C.** The capability description *worked* — agents tried the tool (5/6) and one fully adopted it. What failed was the target contract: function names, invented flags, bare shas. This extends 6B's finding: the problem is not that agents don't know the tool exists or what it's for; it's that **the primary target form (`<file>:<line>`) is not the shape agents naturally reach for**, and the error path does not convert them.
- **H1 (pure discoverability) is partially disproven.** Telling agents what the tool does caused attempts. Discoverability-of-capability is not the whole story.
- **H2 (pure value) is not supported either.** The one agent that used it (the Git Expert!) endorsed it strongly; the differentiation answers skew positive. Value is perceived *once the tool is used*.
- **H4 (niche value) fits best.** Value is real and concentrated in the WHY/CALLER/RISK workflow, delivered through one demonstrated adoption (ST5_C) plus 6A's guided evidence.

**Outcome classification (per §12 of the phase instructions):** closest to **Outcome C with elements of B** — "agents use agent-blame for movement/callers/diff archaeology" (ST5's WHY/CALLER/RISK use is the same family) *and* "agents conclude Git is usually sufficient" (the skeptic, and the fact that git-only arms answered every task correctly). **Not** Outcome A (Condition C did not cause frequent successful adoption), **not** Outcome D (agents did not continue to prefer git after understanding the capability — 5/6 tried it, 9/11 usable sessions said they'd use it again).

**What this means for the product:** the capability is credible to the agents that engage with it, but the product currently **asks the user to express a target in `<file>:<line>` form**, which is the single biggest friction point. The tool's differentiated value (aggregated WHY/callers/risk) is only visible *after* a successful invocation — so the entire value proposition is gated behind the invocation contract. That is a UX problem with a specific, small shape.

## 15. Recommended next experiment

**Proposed minimal change (NOT implemented — per phase §13, proposed and stopped):**

1. **Evidence:** 4/5 Condition C attempts failed on the target contract: function-name-as-line (ST1), invented `--file/--function/--line/--show-code/--all` (ST2, ST6), bare sha (ST4). The capability description successfully drove attempts; the contract killed them.
2. **Hypothesis:** "Agents (and unfamiliar humans) naturally express a target as a *function name, file, or bare sha* — not `file:line`. If the CLI accepted these forms (resolving function names to their defining line, bare files to a prompt/usage of available lines, bare shas to COMMIT mode) and clearly labeled the resolution, the value proposition would become visible without a syntax lesson."
3. **Proposed change (smallest):** extend target parsing to accept a bare file (auto-offer its symbol table or ask for a line), `file:function` (resolve via AST to the defining line, with an explicit "resolved to line N" note), and a bare sha (route to `--commit`). No change to the analysis engine, ranking, confidence, movement, or regression logic — parsing/UX only.
4. **Expected effect:** natural attempts convert (the 4/5 failure class disappears); agents reach the aggregated output and can judge value on evidence.
5. **Risk:** target ambiguity (file vs sha), resolution errors, scope creep into "features." Mitigation: resolution is explicit and overridable; keep `file:line` as the canonical form.
6. **How to test:** rerun the Condition C matrix (6 sessions, same tasks); success criterion = ≥3/6 sessions with a valid invocation *without* syntax guidance, and ≥1 session that continues using the tool after the first result. Plus deterministic parser tests and the full suite.

Also recommended (cheap, no code): the adversarial skeptic should be re-run *after* a successful invocation has been shown to it — the current rejection is based on description-only, which we know is the weakest evidence form.

## 16. What should NOT be built yet

Per phase §16 and the deferred list from §13 of Phase 6B — **do not build**:

- merge-aware analysis
- new languages
- LLM integration
- web UI
- persistent indexing
- blame ancestry
- richer JSON
- new evidence types
- further `--help` wording iteration (Phase 6B already tested that hypothesis: 0/3)

The next move — *if the user directs it* — is the §15 target-resolution experiment, nothing more.

---

## Verdict (honest)

- **Value:** demonstrated, not assumed — one full adoption (ST5_C) produced git-verified ground truth, and the adopting agent (the Git Expert) endorsed the tool while its git-only twin stayed skeptical.
- **Adoption:** Condition C raised attempts (5/6) but not success (1/6). The blocker is the **invocation contract**, not capability awareness and not (demonstrably) perceived value.
- **Classification: USEFUL MVP (C) — PROVISIONAL, unchanged.** AI simulation cannot upgrade it.
- **REAL HUMAN VALIDATION: NOT RUN** — remains true.
- No product code was changed in this phase. 279 tests + 5 Phase 6B UX tests remain green (verified 2026-08-18, final state).

---

## Addendum (2026-08-19): Target-resolution retest — §15 implemented and measured

This addendum records the §15 experiment AFTER the proposed change was
implemented (the addendum supersedes the verdict line "no product code was
changed in this phase").

### What was implemented (parsing/entry-point/UX only)

- **`agent-blame <file>`** — a bare file now resolves to the file's
  blame-able lines instead of erroring (Phase 6B §11 suggestion): Python
  files print the AST symbol table (every symbol's defining line); other
  files print the line count. Either way the output points at
  `agent-blame <file>:<line>`. Exit 0 — an affordance, not an error.
- **`agent-blame <file>:<function>`** — resolves the function/method/class
  to its DEFINING line via the Phase 2C stdlib-AST symbol extraction at
  HEAD, with an explicit "resolved '<name>' to line N" warning in terminal
  and JSON. Qualified names (`Server.handle`) are the identity; an
  unqualified name must be unique in the file (ambiguity is a clean error
  naming the candidates — never a guess); non-Python files are rejected
  (Python-only, the same honesty rule as the caller machinery).
- **`agent-blame <sha>`** — equivalent to `--commit <sha>`, verified with
  `git rev-parse` so a hex-shaped FILE in the repo is never hijacked; a
  sha that does not resolve falls through to the bare-file affordance.

Explicitly NOT changed: ranking, confidence, movement, regression,
evidence, merge analysis, languages, LLM, web UI, indexing, blame
ancestry, JSON schema (the resolution is surfaced through the existing
`warnings` field), and `--help` wording. Validation: 321 tests green (284
before + 37 new); JSON for `agent-blame <sha>` is identical to
`--commit <sha> --json`.

### Retest: the exact Condition C matrix, rerun

Same harness (`run_session.py`), same `CAPABILITY_ENV` prompt (verbatim),
same personas/models/tasks/command and wall budgets — the ONLY change is
the tool under test. New session IDs (`*_6C2_C`) keep the original
transcripts intact; transcripts are in `validation/ai/transcripts/`.

| Session | Before (6C) | After (6C2) | Target form used when valid |
|---|---|---|---|
| ST1 T1 WHY | 0 valid — `models.py:prepare_url` (function-as-line) | **1 valid** — `models.py:483` | `file:line` (after `--help`) |
| ST2 T2 MOVED | 0 valid — invented `--file/--function` | 0 valid — invented `--function` | — |
| ST4 T4 COMMIT | 0 valid — bare sha rejected | 0 valid — invented `--file/--line` | — |
| ST5 T5 CALLER | 1 valid — `:969` + `--risk`/`--history` after `--help` | **2 valid** — `app.py:dispatch_request` (×2) | `file:function` (no `--help`) |
| ST6 T6 REGRESSION | 0 valid — invented `--file/--line/--show-code` | 0 valid — invented `--file/--function/--line` | — |
| ST7 T7 INSUFFICIENT | 0 valid — never tried | 0 valid — invented `--file/--line` | — |
| **Sessions with ≥1 valid** | **1/6** | **2/6** | |

**The §15 success criterion (≥3/6 sessions with a valid invocation without
syntax guidance) was NOT reached: 2/6.**

### What the retest shows

1. **`file:function` converted exactly the class it was built for.** ST5 ran
   the IDENTICAL command that failed before (`app.py:dispatch_request` →
   "bad line spec") and it now resolves to the git-verified line 969, HIGH
   0.65, without reading `--help`. The agent reached for the function name
   naturally — the §15 hypothesis, demonstrated.
2. **ST1 converted via the canonical `file:line` form** (`models.py:483`
   after `--help`) — a class-C conversion, though not directly attributable
   to the new forms.
3. **The remaining 4/6 failures are all the same class:** git-flag-shaped
   guesses (`--file`, `--function`, `--line`, `-L`, `--show-code`, `--all`)
   from agents that never read `--help` and never ran a bare-file or colon
   form — so they never SAW the affordance or the quick start. No parsing
   change can reach an agent that invents flags it never saw; that class
   needs a different lever (or is a model-behavior boundary, cf. Phase 6B
   §11).
4. **The bare-sha form was exercised by zero sessions in either run** (ST4
   used `--file/--line` this time instead of the bare sha it tried before).
   Its equivalence to `--commit` is test-covered, but its natural adoption
   remains unmeasured.

### Honest limitations

- n=6 per arm, temperature 0.6, single model family (qwen3-coder): the
  1/6 → 2/6 delta is directional, not statistical. The tool is the only
  changed variable, but session-level variance is real (ST4 tried a bare
  sha before and flags now).
- The bare-file affordance never fired in this run (no agent ran a bare
  file alone), so its conversion value stays unmeasured by this retest.
- This remains AI evidence. **REAL HUMAN VALIDATION: NOT RUN** — still true.
- Classification remains **USEFUL MVP (C), provisional**: the invocation
  contract is no longer the single blocker (2 of the 6 agents still invent
  flags without reading anything), but value is still only demonstrated
  post-invocation.
