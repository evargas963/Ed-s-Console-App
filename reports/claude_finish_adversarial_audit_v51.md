# Claude Finish Adversarial Audit v51 — RC-165 ledger honesty after v50 (2026-07-31)

**Auditor:** Cursor (adversarial), 2026-07-31 ~13:04–13:20 CT  
**Target claims (Claude post-v50):** RC-165 restamped CLOSED→PARTIAL with BLOCKER/UNBLOCKED-BY; VISIBLE_SURFACE `#gsrc`; live re-probe ~13:28 ET still old 60s sentence (fix not live); residual PARTIAL; accrual ~1571/39 max et_minute=808; nothing committed; Decide untouched; DB parked.  
**Scope:** verify only. **No commit. No console restart.**

**Admission:** MISSION_CLASS=Collect (adversarial honesty) · GAP=confirm v50 ledger-honesty fixes · SMALLEST_COMPLETE_CHANGE=this file · MINIMUM_SUFFICIENT_EVIDENCE=RC-165 row + git HEAD/status + cheap live + accrual COUNT · DECISION_PATH_EFFECT=none · WHY_NOW=v50 FAILED CLOSED stamp · TASK_ADMISSION=audit only.

---

## Verdict: v50 ledger-honesty items **PASS** · residual **PARTIAL** · restart **operator call (not emergency)**

| # | Claim | Same-turn evidence | Result |
|---|---|---|---|
| 1 | RC-165 status PARTIAL not CLOSED; BLOCKER + UNBLOCKED-BY; VISIBLE_SURFACE `#gsrc`; no false CLOSED | Row cell **`PARTIAL`**. Fix cell: `STATUS IS **PARTIAL, NOT CLOSED**`; `BLOCKER:` worktree-only / live `6c47b89b` still old sentence; `UNBLOCKED BY:` operator restart + re-probe for DELIVERED wording; `VISIBLE_SURFACE: #gsrc`. DOM `#gsrc` exists in `static/chart.html` | **PASS** |
| 2 | Live `/api/build` still `6c47b89b`; one stale reason still old 60s sentence | HEAD `6c47b89b` (git). Working tree dirty (`server.py`, RC log, tests). Live HTTP: **8787 refused**; **8000 listens but `/api/build` TimeoutError (3s)** — hung accept, not a fresh SHA. Stale-reason sentence **not re-readable this turn** | SHA/process **consistent with not-live**; sentence **[UNVERIFIED] this turn** (hung API). Claude's ~13:28 ET probe stands as prior same-day claim, not contradicted |
| 3 | Accrual ~1571/39 max minute ~808; SPY OV climbing | PROVEN RO SQL `et_date='2026-07-31'`: **COUNT=1880, tickers=39, MAX(et_minute)=857**; SPY rows=100, max et_minute=853, **MAX(session_volume)=10,614,611**. Growing past Claude snapshot — expected | **PASS** (compatible; not exact match required) |
| 4 | Nothing committed; Decide untouched; combo forbidden; DB parked | `git status`: modified uncommitted; HEAD still prior SHA; `decision_path_admissions.json` `admissions: []`. No commit/restart by auditor | **PASS** |

---

## Residual

**PARTIAL confirmed.** Worktree fix + ledger honesty restamp are in place; production reach still awaits operator-approved restart. Restart is **cosmetic-misleading honesty** (false STALE sentence / yardstick), not data loss — accrual bank still writing. Do **not** force restart from this audit. Note only: `/api/build` on :8000 currently times out (OBSERVED hang), separate from ledger stamp.

---

## STATUS

`CLAIM:` RC-165 ledger honesty PASS (PARTIAL + BLOCKER/UNBLOCKED-BY + VISIBLE_SURFACE #gsrc); residual PARTIAL; accrual growing 1880/39/max 857 · `DONE:` v51 audit artifact · `NEXT:` operator restart when convenient → re-probe `/api/build` SHA + MSFT `levels_stale_reason` for DELIVERED-cycle wording · `BLOCKER:` restart consent (not auditor-forced; not emergency)
