> **Classification:** Policy Specification | **Scope:** Governance documentation `SCHWAB_REMEDIATION_GATE_FAIL_CLOSED_WORKING_SYNC_V1.md`.

# Schwab Remediation — GATE_FAIL_CLOSED WORKING Sync V1

**Status:** IMPLEMENTED (2026-05-08)  
**SYSTEM STATUS:** FAIL (residual queue reduced; not full closure)

---

## Scope

Forty rows in `SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_RESIDUAL.csv` had classification `DEFAULT_OR_DERIVATION_REVIEW` and disposition `GATE_FAIL_CLOSED_OR_PROVENANCE` (silent default / zero-fill on Schwab-backed fields).

**Production code on `main` already implemented fail-closed or non-degrading paths** for these sites (OHLC bar drop rules, spot validation, chain `underlyingPrice` error return, etc.). Evidence tests include:

- `tests/test_liquidity_engine.py` — `test_bars_normalization_drops_missing_ohlc_bar`, `test_schwab_candles_to_bars_drops_missing_ohlc_bar` (S003)
- `tests/test_spot_fail_closed_contract.py` — `engineer_single_snapshot` rejects null/zero spot

This batch **does not** use classifier disambiguation. It **syncs** `SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_WORKING.csv` to current source: strip `DEFAULT_ZERO_OR` / `GET_DEFAULT_ZERO` tags and refresh `code` (and relocate `server.py` underlyingPrice to the fail-closed line).

**Tool:** `tools/sync_schwab_gate_fail_closed_working_rows_v1.py` (reads current residual keys, then patches WORKING). Re-run `python tools/classify_schwab_csv_crosswalk.py` after sync.

---

## Commit lineage and scope clarification

Commit **`589d94c`** is a **register / `WORKING.csv` sync**, not a runtime gates batch.

The forty `GATE_FAIL_CLOSED_OR_PROVENANCE` rows it cleared from the manual residual queue were **stale mechanical references** against an earlier code state. The intended fail-closed behavior was **already shipped** in prior commits (e.g. **S002** volume, **S003** OHLCV, **S005** spot, **S006** OHLCV-related paths) and is verified by **existing** tests — notably `tests/test_liquidity_engine.py` and `tests/test_spot_fail_closed_contract.py`.

This batch:

- updated `SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_WORKING.csv` to reflect current code reality (line snippets refreshed; e.g. `server.py` `underlyingPrice` row relocated **6605 → 6738**);
- regenerated `CLASSIFIED` / `RESIDUAL` / `DISPOSITION_REGISTER` outputs;
- **did not** add new fail-closed branches in production `.py` files.

**For future readers:** residual-cell movement from **`589d94c`** is **register hygiene**, not equivalent to **slice-closure-cell** movement. The substantive fail-closed code work lives in the **cited prior slices** and their tests.

**Accounting:** treat cumulative residual reduction from this commit as **“closed via register/classifier sync,”** separately from residuals closed by **new production diffs** in the same conversation. That keeps the proof components honest when both appear on the scorecard.

---

## Explicit exclusions (no whitewash)

- **N7** — `mc_fusion_adjustment.py:29` (`volatility` default-zero) remains **`CSV_PRIMITIVE_RISK_REVIEW`**, **`REPLACE_WITH_SCHWAB_OR_GATE`**, **`manual_review_required=yes`**. It was **not** in the 40-row `DEFAULT_OR_DERIVATION` set and was not modified.

---

## Evidence (post-batch)

| Metric | Before | After |
|--------|--------|--------|
| Manual residual rows | 90 | **50** |
| Residual `DEFAULT_OR_DERIVATION_REVIEW` | 40 | **0** |
| Residual `GATE_FAIL_CLOSED_OR_PROVENANCE` | 40 | **0** |
| `NOT_MARKET_DATA` (classified) | 1908 | **1948** (+40 mechanical rows aligned with live fail-closed behavior) |

Remaining **50** residuals: **41** primitive-risk (includes N7), **9** spread/mid provenance.

---

## File:line keys (40) synced

Paired with `DEFAULT_OR_DERIVATION_REVIEW` rows in `CROSSWALK_RESIDUAL.csv` immediately before sync:

`call_engine.py:998`, `features/signal_layer_v1.py:57`, `features/signal_layer_v1.py:58`, `features/signal_layer_v1.py:144`, `features/signal_layer_v1.py:145`, `liquidity_value_engine.py:57–60,97–100,448,732,765,880,1065`, `lstm_data.py:168,187,188`, `market_context.py:634–637,679–681,883–886`, `market_data_adapter.py:105–108`, `ml_train.py:417`, `server.py:6605` (relocated to **`server.py:6738`** for `underlyingPrice` read), `signals.py:262,269`.

---

**Forward reference:** OHLCV / spot fail-closed behavior is governed under **S002–S006** slice family and the tests cited above; no new slice contract was required for this sync-only batch.
