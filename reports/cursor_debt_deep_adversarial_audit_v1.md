# Cursor debt deep adversarial audit v1 — 2026-08-02

**Protocol:** `.claude/skills/drift-audit/SKILL.md` (deep — do not trust v1 prose).  
**Prior:** `reports/cursor_debt_clear_adversarial_audit_v1.md`, `reports/debt_clear_2026_08_02.md`.  
**Law:** `reports/zero_debt_work_law_v1.md`.  
**Decide:** WAIT. **No commit** this turn.

Next RTH (America/New_York + `time_et.is_trading_day_et`): **2026-08-03 Monday**.

---

## A. Phase 1 — Intent & drift

Operator wanted four deliverables today: (1) deep self-adversarial re-proof of debt-clear claims, (2) a real Monday-open alarm that wakes agents, (3) honest UNPROVEN explanation (epistemic ≠ RC bug), (4) no-soft-stop playbook.

North star: zero parked product debt; Collect calendar honesty continuum; Chart consumer not soft-out; Decide remains WAIT.

Drift vs v1 audit prose:
1. v1 cited a nonexistent test path `tests/test_chart_liquidity_levels_v6_surface_v1.py` — Chart v6 surface locks live in `tests/test_liquidity_engine.py` (still green). Presence-of-claim vs capability of the *audit report*.
2. Two python processes show the uvicorn cmdline; netstat LISTEN is only pid **21028**, whose parent is **32996** — normal parent/child pair, not a dual-listener. Monday prompt still says keep a single console tree.
3. `EdRthCompletenessCheck` exists but Last Result was unhealthy on a Sunday off-hours fire — RC-181 still correctly OPEN until Mon 15:35 CT.

---

## B. Same-turn mechanical re-proof

### B1. RC inventory (exact parse)

```text
TOTAL_UNIQUE 190
COUNTS {'CLOSED': 187, 'PARTIAL': 2, 'OPEN': 1}
ACTIVE: RC-166 PARTIAL, RC-180 PARTIAL, RC-181 OPEN
```

Method: `governance/root_cause_log.md` rows `| RC-<n> | OPEN|PARTIAL|CLOSED |`.

### B2. Pytest re-run (do not cite v1 counts)

```text
.venv/Scripts/python.exe -m pytest
  tests/test_rc191_zero_debt_product_v1.py
  tests/test_rc193_morning_full_calendar_gate_v1.py
  tests/test_study_calendar_gates_v1.py
  tests/test_client_spot_single_faucet_v1.py
  tests/test_liquidity_engine.py
-q
→ 90 passed, 1 warning in 35.37s
```

### B3. RC-193 writers/readers (code + DB + live)

| Seam | Evidence |
|---|---|
| Writer | `calibration/option_chain_morning_full.py` returns `skipped/non_trading_day` via `is_trading_day_et` (morning_full + accrual) |
| Reader | `server.py` forces/ghost filter: `rows = [r for r in cand if is_trading_day_et(...)][:2]` |
| DB stock | `morning_full_non_trading_dates=0`, `accrual_non_trading_dates=0` |
| Live `/api/forces?ticker=SPY` | `newer_et_date=2026-07-31`, `older_et_date=2026-07-30` — **not** Sunday 2026-08-02 |
| OpenAPI | `/api/forces` present |

### B4. Collect calendar continuum (bars / snapshots)

| Check | Result |
|---|---|
| `price_bars_1m` non-trading bar count | **0** of 1,313,067 |
| non-trading snapshots still `rth` | **0** |
| non-trading snapshots `closed` | **49011** |

### B5. Chart v6 shipped?

`static/chart.html` carries candles/line mode chips, `#firedrow`, `#forces`, `offScale`/`pinRow`, `/api/forces` fetch, levels manager DOM ids. Structural tests in `test_liquidity_engine.py` assert `firedrow`, `firedpills`, `lvlmenu`, `mode-candles`, `mode-line`, `forces`. RC-110/115/124/192 remain CLOSED in the ledger.

### B6. Monday residue code readiness

| id | Code ready? | Live closeable today? |
|---|---|---|
| RC-166 | Yes (incremental upsert + tests historically green; contention endpoint live) | **No** — Sunday idle `lock_wait_count=0` is not RTH proof |
| RC-180 | Desk honesty FIXED; F-10 = same RTH probe | **No** |
| RC-181 | Tool + schtask registered | **No** until Mon **15:35 CT** fire |

Live contention (Sunday): all zeros / `operator.state=OK` — expected idle; must not close 166/180 on this.

Console: LISTENING `:8000` pid **21028** (parent **32996**) via `.venv\Scripts\python.exe -m uvicorn server:app ...` — one listener tree.

---

## C. Drift-audit failure-class checklist

- [x] **Arity/unpack** — no new shared return-shape changes this turn; RC-193 skip dict shape exercised by tests.
- [x] **Presence vs capability** — morning_full calendar gate present AND stocked weekend rows gone AND live forces uses Fri/Thu; Chart v6 DOM present AND liquidity_engine tests pass. **FAIL class in v1 prose:** cited missing test file name (audit soft-claim).
- [x] **Silent-swallow** — persist returns explicit `non_trading_day`; forces filter drops non-trading instead of preferring them.
- [x] **Caller/consumer** — writers + forces + ghost + Chart `/api/forces` consumer traced.
- [x] **Fail-closed** — non-trading persist skip; Desk replay refusals previously locked (RC-180 suite in liquidity/desk history).
- [x] **Test exercises path** — RC-193 refuses Sat/Sun timestamps; faucet/calendar suites green.
- [x] **Stale vs live** — live forces/openapi/contention probed this turn; terrain `levels_stale=true` age~1026s outside logging window = expected Sunday, not a reopen of RC-165.
- [x] **Gate strength** — bars=0 does not alone prove chain banks; chain banks re-proved separately (completeness critic from v1 still holds).
- [x] **Full-stack / continuum** — bars, snapshot labels, morning_full, accrual, forces readers checked.
- [x] **Side-channel** — dual uvicorn cmdline traced to parent/child (one LISTEN); not dual bind.
- [x] **EXPLAIN-before-join** — N/A (no multi-GB ad-hoc join this turn; bar scan was full-table COUNT-class via Python date derive — slow but exact).
- [x] **Classification-by-complement** — non-trading via `is_trading_day_et`, not weekday≠.
- [x] **Patch/gate-relax** — none; alarm is ops wake, not a money-path bypass.

Completeness critic: “What would still bite Monday?” → (1) `EdRthCompletenessCheck` last unhealthy off-hours result, (2) two UNPROVEN rows become overdue on 2026-08-03 if untouched, (3) LP-01 still NEXT (separate product debt), (4) closing 166/180 on Sunday idle zeros.

---

## D. Findings

| id | Class | Verdict | Action this turn |
|---|---|---|---|
| F1 | Audit prose | **PARTIAL** | v1 named a nonexistent Chart v6 test file; real locks in `test_liquidity_engine.py` — corrected in this report |
| F2 | Ops / process | **PASS** | Second uvicorn cmdline is parent of the LISTEN child — not dual-bind / not orphan |
| F3 | RC-181 host | **OBSERVED** | Completeness task Last Result unhealthy on off-hours Sunday fire; first legal PASS remains Mon 15:35 CT |
| F4 | Epistemic | **HONEST** | 6 UNPROVEN remain — not RC bug debt (see §E) |
| F5 | Product Mon | **CLOCK_BLOCK** | RC-166/180/181 only active RC residue |

### FIX landed today (alarm + docs)

- Installed `EdMondayDebtWake` (Mon 08:25 CT) → `tools/monday_debt_wake.py`
- Wrote `reports/monday_debt_wake_prompt.md`, `reports/monday_debt_alarm_setup.md`, `reports/no_soft_stop_completion_playbook.md`
- Updated `governance/host_scheduled_jobs.md` inventory

No product CLOSE of 166/180/181 (would be false completion).

---

## E. UNPROVEN register — why “debt” remains (epistemic ≠ defect)

**Exact counts this turn:** UNPROVEN **6**, DISPROVED **0**, PROVEN 13, REMEDIATED 5.

Gate rule: overdue when `due < today` (`check_unproven_register`). On **2026-08-02**, due=2026-08-02 is **not yet overdue**. On **2026-08-03**, the two 08-02 dues become commit blockers unless measured / re-dated / dispositioned.

| # | claim (short) | due | why still UNPROVEN | cheapest measure command | clear condition |
|---|---|---|---|---|---|
| U1 | Dealer gamma sign predicts intraday range **beyond** realized vol (sig test) | 2026-08-02 | Directional strata seen historically; **no permutation/bootstrap significance** yet; cheap scoreboard often lacks fair per-ticker-day range×regime cells | Build/run a purged range-diff perm test within RV strata on operable trusted days (extend prior pin/GEX scorecard scripts; cite n + p) | PROVEN if strata diff survives pre-registered perm at α; else DISPROVED→retract signal claim (structure-only) |
| U2 | Whether **per-strike charm walls** should exist beside gamma/vanna walls | 2026-08-02 | Product/design claim: we persist chain-level charm only; no per-strike charm surface to test residence | Either (a) ship per-strike charm compute + placebo residence study, or (b) decide NOT to ship and REMEDIATE/retract the “should exist” question with operator ruling | Operator decision + study, or explicit “will not ship” remediation note |
| U3 | Wide-chain gamma pin vs close better than narrow null | 2026-08-14 | Wide `option_chain_morning_full` n still below verdict-grade power (re-dated 2026-07-28; accrues ~1 morning/RTH day) | Re-run pin residence/close study on morning_full days only when n legal (~08-14 checkpoint) | PROVEN/DISPROVED table at n with declared power |
| U4 | +call/−put dealer-sign + prior-night OI hold on **single-name** universe | 2026-08-03 | Split evidence already partial (OI walls hold; volume wins some rho); sentinel frame historically n=0 on narrow history — needs accrued wide/single-name scorecard continuity | Continue `sign_split` / weighting scorecard on accrued operable days; do not collapse to SPY-only | Sustained predictive utility vs placebo under pre-reg rule → PROVEN; else DISPROVED/retract regime input |
| U5 | Wall-break follow-through stronger into a **void** than into next structure | 2026-08-14 | Needs wide-chain days + pre-registered void gap X; capture still accruing | Pre-reg X, then break→close drift study on wide days vs placebo breaks | PROVEN/DISPROVED vs placebo at checkpoint |
| U6 | KDS / MAX PAIN / HVP-LVP / NET Γ PEAK have touch/residence edge | 2026-08-14 | **Never studied** on our data; display-only until proven (operator 2026-08-02) | Shared wide-chain residence protocol vs placebo (±0.25%) from 10:00 ET | Each level PROVEN or stay structure-facts default OFF |

**Honesty line:** clearing RC-166/180/181 does **not** clear U1–U6. UNPROVEN rows are dues on claims about the market/data — not unfinished bugfixes. Fake-PROVEN is forbidden.

---

## F. Alarm status

| Item | Status |
|---|---|
| `EdMondayDebtWake` schtask | **INSTALLED** — Next Run 2026-08-03 08:25 |
| Smoke `--force` | GO marker written; clipboard ok |
| Cursor Automation | Draft in `reports/monday_debt_alarm_setup.md` — needs operator “yes, open editor” (skill gate) |
| Playbook | `reports/no_soft_stop_completion_playbook.md` |

---

## G. VERDICT

**VERDICT: PARTIAL**

- Debt-clear CLOSED set + RC-193 continuum: **PASS** on same-turn re-proof (tests, DB, live forces).
- Chart v6: **PASS** (code + liquidity_engine surface tests); v1 audit’s test filename was wrong.
- Active RC debt: **only** Mon clock-blocks RC-166 / RC-180 / RC-181.
- New residue named (not museum-closed): unhealthy completeness Last Result off-hours; UNPROVEN dues flip tomorrow; LP-01 still NEXT.
- Monday alarm: **installed** (Task Scheduler).

Named residue: **RC-166, RC-180, RC-181** (+ epistemic U1–U6; + ops note F3).

drift-audit run; findings: F1–F5; corrections: Monday wake installed + reports/playbook + inventory; gate hardened: n (product/ops wake > new commit gate).

---

## H. Admission

| Field | |
|---|---|
| MISSION_CLASS | Collect / governance hygiene — deep audit + Monday wake |
| GAP | v1 audit trust; no wall-clock agent wake; UNPROVEN confusion vs RC debt; soft-stop pattern |
| SMALLEST_COMPLETE_CHANGE | Re-prove + install schtask wake + docs |
| MINIMUM_SUFFICIENT_EVIDENCE | Exact RC/UNPROVEN counts; 90 passed; DB zeros; live forces dates; schtask Next Run |
| DECISION_PATH_EFFECT | none |
| WHY_NOW | Operator bind-all ask 2026-08-02; next RTH Mon |
| TASK_ADMISSION | Deliverables written; Decide WAIT; no commit |
