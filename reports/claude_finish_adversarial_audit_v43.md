# Claude Finish Adversarial Audit v43 — LP-01 Step 5

**Target commit:** `7923df8b0974a535419a5250143c1c77c489c55f` (no push; local HEAD)  
**Auditor:** Cursor (adversarial), 2026-07-30 ~18:11–18:25 CT  
**Protocol:** `reports/lp01_step_protocol_v1.md` — Step 5 only  
**Prior:** Steps 1–4 **ACCEPT** through `0d1a3e78` / v42 (not reopened)  
**Claude claim:** Step 5 complete — F&P touch→5/15/30m vs TOD harness built+run; **FAIL** after placebo; structure-only; money-path WAIT; commit `7923df8b`; 62 tests; RC-158 CLOSED; zero UI. Does **not** self-ACCEPT.

**Admission preamble (AGENTS.md):** MISSION_CLASS=Find & Prove (adversarial audit) · GAP=verify Step 5 Done (harness+report+FAIL locked+money-path WAIT+RC+commit; study FAIL may still ACCEPT) · SMALLEST_COMPLETE_CHANGE=audit + `reports/claude_finish_adversarial_audit_v43.md` (+ protocol update only on ACCEPT) · MINIMUM_SUFFICIENT_EVIDENCE=same-turn harness re-run + pytest 62 + git scope + RC close-contract + method/placebo attack · DECISION_PATH_EFFECT=none required; must prove Decide untouched · WHY_NOW=kill-rate honesty gate before LP-01 COMPLETE · TASK_ADMISSION=audit only; no Decide admission; no UI; no push.

**drift-audit run:** phases 1–7 this turn. Intent = protocol Step 5 Done (“Harness + report; money-path unchanged (WAIT); RC + commit”) with honest FAIL keeping structure-only. Mechanical: `git show --stat 7923df8b`; same-turn `python tools/lp01_touch_study_v1.py`; same-turn `pytest tests/test_lp01_touch_study_v1.py tests/test_liquidity_engine.py -q` → 62; `check_five_why_recursive_lock` → 0; `check_root_cause_log` → **RC-158 FAIL**; `check_closed_rows_ship_their_code` → no RC-158 hit; admissions `[]`; commit static/money-path empty. AST `--ast-callsites` N/A (`enforce_all_rules.py` absent; Step 5 adds a consumer, does not change engine arity). Findings below. No product-code correction (audit-only). Gate hardened: n/a (auditor).

---

## Verdict: **PARTIAL**

| Claim | Result |
|---|---|
| Commit `7923df8b` exists; parent `0d1a3e78` (Step 4); HEAD | **ACCEPT** |
| Step-5-only file set (5 files); **zero** `static/*` / CSS | **ACCEPT** |
| Money-path untouched (`decision_path_admissions.json` empty; not in diff) | **ACCEPT** |
| Artifact verdict FAIL; n/d/CI/placebo excess match same-turn re-run **exactly** | **ACCEPT** |
| Placebo arm locks FAIL (excess &lt; 0; horizon_pass false ×3) | **ACCEPT** |
| No lookahead (levels causal / ORB gated / fwd in-session / TOD paired) — tests drive code | **ACCEPT** |
| TOD baseline ≠ flat average — tested | **ACCEPT** |
| Horizon matching placebo cannot PASS — tested | **ACCEPT** |
| Direction/magnitude not claimed as edge; NEXT-DEPTH stated | **ACCEPT** |
| pytest 62 (11 harness) same-turn EXIT 0 | **ACCEPT** |
| UI hard-stop in commit; dirty Enter-UX unstaged only | **ACCEPT** |
| five_why recursive lock clean; FIXED reach named | **ACCEPT** |
| RC-158 CLOSED satisfies `check_root_cause_log` proof-in-**fix**-cell | **REJECT** — gun |
| Protocol Step 5 → ACCEPT / LP-01 COMPLETE | **held** until residual close |

**Why PARTIAL (not ACCEPT):** the study gate is honest and complete — FAIL is locked by placebo, money-path WAIT, zero UI — but RC-158’s **fix** cell lacks any of `PROVEN` / `VERIFIED` / `MEASURED` / `OBSERVED`. `PROVEN by the placebo` sits in the **why** column. `check_root_cause_log` (ENFORCED) therefore flags: `RC-158 is CLOSED without observed evidence`. Protocol Done includes RC; this is a residual-close, not a study reopen.

**Why not REJECT:** PASS criteria are not gameable toward PASS (placebo excess required; match-placebo test fails closed); placebo on a 40-session probe does **not** select wider bars than real (mean range ratio placebo/real ≈ 0.956) so FAIL is not manufactured by an harsher control; Decide/UI/lookahead clean; evidence re-run matched the artifact bit-for-bit.

---

## 1) ARTIFACTS / REPRO (PROVEN this turn)

### Commit scope

| Fact | Value | Method |
|---|---|---|
| SHA | `7923df8b0974a535419a5250143c1c77c489c55f` | `git rev-parse` |
| Parent | `0d1a3e781f74444d637d9d08086bbf94205dcdc8` | Step 4 ACCEPT |
| Files | `governance/root_cause_log.md`, `reports/lp01_touch_study_v1.{json,md}`, `tests/test_lp01_touch_study_v1.py`, `tools/lp01_touch_study_v1.py` | `git diff --name-status ^..` |
| `static/*` | **empty** | `git diff --name-only … -- static/*` |
| Money-path files | **empty** (admissions / server / index / chart) | same |
| Push | not performed; branch ahead 72 of origin | `git status -sb` |
| Worktree UI dirt | `M static/chart.html` **unstaged** (Enter-UX) — OK per claim | `git status --short` |

### Artifact numbers (committed + re-run)

Same-turn: `.venv/Scripts/python.exe tools/lp01_touch_study_v1.py` →

```
verdict=FAIL sessions=299 touches=12471
  5m n=12471 d=0.26373652419249677 pass=False
  15m n=12275 d=0.24030859319640524 pass=False
  30m n=12054 d=0.2319813020516034 pass=False
```

| horizon | n | Cohen's d | placebo d | excess | CI95 | horizon_pass |
|---|---|---|---|---|---|---|
| 5m | 12471 | 0.2637 | 0.3268 | **−0.0631** | [0.000180, 0.000216] | false |
| 15m | 12275 | 0.2403 | 0.3122 | **−0.0719** | [0.000256, 0.000311] | false |
| 30m | 12054 | 0.2320 | 0.3055 | **−0.0735** | [0.000321, 0.000397] | false |

`artifact_exact_match_commit = True` (per-horizon n/d/placebo/excess/pass + verdict + n_touch vs `git show 7923df8b:reports/lp01_touch_study_v1.json`).

### Pytest (auditor, same turn)

`.venv/Scripts/python.exe -m pytest tests/test_lp01_touch_study_v1.py tests/test_liquidity_engine.py -q` → **62 passed** in 7.48s. Harness file alone: **11 tests collected**.

---

## 2) METHOD ATTACKS

### No lookahead — ACCEPT

| Guarantee | Evidence |
|---|---|
| Causal level set excludes TODAY_*/VWAP* by name | `CAUSAL_LEVELS` + `test_levels_under_test_are_all_fixed_before_the_touch` |
| Level values invariant to tested session’s RTH bars | `test_session_levels_do_not_see_the_session_being_tested` drives `_levels_for_session` |
| ORB unusable before `ORB_END_MIN` | operative branch in `run()` + source guard test |
| Forward returns in-session only (`i+h` or None) | `_forward_ret` + boundary / strictly-after tests |
| Baseline = same clock minute, not flat pool | `_paired` + `test_baseline_is_time_of_day_matched_not_a_flat_average` |

### TOD vs flat average — ACCEPT

Baseline dict is `horizon → min_of_day → [|fwd|…]`; pairing uses that minute’s mean. Test asserts unequal loud/quiet minutes and zero excess when touch equals its minute.

### Placebo fairness (fair-method) — ACCEPT with soft residual

**Attack:** displaced levels get fewer touches (full run placebo_n 7717 vs real 12471) — could that select *wider* bars and manufacture FAIL?

**Probe (auditor, last 40 sessions × SPY/QQQ/IWM):**  
mean touch-bar range real 0.636 vs placebo 0.608 (ratio **0.956**); median likewise lower for placebo. Placebo is **not** a harsher wide-bar filter than real on this sample. Real still loses on Cohen’s d excess in the full seeded run → FAIL is not an artifact of “placebo always wider.”

**Can placebo be tuned to always beat real?** Offset band and seed are fixed in code (`PLACEBO_OFFSET_PCT=(0.003,0.012)`, `PLACEBO_SEED=20260730`); `test_placebo_levels_are_displaced_but_still_reachable` bounds displacement. Post-hoc *addition* of the placebo criterion after a false PASS is disclosed in commit + RC (honest; makes PASS harder). Soft residual: OOS consistency checks **sign of real d only**, not placebo beat — does not unlock PASS today (`horizons_passing=0`).

### PASS criteria pre-registered / fail-closed — ACCEPT

`PASS` dict in module; `test_pass_criteria_are_preregistered_and_strict`; one-event → FAIL; **match-placebo → cannot pass** (`test_pass_requires_beating_a_placebo_arm`). Without placebo, raw TOD effect would have passed (d≈0.24, CI excludes 0, OOS sign-consistent) — Claude correctly refused that and locked FAIL.

### Direction / magnitude — ACCEPT

Question and metrics are **absolute** forward move vs TOD. Commit/RC explicitly **not** claim tradeable edge / direction. NEXT-DEPTH: range-matched baseline + direction.

### Decide path — ACCEPT

`decision_path_effect` always `NONE — structure-only…`; admissions registry `admissions: []`; not in commit diff; markdown asserts Decide stays WAIT / not admitted.

---

## 3) UI HARD STOP — ACCEPT

Commit touches no `static/index.html`, no `static/chart.html`, no new chrome. Worktree may still carry dirty Enter-UX on `chart.html` — unstaged; not in `7923df8b`.

---

## 4) RC-158 — PARTIAL (close-contract evidence gun)

| Check | Result |
|---|---|
| Status CLOSED; five_why depth (≥4 `->`) | PASS (`check_five_why_recursive_lock` → 0) |
| `FIXED:` reach names harness/tests/artifacts | PASS (in fix cell) |
| FAIL → structure-only / admissions untouched / WAIT | PASS (in fix cell) |
| No banned pending vocab in fix; no DOM → no VISIBLE_SURFACE required | PASS |
| `check_closed_rows_ship_their_code` RC-158 | PASS (no violation) |
| `check_root_cause_log` proof words in **fix** cell | **FAIL** — `PROVEN` is in **why** cell only; fix has “Verification:” (does not match `PROVEN\|VERIFIED\|MEASURED\|OBSERVED`) |

This is the sole Step-5 Done gun.

---

## 5) PROTOCOL / STATUS

**Step 5 remains NEXT** (not ACCEPT). LP-01 program **not** marked COMPLETE. No Decide admission drafted.

### Residual-close prompt (only)

> **LP-01 Step 5 residual close (v43 PARTIAL @ `7923df8b`)**  
> Do **not** reopen the study, change PASS criteria, re-tune placebo, touch UI, or draft Decide admission.  
> **Only:** edit RC-158’s **fix** cell so `check_root_cause_log` passes — include a proof token (`MEASURED` / `PROVEN` / `VERIFIED` / `OBSERVED`) **and** the same-turn harness numbers (e.g. `MEASURED: .venv/Scripts/python.exe tools/lp01_touch_study_v1.py → verdict=FAIL, n_touch=12471, d_5/15/30=0.264/0.240/0.232, excess=-0.063/-0.072/-0.074`). Keep `FIXED:` reach and structure-only disposition. New commit (do not amend unless operator asks). Re-run `check_root_cause_log` filtered to RC-158 = clean. Zero UI. No push unless asked.

### Soft residuals / NEXT-DEPTH (do **not** block residual close)

- OOS gate is sign-consistency of real arm only (not placebo).
- `n_sessions=299` is ticker×session keys, not unique calendar days.
- Placebo criterion added after first false-PASS run (disclosed).
- NEXT-DEPTH if revisited: range-matched baseline; **direction** not magnitude.

---

## 6) drift-audit checklist (explicit)

- [x] Intent vs protocol Done (harness+FAIL+WAIT+RC) — study yes; RC evidence word no  
- [x] Arity/AST — N/A (no engine signature change; consumer-only)  
- [x] Presence vs capability — ORB/lookahead/pass gates operative in `run`/`_analyse`, not docstring-only  
- [x] Silent-swallow — forward `None` on boundary; no fake PASS default  
- [x] Fail-closed — one-event and match-placebo → FAIL  
- [x] Tests exercise path — 11 harness tests drive functions  
- [x] Stale vs live — artifact regenerated this turn; exact match  
- [x] Gate strength — placebo prevents method-manufactured PASS  
- [x] Fair-method — placebo range probe does not manufacture FAIL  
- [x] Patch/gate-relax — none; Decide admissions empty  
- Completeness critic: RC proof-token column miss would have been missed by reading the why chain alone — caught by running `check_root_cause_log`.

**drift-audit run; findings: RC-158 fix-cell lacks PROVEN/VERIFIED/MEASURED/OBSERVED; corrections: residual-close prompt only (no code change this turn); gate hardened: n/a.**

---

## Parent status line

`CLAIM:` Step 5 study FAIL locked + money-path/UI clean @ `7923df8b`; RC-158 proof-word gun → PARTIAL · `DONE:` audit v43 · `NEXT:` Step 5 residual close (RC-158 fix-cell MEASURED/PROVEN) · `BLOCKER:` none (operator/Claude residual)
