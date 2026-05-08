# Schwab Derived Field Replacement Register V1

**Status:** Draft replacement register - repo-wide closure OPEN  
**Date:** 2026-05-08  
**Scope:** Derived/recomputed market-data primitives and formulas crosswalked against Schwab-native field availability  
**Mode:** Read-only register plus remediation plan; no code changes authorized by this document

This register exists to answer one question for every market-data formula:

```text
If Schwab provides the primitive directly, are we using Schwab first?
```

If not, the item must be fixed, failed closed, or explicitly governed as a derived analytic. This is a V3 I-01 control: no silent substitution and no silent quality degradation.

Per `ENGINEERING_GATEKEEPING_POLICY.md` §Schwab Same-or-Better Rule, derived fields stay only when Schwab does not provide the primitive at the appropriate site or when an investigation produced a governed exception. "Schwab looked worse" is not a standing exception.

---

## Source Priority

For primitive market-data fields:

```text
schwab_native_normalized > schwab_native_raw_fallback > governed_derived_fallback > unavailable_gate
```

For app analytics that Schwab does not provide:

```text
schwab_inputs + governed_formula + provenance/source label
```

No formula may silently stand in for a Schwab-native primitive when that primitive is available in the selected endpoint and has reached the consumer.

---

## Closure Status

| Track | Status | Notes |
|---|---|---|
| Price/quote primitives | Inventory drafted | Quote/spot/spread/staleness hotspots identified. |
| Option-chain primitives | Inventory drafted | Greek/IV/timestamp/DTE/identity hotspots identified. |
| Model/training/calibration derivations | Inventory drafted | Missing-value laundering, imputation, and provenance gaps identified. |
| API/UI derivations | Inventory drafted | Trader-visible stale/fallback and source-display gaps identified. |
| Runtime code fixes | Not started in this register | This file ranks work; implementation slices follow. |
| Repo-wide replacement closure | OPEN | No claim of all-inclusive completion. |

Commit closure notes (reconciled to `main`; supersedes informal 2026-05-07 “working tree / pending” rows):

| Finding | Status | Evidence |
|---|---|---|
| DFR-001 | CLOSED | `f4e58d9` — A2 proof row preserves Schwab option-chain fields. Post-fix live/archive **theta measurement** (S008 window) still open. |
| DFR-002 | ADDRESSED | `a03e5ba` (S017 live plane / quote-time wiring). Re-audit if new residuals flag streaming carry-forward. |
| DFR-003 | ADDRESSED | `a03e5ba` — REST fast-quote / Tier A paths; fail-closed spot + source metadata (see S005 `d4b2f1a` for related consumers). |
| DFR-004 | ADDRESSED | `a03e5ba` + `569af08` (S009) — spread pts vs fraction + spread age / non-tradeable gating; re-audit sticky cache if residuals return. |
| DFR-010 / MT-001 | CLOSED | `d4b2f1a` (S005) — `features/replay_signal_input_v1` spot fail-closed. |
| DFR-021 | CLOSED | `df58fe9` — `build_inference_snapshot_v1_from_signal_input` no `time.time()` fallback (`SCHWAB_REMEDIATION_S017_INFERENCE_SNAPSHOT_TIME_CONTRACT.md`). |

---

## Action Classes

| Action | Meaning |
|---|---|
| `replace-with-Schwab` | A Schwab-native primitive exists and should be consumed instead of app-derived/defaulted value. |
| `keep-derived` | Schwab does not provide the analytic; keep formula but require provenance. |
| `gate/fail-closed` | Missing/stale Schwab-native input must block or degrade explicitly, not substitute silently. |
| `redesign` | Current flow mixes units/sources or carries stale state; module-level rework needed. |

---

## Highest Priority Blockers

| ID | Site | Field/formula | Why it matters | Action | Severity |
|---|---|---|---|---|---|
| DFR-001 | `market_state.py::_oe_chain_row_snapshot()` | Selected option proof row field truncation | Dropped Schwab theta/IV/timestamps before A2; addressed in `f4e58d9`; post-fix theta measurement still required. | replace-with-Schwab | High |
| DFR-002 | `live_market_plane.py::record_from_level_one_equity()` | `spot = LAST_PRICE or MARK or prior spot or bid/ask midpoint`; bid/ask carry-forward | Streaming authority can silently carry stale quote fields into Tier A/B/C overlays. | redesign | High |
| DFR-003 | `server.py::_build_rest_fast_quote_payload()` | `spot = last or mark or 0.0` | Fast quote can degrade to zero/None without field-level source; trader-visible spot and L1 overlays affected. | gate/fail-closed | High |
| DFR-004 | `server.py::_fetch_state()` | Cached `_last_spread_by_ticker` reused when current bid/ask missing | Stale spread can affect liquidity and A2 spread gates. | gate/fail-closed | High |
| DFR-005 | `server.py::_fetch_state()` | Selected-expiry filter falls back to full chain when no rows match | Wrong expiry slice can alter strike selection and option expression scoring. | gate/fail-closed | High |
| DFR-006 | `v2_decision/a2_option_expression.py` | `spread = ms_dict.spread or (ask - bid)` | Underlying spread and contract spread can be semantically mixed unless provenance is explicit. | redesign | High |
| DFR-007 | `v2_decision/a2_option_expression.py::_quote_staleness_ms()` | Uses `quoteTimeInLong`; missing means not implemented | Schwab also provides `tradeTimeInLong`; missing quote timestamp can hard-gate A2 despite usable trade timestamp. | gate/fail-closed / governed fallback | High |
| DFR-008 | `server.py` expected move block | Falls back to IV EM with default IV = 20% and full-session hours | Synthetic default-IV EM can affect risk framing when Schwab IV/marks are unavailable. | gate/fail-closed | Medium/High |
| DFR-009 | `snapshot_normalizer.py::resample_to_1m()` | Rebuilds OHLCV from snapshots and spot fallback | Can create training/history bars unlike Schwab price-history candles. | redesign | Medium/High |
| DFR-010 | `features/replay_signal_input_v1.py` | `spot = float(row.get("spot") or 0.0)` | Missing spot becomes 0.0 instead of unavailable; V3 I-01 risk in replay feature path. **Closed `d4b2f1a` (S005).** | gate/fail-closed | High |
| DFR-011 | `market_data_adapter.py` | OHLCV missing/unparseable values default to `0.0` | Schwab price-history candles provide native OHLCV; zero-injected bars can pollute ATR/VWAP/volatility/replay. | gate/fail-closed | High |
| DFR-012 | `features/inference_snapshot.py` | Snapshot-level provenance only | Mixed Schwab-native and derived features lose per-field source lineage before model consumers. | redesign | High |
| DFR-013 | `features/fusion_model_input.py` | Missing `vwap_side` defaults to `above` | Missing market context becomes deterministic retrieval bucket. | gate/fail-closed / redesign | High |
| DFR-014 | `ml_train.py` / `ml_predict.py` | Median and zero imputation can hide upstream market-data failures | Model training/inference can continue with degraded inputs without authority downgrade. | redesign | High |
| DFR-015 | `static/index.html` utility/sidebar | Sticky previous VIX/PCR/bid/ask values when current payload omits fields | Trader can see stale values as current. | gate/fail-closed | High |
| DFR-016 | `server.py` Tier C VIX payload | `vix_direction` / `vix_vs_prev` computed but not serialized where UI expects them | Trader-visible VIX momentum can show neutral/missing despite movement. | replace-with-Schwab + derived provenance | High |
| DFR-017 | `chains.py::contract_fields()` / `math_exposure_core.py::compute_exposures_by_strike()` | `multiplier` defaulted to `100` | Missing Schwab multiplier silently coerces non-standard contracts into standard-contract dollarized exposure math. | gate/fail-closed / replace-with-Schwab | High |
| DFR-018 | `liquidity_value_engine.py` | OHLCV defaults to `0` | Parallel OHLCV zero-injection path outside `market_data_adapter.py`. **ADDRESSED `9a863fc` (S002/S003 overlap) — re-audit if residuals persist.** | gate/fail-closed | High |
| DFR-019 | `order_flow_engine.py::_compute_rvol()` | RVOL returns `1.0` when average volume is invalid | Missing baseline volume becomes neutral RVOL instead of unavailable. | gate/fail-closed / derived provenance | Medium |
| DFR-020 | `signals.py::_spot_for_mc_fusion_adjustment()` | spot returns `0.0` in fusion adjustment path | Post-fusion spot consumer can silently substitute zero. **Closed `d4b2f1a` (S005).** | gate/fail-closed | High |
| DFR-021 | `features/inference_snapshot.py` | `as_of_ts -> refresh_ts_utc -> time.time()` | Decision/input timestamp can fall back to wall clock without source label. **Closed `df58fe9` (S017 inference snapshot amendment).** | gate/fail-closed / provenance | Medium |
| DFR-022 | `server.py` MC expected move block | fallback hours defaults to `6.5` | Synthetic full-session horizon can affect expected-move framing. | gate/fail-closed | Medium |
| DFR-023 | `mc_fusion_adjustment.py` | MC output zero-fill via `or 0.0` | Missing MC output can become neutral zero-valued adjustment. | gate/fail-closed | Medium |
| DFR-024 | `static/index.html` utility bid/ask rendering | sticky bid/ask display | Operator-visible quote fields can persist when current payload omits them. | gate/fail-closed | High |

---

## Price And Quote Primitive Findings

| ID | Site | Derived field | Formula/fallback | Schwab availability | Action | Severity |
|---|---|---|---|---|---|---|
| PQ-001 | `server.py::_build_rest_fast_quote_payload()` | `spot` | `last or mark or 0.0` | `lastPrice`, `mark` | gate/fail-closed; emit source leg | High |
| PQ-002 | `server.py::_build_rest_fast_quote_payload()` | `spread_frac` | `(ask - bid) / midpoint` | `bidPrice`, `askPrice`; no spread fraction | redesign split `spread_pts` vs `spread_frac` | High |
| PQ-003 | `server.py::_fetch_state()` | quote spread | sticky cached prior spread when bid/ask missing | `bidPrice`, `askPrice` | TTL and stale reason; fail closed for gates | High |
| PQ-004 | `live_market_plane.py::record_from_level_one_equity()` | `spot`, bid/ask | `LAST_PRICE or MARK`, prior spot, midpoint; prior bid/ask carry-forward | `LAST_PRICE`, `MARK`, `BID_PRICE`, `ASK_PRICE` | redesign with field TTL/source freshness | High |
| PQ-005 | `live_market_plane.py::record_from_level_one_equity()` | `spread_frac` | `(ask - bid) / midpoint` | bid/ask native; spread derived | keep-derived with units/age metadata | Medium |
| PQ-006 | `market_context.py::_extract_quote()` | `% change` | `netPercentChange`, else `netChange / prior` | `netPercentChange`, `netChange` | replace-with-Schwab when present; provenance on derived fallback | Medium |
| PQ-007 | `server.py::_fetch_state()` | total volume | stream, chain underlying, quote/regular/extended/reference fallback chain | volume fields native but endpoint-specific | keep fallback order with chosen source field | Medium |
| PQ-008 | `server.py::_CandleAccumulator.tick()` | per-bar volume | `max(0, total_now - prev_total)` | cumulative volume native; bar delta derived | keep-derived with session reset guard/source note | Medium |
| PQ-009 | `snapshot_normalizer.py::resample_to_1m()` | synthetic OHLCV | first/last candle fields or spot fallback | price-history OHLCV native | redesign/tag synthetic rows; prefer Schwab bars where present | Medium |
| PQ-010 | `market_data_adapter.py::normalize_bar()` | OHLCV aliases | maps `open/o`, `high/h`, etc. | Schwab candles canonical | keep-derived adapter, but schema drift must not be hidden in Schwab path | Low |
| PQ-011 | `order_flow_engine.py::_compute_top_book_pressure()` | top-book pressure | `(bid_size - ask_size) / total` | sizes native | keep-derived with source tier | Medium |
| PQ-012 | `order_flow_engine.py::_compute_spread()` | spread points | `ask - bid`, source fallback content/quote/underlying | bid/ask native | keep-derived with source stamp | Medium |
| PQ-013 | `server.py::_compute_vwap_from_bars()` | VWAP | OHLCV weighted calculation | raw bars native, VWAP may vary by source | keep-derived with provenance | Medium |
| PQ-014 | `order_flow_streaming.py` diagnostics | stream staleness | now minus last stream update | timestamps native; health metric derived | keep-derived; gate unhealthy source | High |

---

## Option-Chain Primitive Findings

| ID | Site | Derived field | Formula/fallback | Schwab availability | Action | Severity |
|---|---|---|---|---|---|---|
| OP-001 | `math_probabilities.py::score_option_expression()` | spread | `ask - bid` | bid/ask native | keep-derived with `schwab_bid_ask` source | Low |
| OP-002 | `math_probabilities.py::score_option_expression()` | `delta_gamma_ratio` | `abs(delta) / abs(gamma)` | delta/gamma native | keep-derived; guard near-zero gamma | Medium |
| OP-003 | `math_probabilities.py::score_option_expression()` | `vol_oi_ratio` | `volume / openInterest`, volume = `totalVolume or volume` | `totalVolume`, `openInterest` native | prefer `totalVolume`; fallback with provenance | Medium |
| OP-004 | `math_probabilities.py::score_option_expression()` | `gamma_x_oi` | `gamma * openInterest` | inputs native, metric not native | keep-derived; standardize rounding | Low |
| OP-005 | `market_state.py::_build_contract_context_ms()` | DTE text | expiry date minus current ET date | `daysToExpiration` native | replace-with-Schwab first; date diff fallback only | High |
| OP-006 | `market_state.py::_oe_bid_ask_mid()` | midpoint/breakeven | `(bid + ask)/2`, strike +/- mid | bid/ask native; BE derived | keep-derived; mark-side-by-side for advisory if needed | Medium |
| OP-007 | `v2_decision/a2_option_expression.py` | mid/spread/breakeven | midpoint, spread, strike +/- mid | bid/ask native; no native BE | redesign source/price precedence matrix | High |
| OP-008 | `v2_decision/a2_option_expression.py::_theta()` | theta | `chain_row.theta -> raw.theta -> Black-Scholes` | theta native | replace-with-Schwab; BS residual only after measurement/governance | High |
| OP-009 | `v2_decision/a2_option_expression.py::_time_to_expiry_years()` | time-to-expiry | `daysToExpiration`, then minutes/hours | `daysToExpiration` native | keep precedence; emit source | Low |
| OP-010 | `v2_decision/a2_option_expression.py::_quote_staleness_ms()` | quote staleness | decision clock - quote timestamp | `quoteTimeInLong`, `tradeTimeInLong` native | fail closed; consider governed trade-time fallback | High |
| OP-011 | `v2_decision/a2_lifecycle_health.py::resolve_a2_option_right()` | option right | app fields and winner side | `putCall` native | add final fallback from `winner.chain_row.putCall` | Medium |
| OP-012 | `math_volatility.py::compute_iv_model_spread()` | IV model spread | `volatility - theoreticalVolatility` | both native | keep-derived | Low |
| OP-013 | `math_volatility.py::_extract_iv_for_strike()` | IV | reads `volatility`, handles sentinel | `volatility`, `theoreticalVolatility` native | keep; optional theoretical fallback with flag | Low |
| OP-014 | `math_levels.py::_mid()` | option mid for parity residual | `mark -> mid -> last -> (bid+ask)/2` | mark/last/bid/ask native | reorder by use case; avoid stale `last` before live bid/ask | Medium |
| OP-015 | `math_probabilities.py::flow_imbalance_normalized_with_fallback()` | flow imbalance | book-size imbalance else volume ratio | sizes/volume native; metric derived | keep dual path; persist source | Low |
| OP-016 | `math_exposure_core.py::compute_exposures_by_strike()` | exposure aggregates | Greek/OI/multiplier/spot aggregations; some default 0/100 | inputs native | keep-derived; add missingness counters | Medium |
| OP-017 | `order_flow_engine.py::_compute_options_flow()` | call/put flow | `totalVolume or lastSize` | both native but different semantics | use `lastSize` only in tick mode with source | Medium |
| OP-018 | `server.py::_expiries_from_contracts()` and selection | expiry identity | expiration fallback, default nearest non-past, full-chain fallback | `expirationDate`, `daysToExpiration` native | strict expiry match; fail closed unless flagged | Medium/High |
| OP-019 | `realized_contract_eval.py::_find_contract_row()` | replay identity | symbol first, else side + strike | symbol/expiry native | add expiry constraint before side+strike fallback | Medium |
| OP-020 | `calibration/v2_a1_execution_ev.py` | quote readiness | requires normalized bid/ask/mark/sizes/timestamp/symbol | fields native | keep strict gate for calibration | Low |

---

## Model, Training, Calibration Findings

| ID | Site | Derived/defaulted field | Formula/fallback | Schwab availability | Action | Severity |
|---|---|---|---|---|---|---|
| MT-001 | `features/replay_signal_input_v1.py` | spot | `float(row.get("spot") or 0.0)` | spot/last/mark native upstream | gate/fail-closed; do not convert missing spot to zero | High |
| MT-002 | `features/fusion_model_input.py::similar_setup_filters_from_canonical_features()` | zone/vwap defaults | `zone unknown`, `vwap_side above` when None | derived features, not Schwab primitives | keep-derived only with explicit missing semantics; verify model impact | Medium |
| MT-003 | `features/lstm_sequence_input.py` | missing canonical numerics | encoder defaults missing numerics to 0.0 | primitives may be native upstream | require missingness/source masks in artifacts | Medium |
| MT-004 | `ml_train.py` | snapshot spot fallback | uses `snapshot.get("spot") or 0` in some paths | spot native upstream | gate/fail-closed or exclude rows for strict training | Medium/High |
| MT-005 | `calibration/v2_advisory_backfill.py` | reconstructed live ms fields | aliases/fills from snapshot/replay context | mixed native/derived archive fields | source-stamp reconstructed fields | Medium |
| MT-006 | `market_data_adapter.py::normalize_bar()` | OHLCV | Missing/unparseable values become `0.0`; aliases accepted | Schwab candles provide `open/high/low/close/volume` | reject incomplete Schwab bars; use `None`/missing fields for non-Schwab adapters | High |
| MT-007 | `market_data_adapter.py::schwab_candles_to_bars()` | OHLCV | `float(c.get(key, 0) or 0)` | Schwab candles native | add `missing_fields`, `source=schwab_pricehistory`, reject zero-price bars | High |
| MT-008 | `features/inference_snapshot.py` | per-field provenance | only envelope-level `source` | mixed Schwab-native and derived | add per-feature lineage map: source, transform, fallback flag | High |
| MT-009 | `ml_train.py` | XGB features | NaNs filled by training medians; final `nan_to_num(..., nan=0.0)` | mixed upstream primitives | imputation caps, hard fail thresholds, training provenance stats | High |
| MT-010 | `ml_predict.py` | live feature matrix/probabilities | stored medians, `nan_to_num`, NaN probs to neutral defaults | mixed upstream primitives | telemetry and authority degradation when imputation triggers | Medium |
| MT-011 | `lstm_data.py` | sequence features | missing invalid numeric -> `0.0`; missing zone -> `pin_neutral`; final zero fill | mixed upstream primitives | missing masks/sentinel channels instead of zero laundering | High |
| MT-012 | `ml_data_common.py::attach_5m_additive_context()` | `m5_*` context | 1m as-of proxy labeled `m5_*` | Schwab native 5m history exists | rename to proxy or persist `m5_source_timeframe=1m_asof` | Medium |
| MT-013 | `calibration/writer.py` | calibration feature lineage | logs structural fields without per-field lineage; wall-clock fallback for decision time | mixed | add `feature_lineage_json` and `decision_ts_source` | High |

---

## API And UI Findings

| ID | Site | Field | Formula/fallback | Schwab availability | Action | Severity |
|---|---|---|---|---|---|---|
| UI-001 | `server.py` fast quote payload | `spot`, bid/ask, `spread` | quote parse and derived spread fraction | quote primitives native | split units and add source fields | High |
| UI-002 | `static/index.html` order-flow display | `cum_delta_proxy` fallback to `cum_delta` | display fallback | derived metrics, not Schwab primitives | show source/missing reason | Medium |
| UI-003 | VIX utility fields | VIX level/change/open | Schwab `$VIX` quote + persisted session open | VIX quote native, session-open derived/persisted | keep with provenance and file-health status | Medium |
| UI-004 | A2 selected contract card | selected contract snapshot/source suffix | consumes A2 leaves | Schwab fields native upstream | relabel once producer path proven and governed | High |
| UI-005 | `server.py::_tier_a_live_state_dict()` | lightweight analytics context | fresh L1 quote mixed with latest cached analytics row | Schwab context native/derived but cached | add `context_age_ms`, `context_expiry_used`, visible stale badge | Medium |
| UI-006 | `server.py` + `static/index.html` | `vix_direction`, `vix_vs_prev` | backend computes but final Tier C payload omits fields expected by UI | VIX level native, direction/change derived | serialize timestamped fields; reset UI when absent | High |
| UI-007 | `server.py::compute_iwm_confluence(...)` call | `vix_direction` argument | passes IV direction into parameter named VIX direction | actual VIX direction available from VIX tracker | rename/pass correct value; add semantic assertion | Medium |
| UI-008 | `static/index.html` sidebar | `sb-vix`, `sb-pcr` | updates only when values present; prior DOM can persist | source values backend/Schwab-derived | reset to `--` plus stale class when omitted | High |
| UI-009 | `static/index.html::refreshUtilityBar` | bid/ask | can reuse `window._lastData` prior fields when payload partial | bid/ask native when present | current payload first; reuse only with age guard/stale indicator | High |
| UI-010 | `server.py::_attach_analytics_freshness_contract()` | `analytics_stale` | true when SSE live OR age >= ttl | local freshness state | split `stale_by_age` vs `superseded_by_stream` | Medium |
| UI-011 | `math_exposure_core.py` / payload consumers | GEX/DEX aggregates | derived from Schwab Greeks/OI/spot | no native GEX/DEX | label derived analytics; include input completeness score | Medium |
| UI-012 | `math_probabilities.py` option scoring payload | static spread threshold and ratios | policy thresholds over Schwab primitives | derived policy outputs | publish threshold version in payload | Medium |
| UI-013 | `server.py` / `order_flow_streaming.py` / UI badge | quote authority badges | local authority classification | not Schwab primitive | keep visible near spot/bid-ask and log transitions | Medium |

---

## Remediation Order

1. **Commit/review proof-row preservation slice**: closes DFR-001/SC-001 implementation path.
2. **Fast quote and live plane source/TTL redesign**: DFR-002, DFR-003, DFR-004, PQ-001 through PQ-005.
3. **A2 spread/price/staleness contract cleanup**: DFR-006, DFR-007, OP-007, OP-010.
4. **Expiry and identity fail-closed fixes**: DFR-005, OP-018, OP-019.
5. **Training/calibration missingness controls**: MT-001, MT-006 through MT-013.
6. **UI/API source display cleanup**: UI-005 through UI-010, then A2/source suffix cleanup.
7. **Historical archive segmentation**: prevent pre-normalization rows from being mixed with post-fix Schwab-complete rows without labels.

---

## Non-Closure Statement

This register is not yet complete. It is the active replacement plan.

```text
repo_wide_derived_field_replacement_status = OPEN
price_quote_inventory = DRAFTED
option_chain_inventory = DRAFTED
model_training_inventory = DRAFTED
api_ui_inventory = DRAFTED
```

