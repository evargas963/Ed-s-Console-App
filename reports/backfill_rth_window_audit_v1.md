# Backfill RTH window audit v1

**Ordered by:** operator, 2026-08-01 — belief: backfill was only RTH 08:15–15:15 CT.
**Mission class:** Collect integrity / scope honesty (no Decide influence).
**Decision:** **WAIT** — no code patch this turn. The historical backfill path intentionally
requests extended hours; that is an intent mismatch vs the operator belief, not a one-line
wrong-constant typo. Fix requires operator GO on the desired window.

**OUT-OF-SCOPE:** Chart render / accrual banking (RC-163). This audit is `price_bars_1m`
backfill session scope only. `# spy-sample-ok:` SPY+MSFT are samples; universe totals are
enrolled-wide.

Measured 2026-08-01T21:21:52Z against `data/ed_console.db`.

---

## Plain answer

**No — we did not only backfill 08:15–15:15 CT.**

The enrolled 1m historical backfill asks Schwab for **extended-hours** candles
(`need_extended_hours_data=True`) over a **UTC calendar lookback**, then upserts every
parsed candle with **no** `[555,975]` filter, **no** `is_rth_ts_utc`, and **no**
`is_rth_trading_ts` gate.

On the last **46 trading days** (2026-05-27 → 2026-07-31):

| Scope | Count | Share |
|---|---:|---:|
| All bars on those ET trading dates | **1,603,255** | 100% |
| Inside 08:15–15:15 CT (`et_minute(bar_start) ∈ [555,975]`) | **813,194** | 50.72% |
| **Outside that window** | **790,061** | **49.28%** |
| Of which `source=schwab_pricehistory` outside | **778,103** | — |

Growth vs `reports/db_validity_audit_v1.md` baseline (same DB family, prior measure):

| Metric | Prior audit | Now | Δ |
|---|---:|---:|---:|
| `price_bars_1m` total | 1,484,957 | **2,537,437** | **+1,052,480** (~1.05M) |
| `source=schwab_pricehistory` | 3,854 | **1,489,121** | **+1,485,267** |

Claude’s ~1.05M new-row claim matches the **total** delta (exact `COUNT(*)` this turn).
Most of the new mass is `schwab_pricehistory`.

---

## 1. Tools, scheduler, config — what window each thing uses

### Historical bar backfill (the 46-day / vendor-floor machine)

| Piece | Path | Window |
|---|---|---|
| Tool | `tools/historical_backfill_enrolled_1m_v1.py` | UTC `now-lookback_days` → `now-90s`; default `--lookback-days 21` (CLI; not RTH-bounded) |
| Fetch | `bar_rehydration_issue19_v1._fetch_minute_window` | `need_extended_hours_data=True` |
| Parse | `market_data_adapter.schwab_candles_to_bars` | no session filter |
| Persist | `EdDB.upsert_1m_bars` | no session filter |
| Host schedule | `governance/host_scheduled_jobs.md` → `EdRthCompletenessCheck` | **not registered yet**; tool exists; on holes runs backfill with `--lookback-days 3` |
| Completeness checker | `tools/rth_completeness_check_v1.py` | classic **09:30–close ET** (`RTH_START_MINS=570`), calendar via `is_trading_day_et` |

Code (fetch — extended hours on):

```79:88:bar_rehydration_issue19_v1.py
            resp = client.get_price_history(
                symbol,
                period_type=None,
                period=None,
                frequency_type=PH.FrequencyType.MINUTE,
                frequency=PH.Frequency.EVERY_MINUTE,
                start_datetime=start_utc,
                end_datetime=end_utc,
                need_extended_hours_data=True,
            )
```

Code (backfill window = calendar days, not RTH):

```401:402:tools/historical_backfill_enrolled_1m_v1.py
    end_dt = datetime.now(timezone.utc) - timedelta(seconds=90)
    start_dt = end_dt - timedelta(days=max(1, lookback_days))
```

### Other “RTH” authorities (different questions — do not confuse)

| Authority | Meaning | Bounds |
|---|---|---|
| Collect / accrual mandate (operator) | 08:15–15:15 CT | ET minutes **[555, 975]** = 09:15–16:15 ET |
| `time_et.is_rth_ts_utc` | clock-only classic cash RTH | **09:30 ≤ t < 16:00 ET** (`RTH_START_MINS=570`, `RTH_END_MINS=960`) |
| `desk_store.is_rth_trading_ts` | clock ∧ calendar | `is_rth_ts_utc` ∧ `is_trading_day_et` |
| `time_et.is_tradable_session_ts_utc` | weekday ∧ holiday calendar ∧ RTH | 09:30–session close |
| Accrual writer start | `calibration/option_chain_morning_full.py` | `MORNING_START_MINS = 555` (09:15 ET); end constants differ (morning archive vs universal capture) |

**None of these gates are applied inside the historical 1m backfill upsert path.**

Preflight backups prove the tool ran on the canonical DB today (UTC):
`backups/db/20260801_185737_*`, `20260801_193121_*`, `20260801_193710_*`
(`operation_name=historical_backfill_enrolled_1m_v1`).

---

## 2. Same-turn DB measurements

Reproduce (scratchpad one-shot used this turn):

```bash
.venv/Scripts/python.exe scratchpad/_backfill_rth_window_audit_v1.py
# writes scratchpad/_backfill_rth_window_audit_v1.json
```

Equivalent SQL skeleton (ET classification needs Python/`time_et` because SQLite has no
America/New_York authority):

```sql
-- totals / growth proxy
SELECT COUNT(*) FROM price_bars_1m;
SELECT source, COUNT(*) FROM price_bars_1m GROUP BY source ORDER BY COUNT(*) DESC;
```

### Outside-window leak breakdown (46 trading days, all tickers)

Definition: `et_minute(bar_start)` **not** in `[555,975]`.

| Bucket | Bars |
|---|---:|
| Premarket earlier than 08:15 CT (04:00–09:14 ET, excl. overnight label) | **256,549** |
| After 15:15 CT (16:16+ ET) | **338,631** |
| Overnight 00:00–03:59 ET | **194,881** |
| **Total outside** | **790,061** |

Also within the calendar span 2026-05-27..2026-07-31 but on **non-trading** ET dates:
**63,817** bars (`schwab_pricehistory` 41,403 + synthetic repair 22,414) — weekends/holidays
leaked into the table alongside the trading-day extended-hours mass.

### Sample tickers (SPY, MSFT) — same 46 trading days

| Ticker | Bars | Inside 08:15–15:15 CT | Outside | Outside buckets (pre / after / overnight) |
|---|---:|---:|---:|---|
| SPY | 56,323 | 19,298 | **37,025** | 11,709 / 16,691 / 8,625 |
| MSFT | 45,072 | 18,942 | **26,130** | 8,620 / 11,163 / 6,347 |

SPY `by_et_hour` is roughly flat ~2.0–2.7k bars/hour across **all 24 ET hours** — proof the
backfill (and prior live accumulator) banked a near-continuous extended session, not a
cash/accrual window.

### Classic cash RTH vs accrual window (same 46-day set)

| Slice | Bars |
|---|---:|
| Classic 09:30–16:00 ET | 775,292 |
| Premarket accrual slice 09:15–09:29 ET | 18,039 |
| Post-cash accrual slice 16:00–16:15 ET | 19,863 |
| Outside accrual 08:15–15:15 CT | 790,061 |

---

## 3. Operator plain English

1. **What the backfill actually uses:** Schwab minute history with **extended hours on**, over
   a **multi-day UTC lookback**, upserting everything returned. Not 08:15–15:15 CT. Not
   classic 09:30–16:00 ET.
2. **Match to 08:15–15:15 CT intent?** **No.** About **half** of bars on the last 46 trading
   days sit outside that window; among `schwab_pricehistory` alone on those days, **778,103 /
   1,447,718 (53.7%)** are outside.
3. **What leaked:** premarket before 08:15 CT, post-15:15 CT / evening session, overnight
   minutes, and additional rows on non-trading dates inside the calendar span.
4. **Is this a clear wrong-window bug?** **High confidence the code does what it says**
   (`need_extended_hours_data=True`, no filter). That is a **product/intent mismatch** with
   the operator’s belief, not an accidental `570` vs `555` typo. **No patch without GO.**

If GO is “accrual window only,” smallest honest patch direction (not applied):
filter bars after `schwab_candles_to_bars` (or before upsert) to
`555 <= et_minute(bar_start) <= 975` and `is_trading_day_et`, and set
`need_extended_hours_data` only if the desired window needs pre/post cash (09:15–09:29 and
16:00–16:15 still need extended=True relative to cash open/close). If GO is “classic cash
RTH only,” use `is_rth_trading_ts` / `[570,960)` instead — that is a **different** product
choice from 08:15–15:15 CT.

---

## 4. Hole census status

| Artifact | Status |
|---|---|
| Full-DB RTH hole census vs session grid | **Exists** in `reports/db_validity_audit_v1.md` (99,381 true holes; 49,478 recoverable ≥ vendor floor 2026-06-17 as of that measure) |
| Post-RTH mechanical checker | **`tools/rth_completeness_check_v1.py`** (RC-181); uses **09:30–close**, not [555,975] |
| Host task `EdRthCompletenessCheck` | Documented in `governance/host_scheduled_jobs.md`; **operator must register** (not yet in the verified task table) |
| Vendor reconcile | Built into checker `--backfill` path (`vendor_reconcile`); distinguishes LOST vs VENDOR_EMPTY |

Cheapest same-turn run (no Schwab calls):

```bash
.venv/Scripts/python.exe tools/rth_completeness_check_v1.py --db data/ed_console.db --date 2026-07-31
```

**Result this turn:** `HOLES`, `total_missing=2123`, `tickers_with_holes=13`,
worst sample: `$TNX/RTY/SATS/XXT` 390 each, `PSCI` 387, `TSL` 98, `FN` 34, …
(grid shortfall — many thin/index symbols are VENDOR_EMPTY until `--backfill` reconcile).

Full 46-day hole census vs vendor floor was **not** re-run this turn (expensive: per-ticker
Schwab calls × days). Prior authoritative numbers remain in `db_validity_audit_v1.md`.
After the large extended-hours land, a **fresh** enrolled×day RTH-grid census is still
needed before claiming holes closed — extended-hours rows do not fill 09:30–16:00 holes by
definition, but the new `schwab_pricehistory` mass likely closed many cash-session gaps;
that claim is **[UNVERIFIED]** until the census is re-run.

---

## 5. Decision / status

**DECISION_PATH_EFFECT:** none (Collect scope audit only; admissions untouched).
**WHY_NOW:** operator priority on DB + backfill scope after ~1.05M row growth.
**TASK_ADMISSION:** investigate + report; patch only on high-confidence wrong-window bug —
not met → **WAIT**.

`CLAIM:` backfill is extended-hours / all-session, not 08:15–15:15 CT; +1,052,480 total bars
vs prior audit; 790,061 / 1,603,255 bars on last 46 trading days outside that window ·
`DONE:` window audit report + SQL/script evidence ·
`NEXT:` operator GO — (A) leave extended as-is, (B) filter future backfills to [555,975],
(C) filter to classic 09:30–16:00, and/or (D) quarantine already-landed outside-window rows ·
`BLOCKER:` operator window choice; host registration of `EdRthCompletenessCheck`; optional
full hole re-census vs vendor after GO

---

# EXTENSION v2 — Claude, 2026-08-01: law encoded, leak stopped, census re-measured (RC-183)

**Operator ruling received (non-negotiable):** the window is **(B)** — 08:15–15:15 CT,
ET bar-end minutes `(555, min(975, cash_close+15)]`, trading days only.

## Full-table census (exact, this turn, whole `price_bars_1m` — not just 46 days)

| Class | Rows | % |
|---|---|---|
| Total | 2,537,437 | — |
| IN window | 1,313,067 | 51.75% |
| PRE-window (trading day, ≤09:15 ET end) | 621,573 | 24.50% |
| POST-window (trading day, >16:15 ET end) | 473,216 | 18.65% |
| Non-trading day | 129,581 | 5.11% |
| **TOTAL OUTSIDE LAW** | **1,224,370** | **48.25%** |

Outside rows with volume>0: 1,104,087. By writer (top): backfill `schwab_pricehistory`
820,531 · live `schwab_1m_accumulator_sqlite` 315,660 (the live writers used a wider window —
the three-laws conflict is CONFIRMED by count) · synthetics 88,171.

## The lock (mandate-to-mechanism, shipped this turn)

1. **Authority:** `time_et.COLLECT_WINDOW_START_MINS=555` / `COLLECT_WINDOW_END_MINS=975` /
   `collect_window_end_mins_for_et_date` (early close = cash close + 15) /
   `is_collect_window_bar_end_ts_utc` (calendar AND clock).
2. **Seam:** `EdDB.upsert_1m_bars` gates every bar; rejections are counted and logged. Every
   writer — live accumulator, backfill, future tools — flows through this one seam, so callers
   need no changes and cannot disagree again.
3. **Grid:** `tools/rth_completeness_check_v1.py` now measures the SAME window (420
   expected minutes/full day).
4. **Institutional check:** `collect_window_single_law` (ENFORCED) — authority present, seam
   gated, and no direct `INSERT INTO price_bars_1m` outside `db.py` (five legacy bypass sites
   found and FROZEN with `collect-window-ok` annotations naming RC-183; routing them through
   the seam is the named next depth).
5. **Blocking proof:** `tests/test_collect_window_law_v1.py` — a 7-bar mixed batch through the
   REAL seam lands exactly the 3 legal bars; stripping the gate makes the institutional check
   scream. 72 tests green across affected suites.

## In-window hole census (law grid, last 46 trading days)

Expected 861,420 window-minutes · present 812,052 (**94.27%**) · grid-missing 49,368 —
of which **34,957 recoverable** (≥ vendor floor 2026-06-17) and 14,411 past the floor.
LOST-vs-VENDOR_EMPTY split runs through `vendor_reconcile` per-day (scheduled tool + Monday).

## Stocked outside-law rows — DISPOSITION REQUIRED (STOPPED, awaiting operator GO)

1,224,370 rows. Options: **(Q) quarantine-move to `price_bars_1m_quarantine`** (recommended —
reversible, table becomes law-clean, stewardship preserved) · **(D) delete** (only with
explicit GO) · **(K) keep-but-tag** (every session-blind reader keeps seeing them; the reader
class RC-58/61 exists because that fails). No destructive action taken this turn.

---

# EXTENSION v3 — EXECUTED (operator GO quarantine, 2026-08-02)

Operator chose **(Q)**, with their own checkpoint wording honoured in full:

| Step | Result |
|---|---|
| Fresh backup | `backups/db/20260802_quarantine_pre_ed_console.db` — 25,516,105,728 bytes + manifest |
| Dry-run | `outside_law_rows: 1,224,370` — EXACTLY the approved number (gate armed with `--expected`) |
| Execute | moved 1,224,370 → `price_bars_1m_quarantine` (reason-stamped, timestamped) |
| Same-run proof | `canonical_outside_law_after: 0` · canonical rows 1,313,067 = census IN_WINDOW exactly |
| Reversibility | `--restore` is the exact inverse, fixture-proven (move out, move back, counts equal) |
| Deleted | **nothing** |
| Re-proof | fresh dry-run after the move: `outside_law_rows: 0, total_rows: 1,313,067` |

Bypass writers dispositioned: 3 ROUTED at source through `is_collect_window_bar_end_ts_utc`
(shared repair conduit, anchor-proof builder, accumulation-validation harness), 1 TRULY
DISABLED (`repair_canonical_1m_bars_for_outcomes` — prev-close carry fabricator, RC-177 class;
no fabricated bars at all, not fabrication confined to legal hours), 1 exempt (research
scratch-db copier, isolated DB). `collect_window_single_law`: 0 violations. Suites: 75 passed.

Tooling defects caught before the real move (fixtures + first invocation): SQLite bound-
parameter ceiling ("too many SQL variables") and the stdlib driver's implicit transaction
("cannot start a transaction within a transaction") — both fixed via TEMP-table staging and
explicit autocommit; the real move ran as ONE verified transaction.

Uncommitted per operator instruction ("No commit unless I say commit").
