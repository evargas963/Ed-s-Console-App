# Cursor adversarial audit v2 — Desk FAIL repair

**Auditor:** Cursor · **this turn** (do not trust Claude)  
**Authority:** `reports/cursor_desk_audit_v1.md` FAIL guns  
**HEAD:** `6213b1e5` (worktree)  
**Mode:** find / measure / report — **no fix, no push, no commit, no Decide touch**  
**Console:** real `python -m uvicorn server:app --host 127.0.0.1 --port 8000` started for probes, then stopped.

**Reproduce:**
```text
$env:PYTHONPATH=(Get-Location).Path
python -m pytest tests/test_desk_store_v1.py -q --tb=line
# with console up:
python scratchpad/_desk_audit_v2_live.py
# outputs: scratchpad/_desk_audit_v2_live_out.json
```

**STATUS: PARTIAL — Desk FAIL guns F-01..F-05 / F-08 CLOSED at the read path on real `:8000`; F-07 latency claims correctly treated as point-in-time (this turn structure@60 = 3.37/5.02/4.07s, light idle ~0.01s); residuals remain (DOM badge under replay not probed; F-10/RC-166 parked NEXT_RTH_PROOF 2026-08-03 Monday; stale ESTIMATED comment at `desk_store.py:84`). Not FAIL. Not full ACCEPT.**

---

## Admission

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — adversarial re-audit of Claude Desk FAIL repair |
| GAP | Claude claimed every gun closed; v1 FAIL must be re-derived same-turn |
| SMALLEST_COMPLETE_CHANGE | This report only |
| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn pytest + AST/read + live `:8000` outputs |
| DECISION_PATH_EFFECT | none |
| WHY_NOW | Operator ordered Cursor adversarial audit of Desk FAIL repair |
| TASK_ADMISSION | ADMITTED — audit-only |

---

## Same-turn suite

| Command | Result |
|---|---|
| `python -m pytest tests/test_desk_store_v1.py -q --tb=line` | **44 passed**, 1 warning, 24.83s · **0 failed** |

No other `tests/test_desk*.py` files exist in the worktree (only `tests/test_desk_store_v1.py`). New RC-180 cases present in that file: `test_replay_refuses_event_time_derivations`, `test_bootstrap_excludes_cross_session_returns`, `test_uncalibrated_outputs_are_unproven_not_estimated`, plus RC-176 Saturday regression.

---

## Soft-language trap (F-01) — not label-only

**Question:** Did Claude only stamp `EVENT-TIME ONLY` without changing the read path?

**Answer: NO — retreat is operative.** Live `:8000` (this turn, `scratchpad/_desk_audit_v2_live_out.json`):

| Probe | Result |
|---|---|
| `dossier_now` MSFT | `spread.n_quotes=374`, `capacity_usd` set, `tiers.capacity_usd=UNPROVEN` |
| `dossier_past` MSFT (`as_of` = now−30d) | `spread=null`, `capacity_usd=null`, `adv_dollar=null`; `missing` includes shared sentence for `effective_spread` and `daily_sigma / capacity` |
| `structure_now` SPY hz=5 | `available=true`, `tier=UNPROVEN`, `n_returns=5835` |
| `structure_past` MSFT | `available=false`, `reason` starts `EVENT-TIME ONLY: snapshots/price bars carry no knowledge clock…`, `knowledge_replay_safe=false` |

Module path (same turn, no HTTP): `effective_spread_bps(..., past) is None`, `daily_sigma_bps(..., past) is None`, `terminal_distribution(..., past)["available"] is False`.

Code path is refuse-then-skip, not annotate-and-serve: `desk_store.py` `_is_replay` + early `return None` in `effective_spread_bps` / `daily_sigma_bps`; `terminal_distribution` returns refusal dict before bootstrap. Offline `allow_event_time=` exists; `inspect.getsource(get_desk_dossier|get_desk_structure)` contains **no** `allow_event_time` (test-locked).

**Soft residual (not a gun re-open):** comment at `desk_store.py:84` still says capacity is “ESTIMATED and not DERIVED” while the payload tiers `UNPROVEN`. Comment drift only — payload/UI corrected.

---

## Gun re-check vs v1

| ID | v1 | Repair claim | This-turn verdict | Evidence |
|---|---|---|---|---|
| F-01 | P0 lookahead under replay | Refuse under replay + shared sentence | **CLOSED at read path** | Live retreat above; pytest `test_replay_refuses_event_time_derivations` |
| F-02 | P0 weekend RTH true | `is_rth_trading_ts` = clock ∧ calendar | **CLOSED** | `is_rth_trading_ts(2026-08-01 11:00 ET)=False`; `session_is_complete('2026-08-01',…)=True`; readers at lines 550/710/813/1012 call helper (AST); `is_rth_ts_utc` only inside the helper at 738 |
| F-03 | 2/39 tests red | Suite green incl Saturday | **CLOSED** | **44/44** green this turn |
| F-04 | ESTIMATED w/o calibration | → UNPROVEN | **CLOSED** | Live `capacity_usd=UNPROVEN`, dist `tier=UNPROVEN`; UI hardcodes capacity badge UNPROVEN + legend; pytest `test_uncalibrated_outputs_are_unproven_not_estimated` |
| F-05 | Overnight gap in 1m returns | Within-session pairs only | **CLOSED** | `_rth_log_returns` pairs only when `da == db_`; live MSFT 10d: `n=2753`, `n_gt_5pct_bp=0`; pytest 20% overnight gap fixture |
| F-06 | σ=earnings gap, not RC-168 | Honoured / untouched | **HONOURED** | RC-168 still **OPEN**; no sigma “volume fix” claimed CLOSED |
| F-07 | False latency claims | Retracted | **UPHELD as retraction** | This turn structure@60 = **3.37 / 5.018 / 4.07 s**; light = **0.018/0.003/0.006/0.015/0.007 s**. Claude’s 3.25/2.62/2.48 not reproduced exactly — point-in-time; prior 1.75s / 8.7s remain REFUTED |
| F-08 | “Candidates” header | “Tradeability structure — screened + listed.” | **CLOSED** | `static/desk.html` has screened+listed; no Candidates h3; radar counts still 12617 / 37 / 12579 |
| F-10 | Contention Saturday-only | Parked Monday | **STILL OPEN / parked** | RC-166 **PARTIAL**; NEXT_RTH_PROOF **2026-08-03 Monday** (`is_trading_day_et`) |

---

## RC ledger (adversarial)

| RC | Ledger status | Auditor check |
|---|---|---|
| RC-180 | **PARTIAL** | Correct — not falsely CLOSED. Names FIXED reach + VISIBLE_SURFACE (`dos-out`, `str-out`, radar heading). Residuals (DOM badge, F-10) keep PARTIAL honest. |
| RC-168 | **OPEN** | Correct — accumulator root untouched |
| RC-166 | **PARTIAL** | Not falsely CLOSED; mid-RTH contention still parked |
| RC-176 | CLOSED | Calendar helper + Saturday regression — suite green this Saturday |
| RC-179 | CLOSED | Charm locks in tree (`tests/test_charm_sign_finite_difference.py`); **deferred** — Desk FAIL is primary. No deep charm re-audit this turn. |

No Decide-path admission change checked beyond empty registry test still in suite.

---

## Drift-audit (self)

1. **Intent:** Operator wanted adversarial proof that Desk FAIL guns are actually closed — not Claude’s narrative.  
2. **Mechanical:** pytest 44/44; live `:8000` past/live dossier+structure+radar+tiers+latency; AST/inspect on refusal + RTH callers + API override absence; RC status extract.  
3. **Checklist:** presence≠capability (retreat returns null/`available=false`, not labels alone); fail-closed under replay; tests exercise real refuse path; weekend calendar; silent ESTIMATED comment residual noted; no Decide touch.  
4. **Critic:** Rendered DOM badge under replay slider not browser-probed; structure@60 variance shows latency is not a fixed SLA; RC-170 CLOSED row text still mentions clock-only filter historically — superseded by RC-176 code (not re-opened here).  
5. **Verdict:** PARTIAL.  
6–7. No fixes (hard stop).

**drift-audit run; findings: Desk FAIL read-path guns closed; residuals DOM/F-10/stale comment; corrections: none; gate hardened: n.**

---

## STATUS

`CLAIM: Desk FAIL repair PARTIAL — F-01 retreat operative on real :8000 (not label-only); F-02/F-03 calendar+44/44; F-04 UNPROVEN tiers; F-05 within-session returns; F-08 header; F-07 retraction upheld with this-turn 3.37/5.02/4.07s @60 · DONE: this audit report · NEXT: rendered-DOM replay badge proof; NEXT_RTH_PROOF 2026-08-03 Monday for RC-166/F-10 · BLOCKER: none for Desk read-path guns; mid-RTH contention still external`

**Plain English residual for operator:** The Desk no longer lies under a past `as_of` on spread/sigma/bootstrap — it refuses with the shared EVENT-TIME ONLY sentence, and live still answers with UNPROVEN tiers. What is still open is (1) proving the UI badge text under the slider in a browser, (2) RC-166 contention on a real Monday session, and (3) a leftover comment that still says capacity is ESTIMATED.
