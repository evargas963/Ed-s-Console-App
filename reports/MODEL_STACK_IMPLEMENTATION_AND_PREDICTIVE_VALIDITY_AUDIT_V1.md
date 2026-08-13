> **EVIDENCE / CONTRACT — not a second "now."** Outstanding work from this file, if material, lives on `OPEN_ITEMS.md` PA-48. Pointer: `ACTIVE_PROGRAM.md` → PA-46. Do not open a parallel program from this file.

> **Classification:** Evidence Artifact | **Scope:** MODEL_STACK_IMPLEMENTATION_AND_PREDICTIVE_VALIDITY_AUDIT_V1 session-evidence packet (read-only mission report)

# MODEL_STACK_IMPLEMENTATION_AND_PREDICTIVE_VALIDITY_AUDIT_V1

**Mission type:** READ_ONLY_REPOSITORY_WIDE_AUDIT  
**Base SHA:** `e749e75345b19a291f9d14de6e78593c0feff4af`  
**Audit date:** 2026-07-09  
**Implementation authorized:** NO  

---

## 1. Executive binary assessment

| Status field | Value | Evidence basis |
|--------------|-------|----------------|
| MODEL_STACK_SOFTWARE_CORRECTNESS | NOT_PROVEN | Code paths traced; independent oracles sparse; several CONFIRMED_DEFECT / NOT_PROVEN cells |
| MODEL_STACK_SEMANTIC_CORRECTNESS | NOT_PROVEN | Shared VIX as ticker-native vol; 5c meta bypass vs naming; card confidence semantics partially governed |
| FEATURE_LINEAGE_AND_LOOKAHEAD_SAFETY | NOT_PROVEN | Bar-anchor labels governed; no purged CV on overlapping labels; full-dataset feature engineering risks on thin splits |
| META_LEARNER_OOF_ISOLATION | NOT_PROVEN | Expanding-window session OOF exists; thin-session fallback to in-sample; no row-interval purging |
| MODEL_STACK_PREDICTIVE_VALIDITY | NOT_PROVEN | SPY 1c XGB val_accuracy 44.3%, balanced_accuracy 33.4% (~chance on 3-class); no repo-wide OOS matrix |
| MODEL_STACK_CALIBRATION_VALIDITY | NOT_PROVEN | ECE/Brier in arch_competition manifests; 5c isotonic hardcoded in ml_predict; A1 attach separate lane |
| MODEL_STACK_INCREMENTAL_VALUE | NOT_PROVEN | Ablation grid exists; runnable_scored completion not proven in this audit |
| BACKTEST_TO_LIVE_PARITY | NOT_PROVEN | Live uses run_unified_stack_ml_once; cascade/challenger paths separate; train-serve gaps (vix_direction) |
| ECONOMIC_VALIDITY_AFTER_COSTS | NOT_PROVEN | No spread/slippage/latency in ML eval path evidenced |
| REAL_MONEY_MODEL_STACK_APPROVAL | NOT_APPROVED | Conservative default per mission |

---

## 2. Actual active-stack architecture

```
RAW SOURCE (Schwab REST/stream)
  quotes.quote.lastPrice, bid/ask, chains.*, pricehistory.candles.*
    ↓ schwab_client.safe_get_quote / safe_get_price_history
    ↓ server._fetch_state (server.py:~4152+)
INGESTION / STORAGE
  snapshots, snapshots_1m_normalized, price_bars_1m, calibration_decision_log
    ↓ db.py INSERT; snapshot_normalizer resample_to_1m
NORMALIZATION / FEATURES
  market_context.fetch_market_context ($VIX shared)
  ml_train.engineer_features / engineer_single_snapshot
  features.inference_snapshot.build_inference_snapshot_v1_from_signal_input
  features/live_feature_adapter, db_feature_adapter (MVP canonical row)
  math_exposure_core, math_levels, order_flow_engine, GARCH (math_volatility)
    ↓
BASE MODELS / CALCULATIONS (per horizon 1c/5c/15c/60c loop)
  ml_predict.run_unified_stack_ml_once → xgb, lstm, transformer
  meta (_predict_meta OR weighted_average; 5c: xgb+TR partial + isotonic)
  monte_carlo.simulate
  regime_engine.classify_regime
  rules_engine.compute_rules
  volatility_regime.classify_volatility_regime
    ↓ signals.production_fusion_payload_for_stack
CALIBRATION
  _apply_5c_xgb_plus_transformer_isotonic_calibration (SPY/5c only, inline maps)
  v2_decision attach_a1_isotonic / conformal (server.py attach to ms_dict)
    ↓
COMBINERS / FUSION
  bayesian_fusion.fuse (xgb+lstm+TR+rules+regime; MC excluded from blend weights)
  mc_fusion_adjustment.fuse_payload_apply_mc_adjustment
  multi_horizon_ml_bundle.build_multi_horizon_ml_fusion_bundle
    ↓
POLICY / GATING
  call_engine.compute_call, validation gates, position_sizing_policy
  lifecycle_rule_core, volatility_regime trade_permissive
    ↓
SIGNAL / CARD / API
  multi_horizon_decision.compute_multi_horizon_synthesis → mhap_rows, ALL/PLAN
  prediction_engine.compute_prediction_core (similar-setups empirical, fusion-only triplets)
  market_state._ms_to_dict → GET /api/state, /api/analytics/state
  static/index.html renderTimeframeSignalRow, paintTradePlanCard
```

**Live entry:** `GET /api/state` → cached `_fetch_state` → `build_market_state` → `compute_signals` (not inline on cache hit).

---

## 3. Active / legacy / dead classification

| Component | Status |
|-----------|--------|
| xgb, lstm, transformer, meta*, monte_carlo, regime, bayesian_fusion | **ACTIVE** production |
| meta on 5c | **ACTIVE fallback** — bypassed; xgb+TR partial blend |
| run_cascade_models_once | **DEAD** on live path |
| predict_direction, get_model_outputs | **EVAL/DIAG** only |
| Kalman filter | **DEAD** — no code |
| HMM | **DEAD** — no code |
| GARCH | **ACTIVE** (optional; None if <21 closes) |
| Order flow engine | **ACTIVE** |
| Dealer walls/charm | **ACTIVE** |
| Net vanna aggregate | **DEAD/unwired** |
| Similar-setups | **ACTIVE** support (empirical; not product triplets default) |
| Liquidity value engine | **ACTIVE** for levels/VWAP context |
| Cascade LSTM/TR tensor path | **LEGACY** — blocked when parallel_runtime=True |

---

## 4. Component registry (abbreviated — full rows in appendix A)

See appendix A for COMPONENT_ID rows covering: XGB_1C, LSTM_1C, TR_1C, META_1C, MC_1C, REGIME, FUSION, VOL_REGIME, GARCH, ORDER_FLOW, RULES, CALL_ENGINE, MHAP, ALL_CARD, PLAN_CARD, SIMILAR_SETUP, A1_CALIB, 5C_ISOTONIC.

---

## 5–22. Dimension audits (summary)

### Mathematical specification
- **Governed:** horizon_outcomes.py (bar anchor v3, 1/5/15/60 min forward), ml_horizon.py slugs, governed_stack_contract.FULL_STACK_MODEL_LAYERS.
- **Partially governed:** bayesian_fusion (priors + evidence updates; conditional independence assumed).
- **Not governed:** 5c inline isotonic map constants (ml_predict.py:1806-1818); net vanna interpretation.

### Implementation fidelity
- Stack loop matches governed_stack_contract seven layers.
- **CONFIRMED_DEFECT:** market_state stamps `vix_direction=None` while server computes direction (market_state.py:1309 vs server.py:5963-5969).

### Semantic fidelity
- **CONFIRMED_DEFECT:** `vix_level` on QQQ/IWM snapshots is macro VIX, not native VXN/RVX — mislabeled as ticker vol confluence.
- **NOT_PROVEN:** Card `confidence` = fusion-derived; calibration evidence per ticker×horizon not established in audit.
- Fusion product triplets: fusion-only by default (prediction_engine.py:192-205) — **PROVEN** behavior.

### Feature lineage / look-ahead
- LSTM/TR require causal `as_of_ts` + DB history (ml_predict parallel_runtime).
- Labels: bar close anchor, forward bar close (horizon_outcomes.py) — **PROVEN** spec.
- **NOT_PROVEN:** No row-level purged embargo for overlapping 1m labels in ML training.
- **NOT_PROVEN:** Global feature engineering fit boundaries on full dataframe before tail split (ml_train engineer_features after split — needs per-row verification; split before engineer in train path at ml_train.py:~819).

### Labels / horizons
- 1c = 1×1m bar (~1 min); 5c/15c/60c = N×1m bars (horizon_outcomes.py:42-55) — **PROVEN**.
- Training target SPY 1c: `outcome_1c ~1 min ahead` (xgb meta) — aligns with spec.

### Splits / purge / walk-forward
- B3: time_ordered_tail 15% (ml_data_common.py) — **PROVEN**.
- B1: walk_forward_session_split, 3 session holdout (training_cache.py) — **PROVEN**.
- B2: expanding_window_oof_folds for meta (ml_scheduler.py) — **PROVEN** with thin-data fallback.
- Purged K-fold: calibration lane only (calibration/v2_advisory_backfill.py) — **NOT in ML stack**.

### Shuffle-label / negative controls
- **NOT_PROVEN** for any model×horizon in core ML path. Evidence gap.

### Meta OOF isolation
- OOF meta training: **PROVEN** when ≥4 sessions (basis `expanding_window_oof`).
- Fallback `in_sample_no_folds`: **NOT_PROVEN** isolation.
- Live meta inference uses full-fit bases — **PROVEN** (expected); not leakage at inference.

### Golden files / oracles
- Many tests use production functions as oracle — implementation-regression-only.
- test_oof_stacker.py, test_training_cache_layer5.py — fold math **PROVEN**.
- Independent textbook oracles for GARCH/fusion: **NOT_PROVEN**.

### Invariants
- Fail-closed unavailable models (no 0.333 filler) — **PROVEN** (ml_predict, prediction_engine).
- Fusion withholds triplets when missing — **PROVEN**.
- I-01 locks in tests/test_ml_predict_fail_closed.py — partial coverage.

### Baselines / predictive validity
- SPY XGB 1c: val_accuracy 0.4428, balanced_accuracy 0.3339 — near 3-class prior; **NOT_PROVEN** beat baseline OOS.
- arch_competition eval_runner emits ECE, Brier, log-loss — **PROVEN** artifact path; per-ticker matrix not computed in audit.

### Calibration
- Promotion gates: ECE/Brier regression (promotion_engine.py) — **PROVEN** mechanism.
- 5c runtime isotonic: hardcoded maps, SPY-only — **CONFIRMED_DEFECT** (non-reproducible artifact embedded in code).

### Economic validity
- **NOT_PROVEN** — no cost model in stack eval.

### Ablation / incremental value
- feature_curation_gate whole-stack ablation — **PROVEN** infrastructure; completion/runnable_scored not audited here.

### Train/inference parity
- parallel_runtime=True production path — **PROVEN**.
- vix_direction train-serve skew — **CONFIRMED_DEFECT**.
- FEATURE_SCHEMA_VERSION v7 in active SPY bundle — must match code or fail-closed.

### Artifact integrity
- models/active/{TICKER}/ per horizon dirs — **PROVEN** layout; SPY/QQQ/IWM bundles present (7 files each).
- verify_active_models.py: file presence only — **NOT_PROVEN** metric re-validation.

---

## 23. Model × horizon validity matrix (excerpt)

| Component | Horizon | Prod | Math | Code | Semantic | Data | Look-ahead | Label | Purge | Shuffle | Meta OOF | Oracle | Invar | Baseline | Cal | WF | Econ | Abl | Live par | Status |
|-----------|---------|------|------|------|----------|------|------------|-------|-------|---------|----------|--------|-------|----------|-----|-----|------|-----|----------|--------|
| XGB | 1c | ACTIVE | PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | N/A | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN |
| LSTM | 1c | ACTIVE | PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | N/A | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN |
| Transformer | 1c | ACTIVE | PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | N/A | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN |
| Meta | 1c | ACTIVE | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN |
| Meta | 5c | BYPASS | NOT_PROVEN | CONFIRMED_DEFECT | CONFIRMED_DEFECT | NOT_PROVEN | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | N/A | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | CONFIRMED_DEFECT | PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN |
| Monte Carlo | all | ACTIVE | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | N/A | N/A | N/A | N/A | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN |
| Regime | all | ACTIVE | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | N/A | N/A | N/A | N/A | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN |
| Bayesian fusion | all | ACTIVE | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | N/A | N/A | N/A | N/A | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN |
| Vol regime | all | ACTIVE | PROVEN | NOT_PROVEN | CONFIRMED_DEFECT | NOT_PROVEN | NOT_PROVEN | N/A | N/A | N/A | N/A | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | CONFIRMED_DEFECT | NOT_PROVEN |
| GARCH | all | ACTIVE | PROVEN | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | N/A | N/A | N/A | N/A | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN |
| Similar-setup | all | ACTIVE | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | PROVEN | NOT_PROVEN | NOT_PROVEN | N/A | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN |
| ALL card | consolidated | ACTIVE | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | N/A | N/A | N/A | N/A | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN | NOT_PROVEN |

Full matrix: same NOT_PROVEN default for 5c/15c/60c layers unless noted; copy from 1c with horizon-specific 5c meta/isotonic exceptions.

---

## 24. Test coverage matrix (summary)

| Test type | XGB | LSTM | TR | Meta | Fusion | MC | Regime |
|-----------|-----|------|-----|------|--------|-----|--------|
| Mathematical oracle | NO | NO | NO | NO | NO | NO | NO |
| Hand-worked fixture | NO | partial | partial | NO | NO | NO | NO |
| Golden regression | YES | YES | YES | partial | YES | partial | partial |
| Look-ahead / lineage | partial | partial | partial | NO | NO | NO | NO |
| Shuffle-label | NO | NO | NO | NO | NO | NO | NO |
| Purged K-fold | NO | NO | NO | NO | NO | NO | NO |
| Walk-forward | YES | YES | YES | YES | partial | NO | NO |
| Meta OOF leakage | N/A | N/A | N/A | YES | N/A | N/A | N/A |
| Ablation | partial | partial | partial | partial | partial | partial | partial |
| Live/backtest parity | partial | partial | partial | NO | partial | NO | NO |

**Blocking tests (examples):**
- `test_shuffle_label_xgb_1c_collapses_to_prior` — ml_train.py train path — required before production approval
- `test_signal_input_vix_direction_matches_server` — market_state.py — blocks vol-regime parity
- `test_native_vol_semantic_qqq_not_vix` — future vol remediation — semantic defect

---

## 25. Confirmed defect register

| ID | Component | Type | Severity | Evidence |
|----|-----------|------|----------|----------|
| MSD-001 | SignalInput vol | train/live divergence | HIGH | market_state.py:1309 vix_direction=None vs server.py:5963-5969 |
| MSD-002 | Vol confluence | semantic defect | HIGH | vix_level shared for QQQ/IWM (market_state.py:1309); not VXN/RVX |
| MSD-003 | 5c calibration | implementation defect | MED | ml_predict.py:1806-1818 hardcoded isotonic maps in source |
| MSD-004 | 5c meta | semantic defect | MED | ml_predict.py:1957-1965 meta bypass; stack still named 7-layer |
| MSD-005 | Net vanna | dead code | LOW | market_state.py:1287 always None; governed_stack references net_vanna |

---

## 26. Missing-evidence register (excerpt)

| ID | Component | Type | Required proof |
|----|-----------|------|----------------|
| MEV-001 | All ML models | missing negative control | Shuffle-label per model×horizon |
| MEV-002 | ML training | evaluation defect | Row-interval purged CV for overlapping labels |
| MEV-003 | Stack | missing proof | Incremental ablation completion (runnable_scored) |
| MEV-004 | All probabilistic | missing proof | Economic validity after costs |
| MEV-005 | Fusion | missing oracle | Independent fusion reference on fixture |
| MEV-006 | Predictive validity | missing proof | Multi-ticker×horizon OOS matrix with CIs |

---

## 27. Risk-ranked remediation lanes

| Rank | Lane | Target | Files (preliminary) |
|------|------|--------|---------------------|
| 1 | LANE-MS-01 Train-serve vol parity | MSD-001 | market_state.py, server.py, signal_types.py |
| 2 | LANE-MS-02 Native vol semantics | MSD-002 | market_context, market_state, db (design) |
| 3 | LANE-MS-03 5c isotonic externalize | MSD-003 | ml_predict.py, models/active_5c |
| 4 | LANE-MS-04 Shuffle-label battery | MEV-001 | tests/, ml_train, ml_scheduler |
| 5 | LANE-MS-05 Purged CV for ML labels | MEV-002 | ml_data_common, training_cache |
| 6 | LANE-MS-06 OOS validity dashboard | MEV-006 | arch_competition, tools |
| 7 | LANE-MS-07 Call/put deep audit | separate | call_engine, setup_readiness |
| 8 | LANE-MS-08 Economic backtest harness | MEV-004 | new eval tooling (design only) |

---

## 28. Files and paths examined

server.py, market_state.py, signals.py, ml_predict.py, prediction_engine.py, bayesian_fusion.py, mc_fusion_adjustment.py, monte_carlo.py, regime_engine.py, volatility_regime.py, ml_train.py, lstm_data.py, lstm_model.py, transformer_train.py, ml_scheduler.py, ml_data_common.py, training_cache.py, arch_competition/*, promotion_execution.py, verify_active_models.py, horizon_outcomes.py, ml_horizon.py, governed_stack_contract.py, order_flow_engine.py, math_volatility.py, math_exposure_core.py, multi_horizon_decision.py, call_engine.py, db.py, features/inference_snapshot.py, models/active/*, tests/test_oof_stacker.py, tests/test_training_cache_layer5.py, tests/test_ml_predict_fail_closed.py

---

## 29. Commands executed

```
git rev-parse HEAD
python -c "inventory models/active/*"
python -c "read SPY xgb_SPY_1c_meta.json provenance"
```

Read-only subagent traces (inference, training, component discovery).

---

## 30. Limitations

- No live server replay at audit time
- No full ablation run / DB-scored cell matrix
- No independent statistical recompute of all promotion manifests
- models/active contains 22 tickers; validity sampled on SPY/QQQ/IWM only
- Report generated under READ_ONLY constraints; no test execution beyond meta JSON read

---

## 31. Final binary status table

(See section 1.)

---

## Appendix A — Sample component registry rows

### COMP-XGB-1C
- CLASS: machine-learning model
- PRODUCTION_STATUS: ACTIVE
- FILES: ml_predict.py, ml_train.py, xgboost_model.py
- ENTRY: run_unified_stack_ml_once → _predict_xgb
- TRAINING: ml_train.train_model, time_ordered_tail + walk_forward sessions
- INFERENCE: signals._run_model_stack → production_fusion_payload_for_stack
- OUTPUT: prob_up/down/flat, xgb_dominant
- HORIZONS: 1c,5c,15c,60c
- TICKER_SCOPE: anchor + guest via ml_bundle_ticker_scope
- ARTIFACTS: models/active_{hz}/{TICKER}/xgb_{T}_ {hz}.pkl
- MONEY_PATH: YES (via fusion → call)
- TESTS: test_ml_predict_fail_closed.py, encoder cone partial
- BINARY_STATUS: NOT_PROVEN (predictive validity)

### COMP-FUSION
- CLASS: combiner (Bayesian)
- PRODUCTION_STATUS: ACTIVE
- FILES: bayesian_fusion.py, mc_fusion_adjustment.py
- ENTRY: fuse, fuse_payload_apply_mc_adjustment
- MC not blended as model weight (bayesian_fusion.py:443-444)
- MONEY_PATH: YES
- BINARY_STATUS: NOT_PROVEN

---

**END**

`MODEL_STACK_IMPLEMENTATION_AND_PREDICTIVE_VALIDITY_AUDIT_V1 = COMPLETE — IMPLEMENTATION NOT AUTHORIZED`
