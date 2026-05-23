> **Classification:** Historical Record | **Scope:** Root point-in-time audit `SNAPSHOT_DATA_AUDIT.md`; not binding unless ACTIVE_PROGRAM cites.

# Snapshot Data Audit — Factual Findings

## 1. Exact Snapshot Write Cadence (from code)

**Source:** `server.py` lines 543-544, 704-755

| Constant | Value | Role |
|----------|-------|------|
| `LOG_INTERVAL` | 30 seconds | Background logger cycle |
| `STAGGER_SECS` | 2.0 seconds | Delay between each ticker in a cycle |

**Write path:**
1. `_logger_loop()` runs in a daemon thread
2. Every `LOG_INTERVAL` (30s), it iterates over all tracked tickers (12 core + any added)
3. For each ticker, `_logger_fetch_and_log(ticker)` → `_fetch_state(ticker, log_only=True)`
4. Inside `_fetch_state`, when `_ed_db` exists: `_ed_db.insert_snapshot(_snap)` (line 2049)
5. **Dedup:** If the UI fetched this ticker in the last 30s, the logger skips (avoids duplicate)

**Effective cadence per ticker:**
- Logger cycle: ~30s
- 12 tickers × 2s stagger ≈ 24s for a full cycle
- Each ticker gets **~1 snapshot per 30 seconds** when it is that ticker's turn
- UI fetches also write snapshots; logger skips when UI recently fetched

**Conclusion:** Snapshots are written every **~20–35 seconds** per ticker, not every 5 minutes.

---

## 2. Exact Meaning of Snapshot OHLC Fields (from code)

**Source:** `server.py` lines 1718-1726

```python
# Candle OHLC from canonical (1m) accumulator's current bar
_cur_bar = _candles_1m._current.get(ticker)
_c_open  = _cur_bar["o"] if _cur_bar else None
_c_high  = _cur_bar["h"] if _cur_bar else None
_c_low   = _cur_bar["l"] if _cur_bar else None
_c_close = _cur_bar["c"] if _cur_bar else None
```

**Accumulator behavior** (`_CandleAccumulator`, lines 348-406):
- `_current` holds the **in-progress** bar: `{ts, o, h, l, c, v}`
- On each `tick()`: if still in same bar (same `bar_ts`), **update** h, l, c, v
- When bar boundary crosses: **close** previous bar, **start new** bar with o=h=l=c=price

**OHLC semantics:**

| Field | Meaning |
|-------|---------|
| `candle_open` | Open of the **current in-progress bar** (fixed until bar closes) |
| `candle_high` | Running high within that bar (evolves with each tick) |
| `candle_low` | Running low within that bar |
| `candle_close` | Latest close = current spot (evolves) |
| `candle_volume` | Volume delta accumulated for that bar (or from price history) |

**Bar length:** `_candles_1m` uses `CANDLE_1M_SECONDS = 60` (line 304). So OHLC reflects an **in-progress 1-minute bar**.

**Note:** The DB rows labeled `timeframe='5m'` were written when `CANONICAL_TIMEFRAME` was `"5m"` (pre-migration). The migration changed the OHLC source to `_candles_1m`. If the server was running a mix (1m OHLC + 5m timeframe label), the OHLC semantics are 1m; the column was simply mislabeled.

---

## 3. SQL / Data Verification Results

**DB:** `data/ed_console.db`  
**Tickers:** SPY, QQQ, IWM  
**Filter:** `timeframe='5m'` (all current rows)

### A. Timestamp Spacing (consecutive rows)

| Ticker | Rows | Avg gap | Min gap | Max gap |
|--------|------|---------|---------|---------|
| SPY | 25,706 | 82.0 sec | 0 sec | 147,687 sec |
| QQQ | 10,456 | 190.5 sec | 0 sec | 157,547 sec |
| IWM | 10,137 | 196.7 sec | 0 sec | 157,535 sec |

*(Max gaps are overnight/session breaks.)*

### B. Rows per Minute

| Ticker | Minutes with data | Avg rows/min | Min | Max |
|--------|-------------------|--------------|-----|-----|
| SPY | 12,448 | 2.1 | 1 | 6 |
| QQQ | 6,412 | 1.6 | 1 | 5 |
| IWM | 6,344 | 1.6 | 1 | 5 |

**Interpretation:** ~2 snapshots per minute. True 5m bars would be 0.2 rows/min.

### C. Intrabar Behavior (sample — QQQ)

```
ts_et                     gap     open     high      low    close
2026-02-25 09:31:02 ET     0s   612.31   612.79   612.31   612.63
2026-02-25 09:31:36 ET    33s   612.31   612.79   612.31   612.63   <- same bar
2026-02-25 09:31:37 ET     1s   612.31   612.79   612.31   612.63   <- same bar
2026-02-25 09:33:44 ET   127s   612.31   612.79   612.26   612.75   <- high/low evolved
2026-02-25 09:34:38 ET    54s   612.75   613.08   612.47   612.56   <- NEW BAR (open changed)
2026-02-25 09:35:38 ET    60s   612.55   613.02   612.44   612.70   <- NEW BAR
2026-02-25 09:36:39 ET    60s   612.69   613.15   612.52   613.09   <- NEW BAR
```

- Within a bar: open fixed; high/low/close evolve.
- New bar: open changes; intervals ~54–66 sec.

### D. Reset Cadence (in-session only, gap < 10 min)

| Ticker | Bar boundaries | Avg interval | Min | Max |
|--------|----------------|--------------|-----|-----|
| SPY | 4,958 | 31 sec | 0s | 572s |
| QQQ | 4,226 | 49 sec | 0s | 594s |
| IWM | 4,205 | 49 sec | 0s | 565s |

**Interpretation:** Open resets every ~30–60 seconds. That matches **1-minute bar** boundaries, not 5-minute.

---

## 4. Final Classification of Current Snapshots Table

| Aspect | Finding |
|--------|---------|
| **Write cadence** | ~1 snapshot per ticker every 20–35 seconds |
| **OHLC source** | In-progress bar from `_candles_1m` (current code) |
| **Bar length** | 60 seconds (1m) |
| **timeframe column** | `5m` (legacy label, does not match OHLC) |

**Classification:** **Sub-minute snapshots of an in-progress 1-minute bar** (or 5-minute bar for data written before OHLC migration), stored with `timeframe='5m'`.

Evidence from data:
- Rows/min ≈ 2 (not 0.2 for true 5m bars)
- Open resets every ~30–60 sec (1m cadence)
- Consecutive rows show same open, evolving high/low/close

---

## 5. Can Current Data Be Normalized into a Usable 1-Minute Sampled Dataset?

### Option A: Keep as 5m

- **No.** The data is not true 5m bars: too many rows and ~60s reset cadence.

### Option B: Resample into 1-minute sampled rows

**Feasible, with caveats.**

1. **Bar boundaries:** Group by 1m bar (e.g. `ts_utc // 60` or `bar_start`).
2. **Per-bar semantics:**
   - **Real:** Multiple snapshots per bar give evolving high/low/close.
   - **Synthetic:** For a “1m sampled” row, take the **last snapshot** in that minute as the bar’s close; open = first snapshot’s open (or prior bar’s close); high/low = max/min over snapshots in that minute.
3. **Volume:** `candle_volume` is bar-level (accumulated). Use the last snapshot’s volume for that bar, or sum if recorded as deltas.
4. **Other snapshot fields:** Greeks, zone, etc. — choose last snapshot in the minute for a “1m sampled” row.

**What is real vs synthetic:**
- **Real:** Price OHLC and timing from actual snapshots.
- **Synthetic:** The 1m bar construct (open/high/low/close) is inferred by resampling; it matches standard 1m bar semantics if the first and last snapshots in each minute are correct.

**Limitations:**
- Gaps (e.g. no data for a minute) leave that bar missing.
- Minutes with a single snapshot: open=high=low=close for that bar.

---

## 6. Exact Recommendation

**Use a hybrid plan:**

1. **Treat existing `timeframe='5m'` rows as sub-minute snapshots of 1m-style bars:**
   - Keep them.
   - Resample into 1m bars when training or analyzing.
   - Document clearly that `timeframe='5m'` is a legacy label and that bar semantics are ~1m.

2. **Going forward:**
   - `db.insert_snapshot` enforces `timeframe='1m'`.
   - New rows are canonical 1m.

3. **Do not:**
   - Use the existing data as true 5m bars.
   - Assume OHLC are completed candles; they are in-progress bar snapshots.

4. **Add a resampling utility** that:
   - Groups existing snapshots by 1m bar
   - Produces one row per ticker per minute with proper open/high/low/close
   - Can be used by ml_train / lstm_data for training on 1m semantics

---

## 7. Closure Result

| Question | Answer |
|----------|--------|
| Write cadence verified? | Yes — ~30s per ticker from code and ~2 rows/min from DB |
| OHLC meaning verified? | Yes — in-progress bar (1m in current code) from `_candles_1m._current` |
| Data classification verified? | Yes — sub-minute snapshots of 1m-style bars, mislabeled 5m |
| 1m resampling possible? | Yes — with clear real vs synthetic semantics |
| Ambiguity remaining? | No — code path and DB evidence align |

---

## 8. Normalization Implementation (Production)

### 8.1 Design

**Module:** `snapshot_normalizer.py`  
**Table:** `snapshots_1m_normalized` (same schema as snapshots + `normalized_from_subminute`)

**Input:** Rows from `snapshots` with `timeframe='5m'` (sub-minute snapshots)  
**Output:** One row per ticker per minute in `snapshots_1m_normalized` with `timeframe='1m'`

**Semantics:** Do NOT call these native exchange 1m candles. They are **normalized 1m sampled rows from sub-minute snapshots**.

### 8.2 Transformation Rules

| Field | Rule |
|-------|------|
| **Grouping** | `minute_bucket = int(ts_utc // 60)`; one row per `(ticker, minute_bucket)` |
| **open** | First snapshot's `candle_open`, or `spot` if null |
| **high** | `max(candle_high)` over bucket; fallback `max(spot)` |
| **low** | `min(candle_low)` over bucket; fallback `min(spot)` |
| **close** | Last snapshot's `candle_close` or `spot` |
| **volume** | Last snapshot's `candle_volume` (accumulated bar volume) |
| **timestamp** | Last snapshot's `ts_utc`, `ts_et` (bar close) |
| **candle_body_pts** | `abs(close - open)` (recomputed from normalized OHLC) |
| **candle_range_pts** | `high - low` (recomputed) |
| **candle_direction** | `'up'|'down'|'flat'` from close vs open |
| **State fields** | Zone, net_gamma, vwap_side, etc.: from **last** snapshot |
| **Outcomes** | outcome_1c, outcome_3c, etc.: from **last** snapshot |

### 8.3 What Is Real vs Derived

- **Real:** Price OHLC from actual snapshot observations; timestamps; state copied from last snapshot.
- **Derived:** The 1m bar construct (open/high/low/close aggregation); candle_body_pts; candle_range_pts; candle_direction.

### 8.4 Where Normalized Data Lives

**New table:** `snapshots_1m_normalized` in the same DB. Created by `db.EdDB._ensure_normalized_table()` on schema init.

**Materialization:** `python snapshot_normalizer.py` — clears and repopulates the table from raw 5m rows.

### 8.5 Validation

- One row per ticker per minute (no duplicate minute buckets)
- Timestamp ordering preserved per ticker
- No duplicate outputs per minute bucket
- Row counts: raw vs normalized logged; per-ticker counts reported

### 8.6 Training Pipeline Integration

- `ml_train.load_data()` reads from `snapshots_1m_normalized` only (never raw 5m)
- `lstm_data.extract_rth_snapshots()` and `build_lstm_dataset()` use `snapshots_1m_normalized` for 1m
- Raw `timeframe='5m'` rows are never used for training

### 8.7 Storage Recommendation

**Use a new table (implemented).**  
- Persisted in same DB; deterministic; no silent mixing with raw rows  
- Alternative: cache to disk parquet — adds complexity; current table approach is sufficient  
- On-demand: possible but slower for training; materialization is preferred

### 8.8 Closure Audit Result

| Check | Result |
|-------|--------|
| Enough valid 1m training history? | Yes — ~70k normalized rows across tickers |
| Estimated 1m row counts (core tickers) | SPY 12,448; QQQ 6,412; IWM 6,344; others 1,800–4,300 |
| Retraining can proceed? | Yes — after running `python snapshot_normalizer.py` |

### 8.9 Execution Sequence (Normalize → Retrain → Verify)

**Order:**
1. **Materialize** — populate `snapshots_1m_normalized` from raw sub-minute snapshots  
2. **Verify normalized counts** — run validation  
3. **Retrain** — train active models under the governed pipeline  
4. **Verify compliance** — confirm active artifacts are compliant  

**Exact commands:**
```bat
:: 1. Materialize normalized 1m data (clears + repopulates table)
python snapshot_normalizer.py

:: 2. Verify normalized counts (validation is included in step 1; standalone check)
python snapshot_normalizer.py --validate

:: 3. Retrain active models (XGB+LSTM+Transformer+Meta)
python train_all.py --db data\ed_console.db

:: Or: scheduler-style parallel/cascade per ticker
python ml_scheduler.py

:: 4. Verify active model compliance
python verify_active_models.py
```

**One-liner (PowerShell):**
```
python snapshot_normalizer.py; python snapshot_normalizer.py --validate; python train_all.py --db data\ed_console.db; python verify_active_models.py
```

### 8.10 Closure Audit (Follow-up Cleanup)

| Check | Result |
|-------|--------|
| train_compare.py | ✓ Uses snapshots_1m_normalized |
| transformer_train.py | ✓ Ticker discovery uses SNAPSHOT_TABLE_1M for 1m |
| train_all.py | ✓ Ticker discovery + _HistoricalDB use normalized |
| ml_scheduler | ✓ _get_tickers_with_rth_data, _load_rth_rows_for_ticker use normalized |
| audit_training_data, audit_gate_labels | Explicitly marked as raw-snapshot audits |
| Raw-snapshot training paths | **None** — all training reads from snapshots_1m_normalized |
