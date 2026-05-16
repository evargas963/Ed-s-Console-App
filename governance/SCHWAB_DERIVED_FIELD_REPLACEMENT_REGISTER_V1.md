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

## Precedence Principle (binding for every row in this register)

For any value where `schwab_field_inventory/schwab_field_dictionary.csv` contains a `canonical_field`:

```text
Schwab canonical_field = primary read.
App-side aliases (ms_dict keys, internal names, alternate keys) = legacy
fallbacks ONLY when the Schwab field is absent.
```

The `v1_approximation`, `not_implemented`, and `policy_object_pending` source labels do **not** apply to values whose source traces to a Schwab `canonical_field`. Such leaves must be labeled `v2_compliant` and cite the Schwab leaf in the `detail` field.

Disposition language for every `REPLACE_WITH_SCHWAB` / `replace-with-Schwab` row in this document follows the same pattern: *"Schwab `<canonical_field>` is the primary source; app-side aliases (`<alias>`/`<alias>`) are legacy fallbacks only when the Schwab field is absent."* No row may use "fallback to Schwab," "add Schwab as a final fallback," or any wording that inverts precedence.

CI gate enforcing this principle for the A2 output surface: `tests/test_v2_a2_option_expression.py::test_a2_no_v1_approximation_leaf_traces_to_a_schwab_canonical_field`.

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
| Option-chain primitives | Inventory drafted | Greek, **`volatility`**, timestamp/DTE/identity hotspots identified. |
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
| DFR-017-REG-MAX-PAIN | CLOSED | `9850a86` — max-pain mult fail-closed; see `math_levels.compute_max_pain`. |
| DFR-017 | CLOSED | `0ee94b8` — repo-wide `multiplier` consumers fail-closed. |
| DFR-008 / DFR-022 | CLOSED | EM path: no synthetic 6.5h fallback; IV EM requires `_hours_rem > 0`. |
| DFR-007 / OP-010 | CLOSED | `tradeTimeInLong` governed fallback when `quoteTimeInLong` absent. |
| OP-008 | CLOSED | Schwab `theta` only; BS behind `_A2_THETA_BS_FALLBACK_GOVERNED`. |
| DFR-005 / OP-018 | CLOSED | `64c3641` — strict `expirationDate` slice; `kl_expiry_source`; no full-chain fallback. |

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
| DFR-001 | `market_state.py::_oe_chain_row_snapshot()` | Selected option proof row field truncation | Dropped Schwab theta, **`volatility`**, and timestamps before A2; addressed in `f4e58d9`; post-fix theta measurement still required. | replace-with-Schwab | High |
| DFR-002 | `live_market_plane.py::record_from_level_one_equity()` | `spot = LAST_PRICE or MARK or prior spot or bid/ask midpoint`; bid/ask carry-forward | Streaming authority can silently carry stale quote fields into Tier A/B/C overlays. | redesign | High |
| DFR-003 | `server.py::_build_rest_fast_quote_payload()` | `spot = last or mark or 0.0` | Fast quote can degrade to zero/None without field-level source; trader-visible spot and L1 overlays affected. | gate/fail-closed | High |
| DFR-004 | `server.py::_fetch_state()` | Cached `_last_spread_by_ticker` reused when current bid/ask missing | Stale spread can affect liquidity and A2 spread gates. | gate/fail-closed | High |
| DFR-005 | `server.py::_fetch_state()` | Selected-expiry filter falls back to full chain when no rows match | Wrong expiry slice can alter strike selection and option expression scoring. **CLOSED** — strict `expirationDate` slice via `_filter_contracts_by_selected_expiry`; `kl_expiry_source` emitted. | gate/fail-closed | High |
| DFR-006 | `v2_decision/a2_option_expression.py` | `spread = ms_dict.spread or (ask - bid)` | Underlying spread and contract spread can be semantically mixed unless provenance is explicit. **CLOSED** — `a2_price_precedence.py` matrix; contract spread chain-only; underlying on separate payload leaves. | redesign | High |
| DFR-007 | `v2_decision/a2_option_expression.py::_quote_staleness_ms()` | Uses `quoteTimeInLong`; missing means not implemented | Schwab also provides `tradeTimeInLong`; missing quote timestamp can hard-gate A2 despite usable trade timestamp. | gate/fail-closed / governed fallback | High |
| DFR-008 | `server.py` expected move block | Falls back to expected-move path with default **`volatility`** = 20% and full-session hours | Synthetic default-**`volatility`** EM can affect risk framing when Schwab **`volatility`/marks are unavailable. **CLOSED** — straddle/IV EM only; no synthetic IV. | gate/fail-closed | Medium/High |
| DFR-009 | `snapshot_normalizer.py::resample_to_1m()` | Rebuilds OHLCV from snapshots and spot fallback | Can create training/history bars unlike Schwab price-history candles. **CLOSED Day 1** — `snapshot_synthetic` tagging; no `o=0.0` spot fallback. | redesign | Medium/High |
| DFR-010 | `features/replay_signal_input_v1.py` | `spot = float(row.get("spot") or 0.0)` | Missing spot becomes 0.0 instead of unavailable; V3 I-01 risk in replay feature path. **Closed `d4b2f1a` (S005).** | gate/fail-closed | High |
| DFR-011 | `market_data_adapter.py` | OHLCV missing/unparseable values default to `0.0` | Schwab price-history candles provide native OHLCV; zero-injected bars can pollute ATR/VWAP/volatility/replay. **CLOSED Day 1** — reject incomplete/zero-close bars; `missing_fields` provenance. | gate/fail-closed | High |
| DFR-012 | `features/inference_snapshot.py` | Snapshot-level provenance only | Mixed Schwab-native and derived features lose per-field source lineage before model consumers. | redesign | High |
| DFR-013 | `features/fusion_model_input.py` | Missing `vwap_side` defaults to `above` | Missing market context becomes deterministic retrieval bucket. | gate/fail-closed / redesign | High |
| DFR-014 | `ml_train.py` / `ml_predict.py` | Median and zero imputation can hide upstream market-data failures | Model training/inference can continue with degraded inputs without authority downgrade. | redesign | High |
| DFR-015 | `static/index.html` utility/sidebar | Sticky previous VIX/PCR/bid/ask values when current payload omits fields | Trader can see stale values as current. | gate/fail-closed | High |
| DFR-016 | `server.py` Tier C VIX payload | `vix_direction` / `vix_vs_prev` computed but not serialized where UI expects them | Trader-visible VIX momentum can show neutral/missing despite movement. | replace-with-Schwab + derived provenance | High |
| DFR-017 | Inline `chain_row.get("multiplier")` reads at consumer sites — **CLOSED repo-wide** (`math_exposure_core`, `backfill_flow_imbalance`, `max_pain`; no `or 100`). | `multiplier` defaulted to `100` | Missing Schwab multiplier silently coerces non-standard contracts into standard-contract dollarized exposure math. | gate/fail-closed / replace-with-Schwab | High |
| DFR-018 | `liquidity_value_engine.py` | OHLCV defaults to `0` | Parallel OHLCV zero-injection path outside `market_data_adapter.py`. **CLOSED Day 1 re-audit** — no `.get("open|high|low|close", 0)` patterns; `_float_or_none` path clean. | gate/fail-closed | High |
| DFR-019 | `order_flow_engine.py::_compute_rvol()` | RVOL returns `1.0` when average volume is invalid | Missing baseline volume becomes neutral RVOL instead of unavailable. **CLOSED Day 2** — `None` + `rvol_unavailable_reason`; no `1.0` fallback. | gate/fail-closed / derived provenance | Medium |
| DFR-020 | `signals.py::_spot_for_mc_fusion_adjustment()` | spot returns `0.0` in fusion adjustment path | Post-fusion spot consumer can silently substitute zero. **Closed `d4b2f1a` (S005).** | gate/fail-closed | High |
| DFR-021 | `features/inference_snapshot.py` | `as_of_ts -> refresh_ts_utc -> time.time()` | Decision/input timestamp can fall back to wall clock without source label. **Closed `df58fe9` (S017 inference snapshot amendment).** | gate/fail-closed / provenance | Medium |
| DFR-022 | `server.py` MC expected move block | fallback hours defaults to `6.5` | Synthetic full-session horizon can affect expected-move framing. **CLOSED** — removed `max(_hours_rem, 6.5)` MC_FALLBACK block. | gate/fail-closed | Medium |
| DFR-023 | `mc_fusion_adjustment.py` | MC output zero-fill via `or 0.0` | Missing MC output can become neutral zero-valued adjustment. | gate/fail-closed | Medium |
| DFR-024 | `static/index.html` utility bid/ask rendering | sticky bid/ask display | Operator-visible quote fields can persist when current payload omits them. | gate/fail-closed | High |

---

## Price And Quote Primitive Findings

| ID | Site | Derived field | Formula/fallback | Schwab availability | Action | Severity |
|---|---|---|---|---|---|---|
| PQ-001 | `server.py::_build_rest_fast_quote_payload()` | `spot` | `last or mark or 0.0` | `lastPrice`, `mark` | gate/fail-closed; emit source leg | High |
| PQ-002 | `server.py::_build_rest_fast_quote_payload()` | `spread_frac` | `(ask - bid) / midpoint` | `bidPrice`, `askPrice`; no spread fraction | **CLOSED Day 2** — `spread_pts` + `spread_frac` + separate `*_source` on fast-quote and `_fetch_state`. | redesign split `spread_pts` vs `spread_frac` | High |
| PQ-003 | `server.py::_fetch_state()` | quote spread | sticky cached prior spread when bid/ask missing | `bidPrice`, `askPrice` | TTL and stale reason; fail closed for gates | High |
| PQ-004 | `live_market_plane.py::record_from_level_one_equity()` | `spot`, bid/ask | `LAST_PRICE or MARK`, prior spot, midpoint; prior bid/ask carry-forward | `LAST_PRICE`, `MARK`, `BID_PRICE`, `ASK_PRICE` | redesign with field TTL/source freshness | High |
| PQ-005 | `live_market_plane.py::record_from_level_one_equity()` | `spread_frac` | `(ask - bid) / midpoint` | bid/ask native; spread derived | **VERIFIED Day 2** — live plane already emits `spread_pts` + fractional `spread` separately (S009). | keep-derived with units/age metadata | Medium |
| PQ-006 | `market_context.py::_extract_quote()` | `% change` | `netPercentChange`, else `netChange / prior` | `netPercentChange`, `netChange` | replace-with-Schwab when present; provenance on derived fallback | Medium |
| PQ-007 | `server.py::_fetch_state()` | total volume | stream, chain underlying, quote/regular/extended/reference fallback chain | volume fields native but endpoint-specific | **VERIFIED Day 2** — existing Schwab-first fallback order unchanged; feeds `_CandleAccumulator` with `totalVolume` delta provenance. | keep fallback order with chosen source field | Medium |
| PQ-008 | `server.py::_CandleAccumulator.tick()` | per-bar volume | `max(0, total_now - prev_total)` | cumulative volume native; bar delta derived | **CLOSED Day 2** — session-reset guard + `get_bars_source()` provenance. | keep-derived with session reset guard/source note | Medium |
| PQ-009 | `snapshot_normalizer.py::resample_to_1m()` | synthetic OHLCV | first/last candle fields or spot fallback | price-history OHLCV native | **CLOSED Day 1** — `source=snapshot_synthetic`, `synthetic=True`; fail closed when open/spot missing. | redesign/tag synthetic rows; prefer Schwab bars where present | Medium |
| PQ-010 | `market_data_adapter.py::normalize_bar()` | OHLCV aliases | maps `open/o`, `high/h`, etc. | Schwab candles canonical | **CLOSED Day 1** — canonical keys only; `source` + `missing_fields` on every bar. | keep-derived adapter, but schema drift must not be hidden in Schwab path | Low |
| PQ-011 | `order_flow_engine.py::_compute_top_book_pressure()` | top-book pressure | `(bid_size - ask_size) / total` | sizes native | **CLOSED Day 2** — `top_book_pressure_source` tier (`schwab_stream`/`schwab_quote`). | keep-derived with source tier | Medium |
| PQ-012 | `order_flow_engine.py::_compute_spread()` | spread points | `ask - bid`, source fallback content/quote/underlying | bid/ask native | **CLOSED Day 2** — `spread_pts` + `spread_frac` + leaf provenance; legacy `spread` = pts only. | keep-derived with source stamp | Medium |
| PQ-013 | `server.py::_compute_vwap_from_bars()` | VWAP | OHLCV weighted calculation | raw bars native, VWAP may vary by source | **CLOSED Day 2** — returns `(vwap, source_bars)` from `get_bars_source()`. | keep-derived with provenance | Medium |
| PQ-014 | `order_flow_streaming.py` diagnostics | stream staleness | now minus last stream update | timestamps native; health metric derived | keep-derived; gate unhealthy source | High |

---

## Option-Chain Primitive Findings

| ID | Site | Derived field | Formula/fallback | Schwab availability | Action | Severity |
|---|---|---|---|---|---|---|
| OP-001 | `math_probabilities.py::score_option_expression()` | spread | `ask - bid` | bid/ask native | keep-derived with `schwab_bid_ask` source | Low |
| OP-002 | `math_probabilities.py::score_option_expression()` | `delta_gamma_ratio` | `abs(delta) / abs(gamma)` | delta/gamma native | keep-derived; guard near-zero gamma | Medium |
| OP-003 | `math_probabilities.py::score_option_expression()` | `vol_oi_ratio` | `volume / openInterest`, volume = `totalVolume or volume` | `totalVolume`, `openInterest` native | Schwab `totalVolume` is the primary source; the legacy `volume` alias is a fallback only when `totalVolume` is absent. Per-row chain volume MUST come from `totalVolume`; keep `volume` as fallback only on payloads where Schwab does not emit `totalVolume` (e.g. movers screeners). | Medium |
| OP-004 | `math_probabilities.py::score_option_expression()` | `gamma_x_oi` | `gamma * openInterest` | inputs native, metric not native | keep-derived; standardize rounding | Low |
| OP-005 | `market_state.py::_build_contract_context_ms()` | DTE text | expiry date minus current ET date | `daysToExpiration` native | Schwab `chains.*.daysToExpiration` is the primary source; the date-diff against current ET date is a legacy app-side fallback only when the Schwab field is absent. Same Schwab-first precedence applies to `is_0dte` (`v2_decision/a2_eod_force_exit.py::is_0dte`) which reads `chain_row.daysToExpiration == 0` first and falls back to `selected_exp` only when `chain_row` is absent. | High |
| OP-006 | `market_state.py::_oe_bid_ask_mid()` | midpoint/breakeven | `(bid + ask)/2`, strike +/- mid | bid/ask native; BE derived | **CLOSED** — mark→last→bid/ask mid ladder with `mid_source` on contract context string. | keep-derived; mark-side-by-side for advisory if needed | Medium |
| OP-007 | `v2_decision/a2_option_expression.py` | mid/spread/breakeven | midpoint, spread, strike +/- mid | bid/ask native; no native BE | **CLOSED** — shared `a2_price_precedence.py` with contract vs underlying spread separation. | redesign source/price precedence matrix | High |
| OP-008 | `v2_decision/a2_option_expression.py::_theta()` | theta | `chain_row.theta -> raw.theta -> Black-Scholes` | theta native | replace-with-Schwab; BS residual only after measurement/governance | High |
| OP-009 | `v2_decision/a2_option_expression.py::_time_to_expiry_years()` | time-to-expiry | `daysToExpiration`, then minutes/hours | `daysToExpiration` native | keep precedence; emit source | Low |
| OP-010 | `v2_decision/a2_option_expression.py::_quote_staleness_ms()` | quote staleness | decision clock - quote timestamp | `quoteTimeInLong`, `tradeTimeInLong` native | fail closed; consider governed trade-time fallback | High |
| OP-011 | `v2_decision/a2_lifecycle_health.py::resolve_a2_option_right()` | option right | app fields and winner side | `putCall` native | `winner.chain_row.putCall` is the Schwab-primary source; app-side aliases (`call_option_right`, `rec_side`, `winner.side`) are legacy fallbacks only when `chain_row.putCall` is absent. | Medium |
| OP-012 | `math_volatility.py::compute_iv_model_spread()` | **`volatility`** model spread | `volatility - theoreticalVolatility` | both native | keep-derived | Low |
| OP-013 | `math_volatility.py::_extract_iv_for_strike()` | **`volatility`** read | reads `volatility`, handles sentinel | `volatility`, `theoreticalVolatility` native | keep; optional theoretical fallback with flag | Low |
| OP-014 | `math_levels.py::_mid()` | option mid for parity residual | `mark -> mid -> last -> (bid+ask)/2` | mark/last/bid/ask native | reorder by use case; avoid stale `last` before live bid/ask | Medium |
| OP-015 | `math_probabilities.py::flow_imbalance_normalized_with_fallback()` | flow imbalance | book-size imbalance else volume ratio | sizes/volume native; metric derived | keep dual path; persist source | Low |
| OP-016 | `math_exposure_core.py::compute_exposures_by_strike()` | exposure aggregates | Greek/OI/multiplier/spot aggregations; some default 0/100 | inputs native | keep-derived; add missingness counters | Medium |
| OP-017 | `order_flow_engine.py::_compute_options_flow()` | call/put flow | `totalVolume or lastSize` | both native but different semantics | **CLOSED Day 2** — `options_flow_tick_mode` + `options_flow_volume_source`. | use `lastSize` only in tick mode with source | Medium |
| OP-018 | `server.py::_expiries_from_contracts()` and selection | expiry identity | expiration fallback, default nearest non-past, full-chain fallback | `expirationDate`, `daysToExpiration` native | Schwab `expirationDate` / `daysToExpiration` are the primary expiry-identity sources. Strict slice via `_filter_contracts_by_selected_expiry`; full-chain fallback removed (DFR-005 closure). | Medium/High |
| OP-019 | `realized_contract_eval.py::_find_contract_row()` | replay identity | symbol first, else side + strike | symbol/expiry native | Schwab `symbol` and `expirationDate` are the primary identity sources; `side + strike` matching is a legacy fallback only when the Schwab `symbol` is absent. Add the Schwab `expirationDate` constraint to gate the legacy `side + strike` fallback. | Medium |
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
| MT-006 | `market_data_adapter.py::normalize_bar()` | OHLCV | Missing/unparseable values become `0.0`; aliases accepted | Schwab candles provide `open/high/low/close/volume` | **CLOSED Day 1** — reject incomplete/zero-close; `missing_fields` + `source`. | High |
| MT-007 | `market_data_adapter.py::schwab_candles_to_bars()` | OHLCV | `float(c.get(key, 0) or 0)` | Schwab candles native | **CLOSED Day 1** — routes through `normalize_bar`; `source=schwab_pricehistory`. | High |
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
| UI-007 | `server.py::compute_iwm_confluence(...)` call | `vix_direction` argument | passes non-VIX direction into parameter named `vix_direction` | actual VIX direction available from VIX tracker | rename/pass correct value; add semantic assertion | Medium |
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

## KEY LEVELS sweep closure summary (2026-05-16, branch `feature/institutional-key-levels`)

| Item | Register IDs | Status | Evidence commit(s) |
|------|----------------|--------|-------------------|
| Max-pain mult | DFR-017-REG-MAX-PAIN | CLOSED | `9850a86`, register typo `7b84758` |
| Expiry slice | DFR-005, OP-018 | CLOSED | `64c3641` |
| Multiplier repo-wide | DFR-017 | CLOSED | `0ee94b8` |
| EM synthetic session | DFR-008, DFR-022 | CLOSED | `db91a47` |
| Quote staleness | DFR-007, OP-010 | CLOSED | `4d71167` |
| Theta Schwab-first | OP-008 | CLOSED | `4d71167`, tests `6a25b53` |
| IV extract | OP-013 | CLOSED | `9fdfbe7` |
| UI sticky reset | DFR-015, DFR-024, UI-008, UI-009 | CLOSED | `1a366eb` |
| VIX serialize + IWM arg | DFR-016, UI-006, UI-007 | CLOSED | `1a366eb` |
| GEX completeness | UI-011 | CLOSED | `1a366eb` |
| MC fusion zero-fill | DFR-023 | CLOSED | `1a366eb` |
| Re-audit quote stack | DFR-002/003/004, PQ-001 | CLOSED | `4ef5864` |
| DTE / putCall / parity mid | OP-005, OP-011, OP-014 | VERIFIED | existing Schwab-first paths |
| MC-EM-ANCHOR | MC-EM-ANCHOR (new) | CLOSED | `2439281` — `resolve_mc_iv_for_kl_em_anchor`; `mc_em_anchor`/`mc_iv_source`; MC `iv_level` aligned |
| A2 spread matrix | DFR-006, OP-006, OP-007 | CLOSED | `eb36afe` (`a2_price_precedence.py`); `2439281` (`_oe_bid_ask_mid` mid_source) |
| PQ re-audit | DFR-003, PQ-001 | CLOSED | `4ef5864` — `test_server_quote_source_contract.py` fail-closed spot |
| Zero-OPEN KL sweep | item 19 | CLOSED | `a48f964` — 13 KL data-flow files; 0 forbidden patterns |
| OHLCV bar adapter | DFR-009, DFR-011, MT-006, MT-007, PQ-009, PQ-010, DFR-018 re-audit | CLOSED | `03ca199` — zero OHLCV injection; `missing_fields` + `source` on every bar; synthetic bars tagged |
| Day 1.5 OHLCV pattern repo-wide | DFR-009/011/018/MT-006/007/PQ-009/010 repo-wide | CLOSED | `17ccf30` — pattern swept across 11-file initial finding; `bucket_metric()`; ALLOWLIST in `test_ohlcv_schwab_first.py` |
| Day 1.6 silent-zero pattern family | DFR-009/011/018 repo-wide (family) | CLOSED | `c4825cc` — `.get(x) or 0` + `int/float(x or 0)` family gate; exposure-bucket fixes; file allowlist in `test_ohlcv_schwab_first.py` |
| Order flow + spread | DFR-019, PQ-002/005/007/008/011/012/013, OP-015/017 | CLOSED | `92b85ff` — RVOL fail-closed; spread_pts/frac split; OF volume + VWAP provenance |
| ML feature provenance | DFR-012, DFR-013, MT-002, MT-003, MT-005, MT-008, MT-012 | CLOSED | `c527b82` — per-field `feature_lineage`; fusion `unknown` + fallback flags; LSTM masks; `m5_source_timeframe` |
| Repo-wide register | all non-KL rows | OPEN | MT/OHLCV/deferred paths out of KEY LEVELS scope |
| CAPS silent-default family | DFR-009/011/018 repo-wide (full family) | CLOSED | `cab3ef4` — `tools/anti_pattern_sweep.py` + `test_anti_pattern_family_repo_wide.py`; 108-prefix allowlist |
| Section 1 Schwab client + adapters | DFR-009, DFR-011, PQ-009, PQ-010 | CLOSED | dictionary derivation audit; inventory below; `test_section1_schwab_derivation_audit.py` |

---

## Section 1 derivation audit inventory

Walked 8 files. **14** derivation records (**2** REPLACED with Schwab `pricehistory.candles.*` leaves, **9** KEEP_DERIVED justified, **3** NONE). Source: `governance/section1_derivation_inventory.py`. Tests: `tests/test_section1_schwab_derivation_audit.py`.

<!-- SECTION1_DERIVATION_INVENTORY_START -->
| file | line | derivation | schwab_leaf | disposition | justification |
|---|---|---|---|---|
| schwab_client.py | — | OAuth client / token | — | NONE | No market-field derivations |
| reauth_schwab.py | — | Manual OAuth CLI | — | NONE | No market-field derivations |
| websocket_adapter.py | — | Abstract WS contract | — | NONE | No field reads |
| sse_adapter.py | — | Abstract SSE contract | — | NONE | No field reads |
| polling_adapter.py | 65-66 | pricehistory → bars | pricehistory.candles.* | PASS_THROUGH | schwab_candles_to_bars only |
| polling_adapter.py | 102-110 | camelCase API fallback | pricehistory.candles | KEEP_DERIVED | SDK transport compat |
| market_data_adapter.py | 67-95 | OHLCV read | pricehistory.candles.{open,high,low,close,volume} | REPLACED | Reject if any leaf missing |
| market_data_adapter.py | 86-89 | timestamp | pricehistory.candles.datetime | REPLACED | Schwab path requires datetime |
| market_data_adapter.py | 154-158 | _ts from datetime ms | pricehistory.candles.datetime | KEEP_DERIVED | ms→s conversion only |
| snapshot_normalizer.py | 118-210 | resample_to_1m synthetic OHLC | pricehistory.candles.* (native via polling) | KEEP_DERIVED | Fallback; tagged synthetic |
| snapshot_normalizer.py | 120-125 | open spot proxy | snapshots.spot | KEEP_DERIVED | missing_fields tag |
| snapshot_normalizer.py | 127-151 | high/low spot proxy | snapshots.spot | KEEP_DERIVED | missing_fields tag |
| snapshot_normalizer.py | 168-175 | spot close proxy | snapshots.spot | KEEP_DERIVED | missing_fields tag |
| snapshot_normalizer.py | 204-207 | body/range from OHLC | derived from candles | KEEP_DERIVED | presentation metric |
| snapshot_normalizer.py | 209-211 | vwap_side | — | KEEP_DERIVED | No Schwab vwap_side leaf |
| snapshot_access.py | — | timeframe SQL guard | — | NONE | No field derivations |
<!-- SECTION1_DERIVATION_INVENTORY_END -->

---

## CAPS allowlist (silent-default substitution family)

Source of truth for allowlist rules: `tools/anti_pattern_sweep.py` (`CAPS_PREFIX_ALLOWLIST`, `CAPS_LINE_ALLOWLIST`).  
Regression gate: `tests/test_anti_pattern_family_repo_wide.py` (production `.py` outside `tests/`/`tools/` must have zero unallowlisted hits).

<!-- CAPS_ALLOWLIST_START -->
| file | line | variant | justification |
|---|---:|---|---|
| `tests/` | * | * | test fixtures and gate documentation |
| `tools/` | * | * | scanner/CLI tooling not production data path |
| `calibration/` | * | * | calibration audit SQL aggregates and phase cleanup counters |
| `verification/` | * | * | verification harness diagnostics |
| `arch_competition/` | * | * | offline arch competition harness |
| `adaptive_shadow_v2_calibration.py` | * | * | shadow calibration ranking aggregates |
| `adaptive_similarity_engine.py` | * | * | adaptive similarity pool diagnostics |
| `replay_bundle_coverage.py` | * | * | replay bundle join row-count audit |
| `bar_rehydration_issue19_v1.py` | * | * | rehydration repair counters |
| `db_health_audit.py` | * | * | DB health audit counters |
| `similarity_audit.py` | * | * | similarity trace diagnostics |
| `similarity_feature_search.py` | * | * | shadow feature-search counters |
| `similarity_feature_universe.py` | * | * | feature universe report counters |
| `training_cache.py` | * | * | training manifest fingerprint counters |
| `training_provenance.py` | * | * | training manifest rows_used counter |
| `ml_scheduler.py` | * | * | scheduler manifest skip/row counters |
| `patch_active_artifact_provenance.py` | * | * | artifact patch counters |
| `planes/` | * | * | L1/runtime plane timestamps and version counters |
| `lifecycle_rule_core.py` | * | * | session minutes-since-open derived input |
| `setup_readiness.py` | * | * | readiness display probability coercion |
| `call_engine.py` | * | * | rules-engine display percent coercion |
| `ml_train.py` | * | * | training window max_ts comparison guard |
| `realized_contract_eval.py` | * | * | contract eval PnL + SQL pool counts |
| `liquidity_value_engine.py` | * | * | internal bar _ts sort keys |
| `order_flow_engine.py` | * | * | Schwab print time_millis sort/cutoff |
| `snapshot_normalizer.py` | * | * | materialize row-count audit |
| `market_state.py` | * | * | wall-score audit diff derived metrics |
| `db.py` | * | * | SQL COUNT aggregate int coercion |
| `server.py` | * | * | L1/SSE instrumentation timestamps and volume deltas |
| `monte_carlo.py` | * | * | MC output dict serialization of derived sim metrics |
| `live_vs_replay_validation.py` | * | * | replay validation row counts |
| `live_market_plane.py` | * | * | streaming plane timestamps and carry-forward guards |
| `bayesian_fusion.py` | * | * | fusion stack model-output defaults when sub-model unavailable |
| `features/signal_layer_v1.py` | * | * | derived signal layer counters |
| `features/fusion_policy_contract.py` | * | * | fusion policy prob normalization |
| `api_pressure.py` | * | * | HTTP client status_code getattr default |
| `tier3_design.py` | * | * | design-only similarity documentation |
| `distance_option_a_backfill_v1.py` | * | * | distance backfill counters |
| `inspect_trading_data.py` | * | * | inspection script |
| `feature_contracts.py` | * | * | legacy contract test helpers |
| `signals.py` | * | * | signal orchestration derived defaults (non-Schwab-leaf paths) |
| `prediction_engine.py` | * | * | prediction orchestration derived defaults and empirical pools |
| `multi_horizon_decision.py` | * | * | horizon decision orchestration derived defaults |
| `ml_predict.py` | * | * | inference orchestration derived defaults |
| `live_pipeline_diag.py` | * | * | live pipeline diagnostic counters |
| `lstm_model.py` | * | * | LSTM model wrapper derived defaults |
| `lstm_data.py` | * | * | training dataset builder — zone/vwap sentinels; non-leaf session fields |
| `transformer_model.py` | * | * | transformer wrapper derived defaults |
| `transformer_train.py` | * | * | transformer training script counters |
| `train_all.py` | * | * | training driver counters |
| `train_compare.py` | * | * | training comparison script |
| `verify_ml_pipeline.py` | * | * | ML pipeline verification counters |
| `levels.py` | * | * | legacy levels helper derived defaults |
| `news_sentiment.py` | * | * | news API optional field coercion |
| `mc_fusion_adjustment.py` | * | * | MC fusion adjustment derived metrics |
| `micro_structure.py` | * | * | microstructure derived metrics |
| `movement_target_threshold.py` | * | * | movement target threshold derived metrics |
| `order_flow_live_state.py` | * | * | order-flow live state derived metrics |
| `order_flow_streaming.py` | * | * | order-flow streaming diagnostics |
| `institutional_behavior.py` | * | * | institutional behavior derived metrics |
| `polling_adapter.py` | * | * | polling adapter timestamps |
| `governed_stack_contract.py` | * | * | stack contract validation defaults |
| `math_volatility.py` | * | * | volatility derived metrics |
| `multi_horizon_ml_bundle.py` | * | * | ML bundle orchestration defaults |
| `training_cache_policy.py` | * | * | training cache policy counters |
| `similarity_feature_survivorship.py` | * | * | similarity survivorship audit |
| `similarity_feature_universe.py` | * | * | similarity universe audit |
| `research/` | * | * | research pilot scripts |
| `schwab_full_accessible_field_inventory.py` | * | * | field inventory scanner |
| `schwab_full_field_inventory.py` | * | * | field inventory scanner |
| `v2_decision/` | * | * | v2 decision adapter derived defaults |
| `audit_` | * | * | audit script counters and diagnostics |
| `backfill_` | * | * | backfill script counters |
| `compare_clustering_modes.py` | * | * | clustering comparison CLI |
| `debug_` | * | * | debug utilities |
| `crash_trace.py` | * | * | crash trace env flag |
| `db_authority.py` | * | * | DB authority env flags |
| `db_safety.py` | * | * | sqlite3 constant getattr defaults |
| `feature_contract_validation.py` | * | * | feature contract validation CLI |
| `feature_presence_contract.py` | * | * | feature presence validation CLI |
| `rules_engine.py` | * | * | rules engine display coercion |
| `market_context.py` | * | * | Schwab quote envelope nesting (quote/extended/regular dict shells) |
| `features/inference_snapshot.py` | * | * | SignalInput getattr with None default — fail-closed read |
| `features/monte_carlo_stack_input.py` | * | * | MC stack input derived defaults |
| `features/live_feature_adapter.py` | * | * | live feature adapter optional reads |
| `features/db_feature_adapter.py` | * | * | DB feature adapter optional reads |
| `features/regime_mvp_context.py` | * | * | regime MVP context derived defaults |
| `features/replay_signal_input_v1.py` | * | * | replay signal input derived defaults |
| `features/training_canonical_input.py` | * | * | training canonical merge path |
| `features/xgb_model_input.py` | * | * | XGB tabular envelope path |
| `features/shared_sequence_context.py` | * | * | shared sequence context derived defaults |
| `math_exposure_core.py` | * | * | explicit None branches on bucket aggregates |
| `math_probabilities.py` | * | * | probability derived metrics |
| `features/parallel_stack_schema.py` | * | * | parallel stack prob triplet defaults when probs dict partial |
| `features/fusion_model_input.py` | * | * | explicit unknown semantics for missing zone/vwap (Day 3) |
| `live_decision_bundle.py` | * | * | env config thresholds not Schwab leaves |
| `ml_data_common.py` | * | * | pandas merge empty-frame guards |
| `normalized_training_sync.py` | * | * | training sync env/debounce config |
| `ops_runner.py` | * | * | ops runner env flags |
| `pin_neutral_outcome_repair_v1.py` | * | * | outcome repair CLI |
| `print_liquidity_value_snapshot.py` | * | * | CLI display script |
| `regime_engine.py` | * | * | regime engine micro attribute read |
| `schwab_field_dictionary_builder.py` | * | * | field dictionary builder tooling |
| `math_levels.py` | * | * | structural window index default (non-price) |
| `market_data_adapter.py` | * | * | Schwab timestamp key alias (datetime vs timestamp) not numeric default |
| `smoke_predict_active.py` | * | * | smoke test CLI |
| `ticker_readiness_lookup.py` | * | * | readiness lookup API envelope |
| `verify_snapshot_pipeline.py` | * | * | snapshot pipeline verification counters |
| `xgboost_model.py` | * | * | XGB model prob triplet defaults when partial dict |
| `calibration/v2_advisory_backfill.py` | * | SETDEFAULT | reconstructed Tier C ms dict setdefault for optional blocks |
<!-- CAPS_ALLOWLIST_END -->

---

## Non-Closure Statement

This register is not yet complete. It is the active replacement plan.

```text
repo_wide_derived_field_replacement_status = OPEN
key_levels_input_sweep_status = CLOSED
price_quote_inventory = DRAFTED
option_chain_inventory = DRAFTED
model_training_inventory = DRAFTED
api_ui_inventory = DRAFTED
```

