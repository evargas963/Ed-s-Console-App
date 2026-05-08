# Schwab Remediation Slice Plan V1

**Status:** System FAIL - closure roadmap active  
**Date:** 2026-05-07  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv`  
**Input artifacts:**

```text
governance/SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_V1.md
governance/SCHWAB_CSV_DERIVED_FIELD_DISPOSITION_REGISTER.csv
governance/SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_RESIDUAL.csv
tools/check_schwab_csv_first.py --whole-repo
```

---

## System Status

```text
SLICE STATUS: clustering produced
SYSTEM STATUS: FAIL
remediation_slices_identified = 38
real_residuals_clustered = 998
manual_residual_rows_current_artifact = 313
whole_repo_guard_status = FAIL
```

The current repo is not Schwab-field clean. The CSV-first guard protects future changes, but existing code still contains risky patterns that must be remediated or explicitly governed.

---

## Severity Summary

| Severity | Slices | Instances |
|---|---:|---:|
| HIGH | 12 | 135 |
| MEDIUM | 15 | 761 |
| LOW | 11 | 102 |

Natural mergers reduce the HIGH slice count from 12 to 9 effective scopes:

```text
S003 + S006 = OHLCV zero/default remediation
S002 + S007 = volume zero/default remediation
S010 + S011 = Greeks zero/default remediation
```

---

## High Priority Slices

| ID | Risk pattern x field | Instances | Files | Top files | Recommended action | Schwab CSV authority |
|---|---|---:|---:|---|---|---|
| S001 | `DATE_DIFF_DTE` x `days_to_expiration` | 42 | 13 | `market_state.py` (9), `math_exposure_core.py` (6), `server.py` (5), `v2_decision/a2_option_expression.py` (4) | `REPLACE_WITH_SCHWAB` | `chains.callExpDateMap.*.daysToExpiration`, `chains.putExpDateMap.*.daysToExpiration` |
| S002 | `DEFAULT_ZERO_OR` x `volume` | 23 | 10 | `liquidity_value_engine.py` (4), `order_flow_engine.py` (4), `math_exposure_core.py` (3), `features/signal_layer_v1.py` (3) | `GATE_FAIL_CLOSED` on missing volume | `quotes.quote.totalVolume`, `chains.*.totalVolume`, `pricehistory.candles.*.volume`, `streaming.content.*.VOLUME` |
| S003 | `DEFAULT_ZERO_OR` x `ohlcv` | 19 | 4 | `market_context.py` (7), `market_data_adapter.py` (4), `liquidity_value_engine.py` (4), `features/signal_layer_v1.py` (4) | reject incomplete Schwab bars | `pricehistory.candles.*.open/high/low/close/volume` |
| S004 | `DEFAULT_ZERO_OR` x `oi` | 14 | 4 | `server.py` (5), `math_levels.py` (4), `math_probabilities.py` (3), `math_exposure_core.py` (2) | `GATE_FAIL_CLOSED` on missing OI | `chains.*.openInterest` |
| S005 | `DEFAULT_ZERO_OR` x `spot` | 11 | 7 | `lstm_data.py` (3), `server.py` (2), `signals.py` (2), `ml_train.py` (1), `call_engine.py` (1) | `GATE_FAIL_CLOSED` | `quotes.quote.lastPrice`, `quotes.quote.mark`, `streaming.content.*.LAST_PRICE`, `streaming.content.*.MARK` |
| S006 | `GET_DEFAULT_ZERO` x `ohlcv` | 9 | 2 | `liquidity_value_engine.py` (5), `market_context.py` (4) | merge with S003 | `pricehistory.candles.*` |
| S007 | `GET_DEFAULT_ZERO` x `volume` | 5 | 4 | `server.py` (2), `backfill_flow_imbalance.py` (1), `liquidity_value_engine.py` (1), `market_context.py` (1) | merge with S002 | volume fields listed in S002 |
| S008 | `BLACK_SCHOLES` x `greeks` | 3 | 2 | `ml_scheduler.py` (2), `v2_decision/a2_option_expression.py` (1) | quarantine BS after post-fix theta measurement | `chains.*.theta`, `chains.*.volatility` |
| S009 | `ASK_MINUS_BID` x `bid_ask` | 3 | 3 | `math_probabilities.py` (1), `server.py` (1), `v2_decision/a2_option_expression.py` (1) | spread unit split | `quotes.quote.bidPrice`, `quotes.quote.askPrice`, `chains.*.bid`, `chains.*.ask`, `chains.*.mark` |
| S010 | `DEFAULT_ZERO_OR` x `greeks` | 2 | 1 | `order_flow_engine.py` (2) | `GATE_FAIL_CLOSED` on missing Greek | `chains.*.delta`, `chains.*.gamma`, `chains.*.vega`, `chains.*.theta`, `chains.*.rho` |
| S011 | `GET_DEFAULT_ZERO` x `greeks` | 2 | 1 | `server.py` (2) | merge with S010 | Greek fields listed in S010 |
| S012 | `DEFAULT_ZERO_OR` x `iv` | 2 | 2 | `mc_fusion_adjustment.py` (1), `signals.py` (1) | `GATE_FAIL_CLOSED` on missing IV | `chains.*.volatility`, `chains.*.theoreticalVolatility` |

---

## Medium Priority Aggregate Slices

These five aggregates are intentionally broad and require sub-triage by actual line content before implementation.

| ID | Risk pattern | Instances | Top concentration | Required sub-triage |
|---|---:|---|---|---|
| S013 | `DATE_DIFF_DTE` | 213 | `server.py` (112), `v2_decision/a2_option_expression.py` (32), `market_state.py` (14) | Split true DTE replacement vs comments/tests/expiry audit logic. |
| S014 | `DEFAULT_ZERO_OR` | 152 | `math_probabilities.py` (32), `server.py` (17), `math_levels.py` (11) | Split by field: volume/OHLCV/OI/spot/analytics default. |
| S015 | `GET_DEFAULT_ZERO` | 137 | `server.py` (50), `ml_scheduler.py` (14), `math_exposure_core.py` (11) | Split by field and runtime vs offline analysis. |
| S016 | `BLACK_SCHOLES` | 126 | `prediction_engine.py` (50), `ml_predict.py` (25), `planes/l1_thresholds.py` (14) | Separate true Black-Scholes pricing/theta from generic model math references. |
| S017 | `TIME_NOW_FALLBACK` | 103 | `server.py` (50), `db.py` (12), `order_flow_streaming.py` (5) | Split market-data timestamp vs decision emit timestamp vs audit wall-clock. |

Smaller medium slices S018-S027 cover roughly 30 instances total and should be scheduled after S001-S012 plus aggregate sub-triage.

---

## Low Priority Tail

The 11 LOW slices cover roughly 102 instances. Expected categories:

```text
tests or comments missed by filters
audit scripts / one-off tools
lower-priority defaults with no Schwab primitive replacement
true analytics requiring provenance only
```

These can be closed in batched review slices after HIGH and MEDIUM remediation.

---

## Required Slice Contract

Every remediation slice MUST include:

```text
Schwab CSV authority checked: yes
CSV row(s): <canonical_field rows or NO_SCHWAB_EQUIVALENT>
Derived-field disposition: REPLACE_WITH_SCHWAB | KEEP_DERIVED_WITH_PROVENANCE | GATE_FAIL_CLOSED | REDESIGN
All consumers checked: yes
```

Every slice must include an all-consumers table:

| Consumer | Status | Evidence | Note |
|---|---|---|---|
| `<path>::<site>` | `fixed-in-this-slice` / `canonical` / `pending-follow-up` / `not-applicable` | `<file:line or symbol-level evidence>` | `<why>` |

File-level grouped dispositions are not closure evidence. Every disposition must cite the specific matching line, function, or symbol that was inspected.

`pending-follow-up` is not closure.

---

## Initial Implementation Recommendation

Start with **S001: `DATE_DIFF_DTE` x `days_to_expiration`**.

Rationale:

```text
highest instance count among actionable HIGH slices
direct Schwab replacement exists in CSV
exercises all-consumers discipline across runtime/A2/replay paths
likely collapses a large portion of S013
```

Next after S001:

```text
S009 spread unit split (CSV-N5/N6)
S002/S007 volume gate
S003/S006 OHLCV gate
S005 spot default multi-consumer gate
S008 Black-Scholes quarantine after theta measurement
```

---

## Closure Definition

System status may not move from `FAIL` to `PASS` until:

```text
1. all HIGH slices are closed or explicitly governed;
2. S013-S017 aggregate slices are sub-triaged and closed/governed;
3. `governance/SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_RESIDUAL.csv` has zero ungoverned manual rows;
4. `python tools/check_schwab_csv_first.py --whole-repo` exits 0;
5. each closure has tests or explicit no-test rationale;
6. affected registers include commit references.
```

---

## Non-Closure Statement

```text
schwab_remediation_slice_plan_status = ACTIVE
system_status = FAIL
whole_repo_guard_status = FAIL
```
