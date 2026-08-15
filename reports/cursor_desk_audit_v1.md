# Cursor adversarial audit — Desk tab (`6c47b89b..1c1fad7e`)

**Auditor:** Cursor · **this turn** (full re-run on real `:8000`)  
**Branch:** `fp-institutional-repair-and-study4` @ `1c1fad7e` (not pushed)  
**Range:** 8 commits `6c47b89b..1c1fad7e` (git author `evarg`; Claude-authored content per operator)  
**Mode:** find / measure / report — **no fix, no push, no commit, no Decide touch**  
**Console:** `python -m uvicorn server:app --host 127.0.0.1 --port 8000` (real `server:app`, not a harness). `scratchpad/desk_verify_server.py` **does not exist** in this worktree. Process stopped after probes.

**Reproduce:**
```text
$env:PYTHONPATH=(Get-Location).Path
python scratchpad/_desk_audit_v1_full.py
# with console up:
python scratchpad/_desk_audit_v1_live.py
python -m pytest tests/test_desk_store_v1.py -q --tb=line
```

**STATUS: FAIL — bitemporality overstated on derived paths; ESTIMATED misused; weekend `is_rth_ts_utc` true (2/39 tests red); structure@60 ~5–6s not 1.75s; analytics/light ~0.1s not 8.7s; materialize lock_wait=0 on Saturday only.**

---

## Admission

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove / Collect — adversarial Desk verification |
| GAP | Claude Desk claims + 10 attacks unverified on real `server:app` `:8000` |
| SMALLEST_COMPLETE_CHANGE | This report only |
| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn command output per finding |
| DECISION_PATH_EFFECT | none |
| WHY_NOW | Operator ordered exact full re-audit |
| TASK_ADMISSION | ADMITTED — audit-only |

---

## Organising claims

| Claim | Verdict |
|---|---|
| `desk_facts` reads filter `knowledge_time_utc` | **CONFIRMED** (Radar / Brief / Evidence / ADV facts) |
| Every Desk number honours knowledge-time replay | **REFUTED** — spread / sigma / bootstrap use event-time columns |
| FINRA lag up to ~6 days | **CONFIRMED** — max lag measured **157.0 h** (~6.5 d) |
| Tiers; Book unbuilt; admissions empty; 0 PASS | **PARTIAL** — Book/admissions/0 PASS yes; capacity+bootstrap **ESTIMATED** without calibration → contradicts own tier law |
| Absence as absence; no fixtures; risk-neutral refused | **CONFIRMED** (SPY only as default ticker input) |

---

## Findings

| ID | Sev | Finding | Numeric / claim | Evidence |
|---|---|---|---|---|
| F-01 | **P0** | **Lookahead / bitemporality break.** `effective_spread_bps`, `daily_sigma_bps`, `_rth_log_returns` filter `ts_utc` / `bar_end_ts_utc <= as_of` only — zero `knowledge_time` in those functions. Live replay: at `as_of` 30d past, dossier `adv_dollar=None` but `spread_n=224`; structure bootstrap still `available` with `n_returns=5351`. Module replay at `2026-07-30 15:00 ET`: ADV facts 0, sigma 165.5, spread 225 quotes, bootstrap on. | **CONFIRMED** break of “reads filter on knowledge time” for Dossier/Structures derived fields | `_desk_audit_v1_full.py` + live `_desk_audit_v1_live.py` dossier_past / structure_past. `snapshots` has **no** knowledge/fetch/ingest column — only `ts_utc` (and friends). Justification “knowable when captured” is an assumption, not a second clock; backfilled bars with historical `bar_end_ts_utc` would be visible under replay. |
| F-02 | **P0** | **`is_rth_ts_utc` ignores the trading calendar.** Saturday `2026-08-01` and `2026-07-04`: `is_trading_day_et=False` but `is_rth_ts_utc(11:00 ET)=True`; `session_close_mins_for_et_date` returns `960` on Saturday. Desk ADV/sigma/bootstrap all use this. | **CONFIRMED** | full script weekend block output. |
| F-03 | **P0** | **2/39 desk tests FAIL** because F-02 injects a fake Saturday “RTH” stamp; incomplete-session drop removes the outlier → median test `1000000 != 1025000`; RTH-only test `KeyError: ZZZ`. | **CONFIRMED** `37 passed, 2 failed` | `pytest tests/test_desk_store_v1.py -q --tb=line` |
| F-04 | **P1** | **Tier self-contradiction.** Docs/UI: ESTIMATED = model with calibration record; UNPROVEN = without. Capacity `_IMPACT_COEFFICIENT=1.0` + bootstrap/POP labeled **ESTIMATED** with no calibration. Evidence scoreboard correctly uses `n_pass>0`. | Should be **UNPROVEN** | dossier_now `coefficient_Y=1.0` tier `ESTIMATED`; `desk_store.py` TIERS + lines 65–68, 848, 1044, 1121 vs Evidence 906–907; UI legend ESTIMATED/UNPROVEN. |
| F-05 | **P1** | **Bootstrap injects overnight jumps.** Adjacent RTH 1m closes across sessions enter `_rth_log_returns`. MSFT 5d: earnings overnight **+923.8 bp** (`gap_sec=64680`). Block=30, paths=4000, seed has no `as_of`. | **CONFIRMED** | full script `cross_session` + live structure `n_paths=4000` `block_bars=30`. |
| F-06 | **P1** | **MSFT σ=391.2 bp CONFIRMED; 13.88% earnings gap CONFIRMED; not RC-168 volume.** Close-to-close `2026-07-29→2026-07-30`: 396.16→451.13 = **+1299.4 bp / +13.88%**. Without that return: **181.8 bp**. Sigma does not use volume. | **CONFIRMED** 391.2 and 13.88%; RC-168 not the sigma cause | full script A5. |
| F-07 | **P1** | **`/api/desk/structure` @60 is not 1.75s; `/api/analytics/light` is not 8.7s median.** Live wall: structure@60 = **6.196 / 5.068 / 4.964 s**; light = **0.136 / 0.237 / 0.123 / 0.138 / 0.065 s** (median **0.136 s**). Structure is slower than light here, not faster. | **REFUTED** 1.75s; **REFUTED** light 8.7s | live script prints. |
| F-08 | **P2** | **Radar 12579/12617 CONFIRMED; “Candidates” still misleading.** `n_total=12617`, `n_structural=37`, `n_single_fact=12579`. Page of 60: 37 ADV + 22 FINRA-only. Coverage note present; header still `Candidates`. | **CONFIRMED** counts | full + live radar_now. |
| F-09 | **P2** | **Replay honesty mixed.** All listed read fns: `time.time()` count 0. Materialize uses wall clock for cutoff. Live: radar/evidence honour past; dossier ADV disappears on past but **spread remains**; structure bootstrap remains. Book = static “Not built”. | **PARTIAL** | full A2 + live subtabs. |
| F-10 | **P2** | **Contention: materialize ~55k while live logger → lock_wait Δ=0.** Wrote 48564+6595+37+39; `skipped_non_rth_bars=19103` of `source_rows=176924` (**CONFIRMED** RC-170 exclusion count); elapsed **16.62s**. `sqlite_lock_wait_*=0` before/after. **LIMIT: Saturday** — not an RTH proof against RC-166. | **OBSERVED** 0 wait; inconclusive for open market | live materialize + contention. |
| F-11 | **P3** | **`static/index.html` additive +1/−0 Desk link only.** | **CONFIRMED** | `git diff --numstat 6c47b89b..1c1fad7e -- static/index.html` → `1 0`. |
| F-12 | **P3** | **RC-168 numerics CONFIRMED; OPEN justified.** MSFT 2026-07-31: count 440, sum vol 719,750,531, max **25,118,525** exact, source `schwab_1m_accumulator_sqlite`. | **CONFIRMED** | full A5 SQL. |
| F-13 | **P3** | Admissions empty; PASS=0; Book Not built; risk-neutral refusal constant; desk.html no fixture tickers; `/desk` 200 on real console. | **CONFIRMED** | admissions_len 0; scoreboard PASS 0; desk_page 200. |
| F-14 | **P2** | **Test quality:** 39 tests; many `assert … in …` presence checks; RC-175 seed check uses AST (`as_of_utc` absent from seed — **CONFIRMED**). Suite **not green** (F-03). | **PARTIAL** | `n_tests 39`; pytest 2 fail. |
| F-15 | **P3** | **`desk_store.py` 1,274 lines CONFIRMED.** Approximate AST complexity of `dossier` ≈ **9** (not 18). Size is real surface area; not automatically “protected cruft,” but splitting is taste until a second consumer appears. Shape metrics track-only per RC-19 — not challenged as a gate failure. | **CONFIRMED** 1274 lines; **REFUTED** complexity-18 under this metric | `len(lines)=1274`; walk `dossier`. |
| F-16 | **P3** | **RC-164:** orphan `_chartCommitInflight` gone (0 live refs). CLOSED OK for that bug. Commit title “every enforced check … clean” **overstated** — Desk suite red this turn. | **CONFIRMED** fix; overstated cleanliness | live_refs 0; pytest red. |
| F-17 | **P2** | **RC-169 CLOSED row is internally confused.** Status CLOSED but Fix cell opens with “OPEN, no fix claimed. Not caused by and not repaired inside the Desk slice…” then “FIXED:…”. Commit `efb1470c` exists for the test pin. | **Overstated / messy ledger** | `RC169_fix_head` extract this turn. |

---

## RC-164 / RC-167..RC-175 verification

| RC | Ledger | Auditor | Overstated? |
|---|---|---|---|
| RC-164 | CLOSED | Orphan ref removed; row exists | Yes — “build clean” / enforced-check claim not true while desk tests fail |
| RC-167 | CLOSED | Cash-index exclude + median + suspect_sessions in code; materialize path present | Partially — encoding tests **FAIL** under weekend RTH bug (F-02/F-03) |
| RC-168 | OPEN | Volume blowup numerics **CONFIRMED**; not sigma cause | No — OPEN correct |
| RC-169 | CLOSED | Test-clock pin commit present | Yes — Fix cell leads with “OPEN, no fix claimed” while status CLOSED (F-17) |
| RC-170 | CLOSED | `skipped_non_rth_bars=19103` / `source_rows=176924` **CONFIRMED** on live materialize | Partially — filter uses broken weekend classifier |
| RC-171 | CLOSED | Sigma-driven capacity; POP outside→None path in code | Yes on tier — Y=1.0 as ESTIMATED without calibration (F-04); prior $5.6B defect not re-hit (fixed shape) |
| RC-172 | CLOSED | Evidence `as_of` refusal live; materialize POST; SQL reduction present | No material dispute this turn |
| RC-173 | CLOSED | Non-positive price refused; `session_is_complete` used | Partial — interacts with F-02 on weekends |
| RC-174 | CLOSED | Relative path; 37/12579/12617 **CONFIRMED** | Mild — “Candidates” header remains (F-08) |
| RC-175 | CLOSED | Seed has no `as_of_utc` (AST); SEQ/ARIA present in page | No material dispute; live p50 pair not re-timed |

---

## Attack-direction scorecard

| # | Attack | Result |
|---|---|---|
| 1 | Lookahead on spread/sigma/returns | **BROKEN** vs knowledge spine (F-01). Snapshots: no second clock column. |
| 2 | Replay / `time.time()` | Reads clean; materialize wall-clock; Dossier spread + Structures bootstrap **do not** fully retreat with slider (F-09) |
| 3 | Radar ADV / 12579 / Candidates | Counts **CONFIRMED**; header still misleading (F-08) |
| 4 | Capacity Y=1.0 ESTIMATED vs UNPROVEN | **UNPROVEN** by own law (F-04) |
| 5 | MSFT σ=391.2 / 13.88% gap | **CONFIRMED**; not RC-168 (F-06) |
| 6 | Bootstrap overnight | **CONFIRMED** jumps in series (F-05); block 30 / 4000 **CONFIRMED** |
| 7 | Contention materialize live | Ran on real `:8000`; **Δ lock_wait=0** Saturday (F-10) |
| 8 | structure 1.75s vs light 8.7s | **Both REFUTED** — structure ~5–6s; light median ~0.14s (F-07) |
| 9 | Additive index.html | **CONFIRMED** (F-11) |
| 10 | Test quality / docstring traps | 39 tests; RC-175 AST-aware; 2 FAIL; many substring `in` asserts (F-03/F-14) |

---

## Drift-audit (self)

1. **Intent:** Operator wanted measured adversarial audit on real console — not fixes.  
2. **Mechanical:** Live `:8000` health/logger, contention, structure, light, all Desk GETs, materialize POST, pytest, SQL.  
3. **Checklist:** presence≠capability (Candidates); silent tier mislabel; fail-closed Evidence/Book; tests red; weekend calendar; EXPLAIN not needed (no new multi-GB ad-hoc join invented).  
4. **Critic:** RTH-hour contention still unproven; snapshot backfill lookahead not proven with a concrete ingested_at lag row (schema has no such column).  
5. **Verdict:** FAIL.  
6–7. No fixes (hard stop).

**drift-audit run; findings F-01..F-17; corrections: none; gate hardened: n.**

---

## STATUS

`STATUS: FAIL — knowledge-time story false for spread/sigma/bootstrap; ESTIMATED mis-tiered; is_rth_ts_utc true on weekends (2 tests red); structure@60 ~5–6s (not 1.75s); analytics/light ~0.14s median (not 8.7s); radar 12579/12617 CONFIRMED; MSFT σ=391.2 + 13.88% gap CONFIRMED; bootstrap overnight jumps CONFIRMED; materialize 19103/176924 non-RTH skip CONFIRMED; lock_wait Δ=0 Saturday only; index.html additive; RC-168 OPEN numerics CONFIRMED; RC-169 Fix cell contradicts CLOSED.`
