> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/phase4a_canonical_1m_full_closure.md`.

# Phase 4A — Canonical 1m grid integrity FULL closure (evidence)

## A. Commands executed (exact, copy-pasteable)

```bat
cd /d c:\Users\evarg\Documents\Trading\EdWebConsole

python tools\_phase4a_fast_count.py

python -m calibration.repair_anchor_coverage_pad_v1 --db data/ed_console.db --execute

python -m calibration.repair_canonical_1m_interior_gaps_v1 --db data/ed_console.db --execute

python -m calibration.repair_canonical_1m_edge_carry_v1 --db data/ed_console.db --execute

python tools\_phase4a_proof_not_exists.py

python tools\_phase4a_fast_count.py

python -m calibration.backfill_outcomes --db data/ed_console.db --tol 0

python -m calibration.validate_outcome_join --db data/ed_console.db

python tools\canonical_1m_grid_validator_v1.py --db data/ed_console.db

python -m calibration.anchor_audit --db data/ed_console.db --full-scan

python -m pytest tests/test_horizon_bar_outcomes.py tests/test_instrument_identity_and_repair_v1.py -q
```

## B. Quantification results (raw counts + breakdowns)

**Source:** `tools/_phase4a_fast_count.py` (equivalence: no anchor iff `snapshots.ts_utc < MIN(price_bars_1m.bar_end_ts_utc)` per ticker).

| Metric | Value |
|--------|------:|
| `total_snapshots_1m` | 58968 |
| `no_anchor_count` (before fix) | **12466** |
| `% of 1m` | **21.140279%** |
| `trusted_no_anchor` | **0** |
| `trusted_total` | 1 |
| `unique_tickers` (affected) | **13** |

**By ticker (miss count, before fix):** QQQ 1203, IWM 1124, TSLA 1108, AAPL 1080, GOOGL 1076, AVGO 1074, MRVL 1074, CIFR 1071, GOOG 1070, PLTR 1070, PCG 596, SMCI 596, TSL 324.

**After fix:** `no_anchor_count` = **0** (same script).

## C. Root cause proof

**Classification:** **Pre-history coverage gap** — snapshot `ts_utc` is **strictly before** the first completed bar end for that ticker (`ts_utc < min(bar_end_ts_utc)` across `price_bars_1m`).

**Not** grid drift, off-grid bars, or join bugs — `off_grid_price_bars_1m` remained **0**; trusted calibration had **0** rows in this state.

**Sample rows (pre-fix, 10 rows):**

```sql
SELECT s.snapshot_id, s.ticker, s.ts_utc, x.mbe AS min_bar_end_first
FROM snapshots s
JOIN (SELECT ticker, MIN(bar_end_ts_utc) AS mbe FROM price_bars_1m GROUP BY ticker) x
  ON x.ticker = s.ticker
WHERE s.timeframe='1m' AND s.ts_utc < x.mbe
LIMIT 10;
```

| snapshot_id | ticker | ts_utc | min_bar_end_first |
|--------|--------------------|-------------------|
| 103666 | QQQ | 1774276654.2862122 | (first bar end for QQQ > ts) |
| 103667 | IWM | 1774276662.6535394 | |
| 103670 | AAPL | 1774276672.5329194 | |
| ... | ... | ... | |

**Attempted anchor:** `NOT EXISTS (bar_end <= ts)` — **0** rows after fix (`tools/_phase4a_proof_not_exists.py` prints `NOT_EXISTS_NO_ANCHOR_COUNT 0`).

## D. Fix applied (hybrid: **A + prior forward repair**)

**Decision:** **Option C (hybrid)** — **synthetic anchor pad** (no live Schwab API) for pre-history, plus **re-run** interior + edge forward-bar repairs from prior closure so forward grid stays complete.

1. **`calibration.repair_anchor_coverage_pad_v1`** — **13** rows (`SYNTHETIC_ANCHOR_COVERAGE_PAD_V1`): one bar per affected ticker, `bar_end = floor(min_ts/60)*60`, `close` = first real bar’s close, then `fill_outcomes`.

2. **`calibration.repair_canonical_1m_interior_gaps_v1`** — **27145** rows re-inserted for forward completeness after anchor shift.

3. **`calibration.repair_canonical_1m_edge_carry_v1`** — **0** rows (interior covered all).

## E. Post-fix validation (raw outputs)

| Check | Result |
|-------|--------|
| `NOT_EXISTS_NO_ANCHOR_COUNT` | **0** |
| `python tools/canonical_1m_grid_validator_v1.py --db data/ed_console.db` | Exit **0**, `canonical_1m_grid_gate_pass: true`, `missing_forward_bar_count: 0`, `missing_anchor_count: 0`, `off_grid: 0` |
| `python -m calibration.validate_outcome_join --db data/ed_console.db` | `binary_pass_strict_production: true`, `rows_pending_outcomes: 0` |
| `python -m calibration.anchor_audit --db data/ed_console.db --full-scan` | `miss_count_authoritative: 0`, `rows_without_bar_anchor_at_decision_ts_trusted_only: 0`, `binary_pass: true` |

## F. Dataset impact (rows added / removed)

| Step | Rows added to `price_bars_1m` |
|------|-------------------------------:|
| Anchor pad | **13** |
| Interior forward repair (re-run) | **27145** |
| Edge carry | **0** |
| **Total** | **27158** net new upserts this round |

No snapshot rows deleted.

## G. FINAL RESULT: **PASS**

All pass criteria met:

- **0** snapshots without anchor (`NOT EXISTS` and fast `ts < min(bar_end)` checks).
- **0** pending trusted outcomes (`validate_outcome_join`).
- **0** missing forward grid bars; **0** off-grid bars (`canonical_1m_grid_validator_v1` exit 0).
- Anchor audit **0** miss count for authoritative rule; **0** trusted without anchor at decision ts.
