# A1 Conformal Artifact Lifecycle Contract

**Status:** Draft lifecycle contract
**Date:** 2026-05-06
**Module:** A - short-horizon directional trading
**Expression profile:** A1 - equity / ETF
**Scope:** Persistence and runtime-load eligibility contract for A1 conformal artifacts.

This contract defines how A1 conformal probability-band artifacts are persisted, identified, version-checked, freshness-checked, and made eligible for future runtime loading. It does not implement a loader, produce artifacts, reconcile calibrated-probability provenance, or inject artifacts into `ms_dict`.

---

## Authority Block

```text
mode = advisory_non_authoritative
tier = C_analytics_only
changes_trade_behavior = False
```

This contract does not authorize trade behavior, position sizing changes, runtime authority, or promotion of `p_low` / `p_high` to `v2_compliant`. It only governs the artifact lifecycle surface that future advisory promotion code may consume.

---

## Scope

In scope:

- persistence venue;
- path convention;
- artifact identity fields;
- schema and version checks;
- freshness fields and failure behavior;
- loader contract surface;
- runtime-promotion lineage discipline.

Out of scope:

- loader implementation, deferred to 2D;
- artifact production hookup, deferred to 2C;
- calibrated-probability provenance reconciliation, deferred to 2B;
- primary-horizon injection, deferred to 2E if needed;
- runtime `ms_dict` injection, deferred to 2F;
- UI, execution EV, lifecycle, scheduler, or runtime authority changes.

---

## Persistence Venue And Path Convention

V1 persistence venue is filesystem JSON. This is the preferred fit for write-once-read-many, immutable-per-run artifacts, natural operator inspection, and compatibility with existing `data/calibration_*.json` patterns. SQLite remains a future alternative only if query-by-criteria semantics become necessary.

Artifacts are written under:

```text
data/v2_calibration/conformal/<module_id>/<expression_profile_id>/<ticker>/<horizon>/<calibration_run_id>.json
```

Example:

```text
data/v2_calibration/conformal/A/A1/SPY/5c/cal-20260506-154200.json
```

Rules:

- Path components are lowercase except `<ticker>`, which preserves broker / Schwab convention, and `<calibration_run_id>`, which preserves operator-set identity.
- Filenames end with `.json`; no compression in v1.
- Artifacts are write-once and immutable after write. Re-running calibration produces a new `<calibration_run_id>` and a new file.
- The newest artifact for a `(module_id, expression_profile_id, ticker, horizon)` tuple is determined by the `generated_at_epoch_seconds` field, not filename mtime; filesystem timestamps may drift.
- A pointer file at `data/v2_calibration/conformal/<module_id>/<expression_profile_id>/<ticker>/<horizon>/_current.json` records the runtime-eligible artifact's relative path.
- Pointer updates use atomic-rename style: write `_current.json.new`, then rename it to `_current.json`.

---

## Required Identity Fields

Artifacts must preserve the identity fields already emitted by the conformal scaffold:

- `schema_version` - conformal artifact schema version, currently `"1"`;
- `calibration_run_id`;
- `calibration_window_id`;
- `conformal_run_id`;
- `module_id`;
- `expression_profile_id`;
- `horizon`.

Artifacts must also carry these lifecycle fields:

- `ticker_universe` - list of tickers this artifact applies to, for example `["SPY"]` or `["SPY", "QQQ"]`.
- `governed_max_age_seconds` - numeric value greater than or equal to `0`, required by `governance/A1_CONFORMAL_INTERVAL_PROMOTION_CONTRACT.md` precondition 6.
- `generated_at_epoch_seconds` - numeric epoch timestamp, required by `governance/A1_CONFORMAL_INTERVAL_PROMOTION_CONTRACT.md` precondition 6.
- `calibration_lineage_id` - a string that uniquely identifies the isotonic calibration artifact used to produce the probabilities that fit the conformal quantile. The recommended format is `<calibration_run_id>:<isotonic_artifact_hash_or_id>`, but 2B may refine the exact encoding so long as the uniqueness-and-identity semantic is preserved. Future encodings must not weaken this requirement.
- `artifact_lifecycle_schema_version` - lifecycle contract schema version, `"1"` for this contract.

---

## Schema And Version Checks

The future loader must:

- verify `schema_version == "1"` or the then-current conformal artifact schema version; otherwise reject;
- verify `artifact_lifecycle_schema_version == "1"`; otherwise reject;
- verify all required identity and lifecycle fields are present and correctly typed; otherwise reject;
- verify `ticker_universe` contains the requested ticker; otherwise reject;
- verify `horizon` matches the requested horizon; otherwise reject.

If any check fails, the loader returns `None` in production. The loader must not raise for ordinary malformed, missing, stale, mismatched, or unsupported artifacts. Logging is debug-level.

---

## Freshness Fields And Failure Behavior

Freshness follows `governance/A1_CONFORMAL_INTERVAL_PROMOTION_CONTRACT.md` precondition 6:

- Both `governed_max_age_seconds` and `generated_at_epoch_seconds` are required.
- Age check: `current_epoch - generated_at_epoch_seconds <= governed_max_age_seconds`.
- No external policy fallback exists in v1.
- `calibration_run_id` and `calibration_window_id` must not be used as freshness proxies.
- Stale artifacts are rejected by returning `None`.

The source of truth for newest-artifact selection and freshness is `generated_at_epoch_seconds`, not filesystem mtime.

---

## Loader Contract Surface

Implementation is deferred to 2D. The future loader surface is:

```python
def load_a1_conformal_artifact(
    *,
    ticker: str,
    horizon: str,
    module_id: str = "A",
    expression_profile_id: str = "A1",
    now_epoch_seconds: float | None = None,
) -> dict | None:
    """Returns the runtime-eligible artifact for (ticker, horizon) or None.

    Reads <data>/v2_calibration/conformal/<module>/<expr>/<ticker>/<horizon>/_current.json,
    follows pointer, applies all schema/version/freshness/ticker_universe checks.
    Returns None on any failure. Never raises in production. Logs at debug.
    """
```

`now_epoch_seconds` exists for testability and mirrors the freshness-check style already used by `v2_decision/a1_conformal_promotion.py`.

The loader location remains TBD, with likely candidates `v2_decision/a1_conformal_artifact_loader.py` or `calibration/a1_conformal_artifact_loader.py`.

---

## Lineage Discipline For Runtime Promotion

Runtime promotion of `p_low` / `p_high` is forbidden unless the calibrated probability fed to `derive_a1_conformal_bounds` was produced by the same calibration model whose outputs were used to fit the conformal quantile.

Lineage match mechanism:

- The artifact carries `calibration_lineage_id`.
- The runtime probability source must carry a matching lineage marker.
- The match mechanism - where the runtime marker comes from, how it propagates through the stack to `ms_dict`, and how comparison happens - is defined in forthcoming `governance/A1_CALIBRATED_PROBABILITY_PROVENANCE_CONTRACT.md` as 2B.

Until 2B exists and is implemented in code, runtime promotion is gated by this contract's discipline. Even if the seven existing preconditions in `governance/A1_CONFORMAL_INTERVAL_PROMOTION_CONTRACT.md` pass, the lineage match precondition is unsatisfied, so `p_low` and `p_high` must remain `not_implemented`.

This is an honest-not-optimistic posture: lifecycle availability is not treated as proof that the runtime probability and conformal quantile share calibration lineage.

---

## Named Gaps

- `a1_conformal_artifact_persistence_venue_pending` - Filesystem JSON is recommended and described here, but the filesystem-vs-SQLite decision is not formally bound until an operator decision register entry exists.
- `a1_conformal_calibration_lineage_match_pending` - Runtime-to-artifact lineage match mechanism is not yet defined; awaits the 2B provenance contract.
- `a1_conformal_artifact_loader_implementation_pending` - Loader is contract-shape-only here; implementation is deferred to 2D.

---

## Crosswalk To Existing Contracts

`governance/A1_CONFORMAL_INTERVAL_PROMOTION_CONTRACT.md`:

- Precondition 1, artifact present, implicitly assumes the artifact came from the loader surface defined here.
- Precondition 6, freshness discipline, depends on `governed_max_age_seconds` and `generated_at_epoch_seconds` as required lifecycle fields defined here.
- Future precondition 8, lineage match, will be added when 2B lands.

`governance/A2_STATIC_LIFECYCLE_DIVERGENCE_AUDIT.md`:

- Out of scope; it governs a different module and lifecycle surface.

Existing `data/calibration_*.json` artifacts:

- Parallel filesystem-artifact pattern only; existing files are not changed or reinterpreted by this contract.

---

## Test Bar

```text
pytest n/a - doc-only contract
```

---

## Non-Goals

This contract does not:

- implement a loader;
- implement artifact production hookup;
- implement a scheduler;
- reconcile runtime calibrated probability with the artifact lineage;
- define the lineage match mechanism beyond the minimum required semantic for `calibration_lineage_id`;
- inject `primary_horizon`;
- inject `a1_conformal_artifact` into `ms_dict`;
- inject `a1_calibrated_probability` into `ms_dict`;
- change runtime authority;
- change trade behavior or sizing behavior;
- change UI;
- add registry entries;
- edit code;
- edit existing calibration artifacts.
