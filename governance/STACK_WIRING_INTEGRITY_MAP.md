> **Classification:** Operational Ledger | **Scope:** Governance register/inventory `STACK_WIRING_INTEGRITY_MAP.md`.

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
| Decision Command rail | `stack_runtime.stack_mode` | `server.py:1999` (`classify_stack_health` in `_attach_stack_runtime_and_governance`; single call site per `tests/test_stack_wire_4_v1.py`; **STACK-WIRE-4-CAND**: `fusion_available` arg is `is_ms_dict_fusion_authoritative(ms_dict)`, not the bare `fusion_available` flag — closes the split-brain case where `fusion_available=True` + non-tradable `canonical_provenance` lied to the operator) | SSE Tier C (`/api/analytics/state`, `/api/stream`) | `decision_generation_id` + `_server_build_ts` | Enum only: FULL / PARTIAL / DEGRADED / INVALID; never inject non-authority values. **UI consumers (4 sites):** `#dr-stack-mode-chip` + `stack_runtime` reads in `static/index.html` ~L3780, ~L4119, ~L6369, INVALID title ~L6436. `signals_engine_failed` sibling ~L5362-5365 → dedicated chip `#dr-signals-engine-fail-chip` updated by `_updateSignalsEngineFailChip(integrity)` (STACK-WIRE-3-UI-SIGNALS-ENGINE-FAILED-BADGE @ `be67e57`). **v2_decision:** `is_ms_dict_fusion_authoritative` in `a1_raw_probability.py` + `module_a_adapter.py` | `tests/test_audit_cand_server_py_full_read_v1.py::test_stack_mode_value_is_authority_only`, `tests/test_stack_wire_4_v1.py`, `tests/test_stack_wire_1_v1.py::test_stack_runtime_fusion_active_uses_tradability_gate_not_bare_flag` | FIND-SERVERPY-15 + STACK-WIRE-4 + STACK-WIRE-4-CAND | producer-only closed @ 05c48d8 (CAND closed this commit) |
| Decision Command rail | `stack_runtime.signals_engine_failed` | `server.py:5365-5368` (`sr["signals_engine_failed"] = True` when `ms_dict.signals_engine_failed`) | SSE Tier C | `decision_generation_id` | **STACK-WIRE-3-UI-SIGNALS-ENGINE-FAILED-BADGE @ `be67e57`:** dedicated chip `#dr-signals-engine-fail-chip` next to `#dr-stack-mode-chip`; `_refreshLiveUiIntegrityDerivations` stamps `signalsEngineFailed = (rt.signals_engine_failed === true)`; `_updateSignalsEngineFailChip(integrity)` shows "SIGNALS ENGINE FAILED" (`.decision-chip.bad`) when true and hides otherwise — chip is independent of `stack_mode` so signals crash is distinct from fusion/MC-only INVALID. | `tests/test_audit_cand_server_py_full_read_v1.py::test_stack_mode_value_is_authority_only` (producer), `tests/test_stack_wire_3_ui_phase3_closure.py::test_wire3_ui_signals_engine_failed_badge_present` (static), `tests/e2e/stack-wire-3-ui-phase3-behavioral.spec.js::dr-signals-engine-fail-chip surfaces signals_engine_failed=true distinctly from stack INVALID` (behavioral: chip visible+text+class on true, hidden on false even when stack_mode=INVALID) | FIND-SERVERPY-15 + STACK-WIRE-3-UI-SIGNALS-ENGINE-FAILED-BADGE | producer + consumer closed |
| Decision Command rail | `decision_generation_id` | `live_decision_bundle.stamp_decision_bundle` (`server.py:5368` call site) | SSE Tier C | `decision_generation_id` | Key always present; `None` when `signals_engine_failed`; check `decision_generation_skipped` first | `tests/test_stack_wire_1_v1.py::test_decision_generation_id_always_present` | STACK-WIRE-1 / FIND-WIRE1-4 |
| Decision Command rail | `decision_timestamp_utc` | same | SSE Tier C | n/a | `None` when signals_engine_failed | (same test) | STACK-WIRE-1 / FIND-WIRE1-4 |
| Decision Command rail | `decision_generation_skipped` | same (`True` on signals_engine_failed) | SSE Tier C | n/a | UI guards on this before comparing `decision_generation_id` | (same test) | STACK-WIRE-1 |
| Decision Command rail | `decision_tick_kind` | same (`"live"` / `"signals_engine_error"`) | SSE Tier C | n/a | Operator-visible tick category | (same test) | STACK-WIRE-1 |
| Decision Command rail | `_server_build_ts` | `server.py:5370` (after `stamp_decision_bundle`) | SSE Tier C / Tier A / fast quote | `lastRenderTimestamp` | Always set, even on signals_engine_failed | `tests/test_stack_wire_1_v1.py::test_server_build_ts_always_set` | STACK-WIRE-1 |
| Decision Command rail | `stack_runtime.fusion_active` | `server.py:1996` (`_attach_stack_runtime_and_governance`) | SSE Tier C | `decision_generation_id` | **STACK-WIRE-4-CAND**: derived from `fusion_contract.is_ms_dict_fusion_authoritative(ms_dict)` — requires BOTH `fusion_available=True` AND `canonical_provenance ∈ TRADABLE_CANONICAL_PROVENANCE` ({"bayesian_fusion"}). Bare `fusion_available` flag alone is insufficient; split-brain cases (e.g., `canonical_forecast_missing`) resolve to `False` + `stack_mode=INVALID`. **STACK-WIRE-3-UI-FUSION-TRADABILITY-GATE**: UI mirror is `isFusionAuthoritative(d)` in `static/index.html` (reads `rt.fusion_active` first, legacy fallback gates on `fusion_available && canonical_provenance==="bayesian_fusion"`); adopted at `dr-stack-fusion` chip, `resolveSignalChain` FUSION step, and `effectiveDirection` direction selector. | `tests/test_stack_wire_1_v1.py::test_stack_runtime_fields_propagate`, `tests/test_stack_wire_1_v1.py::test_stack_runtime_fusion_active_uses_tradability_gate_not_bare_flag`, `tests/test_stack_wire_4_cand_ui_fusion_gate.py` (4 static-HTML guards), `tests/e2e/stack-wire-4-cand-ui-fusion-gate.spec.js` (2 behavioral specs) | STACK-WIRE-1 + STACK-WIRE-4-CAND + STACK-WIRE-3-UI-FUSION-TRADABILITY-GATE |
| Decision Command rail | `stack_runtime.mc_participated` | `server.py:1997` | SSE Tier C | `decision_generation_id` | From `ms_dict["mc_available"]` | (same first test) | STACK-WIRE-1 |
| Decision Command rail | `stack_runtime.n_base_models_live` | `server.py:1998` | SSE Tier C | `decision_generation_id` | 0–3 count | (same first test) | STACK-WIRE-1 |
| Decision Command rail | `stack_runtime.contributing_models` | `server.py:2004` | SSE Tier C | `decision_generation_id` | From `fusion_contributing_models` or policy cols | (same first test) | STACK-WIRE-1 |
| Decision Command rail | `state_error` + `state_error_detail` | `market_state.py:1340-1341` + server minimal-dict paths | SSE Tier C | `decision_generation_id` | Truncated to `STATE_ERROR_DETAIL_MAX_CHARS=120` | `tests/test_stack_wire_1_v1.py::test_state_error_truncation_constant` | STACK-WIRE-1 / FIND-WIRE1-6 |
| Decision Command rail | `stack_integrity_v1` + `stack_integrity_events` | `server.py:5347-5354` (`finalize_stack_integrity_v1` when `ms.stack_integrity_events` non-empty) | SSE Tier C | `decision_generation_id` | Post-FIND-WIRE1-2: mid-pipeline WARNING-tier events included | `tests/test_stack_wire_1_v1.py::test_stack_integrity_v1_propagates_mid_pipeline_events` | STACK-WIRE-1 / FIND-WIRE1-2 |

---

## Card cluster

| surface | field | producer | transport | client_clock | stale_rule | test | open_items_id | phase_2_3 |
|---------|-------|----------|-------------|--------------|------------|------|---------------|-------------|
| Card cluster: Volatility / IV strip | `iv_rank`, `iv_percentile` | `server.py:3128` (`_ed_db` hoist) → `3657-3658` → `4997-4998` | SSE Tier C | `decision_generation_id` | **STACK-WIRE-3-UI-IV-RANK @ `be67e57`:** `renderContextLayer` binds `d.iv_rank` / `d.iv_percentile` to `#ctx-iv-rank` / `#ctx-iv-percentile` in the "Volatility regime" subsection; helper `_fmtIvBp(v)` → `'—'` for null/NaN (withheld, never substituted), zero → `'0'` (real lowest-on-record value). | `tests/test_audit_cand_server_py_full_read_v1.py::test_ed_db_bound_before_iv_rank_references`, `::test_iv_rank_non_none_when_atm_iv_and_db_history` (producer), `tests/test_stack_wire_3_ui_phase3_closure.py::test_wire3_ui_iv_rank_bound_with_withhold_semantic` (static), `tests/e2e/stack-wire-3-ui-phase3-behavioral.spec.js::renderContextLayer binds iv_rank / iv_percentile with em-dash withhold (not zero)` (behavioral) | FIND-SERVERPY-8 + STACK-WIRE-3-UI-IV-RANK | producer + consumer closed |
| Card cluster: canonical provenance | `canonical_provenance` | `signals.canonical_forecast_from_fusion` → `market_state.py` L1535+ → `ms_dict` | SSE Tier C | `decision_generation_id` | `bayesian_fusion` tradable; `fusion_unavailable` / `fusion_directional_missing` / `fusion_directional_invalid` / `debug_override:*` withheld; fail-closed sentinel `canonical_forecast_missing` when `_sig_out.canonical_forecast is None` (FIND-WIRE2-5 — not in `TRADABLE_CANONICAL_PROVENANCE`) | `tests/test_stack_wire_1_v1.py::test_canonical_provenance_enum_complete`, `tests/test_stack_wire_2_v1.py::test_canonical_provenance_fallback_is_fail_closed` | STACK-WIRE-1 / FIND-WIRE2-5 |
| Card cluster: mhap_rows ordering | `mhap_rows[*].horizon` sort key | `market_state.py` L1497 (`enumerate(PRIMARY_DECISION_HORIZONS)`) | SSE Tier C | `decision_generation_id` | Row order follows authority horizon list, not hardcoded rank dict | `tests/test_stack_wire_2_v1.py::test_market_state_mhap_rank_derived_from_primary_decision_horizons` | FIND-WIRE2-1 |
| Card cluster: Position sizing strip | `r_units` | `signal_types.TheCall` (default `None`) → `call_engine.compute_position_size` → `market_state.py:1433` → `server.py:4569` / `5057` | SSE Tier C | `decision_generation_id` | `None` = call_engine path not reached (no `_call`); `0.0` = explicit NO_TRADE / wait from sizing; `(0.0, 1.25]` = sized trade. **STACK-WIRE-3-UI-R-UNITS-NONE withhold-by-absence closed @ `be67e57`:** UI does NOT bind `r_units` to any DOM surface → None is trivially withheld; guard test locks against future bind substituting 0 for None. | `tests/test_stack_wire_1_v1.py::test_r_units_none_propagates_end_to_end`, `tests/test_stack_wire_3_v1.py::test_exec_mode_derives_from_exec_modes_dict`, `tests/test_stack_wire_3_ui_phase3_closure.py::test_wire3_ui_r_units_none_treated_as_withheld` | FIND-SERVERPY-11 + FIND-WIRE1-1-CALLCARD + FIND-WIRE3-3 + STACK-WIRE-3-UI-R-UNITS-NONE | producer + consumer closed |
| Card cluster: Call / Put readiness | `readiness_component_scores` / `structure_higher_tf` input | `prediction_engine._timeframe_reads` writes `60m` → `call_engine.compute_call` `_tf.get("60m")` → `setup_readiness` | SSE Tier C | `decision_generation_id` | Was silent-empty when consumer used legacy `"1h"` key (FIND-WIRE3-1) | `tests/test_stack_wire_3_v1.py::test_call_engine_reads_timeframe_60m_not_legacy_1h`, `::test_no_legacy_timeframe_keys_in_call_engine_consumer_source` | FIND-WIRE3-1 |
| Card cluster: Pressure / DPI strip | `pressure_label` (snapshot + `ms_dict`) | `server.py:4296` (`unavailable_no_dpi_or_hedging_flow_direction`) | SSE Tier C | `decision_generation_id` | Treat `unavailable_*` as withheld, not neutral styling. **STACK-WIRE-3-UI-PRESSURE-UNAVAILABLE withhold-by-absence closed @ `be67e57`:** UI does NOT bind `pressure_label` to any DOM surface → the sentinel string is trivially withheld; guard test locks against future bind without an explicit withhold check on the sentinel. | `tests/test_audit_cand_server_py_full_read_v1.py::test_pressure_label_unavailable_when_no_dpi_or_hedging_flow`, `tests/test_stack_wire_3_ui_phase3_closure.py::test_wire3_ui_pressure_label_unavailable_treated_as_withheld` | FIND-SERVERPY-9 + STACK-WIRE-3-UI-PRESSURE-UNAVAILABLE | producer + consumer closed |

---

## Quote header

| surface | field | producer | transport | client_clock | stale_rule | test | open_items_id | phase_2_3 |
|---------|-------|----------|-------------|--------------|------------|------|---------------|-------------|
| Quote header / spread chip | `spread`, `spread_semantic` | `server.py:838-839` (fraction fast quote), `3052-3053` (dollar Tier A) | SSE fast-quote + Tier A (`/api/live/state`) | `lastFastTs` | **STACK-WIRE-3-UI-SPREAD-SEMANTIC @ `be67e57`:** UI consumer `computeSpreadGate(inp)` in `static/index.html` dispatches on `d.spread_semantic` — `"fraction"` → unit-less gate (`spread < 0.05`, no `/spot` conversion), `"dollar"` → dollar-width gate, absent → legacy heuristic. Single authority called from `render()`. SPD gate label/ok feed `#gate-pills` row. | `tests/test_audit_cand_server_py_full_read_v1.py::test_spread_semantic_stamped_on_fast_quote_and_tier_a` (producer), `tests/test_stack_wire_3_ui_phase3_closure.py::test_wire3_ui_spread_semantic_consumer_dispatch` (static), `tests/e2e/stack-wire-3-ui-phase3-behavioral.spec.js::computeSpreadGate dispatches on producer-stamped spread_semantic` (behavioral: fraction OK/BAD, dollar, heuristic, withheld) | FIND-SERVERPY-5 + STACK-WIRE-3-UI-SPREAD-SEMANTIC | producer + consumer closed |

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
| Internal | `RTH_OPEN_MINS` / `RTH_SESSION_MINUTES` | `time_et.py` (`RTH_OPEN_MINS = RTH_START_MINS`, `RTH_SESSION_MINUTES = RTH_END_MINS - RTH_START_MINS`); consumers `server.py`, `call_engine._stop_distance`, `prediction_engine.build_fusion_model_overlay_for_stack`, `order_flow_live_state.is_rth_open`, `replay_hold_bars.replay_max_hold_bars_from_context` | N/A | N/A | Single authority for 9:30 ET open (570 mins) + RTH session length (390 1m bars); no bare `9*60+30` in OF RTH gate; no bare `390` in replay hold cap | `tests/test_stack_wire_3_v1.py`, `tests/test_stack_wire_5_v1.py`, `tests/test_stack_wire_6_v1.py` | FIND-WIRE3-2 + FIND-WIRE5-1 + FIND-WIRE6-1 |
| Internal | `replay_max_hold_bars` | `replay_hold_bars.py` (`TRADE_TYPE_HOLD_BARS` dict + `MICRO_REGIME_HOLD_BARS_COMPRESSION`; functions `_for_setup` / `_for_trade_type` / `_from_context` / `resolve_*`); consumers `call_engine.py:1655` (`_for_setup`), `realized_contract_eval.py` (`build_replay_context_payload` → `resolve_*`; `_evaluate_realized_contract_trades_for_rows` → `_from_context`) | N/A | N/A | `for_setup` + `for_trade_type` MUST agree on shared trade_types via single `TRADE_TYPE_HOLD_BARS` dict; `trade_type="none"` returns 0 in BOTH paths (FIND-WIRE6-2 parity); `from_context` caps via `RTH_SESSION_MINUTES` | `tests/test_stack_wire_6_v1.py`, `tests/test_replay_hold_bars.py` | FIND-WIRE6-2 |
| Internal | `chains.callExpDateMap.*.multiplier` / `chains.putExpDateMap.*.multiplier` | Schwab leaf; consumer `realized_contract_eval._contract_multiplier(ct)` — read per chain row in `_contract_pnl_at_horizon` + `_evaluate_realized_contract_trades_for_rows` (entry_ct multiplier path) | SSE Tier C / archived `option_chain_json` | n/a | Three-way semantics per **GOVERNED_EXCEPTION O-54**: (a) leaf PRESENT + valid → return Schwab int authority; (b) leaf ABSENT (key not in row or None) → return `LEGACY_CHAIN_MULTIPLIER_DEFAULT = 100` (archived pre-multiplier-emission snapshots; legacy SPY/QQQ/IWM equity); (c) leaf PRESENT but INVALID (zero / negative / non-numeric) → return None, fail-closed, new "missing_multiplier" skip-reason in trade log. Modern (post-emission) captures use the leaf directly. Sunset of O-54 fallback: when legacy snapshots backfilled OR aged out. | `tests/test_stack_wire_6b_v1.py::test_contract_multiplier_reads_schwab_leaf_with_legacy_fallback` | FIND-WIRE6-3 + O-54 |
| Internal | `REPLAY_BUNDLE_MIN_JSON_LENGTH` | `replay_bundle_coverage.py` (`REPLAY_BUNDLE_MIN_JSON_LENGTH = 10`); consumers `realized_contract_eval.compute_replay_coverage_stats`, `live_vs_replay_validation` (count + select SQL), `tools/measure_post_fix_theta_v1` (snapshots iterator) | N/A | N/A | Single authority for `length(<json>) > N` non-trivial-bundle predicate; no bare `> 10` in consumer SQL | `tests/test_stack_wire_6b_v1.py::test_replay_bundle_min_json_length_authority_and_adoption` | FIND-WIRE6-5 |
| Card cluster: Order flow strip | `order_flow_score`, `order_flow_direction` | `order_flow_engine.OrderFlowEngine.compute` → `server` ms_dict → `call_engine` `of_vote` | SSE L1 light + Tier C | `order_flow_as_of_ts` / `order_flow_age_sec` (OF wall-clock) vs `decision_generation_id` (Tier C bundle) | OF staleness via `order_flow_stale`; Tier C freshness separate — `_l1_attach_freshness_semantics` | `tests/test_stack_wire_5_v1.py` | FIND-WIRE5-2..3 |
| Decision Command: stack vote layer | `order_flow` stack vote | `call_engine` reads `inp.order_flow_direction` only (no second OF score derivation) | SSE Tier C | `decision_generation_id` | Fail-closed neutral vote when direction missing | `tests/test_stack_wire_5_v1.py` | FIND-WIRE5-2 |
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
