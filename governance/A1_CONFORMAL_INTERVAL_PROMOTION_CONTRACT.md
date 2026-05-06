# A1 Conformal Interval Promotion Contract

**Status:** Draft promotion contract
**Date:** 2026-05-06
**Module:** A - short-horizon directional trading
**Expression profile:** A1 - equity / ETF
**Scope:** Runtime advisory promotion of `p_low` and `p_high` only.

This contract defines the preconditions for promoting the A1 conformal probability interval leaves in `v2_decision/module_a_adapter.py` from structural placeholders to populated Tier C advisory leaves.

---

## Authority Block

```text
mode = advisory_non_authoritative
tier = C_analytics_only
changes_trade_behavior = False
```

This contract does not authorize trade behavior, position sizing changes, policy binding, or promotion to runtime authority. It only defines when `p_low` and `p_high` may become advisory `v1_approximation` leaves.

---

## Scope

In scope:

- `v2_decision/module_a_adapter.py` `p_low`
- `v2_decision/module_a_adapter.py` `p_high`

Out of scope:

- `EV_lower`
- `EV_upper`
- `net_expected_value_r`
- execution-adjusted EV fields
- lifecycle-adjusted probability fields
- UI display changes
- policy-object binding

Promotion is single-direction under this contract: `p_low` and `p_high` may move from `not_implemented` to `v1_approximation`. They must not be marked `v2_compliant` under this contract.

---

## Promotion Preconditions

All preconditions are required and must be evaluated in this order:

1. **Conformal artifact present.** A conformal artifact is loadable for the decision context.
2. **Artifact schema version valid.** Artifact `schema_version` equals `A1_CONFORMAL_ARTIFACT_SCHEMA_VERSION` from `calibration/v2_a1_conformal.py` (currently `"1"`).
3. **Honest evaluation gate (O1).** Separate post-fit evaluation rows are present in the artifact and measured empirical coverage is at least `A1_CONFORMAL_DEGRADED_COVERAGE` (currently `0.85`). Same-holdout coverage alone is insufficient for runtime advisory promotion because the conformal scaffold documents that it can be optimistic.
4. **Aggregate sample threshold (G3).** The fit set contains at least `A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES` rows.
5. **Horizon match.** Artifact `horizon` equals the decision context's target horizon.
6. **Freshness discipline.** The artifact carries a numeric `governed_max_age_seconds` field and a numeric `generated_at_epoch_seconds` timestamp. Artifact age = current epoch - `generated_at_epoch_seconds`; promotion requires age <= `governed_max_age_seconds`. The freshness policy is bound by **O-29** to **691200 seconds (8 days; operational freshness bound for weekly cadence plus one-day tolerance, not a statistical validity claim about coverage guarantee)**. `calibration_run_id` / `calibration_window_id` must not be used as freshness proxies. If either field is missing or the artifact is stale, precondition 6 fails.
7. **Calibrated probability available.** `ms_dict["a1_calibrated_probability"]` is a numeric value in [0, 1]. The input probability must have passed through the A1 isotonic calibration before the conformal interval is applied. Banding a raw or uncalibrated probability is invalid because the conformal scaffold's quantile was fit on calibrated probabilities. If `a1_calibrated_probability` is absent or outside [0, 1], precondition 7 fails.
8. **Calibration lineage match.** `ms_dict["a1_calibrated_probability_lineage_id"]` is a non-empty string that exactly equals `artifact["calibration_lineage_id"]`. Lineage match is required because the conformal quantile was fit on probabilities produced by a specific isotonic calibration model. Applying the band to a probability from a different model is invalid even if the value happens to be in [0, 1].

If any precondition fails, both leaves remain `not_implemented` unless a future contract explicitly permits independent leaf promotion.

---

## Population Semantics

When all preconditions pass:

```text
p_low  = leaf(<lower interval value from artifact>, "v1_approximation", detail="<artifact provenance>")
p_high = leaf(<upper interval value from artifact>, "v1_approximation", detail="<artifact provenance>")
```

When any precondition fails:

```text
p_low  = leaf(None, "not_implemented", detail="<which precondition failed>")
p_high = leaf(None, "not_implemented", detail="<which precondition failed>")
```

The detail string is the only required place where precondition failure is conveyed. This contract does not introduce a separate gating field, status enum, or sidecar wrapper for these two leaves.

---

## No Synthetic Intervals

When conformal intervals are unavailable or any precondition fails, implementations must not emit synthetic, default, mean-of-stack, interpolated, copied-from-another-horizon, or stale interval values.

The leaves must stay `not_implemented` with `value = None`. A populated value must never appear with a failed precondition, and `source = "v1_approximation"` must never appear with `value = None`.

---

## Test Bar For Future Code

The implementation commit must use red-green evidence. Minimum required tests:

- all eight preconditions pass -> `p_low` and `p_high` are populated and use `source = "v1_approximation"`;
- each precondition fails independently -> both leaves remain `not_implemented` with a detail string naming the failed precondition;
- lineage match failure modes are tested per `governance/A1_CALIBRATED_PROBABILITY_PROVENANCE_CONTRACT.md` test bar (match, mismatch, missing marker, empty marker), with explicit `precondition_8_calibration_lineage_match_failed` status assertion;
- no-synthetic-intervals regression: `source = "v1_approximation"` if and only if `value` is non-`None`;
- backward-compatibility regression: when no artifact is loadable, both leaves remain byte-identical to the current baseline in `v2_decision/module_a_adapter.py`;
- schema regression: `validate_v2_decision` accepts both promoted and unpromoted states.

The implementation commit message must cite the failing red test invocation and the passing green invocation.

---

## Named Gaps

- `a1_conformal_per_regime_coverage_pending` - Per-regime coverage gating is not implemented in v1. Aggregate gating may mask edge-regime undercoverage; future work may adopt per-regime or hybrid gating.
- `a1_conformal_artifact_freshness_threshold_policy_object_pending` — **resolved** by **O-29** (consolidated with `a1_conformal_artifact_governed_max_age_seconds`; 691200 seconds operational freshness bound). Precondition 6 wording updated to cite O-29.

These are contract-level discipline gaps. They do not alter A2 lifecycle sidecar preview-blocking gap semantics.

---

## Promotion To `v2_compliant`

None of the following criteria are satisfied by this contract. Promotion from `v1_approximation` to `v2_compliant` requires all of them plus a future operator decision:

- per-regime coverage gating implemented, closing `a1_conformal_per_regime_coverage_pending`;
- freshness threshold policy bound by operator decision register, closing `a1_conformal_artifact_freshness_threshold_policy_object_pending`;
- counterfactual sensitivity exposed alongside the interval;
- approximate-guarantee disclosure attached to the leaves;
- operator decision register entry explicitly promoting the source.

This contract does not make `p_low` or `p_high` `v2_compliant`.

---

## Crosswalk

Existing `v1_approximation` leaves in the current Module A/A1 decision block are not changed by this contract:

- `action`
- `direction`
- `probability`
- `P_entry_success`
- `confidence`
- `position_size_fraction`
- `entry`
- `stop`
- `targets`
- `invalidation`

The following leaves remain out of scope and must stay under their existing source indicators until separate contracts govern them:

- `P_lifecycle_adjusted_success`
- `net_expected_value_r`
- `EV_lower`
- `EV_upper`
- `timeout`
- `decision_latency_budget_ms`

Related contracts:

- `governance/A1_CONFORMAL_ARTIFACT_LIFECYCLE_CONTRACT.md` (2A) - defines artifact persistence, identity, freshness fields, loader surface, and `calibration_lineage_id` producer-side semantics.
- `governance/A1_CALIBRATED_PROBABILITY_PROVENANCE_CONTRACT.md` (2B) - defines canonical calibration source, runtime marker shape, lineage match comparison rule, and the failure status emitted when precondition 8 fires.

---

## Non-Goals

This contract does not:

- promote EV bounds;
- promote execution-adjusted EV;
- change UI;
- change runtime authority;
- change trade or sizing behavior;
- bind a freshness policy;
- add registry entries;
- add named gaps beyond the two listed above;
- edit `v2_decision/module_a_adapter.py`;
- assume any input probability is calibrated; calibrated probability must be explicitly supplied via `ms_dict["a1_calibrated_probability"]`;
- treat `calibration_run_id` or `calibration_window_id` as freshness signals.
