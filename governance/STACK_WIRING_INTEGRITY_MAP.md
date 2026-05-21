# STACK_WIRING_INTEGRITY_MAP

**Program:** STACK-WIRING-INTEGRITY (OPEN_ITEMS rider @ `0a2e5ee` L148+)  
**Phase 0 seed:** STACK-WIRE-0 @ AUDIT-CAND-SERVER-PY-FULL-READ code `05c48d8`  
**Phase 1 seed:** STACK-WIRE-1 @ producer cone trace (FIND-WIRE1-1..6)  
**Authority:** One row per `surface × field` wiring concern. Phases 1–4 extend this file; sign-off requires money-path roster complete.

**`stack_integrity_v1` UI dispatch (STACK-WIRE-1):** Events with `authority_intact=False` → operator-visible degraded badge; `authority_intact=True` → info-tier (may be silent in UI).

## Schema (required columns — use verbatim for new rows)

| Column | Meaning |
|--------|---------|
| **surface** | Operator-visible category (matches UI vocabulary where possible) |
| **field** | JSON / payload key path |
| **producer** | Module + `file:line` (primary write site) |
| **transport** | How value reaches client (`SSE Tier C`, `SSE fast-quote`, `Tier A`, `HTTP debug`, `N/A`) |
| **client_clock** | Freshness key (`decision_generation_id`, `lastFastTs`, `l1_generation`, `N/A`) |
| **stale_rule** | When UI must withhold / em-dash / not substitute |
| **test** | Regression cite (`tests/...::test_name`) |
| **open_items_id** | `FIND-SERVERPY-N` and/or `STACK-WIRE-*` follow-on |
| **phase_2_3** | `producer-only closed` or paired Phase 2/3 row id |

## Anchor index (navigation)

| Anchor | Scope | First seeded row |
|--------|-------|------------------|
| **Decision Command rail** | Top strip: stack chip, trust badges, headline | FIND-SERVERPY-15 |
| **Card cluster** | Per-hz cards + legacy Call/Put: fusion, IV, pressure, sizing | FIND-SERVERPY-8, 9, 11 |
| **Quote header** | Spot, bid, ask, spread | FIND-SERVERPY-5 |
| **Diagnostic surfaces** | Model Health, `/api/debug/*`, L1 diag exposure | FIND-SERVERPY-14, 19 |

---

## Decision Command rail

| surface | field | producer | transport | client_clock | stale_rule | test | open_items_id | phase_2_3 |
|---------|-------|----------|-------------|--------------|------------|------|---------------|-------------|
| Decision Command rail | `stack_runtime.stack_mode` | `server.py:1993` (`classify_stack_health` in `_attach_stack_runtime_and_governance`) | SSE Tier C (`/api/analytics/state`, `/api/stream`) | `decision_generation_id` + `_server_build_ts` | Enum only: FULL / PARTIAL / DEGRADED / INVALID; never inject non-authority values | `tests/test_audit_cand_server_py_full_read_v1.py::test_stack_mode_value_is_authority_only` | FIND-SERVERPY-15 | producer-only closed @ 05c48d8 |
| Decision Command rail | `stack_runtime.signals_engine_failed` | `server.py:5365-5368` (`sr["signals_engine_failed"] = True` when `ms_dict.signals_engine_failed`) | SSE Tier C | `decision_generation_id` | When true, UI must distinguish signals crash from fusion/MC-only INVALID | `tests/test_audit_cand_server_py_full_read_v1.py::test_stack_mode_value_is_authority_only` | FIND-SERVERPY-15 | **Phase 3:** `STACK-WIRE-3-UI-SIGNALS-ENGINE-FAILED-BADGE` (mid-pipeline events require FIND-WIRE1-2 @ STACK-WIRE-1) |
| Decision Command rail | `decision_generation_id` | `live_decision_bundle.stamp_decision_bundle` (`server.py:5368` call site) | SSE Tier C | `decision_generation_id` | Key always present; `None` when `signals_engine_failed`; check `decision_generation_skipped` first | `tests/test_stack_wire_1_v1.py::test_decision_generation_id_always_present` | STACK-WIRE-1 / FIND-WIRE1-4 |
| Decision Command rail | `decision_timestamp_utc` | same | SSE Tier C | n/a | `None` when signals_engine_failed | (same test) | STACK-WIRE-1 / FIND-WIRE1-4 |
| Decision Command rail | `decision_generation_skipped` | same (`True` on signals_engine_failed) | SSE Tier C | n/a | UI guards on this before comparing `decision_generation_id` | (same test) | STACK-WIRE-1 |
| Decision Command rail | `decision_tick_kind` | same (`"live"` / `"signals_engine_error"`) | SSE Tier C | n/a | Operator-visible tick category | (same test) | STACK-WIRE-1 |
| Decision Command rail | `_server_build_ts` | `server.py:5370` (after `stamp_decision_bundle`) | SSE Tier C / Tier A / fast quote | `lastRenderTimestamp` | Always set, even on signals_engine_failed | `tests/test_stack_wire_1_v1.py::test_server_build_ts_always_set` | STACK-WIRE-1 |
| Decision Command rail | `stack_runtime.fusion_active` | `server.py:1992` (`_attach_stack_runtime_and_governance`) | SSE Tier C | `decision_generation_id` | From `ms_dict["fusion_available"]` | `tests/test_stack_wire_1_v1.py::test_stack_runtime_fields_propagate` | STACK-WIRE-1 |
| Decision Command rail | `stack_runtime.mc_participated` | `server.py:1993` | SSE Tier C | `decision_generation_id` | From `ms_dict["mc_available"]` | (same test) | STACK-WIRE-1 |
| Decision Command rail | `stack_runtime.n_base_models_live` | `server.py:1994` | SSE Tier C | `decision_generation_id` | 0–3 count | (same test) | STACK-WIRE-1 |
| Decision Command rail | `stack_runtime.contributing_models` | `server.py:2000` | SSE Tier C | `decision_generation_id` | From `fusion_contributing_models` or policy cols | (same test) | STACK-WIRE-1 |
| Decision Command rail | `state_error` + `state_error_detail` | `market_state.py:1340-1341` + server minimal-dict paths | SSE Tier C | `decision_generation_id` | Truncated to `STATE_ERROR_DETAIL_MAX_CHARS=120` | `tests/test_stack_wire_1_v1.py::test_state_error_truncation_constant` | STACK-WIRE-1 / FIND-WIRE1-6 |
| Decision Command rail | `stack_integrity_v1` + `stack_integrity_events` | `server.py:5347-5354` (`finalize_stack_integrity_v1` when `ms.stack_integrity_events` non-empty) | SSE Tier C | `decision_generation_id` | Post-FIND-WIRE1-2: mid-pipeline WARNING-tier events included | `tests/test_stack_wire_1_v1.py::test_stack_integrity_v1_propagates_mid_pipeline_events` | STACK-WIRE-1 / FIND-WIRE1-2 |

---

## Card cluster

| surface | field | producer | transport | client_clock | stale_rule | test | open_items_id | phase_2_3 |
|---------|-------|----------|-------------|--------------|------------|------|---------------|-------------|
| Card cluster: Volatility / IV strip | `iv_rank`, `iv_percentile` | `server.py:3128` (`_ed_db` hoist) → `3657-3658` → `4997-4998` | SSE Tier C | `decision_generation_id` | Withhold (em-dash) when `None`; never synthetic IV rank | `tests/test_audit_cand_server_py_full_read_v1.py::test_ed_db_bound_before_iv_rank_references`, `::test_iv_rank_non_none_when_atm_iv_and_db_history` | FIND-SERVERPY-8 | producer-only closed @ 05c48d8 (**Phase 3:** `STACK-WIRE-3-UI-IV-RANK`) |
| Card cluster: canonical provenance | `canonical_provenance` | `signals.canonical_forecast_from_fusion` → `market_state.py` L1535+ → `ms_dict` | SSE Tier C | `decision_generation_id` | `bayesian_fusion` tradable; `fusion_unavailable` / `fusion_directional_missing` / `fusion_directional_invalid` / `debug_override:*` withheld; fail-closed sentinel `canonical_forecast_missing` when `_sig_out.canonical_forecast is None` (FIND-WIRE2-5 — not in `TRADABLE_CANONICAL_PROVENANCE`) | `tests/test_stack_wire_1_v1.py::test_canonical_provenance_enum_complete`, `tests/test_stack_wire_2_v1.py::test_canonical_provenance_fallback_is_fail_closed` | STACK-WIRE-1 / FIND-WIRE2-5 |
| Card cluster: mhap_rows ordering | `mhap_rows[*].horizon` sort key | `market_state.py` L1497 (`enumerate(PRIMARY_DECISION_HORIZONS)`) | SSE Tier C | `decision_generation_id` | Row order follows authority horizon list, not hardcoded rank dict | `tests/test_stack_wire_2_v1.py::test_market_state_mhap_rank_derived_from_primary_decision_horizons` | FIND-WIRE2-1 |
| Card cluster: Position sizing strip | `r_units` | `signal_types.TheCall` (default `None`) → `call_engine.compute_position_size` → `market_state.py:1433` → `server.py:4569` / `5057` | SSE Tier C | `decision_generation_id` | `None` = call_engine path not reached (no `_call`); `0.0` = explicit NO_TRADE / wait from sizing; `(0.0, 1.25]` = sized trade | `tests/test_stack_wire_1_v1.py::test_r_units_none_propagates_end_to_end`, `tests/test_stack_wire_3_v1.py::test_exec_mode_derives_from_exec_modes_dict` | FIND-WIRE1-1-CALLCARD + FIND-WIRE3-3; **Phase 3:** `STACK-WIRE-3-UI-R-UNITS-NONE` |
| Card cluster: Call / Put readiness | `readiness_component_scores` / `structure_higher_tf` input | `prediction_engine._timeframe_reads` writes `60m` → `call_engine.compute_call` `_tf.get("60m")` → `setup_readiness` | SSE Tier C | `decision_generation_id` | Was silent-empty when consumer used legacy `"1h"` key (FIND-WIRE3-1) | `tests/test_stack_wire_3_v1.py::test_call_engine_reads_timeframe_60m_not_legacy_1h`, `::test_no_legacy_timeframe_keys_in_call_engine_consumer_source` | FIND-WIRE3-1 |
| Card cluster: Pressure / DPI strip | `pressure_label` (snapshot + `ms_dict`) | `server.py:4296` (`unavailable_no_dpi_or_hedging_flow_direction`) | SSE Tier C | `decision_generation_id` | Treat `unavailable_*` as withheld, not neutral styling | `tests/test_audit_cand_server_py_full_read_v1.py::test_pressure_label_unavailable_when_no_dpi_or_hedging_flow` | FIND-SERVERPY-9 | **Phase 3:** `STACK-WIRE-3-UI-PRESSURE-UNAVAILABLE` (grep verify; likely fast close) |

---

## Quote header

| surface | field | producer | transport | client_clock | stale_rule | test | open_items_id | phase_2_3 |
|---------|-------|----------|-------------|--------------|------------|------|---------------|-------------|
| Quote header / spread chip | `spread`, `spread_semantic` | `server.py:838-839` (fraction fast quote), `3052-3053` (dollar Tier A) | SSE fast-quote + Tier A (`/api/live/state`) | `lastFastTs` | Dispatch on `spread_semantic`; missing key → legacy back-compat | `tests/test_audit_cand_server_py_full_read_v1.py::test_spread_semantic_stamped_on_fast_quote_and_tier_a` | FIND-SERVERPY-5 | **Phase 3:** `STACK-WIRE-3-UI-SPREAD-SEMANTIC` (`index.html` L5341 documents unit split but no `spread_semantic` dispatch) |

---

## Diagnostic surfaces

| surface | field | producer | transport | client_clock | stale_rule | test | open_items_id | phase_2_3 |
|---------|-------|----------|-------------|--------------|------------|------|---------------|-------------|
| Diagnostic: Model Health panel | `model_health[*].edge`, `.version` | `server.py:5196-5213` (`json.loads` L5136 arch + L5207 meta) | SSE Tier C | `decision_generation_id` | On meta load failure: status enum + `0` / `"—"` (not silent NameError) | `tests/test_audit_cand_server_py_full_read_v1.py::test_no_underscore_json_references` | FIND-SERVERPY-14 | producer-only closed @ 05c48d8 (`index.html` L5987+ consumes `model_health`) |
| Diagnostic: `/api/debug/prediction` | `db_zone_distribution` | `server.py:7414` → `db.py:3705` (`get_zone_distribution`) | HTTP GET one-shot | N/A | Empty dict OK; no error trace | `tests/test_audit_cand_server_py_full_read_v1.py::test_debug_prediction_returns_populated_distribution` | FIND-SERVERPY-19 | producer-only closed |

---

## Internal / hygiene (no live operator surface)

| surface | field | producer | transport | client_clock | stale_rule | test | open_items_id | phase_2_3 |
|---------|-------|----------|-------------|--------------|------------|------|---------------|-------------|
| Internal | `_CandleAccumulator.max_bars` | `server.py:1121` (required arg) | N/A | N/A | Must pass authority `CANDLE_*_MAX_BARS` from callers | `tests/test_audit_cand_server_py_full_read_v1.py::test_candle_accumulator_max_bars_required` | FIND-SERVERPY-1 | producer-only closed |
| Internal | `_PRIMARY_UI_HORIZON_MINUTES` | `server.py:1872`, used `1915` | N/A | N/A | Derived from `PRIMARY_DECISION_HORIZONS` only | `tests/test_audit_cand_server_py_full_read_v1.py::test_filter_horizon_prob_bars_derived_from_primary_decision_horizons` | FIND-SERVERPY-2 | producer-only closed |
| Internal | `MARKET_CLOSE_HOUR` | `server.py:2219` | N/A | N/A | No literal `hour=16` | `tests/test_audit_cand_server_py_full_read_v1.py::test_market_close_uses_market_close_hour_constant` | FIND-SERVERPY-3 | producer-only closed |
| Internal | `RTH_OPEN_MINS` | `server.py:1060`, `2359` | N/A | N/A | No `9*60+30` / `16*60` literals in `_update_rest_cum_delta` | `tests/test_audit_cand_server_py_full_read_v1.py::test_rth_open_mins_constant_exists_and_used` | FIND-SERVERPY-4 | producer-only closed |
| Internal | `PRICE_LEVELS_CACHE_SEC` | `server.py:1108`, `3531` | N/A | N/A | Module-level constant only | `tests/test_audit_cand_server_py_full_read_v1.py::test_price_levels_cache_sec_at_module_level` | FIND-SERVERPY-6 | producer-only closed |
| Internal | `_l1_next_generation` | `server.py:2474-2483` | N/A | N/A | `RuntimeError` on regression (survives `python -O`) | `tests/test_audit_cand_server_py_full_read_v1.py::test_l1_next_generation_regression_raises_runtime_error_not_assert` | FIND-SERVERPY-7 | producer-only closed |
| Internal | `MC_EM_PRE_BMS` log | absent | N/A | N/A | No WARNING-level MC em trace | `tests/test_audit_cand_server_py_full_read_v1.py::test_no_mc_em_pre_bms_warning_log` | FIND-SERVERPY-12 | producer-only closed |
| Internal | `RECENT_CROSSES_DISPLAY_LIMIT` | `server.py:1107`, `3961` | N/A | N/A | Magic `n=5` banned | `tests/test_audit_cand_server_py_full_read_v1.py::test_recent_crosses_uses_named_constant` | FIND-SERVERPY-13 | producer-only closed |
| Internal | `liquidity_zone_tradeable_score` | `liquidity_value_engine.py:59-71`; callers `server.py:7023`, `7036` | N/A | N/A | Weights live in engine module only | `tests/test_audit_cand_server_py_full_read_v1.py::test_tradeable_score_calls_liquidity_engine_authority` | FIND-SERVERPY-18 | producer-only closed |
| Internal | `RTH_OPEN_MINS` | `time_et.py` (`RTH_OPEN_MINS = RTH_START_MINS`); consumers `server.py`, `call_engine._stop_distance`, `prediction_engine.build_fusion_model_overlay_for_stack` | N/A | N/A | Single authority for 9:30 ET open (570 mins); no bare `570` in call_engine / overlay | `tests/test_stack_wire_3_v1.py::test_rth_open_mins_single_authority_call_engine_prediction_engine` | FIND-WIRE3-2 |
| API input | `direction` (`/api/prediction/override`) | `server.py:6832-6834` | HTTP POST | N/A | Empty → HTTP 400; no silent `"flat"` | `tests/test_audit_cand_server_py_full_read_v1.py::test_prediction_override_rejects_empty_direction` | FIND-SERVERPY-17 | producer-only closed |

---

## Phase 0 housekeeping (STACK-WIRE-0)

| Item | Site | Action |
|------|------|--------|
| Stale diag markers | `server.py` (was L3938-3941) | Removed `pre_get_db` / `get_db` wraps; `pre_db_counts` / `db_counts` at L3938 / L3971 remain |
| Commit-body tiers | N/A | Use Critical / Semantic / Hygiene (not HIGH/MEDIUM) going forward |

## Demoted slots (not ingested)

| Slot | Status |
|------|--------|
| Serverpy slot 10 | Demoted — not in 17-real set |
| Serverpy slot 16 | Demoted — not in 17-real set |
