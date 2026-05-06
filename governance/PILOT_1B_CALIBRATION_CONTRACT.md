# Pilot 1B Calibration Scaffold Contract

**Status:** DRAFT implementation contract  
**Date:** 2026-05-05  
**Module:** A - short-horizon event-driven trading  
**Initial scope:** A1 calibrated entry probability; A2 calibration placeholder only  
**Initial tickers:** SPY / QQQ unless amended  
**Runtime plane:** Tier C only  
**Depends on:** `governance/IMPLEMENTATION_BLUEPRINT_V2.md`, `governance/PILOT_1B_A2_0DTE_CONTRACT.md`, `governance/Framework-ED-Decision-Engine-v2.0-DRAFT.md`, `docs/calibration_statistical_integrity_v2.md`

This contract defines the calibration scaffold required before v2 probability, conformal, and EV fields can move from `not_implemented` to measured advisory outputs.

It is not production authority, does not bind replay/live parity, and does not change locked v1.1 behavior.

---

## Objective

Pilot 1B calibration first promotes Module A/A1 from raw stack/fusion probability to calibrated advisory probability:

> Given an advisory v2 A1 decision snapshot and a realized short-horizon outcome label, estimate calibrated `P_entry_success` and health metrics honestly enough to support later conformal and EV layers.

Initial implementable path:

| Field | Initial target | Status |
|---|---|---|
| `P_entry_success` | existing raw A1 stack/fusion probability | Already present as `v1_approximation` |
| `calibrated_P_entry_success` | isotonic-calibrated A1 probability | Scaffold target |
| `calibration_health` | ECE, Brier, reliability table, sample gates | Scaffold target |
| `p_low` / `p_high` | conformal bounds over calibrated probability | Follow-on after calibration |
| `EV_lower` / `EV_upper` | EV bounds using calibrated/conformal probabilities | Follow-on after conformal |
| `execution_adjusted_EV` | EV after spread/fill/slippage costs | Follow-on after execution model |

A2 contract-profit calibration is explicitly deferred until contract-level payoff labels exist.

---

## Non-Goals

This scaffold does not:

- enable live retraining;
- feed a learning loop;
- bind replay/live parity;
- alter trade authority;
- promote calibration artifacts;
- claim A2 contract-profit calibration;
- compute lifecycle-adjusted probability;
- replace v1.1 stack/fusion authority.

All outputs remain advisory, Tier C only, and source-indicated until a future preregistration or authority-binding event.

---

## Required Calibration Outputs

A calibration run must produce:

| Output | Required behavior |
|---|---|
| `calibration_run_id` | Stable run identifier, content-addressable once artifact promotion exists |
| `calibration_window_id` | Walk-forward window identity with train/calibration/holdout dates |
| `calibrated_P_entry_success` | A1 calibrated probability, source `v2_compliant` only after backfill data and holdout metrics satisfy this contract |
| `raw_P_entry_success` | Input probability used for calibration |
| `ece` | Expected calibration error on holdout, with bin definition and sample count |
| `brier_score` | Holdout Brier score with sample count |
| `reliability_table` | Probability bins with predicted mean, observed hit rate, and `n` |
| `regime_reliability` | Reliability metrics stratified by required regime axes |
| `sample_gates` | Explicit sufficient/insufficient flags for every aggregate and regime cell |
| `calibration_health` | `ok`, `warning`, or `degraded`, with reason codes |

No aggregate or regime statistic may emit numeric rates or means below the governed sample floor. Existing `calibration.statistical_integrity` rules apply.

---

## Backfill Data Plane Requirements

Calibration requires `(decision_snapshot, outcome_label)` pairs. Because Pilot 1A/1B has been advisory-only, these pairs must be produced by a governed historical backfill plane before calibration can be attached to runtime payloads.

Backfill requirements:

- reconstruct historical Tier C `ms_dict` payloads at decision time;
- run the current v2 adapter on each reconstructed historical state;
- persist the v2 advisory decision snapshot with schema version, source indicators, and decision-generation metadata;
- compute realized short-horizon outcome labels from forward bars;
- for A2 later, compute realized contract outcomes from archived option chains and lifecycle policy;
- enforce purged walk-forward train/calibration/holdout windows;
- apply an embargo between training data and serving/evaluation windows;
- record excluded rows and exclusion reasons;
- preserve `snapshot_id`, `decision_time`, ticker, regime fields, and raw probability inputs for traceability.

Backfill adapter version must equal the live serving v2 adapter version at the moment calibration is fit. If the v2 adapter changes through a new gate, source-field change, probability input change, or other decision-logic modification, calibration backfill must re-run from scratch with the new adapter version. Partial calibration backfills across adapter versions are forbidden.

Existing useful surfaces:

| Surface | Reuse role | Gap |
|---|---|---|
| `calibration_decision_log` | Existing decision/outcome logging path for calibration studies | Must capture v2 advisory decision shape, not only current v1.1/fusion payloads |
| `calibration.backfill_outcomes` | Existing outcome backfill concept | Needs v2 advisory decision snapshot linkage |
| `realized_contract_eval.py` | Contract replay and trade-log semantics | A2 calibration deferred until contract-label schema and lifecycle policy exist |
| `calibration.analyze_phase3` | Reliability/Brier/regime analysis | Must be adapted or wrapped for v2 A1 calibrated probability |
| `calibration.statistical_integrity` | Minimum-n gates and no numeric leakage | Must remain mandatory for all calibration output paths |

Calibration cannot be implemented honestly without this backfill plane.

---

## A1 Calibration Path

A1 calibration is implementable before A2 contract-profit labels.

Inputs:

- raw Module A/A1 stack or fusion probability;
- advisory v2 A1 action/direction;
- realized short-horizon label from historical forward bars;
- regime context at decision time.

Default method:

- isotonic regression over raw `P_entry_success`;
- fitted only on training/calibration windows;
- evaluated on holdout windows;
- no same-window training/evaluation;
- no unlabeled rows included in fit or reported as neutral outcomes.

Calibration acts on the post-fusion meta probability that flows into `v2_decision.decision.P_entry_success`. Base models are not separately calibrated under this scaffold; the fused probability is the calibration target.

Rationale:

Isotonic regression is the default because short-horizon trading score distributions are skewed and often non-Gaussian. Platt or beta calibration may be evaluated later, but using them as the default requires an operator decision or registered alternative.

---

## A2 Calibration Path

A2 calibration is pending.

`P_contract_profit` must remain `not_implemented` until all of these exist:

- contract-level entry and exit labels;
- selected contract entry price and exit price;
- governed lifecycle policy or static baseline policy;
- realized contract PnL decomposition;
- IV/Greeks path attribution where available;
- replay/live parity status for option-chain selection;
- sufficient holdout sample size after skip/exclusion gates.

Until then:

| A2 field | Required source behavior |
|---|---|
| `P_contract_profit` | `not_implemented` |
| `P_lifecycle_adjusted_profit` | `not_implemented` |
| `EV_contract_mid` | `not_implemented` |
| `execution_adjusted_EV` | `not_implemented` |

---

## Per-Regime Stratification

Calibration quality must be reported both aggregate and stratified.

Regime axes for calibration must be deterministic rule-based buckets to avoid circular dependency on learned regime classifiers. The `volatility_regime` bucket is computed from observable volatility features such as VIX percentile cutoffs at decision time, not from a classifier output.

Required regime axes:

- `volatility_regime`;
- `time_of_day_bucket`;
- `expiry_dte_bucket`;
- ticker;
- action/direction;
- primary horizon.

Suggested `time_of_day_bucket` values:

- `open_30m`;
- `midday`;
- `power_hour`;
- `late_day_30m`.

Suggested `expiry_dte_bucket` values:

- `0DTE`;
- `1DTE`;
- `2_5DTE`;
- `gt_5DTE`;
- `not_options_applicable`.

Every cell must report `n` and a sample gate. Cells below `MIN_SAMPLES_STATISTICAL` may be listed but must not emit reliability rates, ECE, or Brier conclusions.

---

## Calibration Health Gates

Calibration health introduces a new advisory hard gate once policy values are bound.

Proposed non-binding operator decisions:

| Proposed ID | Topic | Starter value | Status |
|---|---|---|---|
| O-22 | `a1_calibration_health_max_ece` | warning above `0.05`; degraded above `0.08` on holdout ECE | Not binding until registered |
| O-23 | `a1_conformal_min_empirical_coverage` | nominal coverage `0.90`; degraded if holdout empirical coverage below `0.85` | Not binding until registered |

Additional policy values pending operator decision:

| Policy | Recommended starter | Status |
|---|---|---|
| Refit cadence | weekly walk-forward refit | Not binding until registered |
| Embargo period | 2 full market sessions | Not binding until registered |
| Minimum aggregate holdout sample | governed by existing statistical-integrity floor, with higher floor preferred before promotion | Pending |
| Minimum regime-cell sample | `MIN_SAMPLES_STATISTICAL` | Existing statistical-integrity floor |

Proposed non-binding sample-floor decisions:

| Proposed ID | Floor | Recommended starter | Status |
|---|---|---|---|
| O-24 | Aggregate holdout | `500` samples | Not binding until registered |
| O-25 | Per-regime cell | `50` samples | Not binding until registered |
| O-26 | Per reliability bin | `30` samples | Not binding until registered |

If a scheduled refit fails statistical-integrity gates, the previously fit calibration model may continue serving in advisory mode with `calibration_age` reported in the v2 output. After three consecutive failed refits, proposed as O-27 if registered, `calibration_health` becomes `degraded` regardless of last-run ECE.

Runtime implication after O-22/O-23 are approved:

```python
if calibration_health["status"] == "degraded":
    emit_wait("calibration_health_degraded")
```

This gate remains advisory during Pilot 1B, but A2 and future v2 surfaces must record when calibration health would block a recommendation.

---

## Existing Module Audit

| Surface | Current capability | Calibration role | Main gaps |
|---|---|---|---|
| `calibration/analyze_phase3.py` | Reliability, Brier, regime buckets over `calibration_decision_log` | Starting point for A1 calibration-health metrics | Analysis only; does not yet fit calibrated probability artifact |
| `calibration/statistical_integrity.py` | Minimum-n gates and no numeric leakage checks | Required for every calibration output | Must be applied to v2-specific calibration reports |
| `calibration/backfill_outcomes.py` | Outcome attachment for calibration rows | Starting point for labeled outcomes | Must attach v2 advisory decision snapshots |
| `calibration/schema.py` | Calibration table setup | Existing persistence path | Needs v2 schema extension or sidecar if current columns are insufficient |
| `realized_contract_eval.py` | Option contract replay and trade logs | Future A2 label path | Not ready for A2 calibration without lifecycle-label contract |
| `v2_decision/module_a_adapter.py` | A1/A2 advisory payload shape | Runtime attachment point for calibrated A1 probability | Currently emits probability fields as approximations/placeholders |

---

## Required Gap List

Initial v2 calibration implementation must name these gaps until closed:

- `v2_backfill_decision_snapshot_plane_not_implemented`;
- `v2_walk_forward_calibration_windows_not_bound`;
- `v2_calibration_artifact_not_promoted`;
- `v2_calibration_health_gate_policy_pending`;
- `v2_conformal_coverage_policy_pending`;
- `v2_a2_contract_profit_labels_not_implemented`;
- `v2_execution_adjusted_ev_not_implemented`;
- `v2_lifecycle_adjusted_probability_not_implemented`;
- `v2_replay_live_parity_not_bound`.

---

## Tests Required Before Runtime Attachment

Before calibrated fields attach to Tier C runtime payloads, tests must prove:

- v2 advisory decision snapshots can be produced from historical backfill inputs;
- walk-forward splits do not overlap;
- embargo windows exclude prohibited rows;
- unlabeled rows are excluded rather than treated as neutral;
- isotonic calibration produces bounded probabilities in `[0, 1]`;
- reliability table includes `n` and sample gates for every emitted bucket;
- ECE and Brier are withheld below sample floor;
- `calibration_health` becomes `degraded` when ECE exceeds O-22 after O-22 is registered;
- conformal coverage becomes `degraded` when empirical coverage falls below O-23 after O-23 is registered;
- A2 contract-profit fields remain `not_implemented` until contract labels exist;
- advisory-only authority remains unchanged.

---

## Binary Closure Criteria

Contract phase is complete when:

- this document exists as a durable governance artifact;
- A1 and A2 calibration scopes are explicitly separated;
- backfill data plane prerequisites are named;
- O-22/O-23 are proposed but not treated as binding until registered;
- no runtime behavior changes are made by this contract artifact.

Implementation phase is complete when:

- v2 advisory historical decision snapshots are backfilled;
- walk-forward and embargo rules are enforced;
- A1 calibrated probability is produced from holdout-safe data;
- ECE, Brier, reliability, and regime tables are emitted with sample gates;
- calibration health is source-indicated in Tier C;
- A2 calibration remains deferred until contract-level labels exist;
- all focused tests pass under the amended green-only advisory policy.
