# A1 Conformal Artifact Production Contract

**Status:** Draft production contract
**Date:** 2026-05-06
**Module:** A - short-horizon directional trading
**Expression profile:** A1 - equity / ETF
**Scope:** Manual production of A1 conformal artifacts for future runtime loading.

This contract defines the v1 production pipeline for A1 conformal artifacts: how training rows, walk-forward windows, forward evaluation rows, lineage identity, lifecycle fields, and `_current.json` eligibility are governed. It is doc-only and does not implement a CLI, producer, scheduler hook, or artifact writer.

---

## Authority Block

```text
mode = advisory_non_authoritative
tier = C_analytics_only
changes_trade_behavior = False
```

This contract does not authorize trade behavior, position sizing changes, runtime authority, or promotion of `p_low` / `p_high` to `v2_compliant`. It only defines the manual artifact production discipline required before future runtime loading.

---

## Scope

In scope:

- production pipeline shape;
- honest evaluation window policy using a separate forward window;
- per-ticker artifact output rule;
- `calibration_lineage_id` hash format;
- `_current.json` eligibility rules;
- manual CLI-driven v1 cadence.

Out of scope:

- code implementation, including CLI, producer, and atomic-rename utility;
- scheduler integration;
- automatic cadence binding;
- ticker discovery;
- edits to `governance/A1_CONFORMAL_ARTIFACT_LIFECYCLE_CONTRACT.md`;
- edits to `governance/A1_CALIBRATED_PROBABILITY_PROVENANCE_CONTRACT.md`;
- edits to existing calibration pipelines.

---

## Production Pipeline Shape

The canonical v1 production sequence is:

```text
1. Parse CLI args: ticker, horizon, train_start/end, calibration_start/end,
   holdout_start/end, eval_start/end, governed_max_age_seconds
2. Load training rows: load_a1_calibration_rows(db_path, horizon)
3. Construct WalkForwardSplit from CLI window args (validate purged-embargo)
4. fit_a1_isotonic_artifact(rows, horizon, split) -> calibration_artifact
5. Load separate forward evaluation rows in [eval_start, eval_end]
   (must be strictly after holdout_end)
6. Apply isotonic model from calibration_artifact to eval rows -> evaluation_predictions
7. build_a1_conformal_artifact(calibration_artifact,
   evaluation_predictions=evaluation_predictions) -> conformal_artifact
8. Augment with lifecycle fields per 2A:
   - ticker_universe = [<ticker>]  # single-element list, per-ticker artifacts
   - governed_max_age_seconds = <CLI value>
   - generated_at_epoch_seconds = current epoch
   - calibration_lineage_id (per Lineage Hash Format below)
   - artifact_lifecycle_schema_version = "1"
9. Write artifact:
   data/v2_calibration/conformal/A/A1/<ticker>/<horizon>/<calibration_run_id>.json
10. Apply _current.json eligibility rules
```

The pipeline is manual in v1. CLI window arguments are explicit and no implicit defaults are allowed for window boundaries.

---

## Honest Evaluation Window Policy

The conformal artifact uses a separate forward evaluation window, not a subdivided holdout.

Rules:

- The eval window `[eval_start, eval_end]` must satisfy `eval_start >= holdout_end`; it is strictly after the calibration holdout window.
- `[eval_start, eval_end]` must contain at least `A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES` rows in v1. A future operator decision may bind a different minimum via `a1_conformal_artifact_evaluation_window_minimum_size_policy_pending`.
- The pipeline applies the fit isotonic model to eval rows and passes the resulting rows to `build_a1_conformal_artifact` as `evaluation_predictions`.
- Same-holdout coverage paths in the conformal scaffold are not used for runtime-eligible artifacts.

If the eval window has insufficient rows, or if the coverage gate fails, the artifact is still written for audit but is not eligible to update `_current.json`.

---

## Per-Ticker Artifact Rule

Each invocation of the production pipeline produces an artifact for a single ticker. In v1, `ticker_universe` is always a single-element list.

Future multi-ticker pooled artifacts require an operator decision register entry.

Path:

```text
data/v2_calibration/conformal/A/A1/<TICKER>/<horizon>/<calibration_run_id>.json
```

The pointer file is per `(ticker, horizon)`:

```text
data/v2_calibration/conformal/A/A1/<TICKER>/<horizon>/_current.json
```

---

## Lineage Hash Format

`calibration_lineage_id` is:

```text
<calibration_run_id>:<isotonic_artifact_hash>
```

Where:

- `calibration_run_id` is the value from the `fit_a1_isotonic_artifact` output.
- `isotonic_artifact_hash` is the SHA-256 hex digest of `json.dumps(model, sort_keys=True, separators=(",", ":"))`.
- `model` is the dict consumed by `apply_isotonic_model`, currently `calibration_artifact["model"]` when `calibration_artifact["status"] == "ok"`.
- Determinism is guaranteed by sorted keys and compact separators.
- The future runtime probability producer must compute the hash with the same recipe to satisfy precondition 8 lineage match.
- Future commits may refine the format but must preserve the uniqueness-and-identity semantic required by `governance/A1_CALIBRATED_PROBABILITY_PROVENANCE_CONTRACT.md`.

---

## `_current.json` Eligibility Rules

An artifact is eligible to be promoted to `_current.json` only if all criteria hold:

- All required identity fields are present per `governance/A1_CONFORMAL_ARTIFACT_LIFECYCLE_CONTRACT.md`.
- `schema_version == A1_CONFORMAL_ARTIFACT_SCHEMA_VERSION`, currently `"1"`.
- `artifact_lifecycle_schema_version == "1"`.
- O1 gate passes: `coverage_evaluation.source == "separate_evaluation_predictions"` and `evaluation_diagnostics.empirical_coverage >= A1_CONFORMAL_DEGRADED_COVERAGE`.
- Aggregate sample threshold passes: `sample_gate.aggregate_holdout.sufficient_sample is True`.
- Both `governed_max_age_seconds` and `generated_at_epoch_seconds` are present and well typed.
- `calibration_lineage_id` is a non-empty string in `<calibration_run_id>:<isotonic_artifact_hash>` format.

Promotion mechanics:

- Write `_current.json.new` with the artifact's relative path.
- Atomic rename `_current.json.new` to `_current.json`.
- If any eligibility criterion fails, the artifact stays on disk for audit, `_current.json` is not updated, and the pipeline logs the failure reason at INFO level.

---

## Manual Cadence

V1 cadence is manual and CLI-driven:

- invocation requires explicit CLI arguments;
- window boundaries have no implicit defaults;
- operator runs the pipeline manually when needed;
- no automatic scheduling exists in v1;
- scheduler integration is deferred.

---

## Named Gaps

- `a1_conformal_artifact_production_scheduler_pending` - Manual cadence is v1; scheduler integration awaits future operator decision and a separate contract.
- `a1_conformal_artifact_governed_max_age_seconds_policy_pending` — **resolved** by **O-29**. Value is bound to `691200` seconds (8 days) as an operational freshness bound for weekly cadence plus one-day tolerance.
- `a1_conformal_artifact_walkforward_window_policy_pending` — **resolved** by **O-30**. Window boundaries are bound to weekly cadence with 90 days train / 30 days calibration / 7 days holdout / 7 days post-fit evaluation.
- `a1_conformal_artifact_evaluation_window_minimum_size_policy_pending` — **resolved** by **O-31**. V1 uses `500` rows, tied to `A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES` (O-24), as the post-fit evaluation window minimum.

---

## Crosswalk

`governance/A1_CONFORMAL_ARTIFACT_LIFECYCLE_CONTRACT.md` (2A):

- This contract operationalizes the producer side of 2A's persistence, identity, freshness fields, and path convention.
- The path convention is preserved verbatim.

`governance/A1_CALIBRATED_PROBABILITY_PROVENANCE_CONTRACT.md` (2B):

- This contract binds the v1 lineage hash format.
- Future runtime probability producers must match this hash recipe to satisfy precondition 8.

`governance/A1_CONFORMAL_INTERVAL_PROMOTION_CONTRACT.md`:

- Precondition 6 consumes `governed_max_age_seconds`; this contract binds the production-side source as CLI-supplied in v1.
- Precondition 8 consumes `calibration_lineage_id`; this contract binds the producer-side format.

`7c9e124` precondition 8 amendment:

- Lineage match becomes meaningful only once this contract's producer-side hash and future runtime-side propagation are implemented.

---

## Test Bar

Future 2C.2 code commit minimums:

- All preconditions satisfied -> artifact written and `_current.json` updated.
- O1 gate failure from insufficient eval coverage -> artifact written and `_current.json` not updated.
- Insufficient eval window size -> artifact written with status reason and `_current.json` not updated.
- Missing or invalid CLI args -> CLI-level validation failure.
- `calibration_lineage_id` matches the `<run_id>:<sha256(...)>` recipe exactly.
- Atomic-rename behavior: `_current.json` is never partially written.
- No-silent-partial-fills regression: an artifact is either fully populated and promoted, or fully populated and not promoted; never partial.

This contract itself:

```text
pytest n/a - doc-only contract
```

---

## Non-Goals

This contract does not:

- implement a CLI, producer, or atomic-rename utility;
- integrate with `ml_scheduler.py` or any cron / scheduler;
- bind a canonical cadence;
- discover tickers automatically;
- pool multi-ticker artifacts;
- edit 2A or 2B contracts;
- edit existing calibration pipelines;
- add registry entries;
- change runtime authority;
- change UI.
