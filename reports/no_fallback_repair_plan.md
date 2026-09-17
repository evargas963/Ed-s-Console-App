# No-fallback mechanical lock — grouped production repair plan

Generated from `reports/no_fallback_inventory.json` (46 confirmed `FALLBACK` entries out of
122 adjudicated candidates, 1104 candidates not yet adjudicated — see that file's own
`verdict_counts`). This plan does **not** repair anything; per the mission's concurrency
boundary, production repair is explicitly deferred to operator authorization and is not
performed in this pass.

## Group 1: `calibration_ml_governance` (35 confirmed FALLBACK)

**Root defect, one shape repeated 26 times:** `COALESCE(horizon_outcome_schema_version, 3)`
(and its bound-parameter equivalent) across `db.py` (9 sites) and `tools/legacy/horizon_7/*`
(11 sites), plus `COALESCE(canonical_timeframe, '1m')` (3 sites, `calibration/anchor_audit.py`)
and `COALESCE(et_minute, 0)` (2 sites, `db.py:compute_accuracy`). Every one of these silently
asserts a specific value for a row whose real historical value was never recorded, with no
per-row proof. `horizon_outcomes.py` documents schema v2 as "invalidated — do not use" and v3
as current — a legacy row silently mislabeled v3 would feed invalidated-schema data into
calibration.

Plus 5 report-integrity sites: `calibration/repair_canonical_1m_edge_carry_v1.py` and
`calibration/repair_canonical_1m_interior_gaps_v1.py` set `tickers_touched`/
`governed_outcome_refresh_tickers`/`fill_outcomes_tickers` to `0` inside an `except` handler —
reporting "confirmed zero" when the true state is "the repair crashed, count unknown."

Plus 1 alternate-field substitution: `calibration/backfill_outcomes.py:14` —
`COALESCE(matched_snapshot_ts_utc, decision_ts_utc)`.

**Repair shape:** (a) confirm via migration/backfill history whether pre-column rows are
provably v3-equivalent; if not, exclude NULL-schema-version rows from version-scoped queries
rather than assuming the current version. (b) Same for `canonical_timeframe`. (c) Exclude
NULL-`et_minute` rows from the time-bucket computation, or backfill from `ts_utc`. (d) Replace
the report-dict `0` defaults with an explicit failure marker distinct from a genuine
zero-count outcome. (e) Expose the snapshot-match failure explicitly in `backfill_outcomes.py`
rather than substituting `decision_ts_utc`.

**Priority note:** `tools/legacy/horizon_7/*` (11 of the 26 schema-version sites) sits in a
directory literally named `legacy` — plausibly retired/frozen tooling not on the live
decision path. Confirm retirement status before spending repair effort there; if retired,
the correct "repair" may be deletion rather than a fix.

**Files:** `calibration/anchor_audit.py`, `calibration/backfill_outcomes.py`,
`calibration/canonical_1m_grid_scan.py`, `calibration/phase65_edge_isolation_v1.py`,
`calibration/phase6_edge_discovery_governed_v1.py`,
`calibration/repair_canonical_1m_edge_carry_v1.py`,
`calibration/repair_canonical_1m_interior_gaps_v1.py`, `db.py`,
`tools/legacy/horizon_7/*` (9 files), `tools/smoke_movement_heads_inference_v1.py`.

**Cursor overlap:** none of these files are in Cursor's current `fix/pr252-whole-ui-live`
overlap list.

## Group 2: `ml_training_pipeline` (6 confirmed FALLBACK)

`tickers = []` inside `except` handlers in `lstm_data.py` (2 sites), `ml_scheduler.py`,
`train_all.py`, `transformer_train.py` — a failed ticker-list computation silently proceeds as
if zero tickers were ever requested, rather than surfacing that ticker-list resolution itself
failed. Plus `train_compare.py:55` — `.map(rules_map).fillna('flat')` — an unmapped/missing
`rules_signal` reads identically to a genuinely-computed flat (no-position) signal.

**Repair shape:** propagate/raise on the ticker-list failure, or mark the training run as
degraded/incomplete rather than silently training on an empty-appearing ticker set. For
`train_compare.py`, expose unmapped signals as a distinct state, never the same string a
genuine flat signal produces.

**Files:** `lstm_data.py`, `ml_scheduler.py`, `train_all.py`, `train_compare.py`,
`transformer_train.py`.

**Cursor overlap:** none.

## Group 3: `market_state_rendering` (2 confirmed FALLBACK)

`market_state.py:1147` — `getattr(consensus_summary, 'gex_magnitude', 'negligible') or
'negligible'` (double fallback landing on a meaningful, valid-looking classification).
`ml_predict.py:2298` — `flags = set()` on an exception in `_active_base_collapse_flags`,
silently proceeding as "no collapse conditions detected" when detection itself failed.

**Repair shape:** expose "not computed" as a state distinct from the genuine "negligible"
classification; distinguish "computed, zero flags raised" from "computation failed, flags
unknown" (raise or return `None`, never an empty set, on the collapse-flag exception path).

**Files:** `market_state.py`, `ml_predict.py`.

**Cursor overlap:** none.

## Group 4: `market_data_server_core` (3 confirmed FALLBACK)

`server.py:13712`/`13844`/`13940` — `tickers = list(CORE_TICKERS)` inside `except` handlers in
the terrain/bars/strike-geometry loops, substituting the static default roster for a failed
DYNAMIC ticker-list computation, without disclosing that the dynamic roster computation
failed.

**Repair shape:** disclose that the dynamic roster computation failed and `CORE_TICKERS` is a
fallback roster, rather than processing it silently as the intended set.

**Files:** `server.py`.

**Cursor overlap: YES — `server.py` is in Cursor's `fix/pr252-whole-ui-live` overlap list.**
Per the mission's concurrency boundary, this group is **not editable in this phase**; hand
off to Cursor's own pass or the operator, after Cursor's branch lands and this census is
rebased onto it.

## Deferred to operator adjudication (not FALLBACK, not NOT_FALLBACK — genuinely ambiguous)

- `governance/no_fallback_registry.json`'s `ml_imputation_authorized_files` pre-authorizes
  `ml_train.py`/`tools/feature_curation_gate.py`'s median imputation as a NAMED, disclosed
  methodology pending the operator's own ruling on whether pipeline-level disclosure
  satisfies the mandate for feature-level ML preprocessing (the mission's PROHIBITED list
  explicitly names "model/training substitution" as its own category — this session did not
  unilaterally clear it).
- `COALESCE(<audit-flag>, 0)` on `research_excluded`/`outcome_filled`/`active` (11 sites) —
  needs the columns' DDL/migration intent confirmed before ruling on whether the 0-default is
  legitimate schema design or a real calibration-integrity gap.
- Several `except`-handler `None`/empty-sentinel assignments (`_contract_admission`,
  `_gamma_surface`, `vendor`, `arch_state`, `price_levels`, `regime`, and others) marked
  `NOT_PROVEN` pending a downstream-consumer trace to confirm the sentinel is always disclosed
  and never rendered as a real reading — see `reports/no_fallback_inventory.json` entries
  tagged `needs_downstream_trace`.

## Not yet reached (1104 of 1226 discovered candidates)

The `OR_LADDER`, `TERNARY`, `DICT_GET_DEFAULT`, and `GETATTR_DEFAULT` patterns (the bulk of
the repo-wide discovery census) were mechanically discovered but not semantically adjudicated
in this pass — this session prioritized the three patterns the mission's own PROHIBITED list
names most explicitly (SQL substitution, exception-driven substitution, model/training
substitution) to a real, evidenced depth rather than shallow-passing the full 1226. The next
adjudication pass should continue file-by-file or pattern-by-pattern through
`reports/no_fallback_inventory.json`'s remaining `NOT_PROVEN` entries.
