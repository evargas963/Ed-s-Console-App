# A1 Isotonic Artifact Lifecycle And Runtime Contract

**Status:** Draft lifecycle and runtime contract
**Date:** 2026-05-06
**Module:** A - short-horizon directional trading
**Expression profile:** A1 - equity / ETF
**Scope:** Isotonic artifact lifecycle and runtime apply path for A1 conformal lineage.

This contract defines the additive v2 isotonic artifact path required to produce the canonical `a1_calibrated_probability` and `a1_calibrated_probability_lineage_id` consumed by A1 conformal interval promotion. It is doc-only and does not implement a producer, loader, runtime apply helper, or `ms_dict` injection.

---

## Authority Block

```text
mode = advisory_non_authoritative
tier = C_analytics_only
changes_trade_behavior = False
```

This contract does not authorize trade behavior, position sizing changes, runtime authority, or promotion of `p_low` / `p_high` to `v2_compliant`. It only governs the isotonic artifact and runtime-apply surfaces needed for advisory A1 conformal lineage.

---

## Scope

In scope:

- persistence venue and path convention for isotonic artifacts;
- required identity fields and freshness rules;
- `_current.json` eligibility rules;
- loader contract surface;
- runtime apply surface;
- lineage hash reuse from `governance/A1_CONFORMAL_ARTIFACT_PRODUCTION_CONTRACT.md` §113-128;
- operator decision reuse from O-28, O-29, O-30, and O-31.

Out of scope:

- code implementation, including producer, loader, runtime apply helper, or `ms_dict` injection;
- `ml_predict` modifications;
- bridge contract drafting for `a1_ml_predict_to_v2_calibration_bridge_pending`;
- A1 EV bounds or execution-adjusted EV runtime promotion;
- A2 lifecycle work;
- edits to existing contracts.

---

## Additive Declaration

The v2 isotonic artifact path is **additive** to the existing `ml_predict._apply_5c_xgb_plus_transformer_isotonic_calibration` runtime calibration. Existing stack runtime behavior remains unchanged: `ml_predict`'s isotonic continues to produce the calibrated probability that flows into existing stack consumers (signal path, sizing, etc.).

A1 conformal promotion uses **only** the v2 isotonic artifact path defined here. `ml_predict`'s calibrated probability does **not** satisfy precondition 7 or 8 of `governance/A1_CONFORMAL_INTERVAL_PROMOTION_CONTRACT.md`. The two paths produce different numerical calibrated probabilities — they are not lineage-equivalent.

`a1_ml_predict_to_v2_calibration_bridge_pending` (named in `governance/A1_CALIBRATED_PROBABILITY_PROVENANCE_CONTRACT.md`) **remains open** until equivalence is empirically validated OR runtime is fully rewired through this v2 path. This contract does not draft a bridge; doing so without empirical equivalence would risk a paper waiver for model mismatch.

---

## Persistence Venue And Path Convention

V1 persistence venue is filesystem JSON per O-28. This binding applies to both A1 conformal artifacts and A1 isotonic artifacts.

Isotonic artifacts are written under:

```text
data/v2_calibration/isotonic/<module_id>/<expression_profile_id>/<ticker>/<horizon>/<calibration_run_id>.json
```

Example:

```text
data/v2_calibration/isotonic/A/A1/SPY/5c/cal-20260506-154200.json
```

Rules:

- Path components are lowercase except `<ticker>`, which preserves broker / Schwab convention, and `<calibration_run_id>`, which preserves operator-set identity.
- Filenames end with `.json`; no compression in v1.
- Artifacts are write-once and immutable after write. Re-running calibration produces a new `<calibration_run_id>` and a new file.
- The newest artifact for a `(module_id, expression_profile_id, ticker, horizon)` tuple is determined by the `generated_at_epoch_seconds` field, not filename mtime; filesystem timestamps may drift.
- A pointer file at `data/v2_calibration/isotonic/<module_id>/<expression_profile_id>/<ticker>/<horizon>/_current.json` records the runtime-eligible artifact's relative path.
- Pointer updates use atomic-rename style: write `_current.json.new`, then rename it to `_current.json`.

---

## Required Identity Fields

Artifacts must preserve the identity and model fields already emitted by `fit_a1_isotonic_artifact`:

- `schema_version`;
- `calibration_run_id`;
- `calibration_window_id`;
- `module_id`;
- `expression_profile_id`;
- `horizon`;
- `method`, currently `isotonic_regression`;
- `raw_probability_field`, currently `v2_decision.decision.P_entry_success`;
- `target_label`;
- `sample_gate.aggregate_holdout`;
- `window`;
- `status`;
- `reason`;
- `model`, the isotonic model dict consumed by `apply_isotonic_model`.

Artifacts must also carry these lifecycle fields:

- `ticker_universe` - single-element list `[<ticker>]` in v1.
- `governed_max_age_seconds` - set to `691200` per O-29.
- `generated_at_epoch_seconds` - numeric epoch timestamp at production.
- `calibration_lineage_id` - same recipe as `governance/A1_CONFORMAL_ARTIFACT_PRODUCTION_CONTRACT.md` §113-128: `<calibration_run_id>:<sha256(json.dumps(model, sort_keys=True, separators=(",", ":")))>`. Reuse the recipe; do not introduce a parallel hash format.
- `artifact_lifecycle_schema_version` - `"1"` for this contract.

---

## `_current.json` Eligibility Rules

An isotonic artifact is eligible to be promoted to `_current.json` only if all criteria hold:

- All required identity and lifecycle fields are present and correctly typed.
- `schema_version` matches the current A1 calibration artifact schema version.
- `artifact_lifecycle_schema_version == "1"`.
- `ticker_universe` contains the requested ticker.
- `horizon` matches the requested horizon.
- Freshness passes: `current_epoch - generated_at_epoch_seconds <= governed_max_age_seconds`.
- `status == "ok"`.
- `model` is a non-empty dict.
- `sample_gate.aggregate_holdout.sufficient_sample is True`.
- `calibration_lineage_id` is a non-empty string in `<calibration_run_id>:<sha256>` format.

There is no O1 coverage gate for isotonic artifacts. Coverage is measured by the conformal artifact and remains governed by the conformal contracts.

---

## Loader Contract Surface

Implementation is deferred to 3.2. The future loader surface is:

```python
def load_a1_isotonic_artifact(
    *,
    ticker: str,
    horizon: str,
    module_id: str = "A",
    expression_profile_id: str = "A1",
    now_epoch_seconds: float | None = None,
) -> dict | None:
    """Returns the runtime-eligible isotonic artifact for (ticker, horizon) or None.
    Reads _current.json pointer, follows to artifact, applies all eligibility checks.
    Returns None on any failure. Never raises in production. Logs at debug.
    """
```

`now_epoch_seconds` exists for testability and mirrors the loader pattern established for conformal artifacts.

---

## Runtime Apply Surface

Implementation is deferred to 3.3. The future runtime apply surface is:

```python
def apply_a1_v2_calibration_to_raw_probability(
    *,
    isotonic_artifact: dict,
    raw_probability: float,
) -> tuple[float | None, str | None]:
    """Returns (calibrated_probability, lineage_id) or (None, None) on failure.

    Calls calibration.v2_a1_calibration.apply_isotonic_model under the hood.
    Computes lineage_id by the locked recipe (reuses compute_calibration_lineage_id
    from calibration.a1_conformal_artifact_production or its extracted contract module).
    Never raises in production.
    """
```

The expected implementation location is `v2_decision/a1_isotonic_runtime.py`, keeping runtime-facing provenance behavior on the consumer side while `calibration/v2_a1_calibration.py` remains the calibration primitive provider.

---

## Operator Decision Reuse

O-28, O-29, O-30, and O-31 apply to isotonic artifacts:

- O-28: filesystem JSON venue.
- O-29: `691200` seconds governed max age.
- O-30: weekly 90 days train / 30 days calibration / 7 days holdout / 7 days post-fit evaluation walk-forward window.
- O-31: `500` row evaluation window minimum for conformal artifact `_current.json` eligibility; isotonic holdout sufficiency remains governed by O-24.

No new operator decision register entries are required by this contract.

---

## Named Gaps

- `a1_isotonic_artifact_producer_implementation_pending` - closes in 3.1.
- `a1_isotonic_artifact_loader_implementation_pending` - closes in 3.2.
- `a1_isotonic_runtime_apply_implementation_pending` - closes in 3.3.
- `a1_isotonic_ms_dict_injection_pending` - closes in 3.4.
- `a1_ml_predict_to_v2_calibration_bridge_pending` - referenced from `governance/A1_CALIBRATED_PROBABILITY_PROVENANCE_CONTRACT.md`; stays open.

---

## Crosswalk

`governance/A1_CONFORMAL_ARTIFACT_LIFECYCLE_CONTRACT.md` (2A):

- Pattern source for path, identity, freshness, and loader rules.
- This contract follows the same shape under the `isotonic/` directory.

`governance/A1_CONFORMAL_ARTIFACT_PRODUCTION_CONTRACT.md` (2C.0/2C.1):

- Lineage hash recipe is reused here verbatim.

`governance/A1_CALIBRATED_PROBABILITY_PROVENANCE_CONTRACT.md` (2B):

- Defines what runtime markers must equal.
- This contract operationalizes the producer-and-runtime-apply side.
- `a1_ml_predict_to_v2_calibration_bridge_pending` stays open per the additive declaration.

`governance/A1_CONFORMAL_INTERVAL_PROMOTION_CONTRACT.md`:

- Preconditions 7 and 8 consume `ms_dict["a1_calibrated_probability"]` and `ms_dict["a1_calibrated_probability_lineage_id"]`.
- Those fields are populated by future 3.3 and 3.4 wiring.

`governance/OPERATOR_DECISION_REGISTER.md`:

- O-28, O-29, O-30, and O-31 are reused.
- No new register entries are required.

---

## Test Bar

Each future code commit must use red-green discipline. Required tests will be specified in each commit's locked spec.

This contract itself:

```text
pytest n/a - doc-only contract
```

---

## Non-Goals

This contract does not:

- implement a producer, loader, runtime apply helper, or `ms_dict` injection;
- edit existing contracts;
- edit `ml_predict`;
- edit existing calibration modules;
- draft a bridge contract;
- promote EV bounds;
- promote execution-adjusted EV;
- perform A2 lifecycle work;
- add named gaps beyond the five listed above;
- add registry entries;
- change runtime authority;
- change trade behavior or sizing behavior;
- change UI.
