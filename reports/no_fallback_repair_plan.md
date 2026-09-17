# No-fallback mechanical lock — grouped production repair plan

Generated from `reports/no_fallback_inventory.json`. **Status 2026-09-17 (operator
correction + repair cycle in progress):** the first-pass "confirmed-safe SQL idiom" and
"deferred ML imputation" classifications were REJECTED by the operator and reclassified
FALLBACK (see `tools/apply_adjudication.py`'s own `_apply_operator_correction_2026_09_17`).
Current counts (after this repair cycle): 54 `FALLBACK`, 1121 `NOT_PROVEN`, 26 `NOT_FALLBACK`,
25 `REPAIRED`, of 1226 candidates. Repair is proceeding continuously group-by-group
(adjudicate → repair → test → lock → reconcile → commit → next group), not gated behind
full census completion.

## Group 1: `calibration_ml_governance` — **partially repaired (18 of 64), 46 remaining**

18 REPAIRED this cycle: `tools/legacy/horizon_7/*` (12 FB ids, whole directory DELETED as
quarantined dead code, 4 dependent files repaired), db.py's 6
`COALESCE(horizon_outcome_schema_version, X) = X` sites simplified to a plain `= ?`. One
item (`FB-00181`) reclassified `NOT_FALLBACK` after direct investigation found it is the
ONE-TIME migration WRITE that establishes the column, not a masking READ — see
`reports/no_fallback_inventory.json`'s own evidence field for that entry, and
`tools/apply_adjudication.py`'s `_apply_fb_00181_investigated_reclassification` for why this
is a considered exception, not a re-run of the operator's rejected blanket idiom
classifications.

**Remaining 46 (not yet repaired this cycle):** `calibration/anchor_audit.py` (3),
`calibration/backfill_outcomes.py` (1), `calibration/canonical_1m_grid_scan.py` (2),
`calibration/operable_surface_quarantine.py` (2),
`calibration/phase65_edge_isolation_v1.py` (1),
`calibration/phase6_edge_discovery_governed_v1.py` (1),
`calibration/repair_canonical_1m_edge_carry_v1.py` (2),
`calibration/repair_canonical_1m_interior_gaps_v1.py` (3),
`calibration/run_production_accumulation_validation.py` (1), `calibration/writer.py` (1),
db.py's `enrollment_source = COALESCE(enrollment_source, ?)` (1, FB-00187, needs the full
UPDATE statement's intent confirmed), `normalized_training_sync.py` (6),
`snapshot_normalizer.py` (1), `tests/test_pin_neutral_1m_5m_divergence_audit_v1.py` (2),
`tools/_multi_timeframe_audit_v1.py` (1), `tools/migrate_snapshots_schema_repair_v1.py` (1),
`tools/operable_surface_gate.py` (4), `tools/pin_neutral_1m_5m_divergence_audit_v1.py` (3),
`tools/repair_validation_counts_v1.py` (1), `tools/repo_exposure_audit.py` (1),
`tools/smoke_movement_heads_inference_v1.py` (1), `audit_model_readiness.py` (1).

Most of these are the `COALESCE(<audit-flag>, 0)` shape (research_excluded/outcome_filled/
active) needing the same DDL-intent confirmation before ruling on the replacement, or the
same `COALESCE(MAX(...), 0)` aggregate shape now confirmed to need an explicit
non-COALESCE rewrite per the operator's ruling (functionally equivalent to
`COALESCE(MAX(x),0)` → `SELECT COALESCE(...)` removed, reading NULL directly and having the
CALLER treat a None result as zero explicitly, rather than doing it inside the SQL).

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

## Group 2: `ml_training_pipeline` — **5 of 11 REPAIRED this cycle; 6 IMPUTATION items
deliberately NOT repaired, paused as an irreducible product decision**

REPAIRED: `tickers = []` inside `except` handlers in `lstm_data.py` (2 sites),
`ml_scheduler.py`, `train_all.py`, `transformer_train.py` — a failed ticker-list computation
used to log/report the identical message a genuinely-empty roster produces; now each site
discloses which actually happened (an accurate error message, and in `ml_scheduler.py`'s
case a distinct `exit_code` for resolution-failure vs. confirmed-empty).

**NOT repaired, deliberately paused:** `ml_train.py`/`tools/feature_curation_gate.py`
median imputation, `train_compare.py:55`'s `fillna('flat')`, `tools/research/
d2_dual_label_eval_report.py`'s `fillna(0)`, `training_cache.py`'s two `fillna(-1.0)`
sites. `ml_train.py`'s own comments show this is deliberate, carefully-engineered ML
methodology (median imputation fit ONLY on the train partition, explicitly to avoid
training-skew leakage, with its own prior leakage-bug fix already on record) — changing it
to "exclude/flag missing rows" per the operator's ruling is a genuine product-accuracy
decision (different training-set size, different model behavior) that this session is
treating as the mission's own named exception: "continue automatically unless there is...
an irreducible product decision." Needs explicit operator sign-off on the REPLACEMENT
methodology (row exclusion? a distinct missing-indicator feature? a minimum-completeness
threshold?) before implementation, not a unilateral pick.

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
