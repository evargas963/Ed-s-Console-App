# Cursor debt-clear adversarial audit v1 — 2026-08-02

`# log-law-ok: frozen dated audit record — evidence, never a live queue; its rows are adjudicated
in governance/root_cause_log.md (RC-58/102/107/117/168/177/178 all CLOSED with measurement 2026-08-04).`

**Target:** `reports/debt_clear_2026_08_02.md` claims (RC-58,102,107,117,168,177,178,191 CLOSED).  
**Protocol:** `.claude/skills/drift-audit/SKILL.md` (intent, mechanical tests, failure-class checklist, completeness critic).  
**Law:** `reports/zero_debt_work_law_v1.md`. Decide WAIT. No commit.

Next RTH (America/New_York + `time_et.is_trading_day_et`): **2026-08-03 Monday**.

---

## A. Phase 1 — Intent & drift

Operator wanted zero parked product debt today: prove or refute the debt-clear CLOSEDs, fix every FAIL/PARTIAL residue, finish Chart v6 if Claude left it, clock-true Monday residuals only, honest UNPROVEN.

Drift found in the prior debt_clear report:
1. Chart victims parked to Claude while `static/chart.html` already held a substantial v6 build — park overstated incompleteness and understated unfinished ship (`RC-192` still `IN PROGRESS`).
2. RC-165 left as restart PARTIAL without executing the safe Sunday restart.
3. **Novel FAIL (not in debt_clear):** weekend `option_chain_morning_full` / accrual contamination poisoned `/api/forces` (`newer_et_date=2026-08-02` Sunday).

---

## B. CLOSED claim verdicts (same-turn evidence)

| id | Prior claim | Audit | Evidence this turn |
|---|---|---|---|
| RC-58 | Loaders calendar-gated | **PASS** | `tests/test_study_calendar_gates_v1.py` in 7-pass RC-191+calendar batch; FIXED names match call sites |
| RC-102 | Console reads levels_stale; edLiveSpot delegates | **PASS** | `static/index.html` reads `levels_stale` / age / reason; `edLiveSpot` -> `consoleSpot(null)`; `tests/test_client_spot_single_faucet_v1.py` in 65-pass faucet/staleness batch |
| RC-107 | session_safe threshold fallbacks | **PASS** | `tests/test_rc191_zero_debt_product_v1.py` (4) — weekend gap dropped; cost_aware/survival structural lock |
| RC-117 | P0_CLOCKS product honesty | **PASS** | faucet suite; ct-conf/trust stale-gated; AST-lock residual honestly OUT-OF-SCOPE under no-lock-harden |
| RC-168 | Accumulator gap >120s volume reset | **PASS** | `test_bar_accumulator_gap_resets_volume_delta` |
| RC-177 | Non-trading `price_bars_1m` = 0 | **PASS** | same-turn DB: `non_trading_bar_count=0` over 105 distinct ET dates |
| RC-178 | calendar `market_session` + relabel | **PASS** | Saturday->closed unit test; non-trading snapshots all `closed` (count 49011); 0 still labeled `rth` |
| RC-191 | Umbrella ship | **PASS as umbrella** | suite green; does **not** cover morning_full continuum (see F1) |

**Presence vs capability:** RC-177 CLOSED for bars was real; it did **not** imply wide-chain banks were clean (completeness critic → F1).

---

## C. Findings

### F1 — FAIL → FIXED same turn (RC-193)

`maybe_persist_morning_full_chain` / `persist_chain_accrual` clock-only; `/api/forces` and ghost morning_full reads took `ORDER BY et_date DESC LIMIT 2` without calendar filter.

- MEASURED: 75 morning_full + 5 accrual rows on non-trading dates; live forces `newer_et_date=2026-08-02`.
- FIX: `is_trading_day_et` on both writers; trading-day filter on forces + ghost reads; DELETE stocked non-trading rows (left 0).
- TEST: `tests/test_rc193_morning_full_calendar_gate_v1.py` + accrual/morning_full suites — **43 passed** in batch with RC-191.

### F2 — PARTIAL → CLOSED (RC-165 restart)

Safe Sunday restart executed (killed stale uvicorn pid from 03:35, started current worktree). Live `HAS_60s_CADENCE=False`. Delivered-cycle unit path covered by staleness tests. Outside-window Sunday cannot show the DELIVERED sentence while not stale — that is not a product defect.

### F3 — Chart park overstated → CLOSED (RC-110/115/124/192)

Claude left an in-progress v6 build (`chart.html` mtime 09:28). Cursor finished/verified: candles/line, levels manager, prox, FIRED, forces strip, `/api/forces` live after restart, wall ranges + pin strength on wire, offScale/pinRow present. Tests: liquidity Chart v6 surface + terrain wall_range / pin suites.

### F4 — Monday clock-true residuals (honest PARTIAL/OPEN)

| id | status | UNBLOCKED-BY |
|---|---|---|
| RC-166 | PARTIAL | **2026-08-03 Monday** RTH — restart already done; `GET /api/diagnostics/sqlite-contention` under RTH load. `NEXT_RTH_PROOF 2026-08-03` |
| RC-180 | PARTIAL | **2026-08-03 Monday** — Desk F-10 / contention re-probe only. `NEXT_RTH_PROOF 2026-08-03` |
| RC-181 | OPEN | **2026-08-03 15:35 CT** — first `EdRthCompletenessCheck` fire |

Code readiness for Mon: RC-166 upsert incremental path already test-green historically; console now on post-fix worktree.

### F5 — UNPROVEN register

6 UNPROVEN remain. Dues 2026-08-02 are **not past due** until tomorrow (`due < today`). Cheap scorecard_history.jsonl lacks per-ticker-day range×regime rows for a fair perm test — left honest UNPROVEN (no fake PROVEN).

---

## D. Drift-audit checklist (explicit)

- [x] Arity/unpack — no signature changes to shared returns beyond calendar skip reasons
- [x] Presence vs capability — morning_full writers present but were not calendar-capable (F1)
- [x] Silent-swallow — forces/ghost no longer silently prefer weekend stock
- [x] Caller/consumer — Chart forces + ghost path updated with writers
- [x] Fail-closed — persist returns `non_trading_day` skip
- [x] Tests exercise path — RC-193 refuses Sunday/Saturday timestamps
- [x] Stale vs live — restarted console; openapi includes `/api/forces`
- [x] Gate strength — debt_clear proxy “bars=0 ⇒ Collect calendar clean” was weaker than continuum
- [x] Full-stack — bars + snapshots session labels were clean; chain banks were not
- [x] Side-channel — N/A
- [x] EXPLAIN — not used (small DISTINCT date deletes)
- [x] Classification-by-complement — non-trading via `is_trading_day_et`, not `weekday!=`
- [x] Patch/gate-relax — none; writers refuse, stock deleted

Completeness critic ask: “Did Collect calendar hygiene cover every chain bank?” → **No** until RC-193.

---

## E. After counts (exact parse)

| Surface | Count |
|---|---|
| RC CLOSED | **187** |
| RC PARTIAL | **2** (RC-166, RC-180) |
| RC OPEN | **1** (RC-181) |
| RC active | **3** |
| UNPROVEN | **6** (dues honest) |

---

## F. VERDICT

**VERDICT: PARTIAL**

- Debt-clear CLOSED set (58/102/107/117/168/177/178/191): **substantively PASS** after same-turn re-test.
- Audit found and **fixed** F1 (RC-193), finished Chart + RC-165.
- Remaining active debt is **only** honest Monday live proofs (166/180/181) + epistemic UNPROVEN accrual.

Named residue after this audit+fix: **RC-166, RC-180, RC-181** (Monday clocks only).

drift-audit run; findings: F1–F5; corrections: RC-193 + Chart/165 closes + DB quarantine; gate hardened: n (product fix > new gate; zero-debt §6).
