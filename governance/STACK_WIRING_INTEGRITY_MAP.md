# STACK_WIRING_INTEGRITY_MAP

**Program:** STACK-WIRING-INTEGRITY (OPEN_ITEMS rider @ `0a2e5ee` L148+)  
**Phase 0 seed:** STACK-WIRE-0 @ AUDIT-CAND-SERVER-PY-FULL-READ code `05c48d8`  
**Authority:** One row per `surface × field` wiring concern. Phases 1–4 extend this file; sign-off requires money-path roster complete.

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
| Decision Command rail | `stack_runtime.signals_engine_failed` | `server.py:5365-5368` (`sr["signals_engine_failed"] = True` when `ms_dict.signals_engine_failed`) | SSE Tier C | `decision_generation_id` | When true, UI must distinguish signals crash from fusion/MC-only INVALID | `tests/test_audit_cand_server_py_full_read_v1.py::test_stack_mode_value_is_authority_only` | FIND-SERVERPY-15 | **Phase 3:** `STACK-WIRE-3-UI-SIGNALS-ENGINE-FAILED-BADGE` (no `static/index.html` consumer yet) |

---

## Card cluster

| surface | field | producer | transport | client_clock | stale_rule | test | open_items_id | phase_2_3 |
|---------|-------|----------|-------------|--------------|------------|------|---------------|-------------|
| Card cluster: Volatility / IV strip | `iv_rank`, `iv_percentile` | `server.py:3128` (`_ed_db` hoist) → `3657-3658` → `4997-4998` | SSE Tier C | `decision_generation_id` | Withhold (em-dash) when `None`; never synthetic IV rank | `tests/test_audit_cand_server_py_full_read_v1.py::test_ed_db_bound_before_iv_rank_references`, `::test_iv_rank_non_none_when_atm_iv_and_db_history` | FIND-SERVERPY-8 | producer-only closed @ 05c48d8 (**Phase 3 verify:** no `static/index.html` grep for keys — confirm card bind in prod or open UI row) |
| Card cluster: Pressure / DPI strip | `pressure_label` (snapshot + `ms_dict`) | `server.py:4296` (`unavailable_no_dpi_or_hedging_flow_direction`) | SSE Tier C | `decision_generation_id` | Treat `unavailable_*` as withheld, not neutral styling | `tests/test_audit_cand_server_py_full_read_v1.py::test_pressure_label_unavailable_when_no_dpi_or_hedging_flow` | FIND-SERVERPY-9 | **Phase 3:** `STACK-WIRE-3-UI-PRESSURE-UNAVAILABLE` (grep verify; likely fast close) |
| Card cluster: Position sizing strip | `r_units` | `server.py:4569` (snapshot), `5057` (response) | SSE Tier C + snapshot row | `decision_generation_id` | UI treats `None` as withheld, not `0.0` | `tests/test_audit_cand_server_py_full_read_v1.py::test_r_units_none_default_not_zero_float` | FIND-SERVERPY-11 | **Phase 3:** `STACK-WIRE-3-UI-R-UNITS-NONE` |

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
