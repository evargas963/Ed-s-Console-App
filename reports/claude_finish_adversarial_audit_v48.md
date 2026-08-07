# Claude Finish Adversarial Audit v48 — honesty-gap close only (2026-07-31)

**Auditor:** Cursor (adversarial), 2026-07-31 ~11:30 ET  
**Target claim:** Claude closed the two v47 honesty gaps — (1) RC-159 CLOSED cell no longer asserts delivered 60s sentinel cadence; (2) `reports/claude_finish_rc162_chart_accrual_consumer.md` has zero banned Monday labels — while residual stays PARTIAL; combo forbidden; nothing committed; Decide untouched.  
**Prior:** v47 PARTIAL — RC-159 ledger still said “sentinels every 60s”; evidence file still carried stale Monday residual prose.  
**Scope this turn:** honesty-gap close only (not residual ACCEPT). Audit report only unless a lying lock needs a trivial fix — **none applied**.

**Admission preamble (AGENTS.md):** MISSION_CLASS=Collect (adversarial honesty audit) · GAP=same-turn verify the two v47 honesty closures · SMALLEST_COMPLETE_CHANGE=`reports/claude_finish_adversarial_audit_v48.md` · MINIMUM_SUFFICIENT_EVIDENCE=Read RC-159 fix cell + lock-pattern grep + exact-COUNT sentinel gap SQL + `check_rc_log_rows_keep_schema` · DECISION_PATH_EFFECT=none (audit) · WHY_NOW=Claude claims gaps closed before clock/paint residual · TASK_ADMISSION=audit only; no commit; no Decide; no RC-163 rewrite.

**drift-audit run:** phases 1–7 this turn.

- **Phase 1 intent:** Operator wanted the two named honesty gaps closed without soft-ACCEPT of the live residual. Gate = ledger no longer claims delivered 60s + evidence file free of RC-163 banned Monday-proof phrases.
- **Phase 2 mechanical:** Read RC-159 cell; `_MONDAY_PROOF` scan on evidence file + ledger; exact SQL gap medians; `check_rc_log_rows_keep_schema`.
- **Phase 3 failure-class checklist:** see §5.
- **Phase 4 critic:** named gaps closed; same RC-159 edit left `MONDAY PROOF` criteria text; evidence NEXT_RTH body still says correction was “rather than restated in the ledger” (now false); mandate-met-at-134s vs residual gap≤120s tension.
- **Phase 5–7:** honesty-gap close **PASS**; residual overall **PARTIAL**; corrections none (audit-only); gate hardened n/a.

---

## Verdict: honesty-gap close **PASS** · residual overall **PARTIAL**

| Named v47 honesty gap | Claude claim | Auditor same-turn | Result |
|---|---|---|---|
| 1) RC-159 CLOSED cell asserts delivered 60s | Corrected to floor-vs-delivered + measured medians | Cell quotes FLOORS of 60s / 300s; MEASURED medians ~134/135/138s; “never a schedule”; terrain cycle >60s; “NOT FIXED HERE — measurement correction, not a scheduler redesign” | **PASS** |
| 2) Banned Monday language in `claude_finish_rc162_chart_accrual_consumer.md` | Zero banned Monday labels | `_MONDAY_PROOF` hits = **0**; `next_rth_monday_lie_violation` = None; bare “Monday” count = **1** (meta: “RC-163 bans Monday labelling…”) | **PASS** |

**Why not FAIL the honesty close:** both named gaps are actually closed under the detectors and the ledger text. Claude did not re-claim ACCEPT, combo, or Decide.

**Why residual stays PARTIAL (unchanged):** sentinel gaps still FAIL the ≤120s criterion; `max(et_minute)≥974` not yet available (clock); browser paint re-check still owed for finish language. These were never the honesty-gap ask.

---

## 1) RC-159 fix cell — cadence honesty (PROVEN)

Quoted from `governance/root_cause_log.md` line 207 fix cell (same-turn extract):

> CADENCE — CLAIM CORRECTED BY MEASUREMENT 2026-07-31, do not read the original figure as achieved: the code sets FLOORS of 60s for sentinels SPY/QQQ/IWM and 300s for other enrolled tickers (minimum spacing between writes, never a schedule), and this cell originally reported those floors as if they were the delivered cadence. MEASURED on the first live RTH session (`SELECT ts_utc FROM option_chain_accrual WHERE et_date='2026-07-31' AND ticker=?` , consecutive differences) at 11:16 ET: SPY n_gaps=40 median 134s mean 177s max 472s with 24 gaps over 120s; QQQ median 135s mean 177s max 488s, 24 over; IWM median 138s mean 180s max 618s, 23 over. Earlier the same session (10:08 ET) SPY measured median 105s max 298s, so the spacing DEGRADES as the session progresses. A floor bounds how OFTEN a write may happen, not how often a chain is available: the terrain cycle over ~40 tickers on TERRAIN_WORKERS=2 against a 2-slot chain gate takes longer than 60s, so the sentinel floor is unreachable by construction and the delivered spacing is whatever the cycle costs. NOT FIXED HERE — this row is a measurement correction, not a scheduler redesign; the accrual mandate (continuous across [555,975], universal) is met at this spacing, and any cadence tightening is a separate slice with its own vendor-budget argument.

No remaining assertion that delivered cadence is “sentinels every 60s.” Gap 1 closed.

---

## 2) Monday language — evidence file + ledger spot-check (PROVEN)

Reproduce:

```bash
# same patterns as tools/chart_intent_lock._MONDAY_PROOF
.venv/Scripts/python.exe scratchpad/_audit_v48_monday_scan.py
```

| File | banned `_MONDAY_PROOF` hits | bare Monday/MONDAY | `next_rth_monday_lie_violation` |
|---|---:|---:|---|
| `reports/claude_finish_rc162_chart_accrual_consumer.md` | **0** | 1 (meta ban note) | None |
| `governance/root_cause_log.md` (whole) | **2** | 14 (mostly historical overnight/Monday calendar rows) | n/a (blob-level) |
| RC-159 row alone | **1** — `MONDAY PROOF` | 1 | **BLOCKS** (next RTH = 2026-07-31 Friday) |

Gap 2 as scoped to the evidence file: **closed**.

**FINDING (new / adjacent — not the named gap):** Claude edited the RC-159 fix cell this turn and left the residual criteria block headed `MONDAY PROOF, stated in advance…`. Same-turn `next_rth_monday_lie_violation(RC-159 line)` returns a BLOCK reason. That is lock-banned language on a residual-language path (`governance/root_cause_log.md`). Prefer rename to `NEXT_RTH_PROOF` + ISO date (or `# next-rth-ok:`) when that cell is next touched — **OBSERVE this turn; not rewritten**.

Second ledger hit is in another CLOSED row’s OUT-OF-SCOPE (`MONDAY_PROOF stays the open residual…`) — also OBSERVE.

---

## 3) Sentinel gap medians — “worse/degrading” (PROVEN direction)

Exact `COUNT` / median on `option_chain_accrual` where `et_date='2026-07-31'` (read-only; `scratchpad/_audit_v48_sentinel_gaps.py`):

| Source | when | SPY median (s) | QQQ | IWM | SPY gaps>120 |
|---|---|---:|---:|---:|---:|
| Claude evidence @ ~10:12 ET | earlier | ~105 | — | — | 7 |
| v47 auditor @ ~11:00 ET | prior audit | 132.4 | 133.7 | 134.1 | 20 |
| Claude ledger correction @ 11:16 ET | claimed | 134 | 135 | 138 | 24 |
| **v48 auditor now** | same turn | **155.9** | **143.4** | **145.0** | **27** |

Also: `n_rows=787`, `distinct_tickers=38`, `min_et=555`, `max_et=691` (974 not yet).

**Claim “spacing degrading (worse than audit)”:** **PROVEN** directionally vs both Claude’s 10:12 snapshot and v47. Cause tagged `[UNVERIFIED]` (DB DEGRADED) by Claude — auditor does **not** elevate that cause; spacing fact stands without it.

**Claim “mandate continuous/universal still met” at this spacing:** **tension** — the same RC-159 cell still lists residual criterion “no inter-row gap above 120s for sentinels,” which today’s series fails. Continuous/universal *presence* (38 tickers, min≤556) is separately measurable; equating that with the gap criterion being met would be a new lie. Claude’s PARTIAL status correctly refuses ACCEPT on cadence.

---

## 4) RC-163 schema claim — OBSERVE (PROVEN true; not rewritten)

Claude: RC-163 has 6 cells vs 7 (missing trailing `|`); Cursor’s row; left alone.

Same-turn:

```text
RC-163 pipe_count=7 → checker_cells = pipe_count - 1 = 6 (want 7)
check_rc_log_rows_keep_schema → 1 viol @ L211:
  "row has 6 cells, schema is 7 …"
```

All seven logical fields are present; the row lacks the trailing `|`, so the RC-105 checker counts 6. Message text blames “interior pipe” — here the defect is missing trailing pipe, not a truncated interior. **OBSERVE.** Trivial trailing `|` would clear the gate; not applied this turn (operator-safe preference: report only).

---

## 5) Failure-class checklist (honesty scope)

- [x] **Presence vs capability** — cadence correction is present in the CLOSED cell and operative as prose; does not invent a 60s scheduler.
- [x] **Stale vs live** — evidence file NEXT_RTH body still says void “stated here rather than restated in the ledger” and cites ~105s — **stale** relative to the ledger edit (FINDING soft).
- [x] **Gate strength** — Monday close proven by lock regex + `next_rth_monday_lie_violation`, not eyeballing.
- [x] **Classification-by-complement** — bare “Monday” ≠ banned pattern; counted separately.
- [x] **Patch / gate-relax** — none; no scheduler redesign claimed; no Decide.
- [x] **Full-stack** — n/a (honesty prose only).

**Completeness critic:** After closing “delivered 60s,” does the cell still smuggle a weekday-named proof label? **Yes — `MONDAY PROOF`.** After closing Monday in the evidence file, does the same residual section contradict the ledger correction? **Yes — “rather than restated in the ledger.”** Neither reopens the named two gaps; both are next-hygiene items.

---

## 6) Path forward

1. Keep residual **PARTIAL** until `max(et_minute)≥974` after 16:14 ET **and** browser paint re-check (yellow OV + GEX; `#gsrc` live+bank) on enrolled surface.
2. When next editing RC-159: replace `MONDAY PROOF` with `NEXT_RTH_PROOF` + ISO date (or `# next-rth-ok:`); reconcile “mandate met at this spacing” with the ≤120s residual criterion (drop, re-scope, or keep FAIL explicit).
3. Refresh stale sentences in `claude_finish_rc162_chart_accrual_consumer.md` NEXT_RTH body (ledger now corrected; medians moved).
4. Optional trivial: append trailing `|` on RC-163 row to clear `rc_log_rows_keep_schema` — OBSERVE until operator asks.
5. No commit assumed; Decide untouched.

---

## STATUS

`CLAIM:` honesty-gap close **PASS** (both named v47 gaps closed; same-turn verified) · residual overall **PARTIAL** (cadence FAIL + clock + paint)  
`DONE:` v48 adversarial audit written  
`NEXT:` after 16:14 ET — `max(et_minute)≥974` + browser paint re-check; optional RC-159 `MONDAY PROOF` → `NEXT_RTH_PROOF` hygiene  
`BLOCKER:` none for honesty close; residual blockers = clock (974) + paint re-derive + sentinel gap≤120s still FAIL

drift-audit run; findings: (1) named gaps closed, (2) RC-159 still carries lock-banned `MONDAY PROOF` after edit, (3) evidence NEXT_RTH body stale vs ledger, (4) RC-163 schema 6-cell claim true — OBSERVE; corrections: none; gate hardened: n.
