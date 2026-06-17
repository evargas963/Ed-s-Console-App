> **Classification:** Policy Specification | **Scope:** Technical documentation `docs/issue19_bar_rehydration_feasibility.md`.

# Issue 19 — Historical 1-minute bar source + rehydration feasibility

**Date:** 2026-04-03  
**Mode:** feasibility study only (no bulk rehydration executed in this pass).  
**Contract:** BAR_ANCHOR_V1 → authoritative series is `price_bars_1m` only (`horizon_outcomes.py`, prior audit).

---

## 1. Executive conclusion

1. **Required wall-clock span** for the audited `pin_neutral` cohort on `data/ed_console.db` is **fully quantified** from SQL: snapshot **`ts_utc`** runs **≈ 34.29 calendar days** before the **earliest** `price_bars_1m.bar_start_ts_utc` in the file, with **per-ticker** gaps **≈ 23–35 days** (or “no local rows” for four symbols). Forward labels need bars through **`max(ts_utc) + 3720 s`** (60-minute horizon + padding from `OUTCOME_BAR_SPECS`).

2. **Schwab Market Data `GET /marketdata/v1/pricehistory`** with **`frequencyType=minute`**, **`frequency=1`**, and **`startDate` / `endDate`** (epoch millis) **can return** large 1-minute candle sets covering the cohort’s start window. **Evidence:** live probes on this machine (authenticated token) returned **HTTP 200** and **tens of thousands** of candles for **every** ticker in the `pin_neutral` set, including **`$SPX`**, **`SPY`**, and symbols with **zero** existing `price_bars_1m` rows (**COP**, **KO**, **UUUU**, **VZ**). A probe anchored with `start_datetime ≈ cohort_min − 1 day` returned a **first candle before** `cohort_min` for **SPY**, supporting **anchor feasibility** after ingest.

3. **Caveat (not a failure):** `schwab_client.safe_get_price_history(..., period_days=…)` only maps **`period` up to 10 days** and is **not** sufficient for long backfill. **`polling_adapter.fetch_bars_via_schwab_for_session`** and raw **`Client.get_price_history(..., start_datetime=, end_datetime=)`** already show the **correct** integration shape for bounded windows.

4. **Alternatives in-repo:** **Polygon / Alpaca** are mentioned only as **adapter commentary** (`market_data_adapter.py`, `websocket_adapter.py`) — **no** working historical REST integration for 1m bars was found. **No alternative vendor is required** to close this gap **if** Schwab access remains available.

5. **`EdDB.upsert_1m_bars`** is **idempotent** (`ON CONFLICT DO UPDATE`), **60s** `bar_end = start + 60`, and compatible with Schwab candle `datetime` ms → seconds. **Operational requirement:** pass **`ticker` exactly as stored** on `snapshots` / `price_bars_1m` (e.g. **`$SPX`**); `upsert_1m_bars` applies **`.upper().strip()`** only and **does not** apply `ticker_storage_key` (so **`SPX`** would **not** merge with **`$SPX`**).

6. **Safe execution:** rehydration is **technically feasible** with integrity **provided** you **backup SQLite**, fetch with **explicit UTC windows**, **upsert** in batches if needed for memory, then run **`tools/bar_history_recovery_audit_v1.py`** and **`tools/repair_validation_counts_v1.py`** before **`pin_neutral_outcome_repair_v1.py`**.

---

## 2. Required historical range

### 2.1 Cohort definition (unchanged from repair audit)

- `zone = 'pin_neutral'`, `outcome_filled = 0`, `horizon_outcome_schema_version = 3`, `timeframe ∈ {'1m','5m'}`  
- On this DB: **797** rows, all **`5m`**.

### 2.2 Global bounds (from `data/ed_console.db`)

| Metric | Value (epoch sec) | Notes |
|--------|-------------------|--------|
| `cohort_min(ts_utc)` | **1771914627.43** | Earliest `pin_neutral` snapshot |
| `cohort_max(ts_utc)` | **1773509166.23** | Latest |
| `latest_required_coverage` | **1773512886.23** | `cohort_max + 3720` (60m horizon + pad) |
| `global_min(bar_start_ts_utc)` | **1774877460** | Earliest bar **start** in entire `price_bars_1m` |
| **Cohort-to-global-bar gap** | **2962833 s (~34.29 days)** | `global_min_start − cohort_min` |

### 2.3 REQUIRED RANGE table (per ticker)

Computed by **`python tools/issue19_rehydration_range_v1.py --db data/ed_console.db`** (also **`data/issue19_rehydration_range_last.json`**).

| ticker | n_snapshots | min_snapshot_ts | max_snapshot_ts | min_bar_start_in_db | gap (snapshot_min → min_bar_start) |
|--------|------------:|----------------:|----------------:|--------------------:|-----------------------------------:|
| $SPX | 183 | 1772974856.29 | 1773509166.23 | 1774963860 | **~23.02 d** |
| AMZN | 35 | 1772548543.13 | 1772553462.39 | 1774963860 | **~27.96 d** |
| COP | 1 | 1771915018.28 | 1771915018.28 | *(null)* | **~34.29 d** (to global min start) |
| KO | 1 | 1771914927.73 | 1771914927.73 | *(null)* | **~34.29 d** |
| META | 11 | 1771914627.43 | 1772554368.38 | 1774963860 | **~35.29 d** |
| MSFT | 21 | 1772548627.47 | 1772553367.44 | 1774963860 | **~27.95 d** |
| NVDA | 2 | 1771914654.07 | 1771914692.10 | 1774963860 | **~35.29 d** |
| SPY | 541 | 1771933501.07 | 1772156472.23 | 1774877460 | **~34.07 d** |
| UUUU | 1 | 1771915336.71 | 1771915336.71 | *(null)* | **~34.28 d** |
| VZ | 1 | 1771914954.05 | 1771914954.05 | *(null)* | **~34.29 d** |

**Interpretation:** `gap_*` here is the **calendar lag** between the **oldest** cohort snapshot and the **first stored 1m bar start** for that symbol (or global minimum if the symbol has **no** rows). It is a **proxy** for missing persisted history, not the literal count of missing minutes (sessions, halts, weekends).

**Earliest bar instant** needed for labeling: any bar with **`bar_end_ts_utc ≤ snapshot.ts_utc`**; in practice, continuous **1m** bars should cover **[~cohort_min − 1 trading session, cohort_max + 62m]** per ticker.

---

## 3. Schwab API feasibility

### 3.1 Code paths (repo)

| Location | Behavior |
|----------|----------|
| `schwab_client.safe_get_price_history` | `get_price_history` with **`periodType=day`**, `period` **1–10** only, `frequencyType=minute` | **Insufficient alone** for multi-week backfill |
| `polling_adapter.fetch_bars_via_schwab` | `period_days` 1–10 minute bars | Same limit |
| `polling_adapter.fetch_bars_via_schwab_for_session` | **`start_datetime` / `end_datetime`** + minute frequency | **Valid pattern** for windowed pulls |
| `schwab.client.base.Client.get_price_history` | Supports **`startDate`/`endDate` millis** without `period` | **Required for long ranges** |

### 3.2 Library / documentation signals (not Schwab legal SLA)

| Source | Statement |
|--------|-----------|
| **schwab-py** `Client.get_price_history_every_minute` docstring (`site-packages/schwab/client/base.py` L813–816) | “**currently appears to return up to 48 days** of data” |
| **schwab-py readthedocs** — Price History | Same “**up to 48 days**” for per-minute utility |

These are **third-party observations**, not a guarantee. **Live response size** must be validated per run.

### 3.3 Live probes (this workspace, authenticated)

**Script:** `tools/schwab_minute_history_probe_v1.py`

| Command | Result |
|---------|--------|
| `python tools/schwab_minute_history_probe_v1.py --symbol SPY --days-back 35` | **200 OK**, **34147** candles |
| `python tools/schwab_minute_history_probe_v1.py --symbol '$SPX' --days-back 35` | **200 OK**, **10279** candles |
| Custom `get_price_history(SPY, start_datetime=cohort_min−1d, end_datetime=now, minute)` | **200 OK**, **39485** candles; **first candle** at **2026-02-23 12:00 UTC** (**before** `cohort_min` **2026-02-24 06:30 UTC**) |
| Same pattern for **`$SPX`** | **200 OK**, **11927** candles; first **2026-02-23 14:30 UTC** |
| Same window for **COP, KO, UUUU, VZ** | **200 OK**; **16962 / 22852 / 19243 / 16201** candles |

### 3.4 SCHWAB FEASIBILITY table

| Parameter | Value | Source | Verdict |
|-----------|-------|--------|---------|
| Endpoint | `GET /marketdata/v1/pricehistory` | `schwab-py` `base.py` | **SUFFICIENT** |
| 1m granularity | `frequencyType=minute`, `frequency=1` | Code + probes | **SUFFICIENT** |
| Long-range query shape | `startDate`/`endDate` epoch ms, omit `period` | `get_price_history` implementation | **SUFFICIENT** |
| `periodType=day` + `period=10` cap in app wrapper | max **10 days** in `safe_get_price_history` | `schwab_client.py` L380–386 | **INSUFFICIENT** for backfill **if used alone** |
| Observed 1m depth (minute helper) | “**~48 days**” (observed) | schwab-py docs / docstring | **UNCERTAIN** as hard limit |
| **This DB cohort gap** | **~34.3 days** (global) | `issue19_rehydration_range_v1.py` | **Below** 48d observation |
| **Live coverage for all 10 tickers** | **200** + large `candles[]` | Probes 2026-04-03 | **SUFFICIENT** *for this environment* |

**Rate limits:** not measured in this pass. **UNCERTAIN** — throttle retries required in any production job.

---

## 4. Alternative authoritative sources (repo-only)

| Source | In codebase | 1m historical | Verdict |
|--------|-------------|---------------|---------|
| **Schwab** | Primary (`server`, `polling_adapter`, `schwab_client`) | **Proven** (probes) | **Primary** |
| **Polygon** | Name-only in `market_data_adapter.py` / `websocket_adapter.py` | **No** importer found | **Not integrated** |
| **Alpaca** | Name-only | **No** importer found | **Not integrated** |
| **snapshots / normalized** | Present | **Not valid** under BAR_ANCHOR_V1 | **Excluded** |

**ALTERNATIVE SOURCE REQUIRED:** **NO** (for this project state), unless Schwab access is lost or future probes fail.

---

## 5. Ingestion path validation (`EdDB.upsert_1m_bars`)

| Component | Role | Validated behavior | Risks | Verdict |
|-----------|------|--------------------|-------|---------|
| SQL | Persist 1m bars | `INSERT … ON CONFLICT(ticker, bar_start_ts_utc) DO UPDATE` | Very large `executemany` memory | **READY** (batch if needed) |
| Timestamps | Align to contract | `bar_end = bar_start + 60`; accepts Schwab ms or sec | Sub-second `ts_utc` vs bar grid | **READY** (same as live path) |
| Ticker | Key alignment | **`.upper().strip()` only** | **`SPX` vs `$SPX` split** | **NEEDS OPERATIONAL DISCIPLINE** (pass **`$SPX`**) |
| Source column | Audit | `AUTHORITATIVE_1M_SOURCE` | None | **READY** |
| Idempotency | Re-run safe | Upsert overwrites OHLCV | Last write wins if sources disagree | **READY** (single source per job) |

**Note:** A future improvement could call `ticker_storage_key` inside `upsert_1m_bars` for consistency with reads — **out of scope** for this feasibility doc; until then, **rehydration jobs must use canonical stored symbols**.

---

## 6. Rehydration plan (design only)

1. **Backup:** copy `data/ed_console.db` (same discipline as `pin_neutral_outcome_repair_v1` backups).
2. **Per ticker** in `per_ticker` JSON (or `snapshots` `DISTINCT ticker` for cohort):
   - `start_dt = utcfromtimestamp(min_snapshot_ts_utc − 86400)` (or wider session buffer).
   - `end_dt = utcfromtimestamp(max_snapshot_ts_utc + FORWARD_PAD)` with **`FORWARD_PAD ≥ 3720`** s.
3. **Fetch:** `client.get_price_history(symbol, period_type=None, period=None, frequency_type=MINUTE, frequency=EVERY_MINUTE, start_datetime=, end_datetime=, need_extended_hours_data=…)`.
4. **Normalize:** `market_data_adapter.schwab_candles_to_bars` or equivalent list of dicts with **`datetime` ms** + OHLCV.
5. **Ingest:** `EdDB.upsert_1m_bars(ticker, bars)` with **`ticker`** equal to **`snapshots.ticker`**.
6. **Chunking (if needed):** if a response is truncated or fails, split `[start,end]` into **non-overlapping** windows (e.g. 5–10 calendar days), upsert each; **`ON CONFLICT`** merges.
7. **Ordering:** SQLite PK `(ticker, bar_start_ts_utc)` — order of insert **irrelevant**.
8. **Failure / restart:** safe to rerun upsert for same window.
9. **Logging:** record per ticker `{http_status, n_candles, first_ms, last_ms, wall_time}`.
10. **Post-validation:** §7 — **only then** `python pin_neutral_outcome_repair_v1.py --db …`.

**Completion criteria:** for each ticker, `EXISTS` bar with `bar_end_ts_utc ≤ min_snapshot_ts` for that ticker’s cohort (see SQL in §7).

---

## 7. Validation before `pin_neutral` backfill

Run in order:

1. **`python tools/bar_history_recovery_audit_v1.py --db data/ed_console.db --json-out data/bar_history_recovery_audit_last.json`**  
   - Require **`pin_neutral_anchor_feasible_count` > 0** (target **797**).

2. **`python tools/repair_validation_counts_v1.py --db data/ed_console.db`**  
   - Same anchor-feasible SQL; human-readable.

3. **Spot SQL (per ticker):**

```sql
SELECT s.ticker, COUNT(*) AS n_need_anchor
FROM snapshots s
WHERE s.zone = 'pin_neutral' AND COALESCE(s.outcome_filled,0)=0
  AND NOT EXISTS (
    SELECT 1 FROM price_bars_1m b
    WHERE b.ticker = s.ticker AND b.bar_end_ts_utc <= s.ts_utc
  )
GROUP BY s.ticker;
```

Require **zero rows** or **0** total across groups.

4. **Forward coverage spot-check** (largest horizon 60m): for random `snapshot_id`, verify `close` exists at `forward_bar_start_utc(ts_utc, 60)` in `price_bars_1m` (scripted or ad hoc).

5. **Ticker identity:** `SELECT DISTINCT ticker FROM snapshots WHERE zone='pin_neutral'` should **match** keys used in `price_bars_1m` after upsert (no stray `SPX` vs `$SPX` duplicates for the same instrument).

6. **Then:** `python pin_neutral_outcome_repair_v1.py --db data/ed_console.db` (with backup).

---

## 8. Risks

| Risk | Mitigation |
|------|------------|
| Schwab truncates or changes limits | Log `n_candles` vs window; split windows; monitor HTTP 4xx/5xx |
| Rate limiting | Backoff, serial ticker pulls |
| Symbol-specific gaps (halts, illiquidity) | Post-SQL residual report per `snapshot_id` skip reason from repair audit |
| **Wrong ticker key** on upsert | Use **`snapshots.ticker`** verbatim |
| Source conflict if mixing vendors | **Do not** mix without versioned `source` policy |

---

## 9. Exact next actions

1. Implement a **dedicated rehydration script** (separate from `safe_get_price_history`) using **`start_datetime` / `end_datetime`** minute history.
2. **Backup** DB → run rehydration per §6 → run §7 validations.
3. Run **`pin_neutral_outcome_repair_v1.py`** → **`snapshot_normalizer.py`** if outcomes updated.
4. Archive probe logs + candle counts for audit trail.

### Commands to reproduce findings

```bash
python tools/issue19_rehydration_range_v1.py --db data/ed_console.db --json-out data/issue19_rehydration_range_last.json
python tools/bar_history_recovery_audit_v1.py --db data/ed_console.db --json-out data/bar_history_recovery_audit_last.json
python tools/schwab_minute_history_probe_v1.py --symbol SPY --days-back 35
python tools/schwab_minute_history_probe_v1.py --symbol '$SPX' --days-back 35
```

---

## Required closing lines

- REQUIRED HISTORICAL RANGE FULLY DEFINED: **YES**
- SCHWAB SUFFICIENT FOR FULL RECOVERY: **YES**
- ALTERNATIVE SOURCE REQUIRED: **NO**
- INGESTION PATH READY: **YES**
- REHYDRATION PLAN COMPLETE: **YES**
- SAFE TO EXECUTE BAR REHYDRATION: **YES**
- SAFE TO PROCEED TO CALIBRATION: **NO**
