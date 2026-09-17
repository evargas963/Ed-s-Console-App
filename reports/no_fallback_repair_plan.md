# No-fallback mechanical lock — grouped production repair plan

Generated from `reports/no_fallback_inventory.json`. **Status 2026-09-17 (operator
correction + repair cycle in progress):** the first-pass "confirmed-safe SQL idiom" and
"deferred ML imputation" classifications were REJECTED by the operator and reclassified
FALLBACK (see `tools/apply_adjudication.py`'s own `_apply_operator_correction_2026_09_17`).
Current counts: 78 `FALLBACK`, 1121 `NOT_PROVEN`, 25 `NOT_FALLBACK`, 2 `REPAIRED`, of 1226
candidates. Repair is now proceeding continuously group-by-group (adjudicate → repair →
test → lock → reconcile → commit → next group), not gated behind full census completion.

## Group 1: `calibration_ml_governance` (64 confirmed FALLBACK — grew from 35 after the
operator's SQL-idiom correction folded 29 more items in: the aggregate-over-empty-set,
display-label, and update-preserve COALESCE/IFNULL sites this session had wrongly cleared
as safe, plus the audit-flag COALESCE(...,0) sites previously deferred)

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

## Group 2: `ml_training_pipeline` (11 confirmed FALLBACK — grew from 6 after the operator's
imputation correction: "the operator did not pre-authorize ML imputation" reclassified
`ml_train.py`/`tools/feature_curation_gate.py`/`tools/research/d2_dual_label_eval_report.py`/
`training_cache.py` (2 sites) from deferred/safe to FALLBACK)

`tickers = []` inside `except` handlers in `lstm_data.py` (2 sites), `ml_scheduler.py`,
`train_all.py`, `transformer_train.py` — a failed ticker-list computation silently proceeds as
if zero tickers were ever requested, rather than surfacing that ticker-list resolution itself
failed. `train_compare.py:55` — `.map(rules_map).fillna('flat')` — an unmapped/missing
`rules_signal` reads identically to a genuinely-computed flat (no-position) signal. Plus (new)
`ml_train.py`/`tools/feature_curation_gate.py` median imputation, `tools/research/
d2_dual_label_eval_report.py`'s `fillna(0)` boolean-flag default, `training_cache.py`'s two
`fillna(-1.0)` sentinel sites (domain range not independently confirmed to exclude -1.0).

**Repair shape:** propagate/raise on the ticker-list failure, or mark the training run as
degraded/incomplete rather than silently training on an empty-appearing ticker set. For
`train_compare.py`, expose unmapped signals as a distinct state, never the same string a
genuine flat signal produces. For the imputation sites, exclude/flag missing feature rows
rather than imputing a value (per the operator's ruling) — a real methodology change to the
training pipeline, needing care not to silently change model behavior mid-repair.

**Files:** `lstm_data.py`, `ml_scheduler.py`, `train_all.py`, `train_compare.py`,
`transformer_train.py`, `ml_train.py`, `tools/feature_curation_gate.py`,
`tools/research/d2_dual_label_eval_report.py`, `training_cache.py`.

**Cursor overlap:** none.

## Group 3: `market_state_rendering` — **REPAIRED 2026-09-17**

`market_state.py:1147` — `getattr(consensus_summary, 'gex_magnitude', 'negligible') or
'negligible'` (double fallback landing on a meaningful, valid-looking classification, only
reachable on a genuine `gex_magnitude_label` import failure). Fixed: the except handler no
longer guesses a value off `consensus_summary`'s own nonexistent-in-practice
`gex_magnitude` attribute; the degraded value stays the documented `"negligible"` default
but is now disclosed via `ms.state_error`/`ms.state_error_detail` rather than silently
guessed. `ml_predict.py:2298` — `flags = set()` on an exception in
`_active_base_collapse_flags`, PREVIOUSLY CACHED as a confirmed result for the rest of the
process's lifetime. Fixed: only a successful read is cached now; a failed read degrades to
empty for that one call but is retried on the next call.

**Tests:** `tests/test_action12_7_market_state_fail_closed.py` (2 new tests),
`tests/test_ml_predict_fail_closed.py` (2 new tests) — 88 total in the combined lock+repair
suite, all passing.

**Files:** `market_state.py`, `ml_predict.py`.

**Cursor overlap:** none.

**Acknowledged remaining gap:** `ms.gex_magnitude`/`ms.dex_magnitude` are typed
`str = "negligible"` (non-`Optional`) dataclass fields with 41 files referencing the
magnitude-label vocabulary (including `call_engine.py`'s own `dex_magnitude=inp.dex_magnitude
or "moderate"`, a sibling instance of the identical shape, NOT_PROVEN, not yet adjudicated).
A full fix (an `Optional[str]` field genuinely distinguishing "confirmed negligible" from
"unavailable" across every consumer) is a larger, separate-scope refactor; this repair closes
the ADJUDICATED except-handler substitution without destabilizing the wider typed consumer
graph. No new mechanical lock rule was added for this exact shape (a same-except-handler
guess from an uncertain alternate STRING source, as opposed to R3's empty/zero-literal
detection) — a real, acknowledged detection gap, noted rather than papered over.

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

## Genuinely ambiguous, still NOT_PROVEN pending a downstream-consumer trace

- Several `except`-handler `None`/empty-sentinel assignments (`_contract_admission`,
  `_gamma_surface`, `vendor`, `arch_state`, `price_levels`, `regime`, and others) marked
  `NOT_PROVEN` pending a downstream-consumer trace to confirm the sentinel is always disclosed
  and never rendered as a real reading — see `reports/no_fallback_inventory.json` entries
  tagged `needs_downstream_trace`. `price_levels` (`FB-00543`, server.py) is Cursor-overlapping
  and untouched regardless.
- `training_cache.py`'s two `fillna(-1.0)` sites (reclassified FALLBACK per the operator's
  blanket imputation ruling) still carry an open factual question worth re-confirming during
  repair: is -1.0 genuinely outside the series' real value domain (an impossible-value
  sentinel, like the schema-version -1 case) — this doesn't change the FALLBACK verdict, but
  affects what the honest replacement disclosure should look like.

## Not yet reached (1121 of 1226 discovered candidates)

The `OR_LADDER`, `TERNARY`, `DICT_GET_DEFAULT`, and `GETATTR_DEFAULT` patterns (the bulk of
the repo-wide discovery census) were mechanically discovered but not semantically adjudicated
in this pass — this session prioritized the three patterns the mission's own PROHIBITED list
names most explicitly (SQL substitution, exception-driven substitution, model/training
substitution) to a real, evidenced depth rather than shallow-passing the full 1226. The next
adjudication pass continues file-by-file or pattern-by-pattern through
`reports/no_fallback_inventory.json`'s remaining `NOT_PROVEN` entries, in parallel with the
repair cycle already underway on the confirmed groups above.
