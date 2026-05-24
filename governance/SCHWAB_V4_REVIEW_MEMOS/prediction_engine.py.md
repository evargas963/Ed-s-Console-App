> **Classification:** Policy Specification | **Scope:** Governance documentation `prediction_engine.py.md`.

# Review memo — prediction_engine.py

**Status:** pending gatekeeper review
**Date:** 2026-05-24
**Reviewer:** Claude (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)
**File language family:** python
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)**

**Closest-shape precedent** (per `AGENTS.md` Posture rules — sibling-pattern conformance, 2026-05-24): `call_engine.py.md` (just-landed, same money-path roster, same all-NOT_MARKET_DATA shape) and `signals.py.md` (original precedent for "no in-file Schwab JSON subscripts → all sites NOT_MARKET_DATA"). prediction_engine.py is a consumer of `SignalInput`, `CanonicalForecast`, DB snapshot rows, and bar objects already normalized by `market_data_adapter.schwab_candles_to_bars` — Schwab wire reads belong to upstream populators.

**Active-posture Class A check** (per `AGENTS.md` §Active agent posture, 2026-05-24): no Schwab-replaceable derivation, no non-canonical fallback, no in-file FIND that would require a code change. **Memo-only commit is admissible under Class A — no fixable code debt is documented.**

---

## Audit methodology (clause 4 — attribute / call / subscript)

Audited **this file** for:

| Channel | Method |
|---------|--------|
| String-literal dict access on Schwab payloads | None — file does not subscript any Schwab JSON payload. |
| Bracket dict access on Schwab payloads | None. |
| String-literal dict access on **DB snapshot rows** | `r.get("outcome_1c"\|"outcome_5c"\|"outcome_15c"\|"outcome_60c"\|"outcome_5c_pts"\|"outcome_15c_pts"\|"outcome_60c_pts"\|"match_tier")` — these are **SNAPSHOTS table columns**, not Schwab JSON fields; reviewed via `db.py` schema, not the Schwab field dictionary. |
| String-literal dict access on **MVP features** | `mvp.get("features")` / `mvp_zone(mvp)` / `mvp_vwap_side(mvp)` / `mvp_spot(mvp)` / `mvp_nearest_distances_for_regime(mvp)` — internal MVP feature namespace, not Schwab JSON. |
| Attribute access on market-bearing objects | `inp.<attr>` on `SignalInput` (~40 attrs read across the file — ticker / timeframe / refresh_ts_utc / charm_direction / spot / et_hour / et_minute / candle_body_pts / candle_range_pts / zone_since_bars{,_1m,_5m} / dist_*_gamma_wall / dist_*_oi_wall / dist_gamma_inflection / dist_delta_inflection / dist_*_vanna_wall / pin_width_pts / net_delta / net_vanna / charm_net / iv_level / put_call_oi_ratio / spy_chg_pct / qqq_chg_pct / iwm_chg_pct / spy_weighted_push / qqq_weighted_push / iwm_weighted_push / vix_level / vix_vs_prev / prev_zone / candle_direction / session_bucket / vix_bucket / charm_magnitude / iv_direction / qqq_vs_spy / iwm_risk_signal / candles_1m / candles_5m / candle_volume / flow_imbalance / bid_ask_imbalance / atr / iv_rank / smart_money_score / breakout_score / pin_score); `getattr(_last_bar, "volume")` on **already-normalized bar objects** (per `market_data_adapter.py.md` S1); `getattr(canonical, "X")`; `getattr(fusion, "X")`; `getattr(regime, "X")`; `getattr(snap, "horizon_fusion_available"\|"prob_up"\|"prob_down"\|"prob_flat")`. |
| Method calls passing Schwab market objects | None. Calls pass `inp` / `db` / `canonical` / `fusion` / `regime` / `rules` / `inference_snapshot_v1` / `ml_bundle` / `multi_horizon_ml_bundle` (all internal Python objects). |
| Internal projection-key reads (NOT Schwab wire) | `_filters["zone"\|"vwap_side"\|"nearest_above_dist"\|"nearest_below_dist"]` from `similar_setup_filters_from_canonical_features(mvp)`; `pack.get("parallel")` / `par.get("eval_accuracy"\|"eval_log_loss"\|"eval_pnl_realized_contract"\|"realized_contract_metrics")` from `eval_metrics_store`; `_mb.get("model_outputs"\|"movement_head_probs"\|"fusion_policy_snapshot_cols"\|"stack_integrity_events")` from ml_bundle. None match any Schwab dictionary row. |
| Environment variables | `os.environ.get("ED_PREDICT_ENRICHMENT", "1")` (L81); `os.environ.get("ED_MH_EMPIRICAL_SUPPORT", "0.15")` (L240) — operator runtime config, not Schwab. |

**Review complete:** Every site **in this file** falls under **S1–S12** below; no Schwab `example_raw_field` tokens, chain JSON subscripts, or streaming content keys occur anywhere in `prediction_engine.py`.

---

## Market-data sites identified

### S1 — Module imports + STACK-WIRE-3 threshold constants

- **lines:** L1–52.
- **surface:** Imports (L1–36); 11 named float/int constants for MC-EAE/EFE, containment thresholds, canonical dominant-prob action minimums, zone-fresh-bars display max, move-severity %-of-spot cuts, avg-outcome min samples, regime boost factor.
- **proposed disposition:** **NOT_MARKET_DATA** — Phase 6 ablation thresholds (`STACK-WIRE-3` comment L38), not Schwab field names.
- **code edit:** none.

### S2 — `_TIER_LABELS` + `PredictionEnrichmentState` + env helper + similarity timestamp helper

- **lines:** L54–103 — `_TIER_LABELS` L54–62; `PredictionEnrichmentState` dataclass L65–77; `_predict_enrichment_enabled` L80–81; `_as_of_ts_utc_for_similarity` L84–103.
- **surface:** Tier-label strings; dataclass field declarations; `os.environ.get("ED_PREDICT_ENRICHMENT", "1")`; reads `inference_snapshot_v1.get("as_of_ts")` (internal MVP key) and `getattr(inp, "refresh_ts_utc", None)`.
- **proposed disposition:** **NOT_MARKET_DATA** — tier-mapping table, config helper, similarity SQL-cutoff helper. `as_of_ts` is an internal snapshot timestamp, not Schwab wire.
- **code edit:** none.

### S3 — Counting + literal empirical-horizon helpers

- **lines:** L106–150 — `_count_labeled` L106–110; `_literal_empirical_horizon` L113–150.
- **surface:** Iterates `similar` list (DB snapshot rows), reads `r.get(outcome_col)` for outcome_1c/5c/15c/60c columns. Returns `(probs_dict | None, source_str, horizon_note_str, labeled_count)`.
- **proposed disposition:** **NOT_MARKET_DATA** — DB-row column reads on SNAPSHOTS table (not Schwab JSON); fail-disclosed withholding semantics (returns `None` probs + reason string when `n < MIN_SAMPLES_STATISTICAL`, never fabricates uniform thirds).
- **code edit:** none.

### S4 — Triplet normalization helpers

- **lines:** L153–181 — `_tri_probs` L153–159; `_fusion_snap_triplet` L162–171; `_norm_triplet_floats` L174–181.
- **surface:** `getattr(snap, "horizon_fusion_available"|"prob_up"|"prob_down"|"prob_flat")` on per-horizon fusion snapshot objects. Pure float math.
- **proposed disposition:** **NOT_MARKET_DATA** — triplet shape conversion + L1 normalization. Fail-disclosed: returns `None` on non-finite or zero-sum inputs.
- **code edit:** none.

### S5 — `_overlay_multi_horizon_ml_on_product_triplets`

- **lines:** L184–273.
- **surface:** Reads `getattr(multi_horizon_ml_bundle, "by_horizon")` (internal MH ML bundle attribute); blends per-horizon fusion triplets with empirical histograms using `ED_MH_EMPIRICAL_SUPPORT` env weight; records `stack_integrity_v1` degradation events via `record_stack_degradation` when MH bundle is malformed.
- **proposed disposition:** **NOT_MARKET_DATA** — MH-ML overlay logic on internal bundle objects. The integrity-event mechanism is operator-visible (per `features.stack_integrity_v1`), not silent fallback.
- **observation:** Per the docstring (L196–197): "Third return value: structured degradation events when MH bundle cannot be applied (never silent — see stack_integrity_v1)." Already-disclosed degradation discipline. The broad `except Exception` at L222 catches custom descriptors / `__getattribute__` failures on bundle types, records the failure to `integrity_events`, logs warning, and falls back to empirical-only. Fail-disclosed, not silent.
- **code edit:** none.

### S6 — `_avg_outcome_pts` + `_pack_horizon_row` + `_build_horizon_prob_bars`

- **lines:** L276–344.
- **surface:** `r[pts_col]` reads on DB snapshot rows for outcome_*c_pts columns; assembles horizon row dicts with `up`/`down`/`flat`/`labeled_count`/`min_samples_required` keys (internal projection); builds the four-horizon `horizon_prob_bars` payload (`1m`/`5m`/`15m`/`60m` ui labels).
- **proposed disposition:** **NOT_MARKET_DATA** — DB-row averaging + internal payload assembly. Fail-disclosed: `_avg_outcome_pts` returns `None` when `len(pts) < AVG_OUTCOME_MIN_SAMPLES`.
- **code edit:** none.

### S7 — `_timeframe_reads`

- **lines:** L346–383.
- **surface:** `mvp_zone(mvp_features)`, `mvp_vwap_side(mvp_features)`, `inp.charm_direction`. Returns dict with `15m` / `60m` plain-English structure read strings.
- **proposed disposition:** **NOT_MARKET_DATA** — narrative composition over internal MVP features and SignalInput attribute.
- **code edit:** none.

### S8 — `_prediction_headline`

- **lines:** L385–440.
- **surface:** `mvp_zone(mvp_features)`, `inp.put_gamma_wall`, `inp.call_gamma_wall`. Plain-English headline construction.
- **proposed disposition:** **NOT_MARKET_DATA** — narrative composition over SignalInput attributes.
- **code edit:** none.

### S9 — `_get_all_recent` + `build_fusion_model_overlay_for_stack`

- **lines:** L442–602.
- **surface:** `_get_all_recent` (L442–455) wraps `db.get_recent_snapshots(...)`. `build_fusion_model_overlay_for_stack` (L458–602) assembles the ML fusion overlay dict from ~40 SignalInput attributes + ~12 derived/normalized fields; the OUTPUT dict keys (`ticker` / `et_hour` / `dist_*_wall` / `net_*` / `iv_*` / `spy_*` / `qqq_*` / `iwm_*` / `vix_*` / `candle_*` / `pred_*c_*_prob`, etc.) are **ML model input projection keys**, not Schwab JSON tokens. Calls `strip_mvp_keys_from_fusion_overlay(raw)` and `assert_fusion_overlay_has_no_mvp_keys(out)` to enforce MVP/overlay separation contract (per `features.fusion_model_input` policy).
- **surface — bar object volume getattr (L510–527):** `getattr(_last_bar, "volume", None)` on the last bar of `inp.candles_1m` (or `inp.candles_5m` fallback). The bar object is already normalized — `pricehistory.candles.*.volume` LEAF disposition belongs to `market_data_adapter.py.md` S1 where `schwab_candles_to_bars` actually subscripts the Schwab dict key.
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — DB-row reads, SignalInput attribute reads, bar-object attribute reads (all already-normalized upstream). The "1m → 5m fallback" pattern at L510–527 is internal candle-source resilience, not Schwab-canonical-vs-alias.
- **provenance trace (for audit only):** Each `inp.X` value traces upstream — e.g., `inp.candles_1m[*].volume` ← `market_data_adapter.schwab_candles_to_bars` ← `payload["candles"]` ← `safe_get_price_history` (per `polling_adapter.py.md` S2/S3 and `schwab_client.py.md` S3).
- **observation:** Broad `except Exception: return []` at L454 in `_get_all_recent` is a DB-failure tolerance pattern. Broad `except Exception as e: log.warning(...)` at L500–501 and L744–745 logs DB lookup failures and proceeds with empty similars; fail-disclosed.
- **code edit:** none.

### S10 — `_forward_probs_from_canonical` + `_empty_prediction`

- **lines:** L605–675.
- **surface:** `canonical.probability_up` / `.probability_down` / `.probability_flat` / `.direction` / `.confidence` / `.provenance` reads on CanonicalForecast; `_empty_prediction` builds a `PredictiveCard` with the no-DB error message and uniform-thirds empirical placeholders that are immediately overlaid by MH-ML if available (otherwise empty PredictiveCard fields).
- **proposed disposition:** **NOT_MARKET_DATA** — uniform-fallback guard discipline. The `is_canonical_tradable(canonical)` check (imported from `fusion_contract`) ensures `_forward_probs_from_canonical` returns `(None, None, None)` for non-tradable uniform fallbacks rather than surfacing thirds as if they were a real forecast — matches the Issue 13 closeout policy in `call_engine.py.md` S10.
- **code edit:** none.

### S11 — `compute_prediction_core` (hot path)

- **lines:** L678–923.
- **surface:** Reads `inference_snapshot_v1["features"]` (MVP namespace), `mvp_spot(mvp)`, similar-setup DB lookup, `db.get_avg_move(...)`, four `_literal_empirical_horizon` calls (S3), `_overlay_multi_horizon_ml_on_product_triplets` (S5), `_avg_outcome_pts` for 5c/15c/60c (S6), `compute_percentile_range(similar)`, MC range derivation from `getattr(fusion, "mc_lower_50"|"mc_upper_50")`, prediction direction/target logic using `canonical.direction`/`canonical.confidence`/`canonical.dominant_probability()`. Builds `PredictiveCard` with the empirical + MH-fusion blended triplets, integrity events, and `PredictionEnrichmentState` for the cold path.
- **proposed disposition:** **NOT_MARKET_DATA** — hot-path orchestration over DB rows, SignalInput, canonical forecast, fusion attributes, and MVP features. Fail-closed via `FusionModelInputError` when `inference_snapshot_v1 is None` (L697–701) or `mvp_spot(mvp) is None` (L704–705).
- **observation:** `if canonical is None: raise ValueError(...)` at L781–782 explicitly forces caller to supply a `CanonicalForecast` (Issue 13 contract).
- **code edit:** none.

### S12 — `compute_prediction_enrichment` + `compute_prediction` orchestrator

- **lines:** L926–1290.
- **surface:** Cold path — reads dashboard eval metrics via `load_dashboard_eval_metrics()` (internal eval_metrics_store), assembles reversal-risk analytics from empirical triplets + MC tail estimates, builds plain-English `headline` and `model_note` parts list using `getattr(fusion, "dominant_outcome"|"dominant_probability"|"model_agreement_label"|"n_sources_active"|"mc_efe"|"mc_eae"|"mc_containment"|"mc_expansion")`, returns enriched `PredictiveCard` via `dataclasses.replace`. The `compute_prediction` orchestrator (L1233–1290) splits into core (hot) + enrichment (cold) per the `ED_PREDICT_ENRICHMENT` env switch.
- **proposed disposition:** **NOT_MARKET_DATA** — narrative composition + reversal-risk derivation over fusion attributes and DB row reversal counts (`row.get("outcome_5c")`, `row.get("outcome_5c_pts")` at L1028–1029 — SNAPSHOTS columns, not Schwab JSON).
- **observation:** `compute_prediction_enrichment` reads `row.get("outcome_5c")` and `row.get("outcome_5c_pts")` (L1028–1029) — same DB-row column reads as S3/S6.
- **code edit:** none.

---

## Appendix A — NOT_MARKET_DATA clusters (wire-token layer)

**Entirety of this file is NOT_MARKET_DATA at the Schwab wire-token layer.** No `q_json[...]` / `c_json[...]` / `pricehistory[...]` / `streaming.content.*` subscripts occur anywhere in 1290 lines. Bulk classification:

- **STACK-WIRE-3 thresholds (S1):** Phase 6 ablation tunables.
- **Tier mapping + state dataclass + env helpers (S2):** Internal scaffolding.
- **Empirical horizon helpers (S3, S4, S6):** DB-row column reads on SNAPSHOTS table (`outcome_*c`, `outcome_*c_pts`, `match_tier`); fail-disclosed withholding on insufficient labeled counts.
- **MH-ML overlay (S5):** Internal bundle attribute reads with `stack_integrity_v1` degradation events (never silent).
- **Timeframe / headline narrative (S7, S8):** Plain-English composition over MVP features + SignalInput attributes.
- **Fusion model overlay assembly (S9):** ~40 SignalInput attribute reads + DB recent-snapshot fallback + bar-object volume read (`getattr(_last_bar, "volume")` — per `market_data_adapter.py.md` S1 normalization). Output keys are ML model projection names, enforced as MVP-free via `assert_fusion_overlay_has_no_mvp_keys`.
- **Canonical-forecast uniform-fallback guard (S10):** `_forward_probs_from_canonical` returns `(None, None, None)` for non-tradable provenance — disclosed non-tradable, not silent thirds.
- **Hot path `compute_prediction_core` (S11):** DB similar-setup + empirical horizons + MH-ML overlay + canonical direction/target logic; fail-closed on missing MVP / canonical.
- **Cold path `compute_prediction_enrichment` (S12):** Reversal-risk analytics + narrative composition; orchestrator `compute_prediction` (S12 tail) hot+cold split via `ED_PREDICT_ENRICHMENT` env switch.

This file's contribution to V4 closure is **establishing the Predictive Card branch** as Schwab-wire-clean: all Schwab-sourced numerics arrive as already-typed `SignalInput` attributes or already-normalized bar object attributes. The producer chain (`schwab_client.py`, `polling_adapter.py`, `live_market_plane.py`) → populator chain (`market_state.build_market_state`, `market_data_adapter.schwab_candles_to_bars`) → consumer (`prediction_engine.py`) is now fully traced across the producer + populator + consumer memos.

---

## Aggregate disposition for inventory

- **status:** pending (awaiting gatekeeper)
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/prediction_engine.py.md
- **Class A determination:** memo-only commit admissible — no in-file Schwab field reads, no Schwab-replaceable derivation, no non-canonical fallback, no actionable FIND. Bundling not required.
