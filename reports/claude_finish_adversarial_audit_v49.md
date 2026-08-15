# Claude Finish Adversarial Audit v49 — honesty hygiene + live spot-check (2026-07-31)

**Auditor:** Cursor (adversarial), 2026-07-31 ~12:39 ET  
**Target claims (operator paste):** three v48 hygiene items closed (0 banned Monday/weekday proof labels in RC ledger + rc162 evidence; evidence degradation trend refreshed; PreToolUse RC-163 caught first attempt); residual still PARTIAL; live probe SHA/rows/OV; DB DEGRADED OUT OF SLICE; RC-163 schema 6 cells OBSERVED.  
**Prior:** v48 honesty-gap close PASS; residual PARTIAL; flagged `MONDAY PROOF` still in RC-159 + stale evidence body.  
**Scope:** audit-only. No commit. No Decide. **No DB remediation** (observe only).

**Admission preamble (AGENTS.md):** MISSION_CLASS=Collect (adversarial honesty audit) · GAP=same-turn verify v48 hygiene closures + live spot-check · SMALLEST_COMPLETE_CHANGE=`reports/claude_finish_adversarial_audit_v49.md` · MINIMUM_SUFFICIENT_EVIDENCE=`_MONDAY_PROOF` scan + exact COUNT SQL + `/api/build` + one `/api/analytics/light` timeout probe · DECISION_PATH_EFFECT=none · WHY_NOW=operator pasted Claude claims before clock residual · TASK_ADMISSION=audit only.

**drift-audit run:** phases 1–7 this turn (honesty + live numbers; not residual ACCEPT).

---

## Verdict: honesty hygiene **PASS** · residual overall **PARTIAL** · new lies **none proven**

| # | Claude claim (v48 items) | Auditor same-turn | Result |
|---|---|---|---|
| 1 | 0 banned weekday/`MONDAY` proof labels in `root_cause_log` (RC-159 + refs) + rc162 evidence | `_MONDAY_PROOF` hits = **0** on both files; RC-159 line `next_rth_monday_lie_violation=None`; bare “Monday” only as RC-163 ban meta in evidence header | **PASS** |
| 2 | Evidence body refreshed with degradation trend | `claude_finish_rc162…` has three-point SPY median table (10:08 / 11:16 / 12:07) + ledger-correction language; voids “60s delivered” | **PASS** |
| 3 | PreToolUse RC-163 lock caught first attempt | No hook log / exit-2 artifact in repo evidence this turn | **[UNVERIFIED]** process narrative — outcome text is clean; catch itself not proven |

**Residual PARTIAL — confirmed.** Criteria still unmet: sentinel gaps ≫120s; `max(et_minute)≥974` not yet (clock); browser paint re-check still owed for finish language. Claude did not claim ACCEPT / combo / Decide.

**DB investigation needs your GO — Claude correctly parked it.**

---

## A) Honesty closures (PROVEN)

Reproduce:

```text
.venv/Scripts/python.exe -c "from tools.chart_intent_lock import _MONDAY_PROOF, next_rth_monday_lie_violation; ..."
```

| File | `_MONDAY_PROOF` hits | Notes |
|---|---:|---|
| `governance/root_cause_log.md` | **0** | RC-159 now says `NEXT_RTH_PROOF for 2026-07-31 Friday` |
| `reports/claude_finish_rc162_chart_accrual_consumer.md` | **0** | Header meta mentions RC-163 bans “Monday” labelling (not a banned proof phrase) |

v48 FINDING (RC-159 still carried `MONDAY PROOF`) is **closed** in the working tree (uncommitted `M` on both files — matches “nothing committed”).

Soft note (not a FAIL): evidence section header still says “Re-derived same-turn at **10:12 ET**” while the cadence table includes **12:07 ET** rows — body was refreshed; header timestamp is stale.

---

## B) Live spot-check (PROVEN this turn ~12:39 ET)

| Probe | Claude (~12:28 ET) | Auditor now | Match? |
|---|---|---|---|
| `/api/build` SHA | `6c47b89b` | `6c47b89bdcb4…` (`startup_git_sha_short=6c47b89bdcb4`) | **PASS** |
| Accrual `COUNT(*)` et_date=2026-07-31 | 1166 | **1240** | Plausible grow (~10 min); **do not treat 1166 as current** |
| Distinct tickers | 38 | **39** | Drift +1 since Claude; earlier same-turn probe also saw 38→39 |
| SPY OV (live strikes `today.all` sum / DB max session_volume) | ~7.9M | **8,285,763** | Directional accumulate **PASS** |
| Live cache age | ~66s | **44.9s** then **112.6s** on second hit | Order-of-magnitude OK; not frozen |
| `max(et_minute)` | (not claimed as 974) | **759** | **PARTIAL** — 974 requires ≥16:14 ET |
| Process start | 10:07 DOWN = SHA restart | `process_started_at_utc` → **2026-07-31 10:07:31 ET** pid 29920 | **PASS** (restart time); “not spontaneous” motive still narrative |
| Decide | untouched | `decision_path_admissions.admissions = []` | **PASS** |
| Commit | nothing committed | Working tree dirty on the two honesty files; HEAD still `6c47b89b` | **PASS** (no new commit) |

Exact SQL (read-only URI):

```text
ACCRUAL exact: rows=1240 tickers=39 min_et=555 max_et=759
SPY gaps: n=66 median=152.5s mean=181.5s max≈617s over120=42
SPY max(session_volume)=8285763
```

Sentinel cadence still **FAIL** the ≤120s residual criterion; median still degraded vs morning (~105s → ~152s).

**Watchdog (141 samples 09:25→12:25; SPY OV monotonic; accrual_bank 28/139; restarted for close):** no watchdog JSON/log artifact found under `reports/` or `scratchpad/` this turn → **[UNVERIFIED]** as numbers. Not elevated to a lie without a counter-measurement.

---

## C) DB DEGRADED / analytics slowness — observe only (one cheap check)

| Check | Result |
|---|---|
| `GET /api/analytics/light?ticker=SPY` timeout=15s | **TimeoutError** after **15.017s** |
| Accrual COUNT query | **0.009s** (indexed path fine) |

**Directionally evidenced:** analytics/light is slow/unavailable under a 15s client timeout right now.  
**Cause (lock waits / WAL / cycle contention → cadence):** remains **[UNVERIFIED]** — Claude tagged it that way and parked it. Auditor did **not** open a remediation slice.

---

## D) RC-163 schema — OBSERVE (still true)

```text
check_rc_log_rows_keep_schema → 1 viol @ L211
RC-163 pipe_count=7 → cells=6; endswith_pipe=False
```

Still Cursor’s OBSERVE item; not rewritten this turn.

---

## E) Failure-class checklist (honesty + live)

- [x] **Stale vs live** — Claude’s 1166 is a past snapshot; exact re-count now is 1240.
- [x] **Presence vs capability** — Monday labels absent; residual still PARTIAL (labels ≠ ACCEPT).
- [x] **Gate strength** — used lock regex, not eyeballing.
- [x] **Patch / gate-relax** — none; no Decide; no commit.
- [x] **Classification-by-complement** — bare “Monday” meta ≠ `_MONDAY_PROOF`.
- [ ] **PreToolUse first-block** — process claim without artifact → [UNVERIFIED].

**Completeness critic:** Could Claude have “closed” Monday by `# next-rth-ok:` escape while leaving proof language? **No** — scan found zero `_MONDAY_PROOF` hits, and RC-159 uses `NEXT_RTH_PROOF` + Friday ISO. Could 1166 have been a lie? **Not proven** — growth to 1240 is consistent with ongoing accrual; auditor refuses to certify the past count without a frozen snapshot file.

---

## Path forward

1. Residual stays **PARTIAL** until after **16:14 ET**: prove `max(et_minute)≥974` + browser paint (yellow OV + GEX; `#gsrc` live+bank) on enrolled surface.
2. Optional trivial: trailing `|` on RC-163 row (schema OBSERVE).
3. **DB investigation needs operator GO** — parked correctly; one cheap check already shows analytics/light timing out.
4. No commit assumed; Decide untouched.

---

## STATUS

`CLAIM:` honesty hygiene **PASS** (Monday labels gone + evidence degradation refreshed; PreToolUse catch [UNVERIFIED]); live SHA/OV/restart-time **PASS**; accrual exact now **1240/39** (Claude 1166 was earlier); residual **PARTIAL** confirmed; DB remediations parked  
`DONE:` v49 adversarial audit written  
`NEXT:` clock to 16:14 ET for max(et_minute)≥974 + paint re-check; DB slice only on operator GO  
`BLOCKER:` none for honesty; residual blockers = clock (974) + sentinel gap≤120s FAIL + paint; DB cause [UNVERIFIED]

drift-audit run; findings: (1) three textual hygiene items closed except PreToolUse catch unproven, (2) live numbers consistent / not lying, (3) analytics/light timeout directional, (4) RC-163 schema still 6-cell OBSERVE; corrections: none; gate hardened: n.
