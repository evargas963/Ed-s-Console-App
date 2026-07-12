# MODEL_STACK_SPECIFICATION_DEFECT_REPRODUCTION_AND_VALIDATION_DESIGN_V1

**Mission type:** READ_ONLY_INVESTIGATION_AND_DESIGN  
**Base audit SHA:** `e749e75345b19a291f9d14de6e78593c0feff4af`  
**Prior audit:** `reports/MODEL_STACK_IMPLEMENTATION_AND_PREDICTIVE_VALIDITY_AUDIT_V1.md`  
**Investigation date:** 2026-07-09  
**Implementation authorized:** NO  
**Machine-readable companion:** `reports/MODEL_STACK_SPECIFICATION_DEFECT_REPRODUCTION_AND_VALIDATION_DESIGN_V1.json`

---

## 0. Mission scope and vocabulary

This mission converts the static audit into an implementation-ready validation and remediation specification. No production code, tests, artifacts, calibration, or runtime behavior were modified.

**Permitted verdict vocabulary:** `PROVEN`, `NOT_PROVEN`, `CONFIRMED_DEFECT`, `NOT_APPLICABLE`, `APPROVED`, `NOT_APPROVED` only.

**Universal coverage requirement:** SPY, QQQ, IWM, all supported guest tickers (22 tickers in `models/active*`), horizons `1c`, `5c`, `15c`, `60c`. Where runtime execution was not performed, cells are `NOT_PROVEN`.

---

## 1. Executive summary

| Determination | Value |
|---------------|-------|
| ACTIVE_STACK_ARCHITECTURE | PROVEN |
| TRANSFORMER_PRODUCTION_CONTRIBUTION | PROVEN |
| FIVE_C_STACK_SPECIFICATION | NOT_PROVEN |
| VOLATILITY_FEATURE_SEMANTICS | CONFIRMED_DEFECT |
| TRAIN_SERVE_PARITY | CONFIRMED_DEFECT |
| FEATURE_LINEAGE_AND_LOOKAHEAD_SAFETY | NOT_PROVEN |
| PURGED_EVALUATION_DESIGN | APPROVED |
| META_LEARNER_OOF_ISOLATION | NOT_PROVEN |
| NEGATIVE_CONTROL_DESIGN | APPROVED |
| PREDICTIVE_VALIDITY_DESIGN | APPROVED |
| CALIBRATION_VALIDITY_DESIGN | APPROVED |
| INCREMENTAL_VALUE_DESIGN | APPROVED |
| ECONOMIC_VALIDITY_DESIGN | APPROVED |
| IMPLEMENTATION_READY | NOT_APPROVED |
| MODEL_STACK_REAL_MONEY_APPROVAL | NOT_APPROVED |

**Confirmed defects reproduced (Phase 2):** MSD-001 through MSD-005 — all `CONFIRMED_DEFECT`.

**Transformer reconciliation:** No binding governance document removes Transformer from the live seven-layer stack. `ACTIVE_PROGRAM.md`, `governed_stack_contract.FULL_STACK_MODEL_LAYERS`, and `active_bundle_contract.BUNDLE_ARTIFACT_TRIPLE` require Transformer. Live path calls `_predict_transformer` and `bayesian_fusion.fuse` consumes `transformer_out`. Prior operator belief that Transformer was removed is **not** supported by current code at base SHA.

---

## 2. Phase 1 — Runtime architecture reconciliation

### 2.1 Live production call graph (PROVEN)

```
GET /api/state
  → server._fetch_state
  → market_state.build_market_state
  → compute_signals (signals.py)
      → build_inference_snapshot_v1_from_signal_input
      → classify_volatility_regime
      → classify_regime (regime_engine)
      → compute_rules
      → per-horizon loop:
          production_fusion_payload_for_stack
            → _run_model_stack
                → ml_predict.run_unified_stack_ml_once (xgb, lstm, transformer)
                → monte_carlo.simulate
            → bayesian_fusion.fuse
            → mc_fusion_adjustment.fuse_payload_apply_mc_adjustment
      → multi_horizon_decision.compute_multi_horizon_synthesis
      → prediction_engine (similar-setups support rail)
      → call_engine.compute_call
  → market_state._ms_to_dict → mhap_rows, ALL/PLAN cards
```

### 2.2 Component effective-contribution summary

| Component | Static reachability | Effective money-path contribution | Runtime class |
|-----------|--------------------|-----------------------------------|---------------|
| XGB | PROVEN | PROVEN when artifact loads — fusion weight | ACTIVE |
| LSTM | PROVEN | PROVEN when artifact + DB history — fusion weight | ACTIVE |
| Transformer | PROVEN | PROVEN when artifact loads — fusion weight + 5c partial blend | ACTIVE |
| Meta-learner | PROVEN called on non-5c | 5c: BYPASS (MSD-004); else PROVEN when `meta_*.pkl` | ACTIVE / BYPASS on 5c |
| Monte Carlo | PROVEN | PROVEN — MC adjustment; excluded from fusion blend weights | ACTIVE |
| Regime classifier | PROVEN | PROVEN — fusion + call gating | ACTIVE |
| Volatility regime | PROVEN | CONFIRMED_DEFECT inputs (MSD-001/002) — still alters WAIT/gates | ACTIVE_WITH_INPUT_GAP |
| GARCH | PROVEN | CONDITIONAL — optional sigma bars | ACTIVE_OPTIONAL |
| Order flow | PROVEN | PROVEN — scores on ms_dict | ACTIVE |
| Bayesian fusion | PROVEN | PROVEN — product triplet authority | ACTIVE |
| MC fusion adjustment | PROVEN | PROVEN when MC valid | ACTIVE |
| Rules engine | PROVEN | PROVEN — fusion evidence | ACTIVE |
| Similar-setups | PROVEN | PROVEN support-only (not default product triplets) | ACTIVE_SUPPORT_ONLY |
| ALL synthesis | PROVEN | PROVEN — consolidated card | ACTIVE |
| PLAN synthesis | PROVEN | PROVEN — trade plan card | ACTIVE |
| Call engine | PROVEN | PROVEN — TRADE/WAIT/AVOID | ACTIVE |
| Kalman / HMM | NOT_APPLICABLE | Dead — no implementation | DEAD |
| Cascade LSTM/TR tensor path | PROVEN exists | DEAD on live path (`parallel_runtime=True`) | DEAD |
| Net vanna aggregate | PROVEN field exists | DEAD — always None (MSD-005) | DEAD |

### 2.3 Matrix 1 — Component × horizon × ticker-class runtime contribution

Ticker classes:

- **anchor_full:** SPY, QQQ, IWM — full meta on all horizons (SPY/QQQ/IWM verified in artifact inventory).
- **guest_meta_1c_only:** AAPL, AMZN, CIFR, GOOGL, META, MSFT, NVDA, TSLA — meta on 1c only.
- **guest_no_meta:** $SPX, AVGO, GOOG, MET, MRVL, NFLX, PCG, PLTR, SMCI, TSL — no meta any horizon.
- **guest_sparse:** CRWD — missing LSTM on several horizons; missing Transformer on 60c.

Full matrix (384 rows): see JSON `matrices.1_component_horizon_ticker_class_runtime`. Excerpt for Transformer × 5c:

| Component | Horizon | Ticker class | Production entry | Artifact | Effective contribution | Alters TRADE/WAIT |
|-----------|---------|--------------|------------------|----------|------------------------|-------------------|
| transformer | 5c | anchor_full | `ml_predict._predict_transformer` | `transformer_{T}_5c.pt` | PROVEN — enters `bayesian_fusion.fuse` and 5c partial blend (40% xgb / 25% tr weight path) | CONDITIONAL |
| transformer | 5c | guest_no_meta | same | present for all guests inventoried | PROVEN fusion path; meta absent → weighted-average fallback on other horizons only | CONDITIONAL |
| meta_learner | 5c | anchor_full | bypass branch | `meta_{T}_5c.pkl` exists but unused | CONFIRMED_DEFECT MSD-004 | PROVEN via stack_probs → MC |
| meta_learner | 1c | guest_no_meta | `_ensemble_parallel_probs` | meta missing | FALLBACK_ONLY weighted average | CONDITIONAL |

---

## 3. Phase 2 — Defect reproduction register (Matrix 4)

### MSD-001 — `vix_direction` / `vix_vs_prev` divergence

| Field | Value |
|-------|-------|
| Classification | CONFIRMED_DEFECT |
| Intended specification | NOT_PROVEN |
| Producer (API/DB) | `server.py` `_vix_tracker` → `ms_dict["vix_direction"]`, `ms_dict["vix_vs_prev"]` (L7247-7250); DB snapshot insert L6741-6877 |
| Producer (money path) | `market_state.py:1312` — `vix_direction=None`; `vix_vs_prev` never assigned on `SignalInput` |
| Consumer | `volatility_regime.classify_volatility_regime` reads `inp.vix_vs_prev` (L194); training uses `vix_vs_prev` column (`ml_train.py` feature list) |
| Observed divergence | Live `compute_signals` path cannot fire rapid-VIX branch; API/DB carry direction delta not seen by vol_regime |
| Downstream | `vol_regime.trade_permissive`, `conviction_multiplier`, snapshot columns |
| Money-path alteration | CONDITIONAL |
| Scope | ALL tickers, ALL horizons |
| Determinism | DETERMINISTIC |
| Minimal reproduction | Read `market_state.py:1312`, `server.py:7247-7250`, `volatility_regime.py:194` |

### MSD-002 — Shared macro VIX semantics

| Field | Value |
|-------|-------|
| Classification | CONFIRMED_DEFECT |
| Intended specification | NOT_PROVEN — operator must decide: macro overlay vs native VXN/RVX |
| Producer | `market_context.fetch_market_context` — `$VIX` only |
| Consumer | `market_state.py:1312` `vix_level=mkt_ctx.vix` for every ticker |
| Observed divergence | QQQ/IWM/guests receive SPY-linked macro VIX without native vol index ingestion |
| Money-path alteration | PROVEN possible via vol_regime + ML `vix_level` feature |
| Scope | QQQ, IWM, ALL guests |
| Determinism | DETERMINISTIC |

**Volatility feature semantic role:** NOT_PROVEN in binding docs. External research (separate mission) supports SPY→VIX, QQQ→VXN, IWM→RVX at wire layer; application does not implement native gauges. **Operator decision required before implementation** (see remediation L0).

### MSD-003 — Hardcoded 5c isotonic calibration

| Field | Value |
|-------|-------|
| Classification | CONFIRMED_DEFECT |
| Producer | `ml_predict._apply_5c_xgb_plus_transformer_isotonic_calibration` L1806-1835 |
| Consumer | 5c `stack_probs` after partial blend |
| Scope | SPY, 5c only (hard guards L1800-1803) |
| Determinism | DETERMINISTIC |

### MSD-004 — 5c meta-learner bypass

| Field | Value |
|-------|-------|
| Classification | CONFIRMED_DEFECT |
| Producer | `ml_predict.py:1957-1965` — `_weighted_average_partial` xgb 0.40 + transformer 0.25 |
| Consumer | `stack_probs` → Monte Carlo direction context |
| Note | Transformer still runs on 5c for fusion; bypass applies to `stack_probs` / meta stack path only |
| Scope | ALL tickers on 5c horizon inference |
| Determinism | DETERMINISTIC |

### MSD-005 — `net_vanna` unwired

| Field | Value |
|-------|-------|
| Classification | CONFIRMED_DEFECT |
| Producer | `market_state.py:1212-1218` `_net_vanna = None` |
| Consumer | `SignalInput.net_vanna` |
| Money-path alteration | NOT_PROVEN (inert None) |
| Determinism | DETERMINISTIC |

---

## 4. Phase 3 — Mathematical specification registry (Matrix 2)

| Component | MATHEMATICAL_SPECIFICATION | Authoritative source | Oracle strategy |
|-----------|---------------------------|----------------------|-----------------|
| horizon_labels | PROVEN | `horizon_outcomes.py` bar-anchor v3 | Independent bar-shift label recompute |
| xgb_class_probabilities | NOT_PROVEN | XGBoost softmax — no pinned formula doc | Holdout probability simplex + log-loss oracle |
| lstm_sequence | NOT_PROVEN | `lstm_data.py`, `features/lstm_sequence_input.py` | Re-encode sequence from frozen bars independent of train path |
| transformer_sequence | NOT_PROVEN | `transformer_train.py` | Same as LSTM oracle |
| meta_learner | NOT_PROVEN | `_predict_meta` logistic on 9 probs | Sklearn refit on OOF matrix |
| 5c_partial_blend | NOT_PROVEN | Inline weights 0.40/0.25 | Weighted simplex + renorm oracle |
| isotonic_calibration | NOT_PROVEN | Hardcoded maps MSD-003 | `sklearn.isotonic.IsotonicRegression` on held-out scores |
| monte_carlo | NOT_PROVEN | `monte_carlo.py` | Moment/quantile Monte Carlo with fixed seed |
| garch_forecast | PROVEN | `math_volatility.py` recursion | ARCH textbook recursion oracle |
| regime_classifier | NOT_PROVEN | `regime_engine.py` thresholds | Rule-table oracle |
| volatility_regime_classifier | PARTIALLY PROVEN | `volatility_regime.py` docstring thresholds | Threshold boundary unit tests |
| order_flow | NOT_PROVEN | `order_flow_engine.py` | Tape replay imbalance oracle |
| dealer_gamma/charm/vanna | NOT_PROVEN | `math_exposure_core.py` | Strike-level sum oracle |
| walls_pins | NOT_PROVEN | `math_levels.py` | OI wall aggregation oracle |
| bayesian_fusion | NOT_PROVEN | `bayesian_fusion.py` | Independent factor-graph numeric oracle |
| mc_fusion_adjustment | NOT_PROVEN | `mc_fusion_adjustment.py` | MC moment adjustment oracle |
| multi_horizon_synthesis | NOT_PROVEN | `multi_horizon_decision.py` | Fusion-only alignment oracle |
| call_engine_output | NOT_PROVEN | `call_engine.py` | Policy table oracle |
| confidence | NOT_PROVEN | Derived from fusion | Calibration-decile oracle |
| risk_reversal_fields | NOT_PROVEN | call_engine + vol_regime | Gate truth-table oracle |

---

## 5. Phase 4 — Feature lineage and information-interval analysis (Matrix 3)

### 5.1 Universal lineage record schema

Each model input feature MUST carry:

`source_system`, `source_table_or_api`, `raw_event_ts`, `availability_ts`, `normalization_ts`, `bar_ts_convention`, `as_of_ts`, `lookback_interval`, `revision_possible`, `missing_fill`, `fallback_source`, `ticker_mapping`, `session_mapping`, `corporate_action`, `training_construction`, `backtest_construction`, `live_construction`.

### 5.2 Sample information interval

For each labeled row:

- `earliest_feature_dependency` = min(feature availability timestamps in lookback window)
- `latest_feature_dependency` = max(same)
- `prediction_ts` = bar close anchor per `horizon_outcomes.py`
- `label_start`, `label_end` = forward horizon window
- `sequence_window` = LSTM/TR `seq_len` bars strictly before `as_of_ts`
- `calibration_dependency_interval` = fit window for any isotonic/conformal
- `meta_dependency_interval` = OOF prediction generation window

### 5.3 High-risk fields (audit checklist)

| Feature family | Look-ahead risk | Current status |
|----------------|-----------------|----------------|
| Bar OHLCV | next-bar execution vs close anchor | NOT_PROVEN row audit |
| session high/low | full-day leakage | NOT_PROVEN |
| option chain OI | snapshot timing | NOT_PROVEN |
| VIX/VXN/RVX | macro delay + revision | CONFIRMED_DEFECT semantics (MSD-002) |
| vix_vs_prev on live path | missing on SignalInput | CONFIRMED_DEFECT (MSD-001) |
| similar-setups query | future row inclusion | NOT_PROVEN |
| forward-filled DB columns | stale-as-current | NOT_PROVEN |
| 5c isotonic maps | fit cohort unknown | CONFIRMED_DEFECT (MSD-003) |

**Matrix 3 execution:** NOT_PROVEN for complete feature × model × horizon grid without immutable golden-record replay (Phase 11).

---

## 6. Phase 5 — Purged cross-validation and embargo design

**Design status:** APPROVED (specification only; not implemented).

### 6.1 Event representation

Each labeled sample `i` is an interval `[t_pred_i, t_label_end_i]` where:

- `t_pred_i` = prediction timestamp (1m bar close anchor)
- `t_label_end_i` = `t_pred_i + horizon_minutes(horizon)`

Feature dependency interval `[t_feat_start_i, t_feat_end_i]` where `t_feat_end_i <= t_pred_i` and `t_feat_start_i` accounts for max lookback + sequence length.

### 6.2 Interval-overlap purge algorithm

For train set `T` and test fold `V`:

Drop from `T` all samples `j` where `interval_j` overlaps `interval_k` for any `k in V` **OR** feature dependency of `k` overlaps label interval of `j`.

Embargo `E` = `max(horizon_minutes) + max(seq_len) + max(calibration_window)` minutes after each test interval end.

### 6.3 Nested selection boundaries

| Stage | Data allowed | Isolation |
|-------|--------------|-----------|
| Base model fit | train purged | no val/test |
| Hyperparameter selection | inner purged CV on train | outer test untouched |
| Meta OOF generation | expanding session folds with purge | no test sessions |
| Calibration fit | calibration fold only | post-model-selection holdout |
| Threshold selection | validation only | final test never seen |
| Promotion decision | final test + economic harness | one-shot |

### 6.4 Method recommendation by use case

| Use case | Recommended architecture |
|----------|-------------------------|
| Base XGB/LSTM/TR selection | Combinatorial purged CV (CPCV) or purged K-fold with interval overlap |
| Walk-forward production monitoring | Anchored walk-forward with session blocks |
| Meta-learner OOF | Expanding session folds + interval purge + embargo |
| Calibration | Nested purged fold strictly after model lock |
| Final untouched test | Single chronological tail ≥ N sessions per ticker |

### 6.5 Mechanical overlap assertion

```python
assert not any(intervals_overlap(train_interval, test_interval) for ...)
```

CI MUST fail promotion if any overlap detected.

---

## 7. Phase 6 — Meta-learner leakage audit design

**Current isolation:** NOT_PROVEN.

| Claim | Status | Evidence |
|-------|--------|----------|
| OOF predictions from bases not trained on same row | NOT_PROVEN | `training_cache.expanding_window_oof_folds` exists; thin-session `in_sample_no_folds` fallback NOT_PROVEN safe |
| Preprocessing fit only on train fold | NOT_PROVEN | needs per-fold artifact trace |
| Calibration excluded from holdout | NOT_PROVEN | 5c uses inline maps MSD-003 |
| Sequence does not cross fold boundary | NOT_PROVEN | needs replay proof |
| Ticker identity cannot leak via split | NOT_PROVEN | pooled training paths exist |

**Promotion lock design (APPROVED):**

- Parse meta training report for `oof_basis != in_sample_no_folds`
- Block `execute_promotion_if_eligible` when meta trained with in-sample fallback
- Require `meta_oof_isolation_certificate.json` with fold manifest hash

---

## 8. Phase 7 — Negative-control battery (Matrix 7)

**Design:** APPROVED. **Execution:** NOT_PROVEN.

| # | Control | Defect class | Expected behavior | Fail threshold |
|---|---------|--------------|-------------------|----------------|
| 1 | Global label shuffle | leakage / phantom signal | metrics → chance | log_loss within 5% of permuted baseline |
| 2 | Within-session label shuffle | session leakage | metrics → chance | same |
| 3 | Session-block permutation | calendar leakage | no improvement vs 1 | Δlog_loss < 0.01 |
| 4 | Timestamp displacement +1 bar | lookahead | metrics collapse | Δlog_loss > 0.15 |
| 5 | Ticker permutation | identity leakage | metrics → chance | same as 1 |
| 6 | Feature-column permutation | false feature importance | importance flat | top feature Δ < ε |
| 7 | Random noise injection | overfit detector | no beat noise control | — |
| 8 | Identifier-only model | memorization | fail promotion | AUC ≈ 0.5 |
| 9 | Future-feature sentinel | lookahead | sentinel coefficient → 0 in purge | sentinel weight > ε → FAIL |
| 10 | Impossible timestamp mutation | pipeline integrity | hard fail | raise / abort |
| 11 | Train/test boundary mutation | split integrity | hard fail | overlap detector trips |
| 12 | Constant-label / class-prior | calibration sanity | metrics match prior | within tolerance |

**Policy:** Material beat of chance on shuffled labels → `NOT_APPROVED` for promotion. Seeds fixed + 20 repetitions for stochastic layers; session-clustered bootstrap CIs.

---

## 9. Phase 8 — Baseline and predictive-validity specification (Matrix 8)

**Design:** APPROVED.

### 9.1 Required baselines (per model × horizon)

Majority class, empirical prior, previous-label persistence, always-neutral, 1m/5m momentum, mean reversion, vol-conditioned prior, regime-conditioned prior, always-WAIT policy, production model, simpler nested model (e.g., XGB-only).

### 9.2 Metrics (not raw accuracy alone)

Balanced accuracy, macro F1, multiclass log loss, Brier, ECE, OVR discrimination, precision/recall at actionable confidence, abstention coverage, conditional return, drawdown, turnover, expected utility after costs.

### 9.3 Evidence requirements

Session-clustered bootstrap CIs; ≥60 independent RTH sessions per ticker×horizon; Holm-Bonferroni across horizons; minimum effect Δlog_loss > 0.02 vs production; stability across volatility regimes.

**Execution:** NOT_PROVEN.

---

## 10. Phase 9 — Calibration validity design (Matrix 9)

**Design:** APPROVED. **Known blocker:** MSD-003.

| Stage | Source score | Storage | Evaluation |
|-------|--------------|---------|------------|
| 5c isotonic | partial xgb+TR blend | **source code** CONFIRMED_DEFECT | per-ticker/decile/regime — blocked until externalized |
| A1 isotonic/conformal | fusion outputs | `v2_decision` attach path | independent calibration holdout |
| arch_competition promotion | ECE/Brier gates | promotion manifests | PROVEN mechanism; per-ticker matrix NOT_PROVEN |

Calibration fit data MUST NOT intersect model selection, meta fit, or final test.

---

## 11. Phase 10 — Incremental-value design (Matrix 10)

**Design:** APPROVED. Nested stacks:

`baseline → xgb → lstm → transformer → xgb+lstm → xgb+transformer → +meta → +monte_carlo → +regime → +order_flow → +dealer → +bayesian_fusion → full → full_minus_each_component`

Each addition: same OOS observations, same cost model, paired comparison with CI, regime/ticker/horizon breakdown, turnover impact. Components without reproducible incremental value → retirement candidate.

---

## 12. Phase 11 — Train/backtest/replay/live parity (Matrix 11)

**Design:** APPROVED. **Execution:** NOT_PROVEN.

Golden-record package flows through:

1. training feature construction  
2. offline inference  
3. backtest inference  
4. replay inference  
5. live inference adapter  

Deterministic stages: bitwise or documented ε tolerance. Stochastic: distributional invariants under fixed seed.

**Known parity defects:** MSD-001, MSD-002, MSD-003, MSD-004.

---

## 13. Phase 12 — Independent oracle and invariant tests (Matrix 12)

**Design:** APPROVED.

Invariants (must hold):

- Probabilities finite, sum to 1  
- Documented monotonicity preserved  
- Row-order permutation invariance for aggregations  
- Zero OI → zero exposure contribution  
- Missing optional data → explicit neutral / withhold, not bullish/bearish bias  
- Ticker vol substitution cannot retain incompatible semantics  
- Identical immutable inputs → identical deterministic outputs  
- Fallback outputs labeled — cannot impersonate model predictions  

---

## 14. Phase 13 — Economic-validity design

**Design:** APPROVED.

Harness includes: bid/ask, slippage, latency, decision-to-entry delay, fees, impact, stops, max hold, EOD flatten, stale quotes, abstention, overlapping signals, capital constraints, position sizing.

Report gross vs net. Separate directional validity, policy validity, execution validity, portfolio validity. Beat always-WAIT on risk-adjusted utility required for economic approval.

---

## 15. Phase 14 — Artifact provenance (Matrix 13)

**Presence:** PROVEN — 22 tickers across `models/active`, `active_5c`, `active_15c`, `active_60c`.

**Provenance validity:** NOT_PROVEN — `verify_active_models.py` checks file presence, not metric re-validation or hash lineage completeness.

| Ticker class | Meta coverage |
|--------------|---------------|
| SPY, QQQ, IWM | meta all 4 horizons |
| guest_meta_1c_only | meta 1c only |
| guest_no_meta | no meta |
| CRWD | sparse LSTM/TR gaps |

Each artifact MUST eventually carry: ticker, horizon, model class, schema version, label version, code SHA, data interval, fold definition, seed, hyperparameters, calibration artifact, metrics, CI, promotion decision, content hash, parent hashes, timestamp, authorization.

---

## 16. Phase 15 — Remediation architecture (Matrix 14)

| Lane | Type | Objective | Prerequisites |
|------|------|-----------|---------------|
| L0 | specification_decision | Operator volatility semantics (native vs macro) | — |
| L1 | confirmed_defect_fix | MSD-001 SignalInput vix parity | L0 |
| L2 | confirmed_defect_fix | MSD-002 native vol or governed O-NN | L0 |
| L3 | artifact_governance | Externalize 5c isotonic MSD-003 | — |
| L4 | confirmed_defect_fix | MSD-004 resolve 5c meta bypass | L3 |
| L5 | specification_decision | Wire or retire net_vanna MSD-005 | — |
| L6 | evaluation_infrastructure | Purged CV + embargo harness | — |
| L7 | mechanical_leakage_lock | Meta OOF promotion lock | L6 |
| L8 | evaluation_infrastructure | Negative-control CI gate | L6 |
| L9 | runtime_parity | Golden-record replay | L1, L2 |
| L10 | predictive_validation | Nested incremental-value eval | L6, L8 |
| L11 | economic_validation | Execution-aware harness | L10 |
| L12 | model_retraining | Retrain/recalibrate post-spec | L1-L4, L6, L7 |
| L13 | promotion_or_retirement | Per-component decision | L10, L11, L12 |
| L14 | card_level_proof | Live mhap_rows parity | L9, L13 |

**Forbidden in read-only mission:** production edits, retrain, recalibrate, promotion changes.

---

## 17. Matrix 15 — Final binary status table

See Section 1 Executive summary and JSON `final_binary_determinations`.

---

## 18. Repository proof

Printed at mission completion (see below).

**Authorized changed files only:**

- `reports/MODEL_STACK_SPECIFICATION_DEFECT_REPRODUCTION_AND_VALIDATION_DESIGN_V1.md`
- `reports/MODEL_STACK_SPECIFICATION_DEFECT_REPRODUCTION_AND_VALIDATION_DESIGN_V1.json`

---

## Appendix A — Live stack entry citations

| Hop | File:line |
|-----|-----------|
| Unified ML | `ml_predict.py:1863-1974` |
| Fusion | `signals.py:321-423` |
| Vol regime | `volatility_regime.py:165-231` |
| SignalInput stamp | `market_state.py:1287-1334` |
| 5c isotonic | `ml_predict.py:1795-1835` |
| Bundle contract | `active_bundle_contract.py:18-23` |

## Appendix B — Artifact inventory summary

22 tickers; anchors SPY/QQQ/IWM have xgb+lstm+transformer+meta on all horizons. Full bundle matrix in JSON `matrices.13_artifact_provenance`.
