> **Classification:** Audit Report | **Scope:** Card signal fidelity and feature provenance

# Card signal fidelity — 2026-06-17

DB: `C:\Users\evarg\Documents\Trading\EdWebConsole\data\ed_console.db`
Read-only: True · No model/threshold/UI changes

## Executive summary

- Horizon **product** direction = **fusion probability argmax** per horizon (`mhap_rows.call`), not trailing price.
- Empirical histogram can **disagree** (often SHORT on 1m/5m) while cards show LONG — fusion-only contract.
- **ALL/PLAN** gate tradeability separately; June 17 SPY decline: horizons LONG, ALL FLAT, PLAN blocked.
- Primary gap: **explainability** — operator cannot see price/fusion/empirical conflict on horizon chips.

## What drives each card

- **1M:** 1M direction/confidence ← mhap_rows[1c] ← fusion triplet (up_prob_1c/down/flat) via multi_horizon_synthesis; empirical histogram (1m) on signal rail only
- **5M:** 5M direction/confidence ← mhap_rows[5c] ← fusion triplet (up_prob_5c/down/flat) via multi_horizon_synthesis; empirical histogram (5m) on signal rail only
- **15M:** 15M direction/confidence ← mhap_rows[15c] ← fusion triplet (up_prob_15c/down/flat) via multi_horizon_synthesis; empirical histogram (15m) on signal rail only
- **60M:** 60M direction/confidence ← mhap_rows[60c] ← fusion triplet (up_prob_60c/down/flat) via multi_horizon_synthesis; empirical histogram (60m) on signal rail only
- **ALL:** ['tools/replay_money_path_probe.py:ui_card_derivation', 'final_bias + final_tradeable from MultiHorizonDecision']
- **PLAN:** ['ui_card_derivation(entry_state) when tradeable', 'call_engine.py:compute_call → entry/stop/target plan']

## June 17 all-horizon LONG during SPY decline

- **all_horizons_long_during_decline:** True
- **primary_driver:** per-horizon fusion posterior favors UP (mhap_rows.call=LONG)
- **empirical_histogram_often_disagrees_short_on_1c_5c:** True
- **fusion_overrides_empirical_count:** 88
- **fusion_long_cell_count:** 110
- **signal_semantics_counts:** {'EMPIRICAL_CONFLICTS_SIGNAL': 76, 'FUSION_OVERRIDE_EMPIRICAL': 76, 'REVERSAL_LONG': 42, 'EMPIRICAL_SUPPORTS_SIGNAL': 26, 'MODEL_DIRECTION_DRIFT': 33, 'UNCLEAR_FEATURE_SOURCE': 15, 'MOMENTUM_SHORT': 18, 'MEAN_REVERSION_LONG': 10, 'TREND_FOLLOWING_LONG': 2}
- **all_and_plan_blocked:** False
- **typical_wait_reason:** call engine veto — ALL consolidated long disagrees with tape stack short
- **interpretation:** Cards show forecast direction (fusion probability argmax), not trailing price direction. June 17 decline samples: fusion LONG + empirical SHORT on short horizons is common; forward 1c returns often positive (reversal/mean-reversion forecasts), explaining high hit rate despite trailing conflict. ALL/PLAN correctly non-tradeable via call-engine veto.

## Feature provenance (leaf vs engineered)

- **spot** (primitive): schwab quote → db.insert_snapshot · stale_risk=Tier A fast-quote can lead Tier C bundle
- **fusion_prob_up/down/flat** (engineered): bayesian_fusion._fuse_impl · stale_risk=stale ML bundle or missing model files
- **horizon_prob_bars (empirical)** (engineered): verification.similar_set_trace.full_similar_and_empirical_trace · stale_risk=sparse DB history / missing normalized rows
- **similar_setup_filters (zone, vwap_side, distances)** (engineered): features.fusion_model_input.similar_setup_filters_from_db_snapshot_row · stale_risk=stale zone/vwap if snapshot old
- **mvp_features / inference_snapshot_v1** (engineered): features.inference_snapshot.build_inference_snapshot_v1_from_signal_input · stale_risk=feature timestamp lag vs spot
- **wait_reason / wait_blocker** (policy): call_engine.compute_call, multi_horizon_decision.compute_multi_horizon_synthesis · stale_risk=low

## Bugs proven

- Horizon cards can show LONG while trailing price declines (forecast ≠ price direction)
- Fusion can override empirical histogram on product cards (fusion-only contract)
- ALL/PLAN can block trade while all horizon cards show LONG (call-engine veto)
- Missing operator chip for price/fusion/empirical conflict on horizon cards
- June 17 SPY normalized rows absent — feature/histogram inputs degraded

## Bugs not proven

- Model weights incorrect or drifted (forward hits on 1c ~72% argue forecasts not random)
- UI rendering wrong direction vs backend mhap_rows (not browser-tested this audit)
- Live STALE pill false positive rate (needs RTH UI transport audit)
- Feature leakage from future data in replay path

## Recommended fix branches

- audit/ui-realtime-transport-fidelity — STALE/LOADING/SQLite contention live
- fix/card-price-conflict-explainability — chip when fusion LONG + trailing down + empirical SHORT
- validate capture+normalization live post PR #9 before trusting feature freshness

## Transport / staleness (June 18 evidence)

- **date_observed:** 2026-06-18
- **sqlite_lock_contention:** Observed database is locked on base capture path (June 18 session)
- **stale_loading_events:** Operator reported STALE/LOADING pills 2026-06-18 08:18–11:42 ET (not re-tested in this audit)
- **capture_improvements:** PR #8 raw cadence improved; PR #9 fixed normalization debounce starvation
- **staleness_risks:** ['Tier A quote lane ahead of Tier C analytical bundle (price_ahead_of_bundle)', 'Sparse normalized rows → stale similar-set / ML inputs', 'SQLite lock wait on concurrent insert + materialize', 'UI analytics_stale while SSE connected']
- **base_capture_summary:** None