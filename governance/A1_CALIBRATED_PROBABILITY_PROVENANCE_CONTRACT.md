# A1 Calibrated Probability Provenance Contract

> Path note (2026-08-25): companion lifecycle/production contract documents referenced below now resolve under `governance/archive/`.

**Status:** Draft provenance contract
**Date:** 2026-05-06
**Module:** A - short-horizon directional trading
**Expression profile:** A1 - equity / ETF
**Scope:** Runtime calibrated-probability lineage for A1 conformal promotion.

This contract defines how a runtime calibrated probability proves it came from the same isotonic calibration lineage as the conformal artifact used to produce A1 `p_low` / `p_high` intervals. It does not amend the existing promotion contract, implement precondition 8, or rewire runtime calibration.

**Track 3 implementation closed** by commit chain `fa72201` -> `1d177ca` -> `f96a5a3` -> `bb648db` -> `b4c8f7d`. Specific gap retirements with closing-commit citations appear under "Named Gaps" below. The `a1_ml_predict_to_v2_calibration_bridge_pending` gap **remains open** per the additive discipline.

---

## Authority Block

```text
mode = advisory_non_authoritative
tier = C_analytics_only
changes_trade_behavior = False
```

This contract does not authorize trade behavior, position sizing changes, runtime authority, or promotion of `p_low` / `p_high` to `v2_compliant`. It only binds the lineage discipline required before A1 conformal intervals may be populated as advisory leaves.

---

## Scope

In scope:

- canonical-source declaration for A1 conformal lineage;
- `ms_dict` marker shape and propagation requirement;
- lineage match comparison rule;
- future precondition 8 wording, locked here but not yet inserted into the existing promotion contract;
- failure status enumeration extension.

Out of scope:

- implementation of precondition 8 in `derive_a1_conformal_bounds`;
- amendment commit adding precondition 8 to `governance/A1_CONFORMAL_INTERVAL_PROMOTION_CONTRACT.md`;
- runtime rewire to the canonical source;
- bridge contract between `ml_predict` isotonic and `v2_a1_calibration` lineage;
- edits to `governance/A1_CONFORMAL_ARTIFACT_LIFECYCLE_CONTRACT.md`;
- artifact production hookup, loader implementation, `ms_dict` injection, UI, execution EV, lifecycle, scheduler, or runtime authority changes.

---

## Canonical Source Declaration

`calibration.v2_a1_calibration` is canonical for A1 conformal artifact lineage.

Conformal artifacts governed by `governance/A1_CONFORMAL_ARTIFACT_LIFECYCLE_CONTRACT.md` must be fit on probabilities produced by `apply_isotonic_model` against isotonic artifacts produced by `fit_a1_isotonic_artifact`.

`ml_predict._apply_5c_xgb_plus_transformer_isotonic_calibration` remains production-active for the existing stack runtime path. It is non-canonical for A1 conformal promotion lineage. Probabilities produced by this path cannot satisfy precondition 8 unless a future bridge contract explicitly declares them lineage-equivalent.

This declaration avoids a silent mismatch where the conformal quantile is fit on probabilities from one isotonic model but applied at runtime to probabilities from another.

---

## `ms_dict` Marker Shape

`ms_dict["a1_calibrated_probability_lineage_id"]` is the runtime marker for A1 conformal promotion lineage.

Required semantics:

- The marker is a string.
- It must uniquely identify the isotonic calibration artifact whose `apply_isotonic_model` output produced `ms_dict["a1_calibrated_probability"]`.
- The recommended format is `<calibration_run_id>:<isotonic_artifact_hash_or_id>`.
- Future code may refine the exact encoding; the uniqueness-and-identity semantic must not be weakened.

This mirrors the minimum required semantics of `calibration_lineage_id` in `governance/A1_CONFORMAL_ARTIFACT_LIFECYCLE_CONTRACT.md`.

---

## Propagation Requirement

The runtime calibrated-probability producer must emit `a1_calibrated_probability_lineage_id` into `ms_dict` alongside `a1_calibrated_probability`.

The canonical runtime producer is currently absent in production. Implementation is deferred and may involve the 2D artifact loader and 2F `ms_dict` injection. The propagation mechanism must preserve exact marker identity from the isotonic artifact through the runtime stack to `ms_dict`.

---

## Lineage Match Comparison Rule

A lineage match holds if and only if:

- `ms_dict["a1_calibrated_probability_lineage_id"]` is a non-empty string; and
- it exactly equals `artifact["calibration_lineage_id"]`.

Comparison is exact string equality. There is no fuzzy matching, version-suffix tolerance, whitespace tolerance, case normalization, or inferred compatibility.

If the marker is missing, empty, or mismatched, lineage match fails.

---

## Future Precondition 8

When `governance/A1_CONFORMAL_INTERVAL_PROMOTION_CONTRACT.md` is amended to add precondition 8, the wording will be:

> **8. Calibration lineage match.** `ms_dict["a1_calibrated_probability_lineage_id"]` is a non-empty string that exactly equals `artifact["calibration_lineage_id"]`. Lineage match is required because the conformal quantile was fit on probabilities produced by a specific isotonic calibration model. Applying the band to a probability from a different model is invalid even if the value happens to be in [0, 1].

This text is binding once the amendment lands. Future amendments must not weaken the comparison rule, including fuzzy matching or version tolerance, without an operator decision register entry.

---

## Failure Status

The promotion module's failure-status enumeration is extended by:

- `precondition_8_calibration_lineage_match_failed` - fires when the runtime lineage marker is absent, empty, or mismatched.

Observers reading the `p_low` / `p_high` leaf detail string can distinguish lineage mismatch from missing artifact or missing calibrated probability via this status string.

---

## Named Gaps

- `a1_runtime_calibration_canonical_source_pending_implementation` — **resolved** by track 3 (`fa72201` isotonic producer, `1d177ca` loader, `f96a5a3` runtime apply, `bb648db` raw probability extraction, `b4c8f7d` ms_dict attachment). The v2 isotonic path is now wired end-to-end through `attach_a1_isotonic_calibration_to_ms_dict`. Note: `ml_predict._apply_5c_xgb_plus_transformer_isotonic_calibration` remains production-active for the existing stack runtime; the v2 path is **additive** per `governance/A1_ISOTONIC_ARTIFACT_LIFECYCLE_AND_RUNTIME_CONTRACT.md`. Runtime preconditions 7 and 8 will pass when isotonic and conformal artifacts exist on disk for the requested (ticker, horizon).

- `a1_calibration_lineage_id_propagation_pending_implementation` — **resolved** by `f96a5a3` (apply helper computes lineage_id via `compute_calibration_lineage_id`) + `b4c8f7d` (attachment helper sets `ms_dict["a1_calibrated_probability_lineage_id"]`). Runtime now threads the lineage marker into ms_dict per the locked SHA-256 recipe.
- `a1_ml_predict_to_v2_calibration_bridge_pending` - No contract exists declaring `ml_predict` isotonic lineage-equivalent to `v2_a1_calibration` lineage. Future bridge contract is optional; if not pursued, the `ml_predict` path remains permanently ineligible for A1 conformal promotion.

---

## Crosswalk

`governance/A1_CONFORMAL_ARTIFACT_LIFECYCLE_CONTRACT.md`:

- The `calibration_lineage_id` artifact field defines the producer-side lineage identity; this contract defines the consumer-side runtime marker and comparison rule.
- The lineage discipline in lines 152-164 is operationalized by this contract. Precondition 8 is the named-but-unimplemented gate referenced there.

`governance/A1_CONFORMAL_INTERVAL_PROMOTION_CONTRACT.md`:

- Precondition 8 amendment is a separate future doc commit, not part of this contract.
- The future amendment's test bar must include match, mismatch, missing marker, and empty marker scenarios cited against the locked wording in this contract.

`ml_predict._apply_5c_xgb_plus_transformer_isotonic_calibration`:

- Referenced as production-active but non-canonical for A1 conformal promotion lineage.
- Not modified by this contract.

---

## Test Bar

Future code commit minimums for landing precondition 8 in `derive_a1_conformal_bounds`:

- Match: marker equals `calibration_lineage_id` -> precondition 8 passes and the prior success status remains unchanged.
- Mismatch: marker does not equal `calibration_lineage_id` -> precondition 8 fails with `precondition_8_calibration_lineage_match_failed`.
- Marker absent -> same failure status.
- Marker empty string -> same failure status.
- No-silent-partial-fills regression extends to precondition 8 status.

This contract itself:

```text
pytest n/a - doc-only contract
```

---

## Non-Goals

This contract does not:

- edit code;
- edit existing contracts;
- draft a bridge contract between `ml_predict` and `v2_a1_calibration`;
- rewire runtime to the canonical source;
- implement artifact production hookup;
- implement a loader;
- implement precondition 8 in `derive_a1_conformal_bounds`;
- add registry entries;
- change UI;
- change runtime authority;
- change trade behavior or sizing behavior;
- commit to a specific encoding for `a1_calibrated_probability_lineage_id` beyond minimum semantics.
