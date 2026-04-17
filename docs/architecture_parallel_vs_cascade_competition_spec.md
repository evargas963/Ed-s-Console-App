# Parallel vs Cascade: Architecture Competition, Shared Artifacts, and Promotion

**Document type:** Source-of-truth architecture specification  
**Status:** Locked for implementation of the execution layer, evaluation runner, and promotion engine  
**Scope:** EdWebConsole ML stack — canonical inference contract (`v1_1m_mvp`, `1m` timeframe) and horizon-scoped training artifacts  

---

## 1. Executive summary

### 1.1 Why Parallel is the default runtime architecture initially

- **Independence:** In the Parallel architecture, base models (XGBoost, LSTM, Transformer) consume the **same** canonical feature and sequence inputs but do **not** depend on one another’s outputs at inference time. Failure or bias in one model does not mechanically propagate into another’s tensor construction.
- **Operational simplicity:** Parallel execution maps cleanly to **single-pass** inference (`run_base_models_once`), simpler debugging, and straightforward latency reasoning (one fan-out, one fusion step).
- **Training stability:** Parallel training does not require staged tensor pipelines where downstream models ingest upstream probability vectors; optimization surfaces are more separable and less entangled.
- **Deployment risk:** Parallel is the **conservative** default for capital-adjacent systems: the stack’s behavior is easier to reason about under stress, model hot-swap, or partial availability.

### 1.2 Why Cascade is treated as a challenger architecture

- **Structural coupling:** In the Cascade architecture, later models may consume **derived signals** from earlier models (e.g., probability vectors or other compact summaries concatenated into sequence or confluence tensors). That coupling can improve empirical fit but introduces **dependency chains** and **error amplification** if upstream calibration shifts.
- **Higher governance burden:** Any change to XGB calibration or LSTM masking affects not only XGB/LSTM marginal quality but also **conditional** inputs to Transformer (and potentially meta-learner inputs), requiring stricter change control.
- **Challenger role:** Cascade is not rejected a priori; it is held to **stricter** evidence standards before it may replace Parallel in production (`models/active/`).

### 1.3 Why both must be trained and evaluated from the same canonical artifact base

- **Fair comparison:** Promotion decisions must compare **architectures**, not accidental differences in feature versions, label definitions, splits, or cache generations.
- **Drift prevention:** If Parallel and Cascade trained from different feature caches, label columns, or split manifests, observed metric gaps are **uninterpretable** and may **invert** under a corrected alignment.
- **Auditability:** Regulators and internal risk review require a **single provenance chain** from raw authorized data through canonical contract rows to cached tensors and evaluation manifests.
- **Rollback safety:** When demoting an architecture, the replacement must be **substitutable** with respect to data lineage, not merely “better on a one-off leaderboard.”

---

## 2. Architecture definitions

### 2.1 Parallel architecture

**Definition:** A runtime and training configuration where:

- **XGBoost** consumes tabular MVP features from the **canonical inference contract** (and non-MVP overlay only where explicitly allowed by that contract’s fusion rules), producing class probabilities per horizon-trained head.
- **LSTM** consumes **merged canonical sequence rows** (structure stream and micro stream as defined by the sequence contract) **without** ingesting XGB or Transformer outputs as model inputs.
- **Transformer** consumes **merged canonical encoder windows** **without** ingesting XGB or LSTM outputs as model inputs, except where a **parallel-specific** training artifact explicitly adds non-cascade extras (e.g., fixed-width optional channels defined only for parallel checkpoints).
- **Meta-learner** (if present) consumes **only** stacked base-model probability outputs (and any explicitly allowed deterministic context defined in training config), not hidden states from other models.

**Allowed dependencies:**

- Shared **canonical cached tensors** (features, sequences, labels, masks).
- Shared **horizon definition** (`outcome_*` column, slug, and label semantics).
- Shared **train/validation/test/OOS** manifests.
- Independent forward passes; fusion of probabilities occurs **after** base models (Bayesian fusion / rules engine), not inside base model tensors except via the meta-learner as specified.

**Forbidden:**

- Using **XGB probabilities** as inputs to LSTM or Transformer **tensor construction** in the Parallel architecture.
- Using **LSTM** outputs as inputs to **Transformer** tensor construction in the Parallel architecture.
- Any **alternative MVP source** (raw L1 dict, legacy snapshot MVP keys, or SignalInput fields) bypassing `InferenceSnapshotV1` / `build_*_mvp_feature_row` at **inference** for models covered by canonical enforcement.

### 2.2 Cascade architecture

**Definition:** A runtime and training configuration where **downstream** base models may consume **compact outputs** from **upstream** base models as **additional input channels**, subject to explicit checkpoint contracts:

- **LSTM** may append or mask **channels derived from XGB class probabilities** (and only those channels defined in the cascade checkpoint metadata).
- **Transformer** may append **channels derived from XGB and/or LSTM class probabilities** (and only those channels defined in the cascade checkpoint metadata).
- **XGBoost** remains the **first** stage; it must not depend on LSTM or Transformer outputs.

**Allowed dependencies:**

- All Parallel allowances for **canonical artifacts** and **label integrity**.
- **Staged** dependency: XGB → (LSTM, Transformer) in the sense of **tensor augmentation**, not shared weights.
- Checkpoint-declared **extra channel widths** and **feature masks** that match saved normalization and model code paths.

**Forbidden:**

- **Circular** dependencies (e.g., XGB consuming LSTM outputs).
- **Hidden** coupling: any cascade extra not recorded in **model metadata** (mask lengths, norm stats alignment, channel semantics).
- **Inference-time** construction of cascade extras from **non-canonical** probability estimates (e.g., recomputing XGB inputs from legacy snapshot dicts instead of the same `_predict_xgb` path used in training).

### 2.3 Model inventory by architecture

| Model              | Parallel                         | Cascade                                      |
|--------------------|----------------------------------|----------------------------------------------|
| XGBoost            | Yes; independent                 | Yes; feeds cascade extras only as specified  |
| LSTM               | Yes; no upstream probs in tensor | Yes; may include XGB prob channels         |
| Transformer        | Yes; no upstream probs in tensor | Yes; may include XGB/LSTM prob channels    |
| Meta-learner       | Yes; on stacked probs            | Yes; on stacked probs (cascade-aware eval)   |

---

## 3. Shared canonical artifact layer

Both architectures **must** branch from the **same** versioned artifact set. The following is the **minimum** institutional set; no promotion may rely on ad-hoc files outside this layer.

### 3.1 Canonical feature artifacts

- **Bar/table extracts** aligned to `1m` canonical timeframe and **MVP contract version** (e.g. `v1_1m_mvp`).
- **Row-level manifests** listing `ts_utc`, ticker, and **data-quality flags** required for exclusion rules.
- **Fingerprint** of source DB tables and extraction query version (stored in scheduler manifest).

### 3.2 Sequence window artifacts

- **LSTM** cache: merged-window-compatible tensors or pre-merged row bundles keyed by a **feature cache key** that includes DB fingerprint + contract version + code version (see `training_cache` / scheduler conventions).
- **Transformer** cache: parallel sequence tensors stored under the **same** cache namespace family as LSTM where the row alignment is shared; cascade-specific tensor caches must declare **lineage** back to the same base windows.

### 3.3 Labels by horizon

- For each trained horizon slug (e.g. `15c`), the authoritative **`outcome_<slug>`** (or configured `target_column`) column in training frames.
- **Label definition document** per horizon: class semantics, leakage rules, and exclusion of post-label information.

### 3.4 Split manifests

- **Train / validation / test / OOS** row identifiers (`ts_utc`, ticker) with **no overlap**.
- **Embargo** rules for sequence models (no overlapping windows across splits where forbidden by policy).
- **Rolling evaluation** manifests: explicit window indices and **as-of** semantics for each fold.

### 3.5 Scaler / encoder artifacts

- **Normalization statistics** per model type, aligned to **feature masks** saved in checkpoint metadata.
- **Categorical encodings** (zone, VWAP side, etc.) with **frozen** vocabulary sourced from training-only splits unless a documented cold-start policy applies (default: **forbid** vocabulary drift between train and eval without retrain).

### 3.6 Regime tags

- **Per-bar or per-window regime labels** (from the approved regime engine output schema) aligned by `ts_utc`.
- Regime definitions **versioned**; regime eval must not mix tag versions across compared architectures.

### 3.7 Evaluation manifests

- **Per-run evaluation JSON** (accuracy, balanced accuracy, log loss, realized-contract or PnL-proxy metrics where applicable) with **architecture name**, **horizon slug**, **split name**, **date range**, **git/hash or build id**, and **cache key**.

### 3.8 Contract, timeframe, and version metadata

- **`feature_contract_version`** (must match across candidates).
- **`canonical_timeframe`** (must match; default `1m`).
- **Model code version** or **scheduler training_cache version** token.
- **Inference snapshot type** and fusion overlay rules version (if overlay affects training data construction for non-MVP channels).

**Rule:** Parallel and Cascade **must** reference the **same** metadata record for a given promotion trial; any mismatch is a **hard block** (see §7).

---

## 4. Training flow

### 4.1 Common trunk (both candidates)

1. **Extract** canonical bars from the authorized DB path for enrolled tickers and configured history.
2. **Materialize** cached feature tensors / NPZ bundles under `models/cache/features/{feature_cache_key}/` (or successor path) with a **scheduler_run_manifest** capturing inputs.
3. **Build** labels per horizon from the same `outcome_*` definitions.
4. **Apply** split manifests; **freeze** scalers and encoders from **training** portions only.
5. **Emit** evaluation-ready manifests for downstream runners.

### 4.2 Parallel candidate branch

1. Train **XGB** from tabular canonical frames.
2. Train **LSTM** from sequence caches **without** XGB outputs in the tensor.
3. Train **Transformer** from sequence caches **without** cascade extras (unless parallel checkpoint explicitly includes optional non-cascade channels documented in metadata).
4. Train **meta-learner** on stacked **parallel** base outputs on the training split; validate on validation split.

**Output directory convention (current codebase alignment):** `models/parallel/{ticker}/` with horizon-qualified filenames (e.g. `xgb_{ticker}_{hz}.pkl`, `lstm_{ticker}_{hz}.pt`, `transformer_{ticker}_{hz}.pt`, `meta_{ticker}_{hz}.pkl`).

### 4.3 Cascade candidate branch

1. Train **XGB** using the **same** tabular frames and labels as Parallel.
2. **Generate frozen** out-of-fold (or strictly train-split) XGB probability features **only** as allowed for cascade tensor assembly (to prevent leakage, use methodology fixed in the runner: either train-only fold generation or approved cross-fit).
3. Train **LSTM** with **cascade augmentation** per checkpoint contract.
4. Train **Transformer** with **cascade augmentation** per checkpoint contract.
5. Train **meta-learner** on stacked **cascade** base outputs.

**Output directory convention:** `models/cascade/{ticker}/` with parallel naming scheme for filenames so diff tools and promotion logic can pair artifacts.

### 4.4 Branching invariant

For a single promotion trial ID `T`:

- `feature_cache_key(T)` is identical for Parallel and Cascade.
- `label_column` / horizon slug is identical.
- `split_manifest_id(T)` is identical.
- Any **cascade-only** tensor cache must include `parent_cache_key = feature_cache_key(T)` in metadata.

---

## 5. Evaluation flow

### 5.1 Train / validation / test / OOS structure

- **Train:** model fitting and threshold tuning **inside** model-specific procedures only.
- **Validation:** hyperparameter and early stopping; **must not** appear in promotion metrics.
- **Test:** primary **offline** leaderboard for architecture comparison (still not live).
- **OOS (out-of-sample):** **frozen** models, **frozen** normalization, **no** refit; this is the **only** split that counts toward **promotion** decisions.

### 5.2 Rolling windows

- For each OOS segment, support **rolling origin** evaluation: multiple contiguous OOS windows with **non-overlapping** primary labels where policy requires.
- Report **mean and dispersion** of metrics across rolls; a single lucky window cannot promote.

### 5.3 Horizon-level evaluation

- Each horizon slug is evaluated **separately**.
- **No** pooling across horizons for promotion unless a **pre-declared** multi-horizon rule exists (default: **no** global pooling).

### 5.4 Regime-level evaluation

- Slice metrics by **regime tag** buckets; define minimum support counts per bucket.
- **Failure** in a materially traded regime (e.g. high-volatility or trend_continuation, per policy) can **veto** promotion even if aggregate metrics rise.

### 5.5 Calibration review

- **Reliability diagrams** or equivalent for predicted probabilities vs empirical outcomes **per base model** and **per fused output** if fusion is in scope for the trial.
- **ECE / Brier**-style summaries where applicable; thresholds defined in §6.

### 5.6 Confidence reliability review

- Compare **stated confidence labels** (high/medium/low) against **realized hit rates** on OOS.
- Cascade must not win on point metrics while **degrading** confidence ordering.

### 5.7 Decision / PnL proxy review

- Where **realized_contract_eval** or equivalent exists, require **OOS** economic proxies (net of friction assumptions) with **confidence intervals** or block-bootstrap bands.
- **No** promotion on accuracy alone if PnL-proxy deteriorates beyond tolerance.

---

## 6. Promotion policy

### 6.1 Required metrics (minimum set)

For each horizon and architecture pair on **OOS**:

- **Classification:** balanced accuracy, log loss (multiclass), **calibration** summary.
- **Stability:** variance across rolling OOS windows; worst-window floor.
- **Economic:** realized-contract or approved PnL proxy (when available for the ticker universe).
- **Operational:** latency and failure rate **budgets** (Cascade must not breach SLO without explicit approval).

### 6.2 Minimum superiority threshold

- **Primary metric gap:** Challenger (Cascade) must exceed Parallel on the **pre-declared primary metric** by at least **Δ** on OOS, where **Δ** is set per horizon (not globally tuned post hoc). Example placeholder: **Δ_logloss ≥ 0.02** or **Δ_balanced_accuracy ≥ 0.02** — **final Δ** must be committed in config before the trial.
- **No single-metric promotion:** see §7.1.

### 6.3 Minimum stability threshold

- **Rolling OOS:** Primary metric mean − **k** × std (k configured, e.g. 1.0–1.5) must still beat Parallel’s mean.
- **Worst-window:** Challenger must not lose to Parallel in **more than** a configured fraction of rolls (e.g. ≤ 40% losses) unless documented **regime-specific** compensation applies.

### 6.4 What blocks promotion

- Any **artifact version mismatch** (§7.4).
- Any **contract/timeframe** mismatch (§7.3).
- **Contaminated** train/test leakage (§7.2).
- **Calibration** regression beyond tolerance vs Parallel.
- **Regime** failure modes on materially important buckets.
- **SLO** breach for Cascade.
- **Insufficient** OOS support count for the ticker or horizon.

### 6.5 Ties

- **Default:** **Remain on Parallel** (incumbent wins ties).
- **Exception:** only if a **pre-registered** secondary metric tie-breaker favors Cascade **and** no calibration or stability regression occurs.

### 6.6 Cascade wins on one metric but loses on calibration or stability

- **No promotion.** Calibration and stability are **co-equal gates**, not post-hoc annotations. Retrain or reject Cascade; do not blend architectures without a separate **ensemble** policy (out of scope for this spec’s promotion act).

### 6.7 Global vs per-horizon promotion

- **Default:** **Per-horizon** promotion. A Cascade win at `15c` does **not** imply promotion at `60c`.
- **Global promotion** (all horizons switch) requires **explicit** executive approval and pre-declared **multi-horizon** criteria met on **all** active traded horizons.

### 6.8 Rollback / demotion policy

- **Automatic rollback** if post-promotion monitoring breaches **worse** than Parallel’s trailing OOS band for **N** sessions or **M** trades (configured).
- **Demotion** restores **Parallel** artifacts to `models/active/{ticker}/` and updates `arch_state.json` (or horizon-scoped `arch_state_{hz}.json`) with reason codes.
- **Incident** requires frozen artifact snapshot and evaluation manifest retention.

---

## 7. Governance rules

### 7.1 No architecture promotion on one metric alone

- A challenger must pass **primary metric**, **calibration**, **stability**, and **regime** gates jointly. No “log loss improved but calibration collapsed” promotions.

### 7.2 No promotion from contaminated datasets

- Any split overlap, label leakage, or **future information** in features → **disqualification** and incident review.

### 7.3 No promotion if feature contract or timeframe differs

- `feature_contract_version` and `canonical_timeframe` must be **bit-identical** strings across compared runs.

### 7.4 No promotion if artifact versions differ

- **Feature cache key**, **split manifest id**, and **label column** must match. **Scheduler / training_cache** version tokens must match unless both runs are **replayed** from the same archived trunk.

### 7.5 No promotion if evaluation windows are mismatched

- OOS date ranges, rolling window definitions, and **universe** (tickers included) must be identical for the trial pair.

---

## 8. Implementation roadmap (build order)

1. **Parallel runtime execution layer**  
   - Harden `models/parallel/{ticker}/` as default load path; ensure `run_base_models_once` and fusion integration use **only** canonical inference for live.

2. **Challenger cascade path**  
   - Isolated inference path loading `models/cascade/{ticker}/` with cascade tensor assembly; **no** fallback to parallel checkpoints when cascade is selected.

3. **Evaluation runner**  
   - Single CLI / job that consumes **shared manifests**, trains or loads both candidates, and emits **paired** evaluation JSON for each horizon and roll.

4. **Promotion engine**  
   - Consumes evaluation JSON; applies §6 gates; writes `models/active/{ticker}/`; updates `arch_state.json`; logs `training_report.jsonl` lines with **decision rationale codes**.

5. **UI / manifest visibility**  
   - Dashboard surfaces: active architecture, last promotion time, metric deltas, cache keys, contract version, and **rollback** status.

**Dependency rule:** Steps 3–4 must not ship without §3 artifact metadata completeness; step 5 depends on structured JSON from step 4.

---

## 9. Final recommendation (operating model)

- **Parallel live first:** Production defaults to Parallel in `models/active/` with explicit `arch_state` documentation.
- **Cascade as challenger:** Cascade trains and evaluates on every scheduled cycle **only** against the **same** canonical trunk; it **never** silently replaces Parallel.
- **Promote only after repeated OOS superiority plus stability:** Require **multiple** OOS rolls and **consistent** outperformance under calibration and regime gates before switching `active`.
- **Tie goes to Parallel:** Incumbent architecture retains production unless Cascade clears **all** gates with margin.

---

**End of specification.**
