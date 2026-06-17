> **Classification:** Policy Specification | **Scope:** Governance documentation `call_engine.py.md`.

# Review memo — call_engine.py

**Status:** pending gatekeeper review
**Date:** 2026-05-24
**Reviewer:** Claude (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)
**File language family:** python
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)**

**Closest-shape precedent** (per `AGENTS.md` Posture rules — sibling-pattern conformance, 2026-05-24): `signals.py.md` — exact shape match. Every site in this file is **NOT_MARKET_DATA at the Schwab wire-token layer** because no `q_json` / `c_json` / `pricehistory` / `streaming.content.*` keys are subscripted in-file. Schwab-sourced values arrive as already-populated dataclass attributes on `SignalInput` / `CanonicalForecast` / `fusion` / `regime` / `vol_regime`, set upstream in `market_state.build_market_state` and fusion / regime engines (dispositioned in their own memos).

**Active-posture Class A check** (per `AGENTS.md` §Active agent posture, 2026-05-24): no Schwab-replaceable derivation, no non-canonical fallback, no in-file FIND that would require a code change. **Memo-only commit is admissible under Class A — no fixable code debt is documented.** This is not a "gatekeeper pending = fix parking" violation; there is genuinely nothing to bundle.

---

---

## Gatekeeper CSV cross-check (retroactive @ 977e706, 2026-05-24)

**Tool:** \python tools/check_schwab_csv_first.py --gatekeeper-crosscheck call_engine.py\n**lexical_csv_collision_count:** 36

Retroactive full-CSV AST cross-check. Prior memo dispositions unchanged; homonym collisions classified in original site sections. Zero new wire FIND from cross-check.

## Audit methodology (clause 4 — attribute / call / subscript)

Audited **this file** for:

| Channel | Method |
|---------|--------|
| String-literal dict access on Schwab payloads | None — file does not subscript any Schwab JSON payload. |
| Bracket dict access on Schwab payloads | None. |
| Attribute access on market-bearing objects | `inp.<attr>` on `SignalInput` (spot / vix_level / call_gamma_wall / put_gamma_wall / vwap / atr / net_delta / iv_level / iv_direction / charm_direction / charm_drift_toward / spy_chg_pct / qqq_chg_pct / iwm_chg_pct / spy_weighted_push / qqq_weighted_push / iwm_weighted_push / order_flow_direction / event_risk_level / et_hour / et_minute / mins_to_close / dex_magnitude / charm_magnitude / put_call_oi_ratio / zone_since_bars{,_1m,_5m} / prev_zone / dist_call_gamma_wall / dist_put_gamma_wall / dist_gamma_inflection / ticker); `getattr(fusion, X)` / `getattr(canonical, X)` / `getattr(regime, X)` / `getattr(vol_regime, X)` / `getattr(micro, X)` / `getattr(pred, X)` — all Python dataclass / object attributes, not Schwab JSON keys. |
| Method calls passing Schwab market objects | None — calls pass `inp` / `fusion` / `canonical` / `vol_regime` / `regime` / `micro` / `pred` / `mh_policy` / `rules` / `mvp_features` (internal Python objects). |
| Internal projection-key reads (NOT Schwab wire) | `mvp_zone(mvp_features)` / `mvp_nearest_distances_for_regime(mvp_features)` reads under MVP feature namespace; `wait_blocker.get("reason"|"long_count"|"short_count"|"threshold"|"long_names"|"short_names"|"detail"|"full_detail"|"gate_reasons")`; `stack_votes` dict keys (`"micro"`/`"Greeks"`/`"spy_basket"`/`"qqq_basket"`/`"iwm_basket"`/`"regime"`/`"fusion"`/`"order_flow"`/`"multi_horizon"`); sizing / readiness internal dict keys. None of these literals match any row in `schwab_field_inventory/schwab_field_dictionary.csv`. |

**Review complete:** Every site **in this file** falls under **S1–S10** below; no Schwab `example_raw_field` tokens, chain JSON subscripts, or streaming content keys occur anywhere in `call_engine.py`.

---

## Market-data sites identified

### S1 — Module imports + sizing / conviction / gate / VIX / MC / RR / time / level / cross-instrument / MH-tier / wait-blocker constants

- **lines:** L1–162.
- **surface:** Imports (L1–32); module logger (L34); ~120 named float / int / str constants for stack thresholds, conviction tiers, time warnings, validate-trade gates, sizing pipeline (confidence / model agreement / VIX vol mult / ATR / MC EAE-EFE / level quality / RR floor / time mult), level proximity, conviction downgrade triggers, cross-instrument signal cuts, MH size tier mods, and `WAIT_BLOCKER_REASON_*` enum-strings (L156–161).
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — decision-policy thresholds, not Schwab JSON keys. No literal matches in `schwab_field_inventory/schwab_field_dictionary.csv`.
- **evidence:** All constants are operator-tunable threshold values (e.g., `STACK_THRESHOLD_DEFAULT = 2`, `VIX_ELEVATED_THRESHOLD = 25.0`, `R_UNITS_CAP = 1.25`) — Phase 6 ablation surface per `STACK-WIRE-3` comment at L36. None are Schwab field names.
- **code edit:** none.

### S2 — Tier / size-cue helper utilities

- **lines:** L164–206 — `_readiness_canonical_fields` L164–169; `_mh_size_tier_from_modifier` L172–179; `_size_cue_tier` L182–190; `_tier_to_size_cue` L193–200; `_merge_size_cue_with_mh` L203–206.
- **surface:** `getattr(canonical, "provenance", "")` — Python attribute on `CanonicalForecast` dataclass. Float comparisons against S1 constants. String tier labels (`"SKIP"` / `"QUARTER"` / `"HALF"` / `"FULL"`).
- **proposed disposition:** **NOT_MARKET_DATA** — internal tier-mapping utilities; `CanonicalForecast.provenance` is an internal forecast-engine attribute, not a Schwab wire token. The `canonical_provenance_is_tradable` check (imported from `fusion_contract`) is governance-policy logic.
- **code edit:** none.

### S3 — Trade-type classification + invalidation builder + time qualifier

- **lines:** L208–310 — `TRADE_TYPE_LABELS` map L208–215; `_classify_trade_type` L217–252; `_build_invalidation` L254–288; `_time_qualifier` L290–310.
- **surface:** Reads `inp.call_gamma_wall` / `inp.put_gamma_wall` / `micro.structure_support` / `micro.structure_resist` / `micro.bos.level` (Python attributes on `SignalInput` and the `micro` micro-structure object). Compares `micro_regime` against `R_*` constants imported from `micro_structure`. Uses `is_pin_zone(zone)` from `math_exposure`.
- **proposed disposition:** **NOT_MARKET_DATA** — copy / classification logic; SignalInput attributes (`call_gamma_wall` etc.) are populated upstream from Schwab chain data in `market_state.build_market_state` (per `market_state.py.md`) — at this site they are already-typed floats on a Python dataclass, not Schwab JSON tokens.
- **provenance trace (for audit only):** `inp.call_gamma_wall` / `put_gamma_wall` lineage: Schwab chain → `safe_get_chain` (per `schwab_client.py.md` S4) → `c_json` → exposure compute → `SignalInput` field assignment in `market_state.build_market_state`.
- **code edit:** none.

### S4 — Headline / reasoning / Greek-note / MC-snippet builders

- **lines:** L313–458 — `_mc_reasoning_snippet` L313–345; `_build_call_headlines` L348–429; `_greek_notes` L431–452; `_add_greek_color` L454–458.
- **surface:** `getattr(fusion, 'mc_available'|'mc_containment'|'mc_expansion'|'mc_sim_prob_up'|'mc_sim_prob_down')` — Python attributes on fusion engine output. `wait_blocker.get(...)` reads on internal blocker dict (keys: `reason`/`long_count`/`short_count`/`threshold`/`long_names`/`short_names`/`gate_reasons`/`vol_detail`/`detail`/`full_detail`). `inp.net_gamma` / `inp.charm_direction` / `inp.charm_drift_toward` / `inp.iv_direction` / `inp.vix_level` reads on SignalInput dataclass.
- **proposed disposition:** **NOT_MARKET_DATA** — output-formatting and narrative-building logic over internal Python objects; `wait_blocker` keys are internal projection names (same rule as `signals.py.md` S3).
- **code edit:** none.

### S5 — Vote helpers (canonical / fusion-authoritative / index-basket / cross-instrument)

- **lines:** L460–590 — `_canonical_stack_vote` L460–474; `_fusion_authoritative_directional_vote` L477–486; `_index_basket_vote` L489–519; `_cross_instrument_signal` L522–560; `_cross_instrument_notes` L562–590.
- **surface:** `getattr(canonical, "direction"|"confidence")`; `canonical.dominant_probability()`; `inp.spy_chg_pct` / `inp.qqq_chg_pct` / `inp.iwm_chg_pct` / `inp.spy_weighted_push` / `inp.qqq_weighted_push` / `inp.iwm_weighted_push` — all `SignalInput` dataclass attributes or `CanonicalForecast` method calls. Float comparisons against S1 thresholds.
- **proposed disposition:** **NOT_MARKET_DATA** — stack-vote logic on internal dataclass / forecast outputs; the SPY/QQQ/IWM `chg_pct` / `weighted_push` values are populated upstream from Schwab quote payloads, dispositioned at their assignment sites (`market_state.py` / `server.py` memos).
- **code edit:** none.

### S6 — Stop-distance + level computation

- **lines:** L592–721 — `_stop_distance` L592–616; `_compute_levels` L618–721 (with closures `_structural_levels` / `_targets` / `_long_levels` / `_short_levels`).
- **surface:** `inp.spot` / `inp.et_hour` / `inp.et_minute` / `inp.vix_level` / `inp.call_gamma_wall` / `inp.put_gamma_wall` / `inp.call_oi_wall` / `inp.put_oi_wall` / `inp.vwap` reads on `SignalInput`. Calls `derive_stop_distance_pct(...)` from `lifecycle_rule_core` and `derive_target_levels(...)` from same.
- **proposed disposition:** **NOT_MARKET_DATA** — entry/stop/target arithmetic on already-populated SignalInput floats. The `inp.vwap` / `inp.spot` / wall attributes trace upstream to Schwab payloads but are floats on a Python dataclass at this site.
- **observation:** `_stop_distance` falls back to `mins_elapsed = 0` (open default) with a `log.debug` when `et_hour`/`et_minute` missing (L601–605). This is a fail-disclosed default with operator-visible log, not a silent fabrication.
- **code edit:** none.

### S7 — Conviction tier + size note + execution mode helpers

- **lines:** L723–821 — `_downgrade` L723–726; `_CONV_ORDER` L732; `_conviction_from_canonical_forecast` L735–778; `_size_note` L781–798; `EXEC_MODES` L802–808; `_exec_mode_for_r_units` L811–821.
- **surface:** `getattr(canonical, "confidence", "low")`; `canonical.dominant_probability()`; float-tier comparisons against S1 constants; `mins_to_close` and `vix` float comparisons.
- **proposed disposition:** **NOT_MARKET_DATA** — tier-derivation logic; `CanonicalForecast.confidence` is a forecast-engine attribute, not Schwab wire.
- **observation:** `_conviction_from_canonical_forecast` has a `log.debug` fallback when confidence is invalid (L750–754) and another when `dominant_probability()` raises (L758–760) — both fail-disclosed to `low` conviction, not silently fabricating a higher tier.
- **code edit:** none.

### S8 — `compute_position_size` (sizing pipeline)

- **lines:** L824–1100.
- **surface:** Eight sizing dimensions (confidence / regime / volatility / MC / level quality / RR floor / time / vol-regime risk-mult) computed against S1 thresholds. Inputs are typed kwargs (`atr` / `iv_level` / `vix` / `stop_distance` / `mc_eae` / `mc_efe` / `mc_containment` / `mc_expansion` / `model_agreement` / `fusion_confidence` / `n_models_active` / `dist_to_nearest_opposing_wall` / `has_void_ahead` / `reward_risk` / `validation_passed` / `mins_to_close` / `vol_regime_risk_multiplier`). Returns dict with internal projection keys (`r_units` / `execution_mode` / `size_cue` / `multipliers` / `reduction_reasons` / `summary`).
- **proposed disposition:** **NOT_MARKET_DATA** — pure sizing math + disclosed-reason aggregation. The float inputs trace to Schwab data upstream (MC outputs from `bayesian_fusion` / `mc_fusion_adjustment`; `vix` from quote payload; etc.) but at this site they are typed function parameters.
- **observation (per the `COH-I-I` comment block L955–960):** When all four MC inputs are `None`, the function adds `"MC unavailable — sizing without MC risk validation"` to `reduction_reasons` rather than silently skipping — already operator-visible, not a fail-silent.
- **code edit:** none.

### S9 — `_validate_trade` (3-layer gate pipeline)

- **lines:** L1104–1325. Layer 1 (structural) L1156–1188; Layer 2 (probabilistic) L1190–1263; Layer 3 (risk) L1265–1302; final gate L1304–1325.
- **surface:** `inp.spot` / `inp.call_gamma_wall` / `inp.put_gamma_wall` / `inp.vix_level` reads; `getattr(fusion, 'model_agreement'|'n_sources_active'|'mc_available'|'mc_eae'|'reversal_posterior'|'continuation_posterior'|'breakout_posterior')`; `canonical.confidence` / `.probability_down` / `.probability_up` / `.direction`; `getattr(vol_regime, "risk_multiplier")`; `getattr(micro, 'is_compressing'|'compression_bars')`. All Python attributes.
- **proposed disposition:** **NOT_MARKET_DATA** — trade-gate validation over dataclass / fusion attributes.
- **observation:** Layer 2c (probability gate) explicitly fail-closes when fusion posteriors are `None` (L1228–1231, L1242–1245) — does not assume "safe" when posteriors are unavailable. Matches the operator's fail-closed posture.
- **code edit:** none.

### S10 — `compute_call` (orchestration: STACK ORDER 8–10)

- **lines:** L1328–1930. Decision Policy (STACK 8) L1378–1604; Risk Engine (STACK 9) L1605–1636; Trade type / levels / invalidation / time / sizing (STACK 10) L1638–1733; time-warning override L1734–1764; diagnostics + headlines + size-note L1766–1793; call / put readiness compute L1794–1889; `TheCall` assembly L1891–1930.
- **surface:** Imports `R_*` micro-structure constants and MVP-feature helpers (`mvp_zone` / `mvp_nearest_distances_for_regime`) inside the function. Reads SignalInput attributes (`inp.spot` / `inp.vix_level` / `inp.event_risk_level` / `inp.mins_to_close` / wall + distance / vwap / regime input fields). Calls `_validate_trade(...)` (S9) and `compute_position_size(...)` (S8) with typed kwargs. Assembles `stack_votes` dict (internal projection keys). Reads `mh_policy.mh_directional_vote()` / `mh_veto_stack_directional(...)` / `final_tradeable_decision` / `final_bias` / `size_modifier` from `MultiHorizonSynthesis`. Builds `TheCall` dataclass.
- **proposed disposition:** **NOT_MARKET_DATA** — stack synthesis orchestration; the `stack_votes` dict keys (`"micro"`/`"Greeks"`/`"spy_basket"`/`"qqq_basket"`/`"iwm_basket"`/`"regime"`/`"fusion"`/`"order_flow"`/`"multi_horizon"`) and `wait_blocker` keys are internal projection names.
- **observation:** `compute_call` builds `CanonicalForecast` `direction="flat", probability_up=1/3, probability_down=1/3, probability_flat=1/3, confidence="low", provenance="missing_canonical_fallback"` when `canonical is None` (L1359–1368). The `provenance="missing_canonical_fallback"` is **disclosed** via `canonical_provenance_is_tradable(_prov)` check at L1471–1483 which forces `final_signal = "wait"` and surfaces `wait_blocker={"reason": "canonical_provenance"}`. **Fail-closed, not a silent uniform-fallback substitution** — matches the operator's Issue 13 closeout policy noted at L729–730.
- **code edit:** none.

---

## Appendix A — NOT_MARKET_DATA clusters (wire-token layer)

**Entirety of this file is NOT_MARKET_DATA at the Schwab wire-token layer.** No `q_json[...]` / `c_json[...]` / `pricehistory[...]` / `streaming.content.*` subscripts occur anywhere in 1930 lines. Bulk classification:

- **Sizing thresholds + constants (S1):** ~120 named threshold values, all decision-policy tunables, no Schwab field names.
- **Tier mapping utilities (S2):** Internal score → label transforms.
- **Trade-type / invalidation / time-qualifier narrative (S3, S4):** Plain-English output composition over SignalInput / fusion / canonical attributes.
- **Vote helpers (S5):** Stack-vote derivation from internal forecast outputs and SignalInput SPY/QQQ/IWM session-pct fields.
- **Level computation (S6):** Entry / stop / target arithmetic.
- **Conviction + execution-mode logic (S7):** Tier derivation from canonical confidence + marginal probability.
- **Sizing pipeline (S8):** 8-dimensional multiplier product with disclosed reduction reasons.
- **Trade-validation gate pipeline (S9):** 3-layer pass/fail with fail-closed semantics on missing fusion posteriors.
- **`compute_call` orchestration (S10):** STACK ORDER 8/9/10 implementation; builds `TheCall` dataclass.

This file's contribution to V4 closure is **establishing the Decision Policy / Risk Engine / Position Sizing branch** as Schwab-wire-clean: all Schwab-sourced numerics arrive as already-typed dataclass attributes from upstream populators (`market_state.build_market_state`, fusion engines, regime classifier, vol-regime engine). The producer chain (`schwab_client.py`, `polling_adapter.py`, `live_market_plane.py` per their respective memos) feeds `market_state.py` / `server.py` which populate the SignalInput / fusion / canonical structures this file consumes. No re-subscript here, no leaf citation needed at this layer — the LEAF citations live in the producer + populator memos.

---

## Aggregate disposition for inventory

- **status:** pending (awaiting gatekeeper)
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/call_engine.py.md
- **Class A determination:** memo-only commit admissible — no in-file Schwab field reads, no Schwab-replaceable derivation, no non-canonical fallback, no actionable FIND. Bundling not required.
