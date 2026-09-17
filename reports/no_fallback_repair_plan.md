# No-fallback mechanical lock — grouped production repair plan

Generated from `reports/no_fallback_inventory.json`. **Status 2026-09-17 (post-second-
rejection corrections applied):** current counts: 115 `REPAIRED`, 41 `NOT_FALLBACK`,
0 `FALLBACK`, 1070 `NOT_PROVEN`, of 1226 candidates
(`REPAIRED + NOT_FALLBACK + FALLBACK + NOT_PROVEN == candidate_count`, checked
mechanically by `tools/apply_adjudication.py`'s own invariant assertion — it refuses to
write the inventory if this ever fails to hold). **Zero FALLBACK remains repo-wide** —
every previously-open FALLBACK candidate across all four ownership groups below is now
REPAIRED. This is NOT a claim the repository is fallback-free: 1070 candidates are still
NOT_PROVEN, meaning they have not yet been individually adjudicated one way or the other.

**The first repair pass on this branch was rejected twice by the operator**, each time for
a specific, named defect rather than a vague "try harder": (1) an early pass treated a
pre-existing structural test's assertion as proof of correctness instead of tracing the
actual source (see the VOL_INPUT_CONTRACT correction below); (2) a later pass kept
disclosing a fallback via `state_error` while still substituting a meaningful default
value ("negligible") for a genuine computation failure, and separately kept a
`getattr()` call specifically because a pre-existing AST-based governance lock couldn't
see through it to count it as a fallback read — checker evasion, not a repair. Both
classes of defect are corrected in the groups below; the corrections are called out
explicitly rather than folded silently into a generic "repaired" note.

## Group 1: `calibration_ml_governance` — **FULLY REPAIRED (0 remaining)**

All 64 originally-flagged FALLBACK candidates in this group are REPAIRED, across commits
`b8c98ee6`, `40516745`, `2c1536bd`, `008f83fc`, `e29eee79`, `a3f8ff48`, `5204a95a`
covering: `calibration/anchor_audit.py`, `calibration/backfill_outcomes.py`,
`calibration/canonical_1m_grid_scan.py`, `calibration/phase6_edge_discovery_governed_v1.py`
+ `phase65_edge_isolation_v1.py`, `calibration/repair_canonical_1m_edge_carry_v1.py` +
`repair_canonical_1m_interior_gaps_v1.py`, `tools/pin_neutral_1m_5m_divergence_audit_v1.py`
(+ its JSON-registered SQL templates), `calibration/run_production_accumulation_validation.py`,
`calibration/writer.py`, `tools/_multi_timeframe_audit_v1.py`,
`tools/repair_validation_counts_v1.py` (+ 3 more JSON-registry siblings unreachable by the
discovery scanner), `tools/smoke_movement_heads_inference_v1.py`, and the earlier
`db.py` / `tools/legacy/horizon_7/*` (whole directory deleted as quarantined dead code) /
`calibration/operable_surface_quarantine.py` / `tools/operable_surface_gate.py` /
`normalized_training_sync.py` / `snapshot_normalizer.py` /
`tools/migrate_snapshots_schema_repair_v1.py` / `tools/repo_exposure_audit.py` /
`audit_model_readiness.py` batch.

**Notable non-mechanical findings surfaced during repair, not just pattern deletions:**
- `calibration/writer.py`'s `_count_enrolled_tickers` queried a `logging_universe.active`
  column that has **never existed** in `db.py`'s real schema — a confirmed production bug
  (always raised `sqlite3.OperationalError`, silently swallowed into a fabricated "0
  enrolled tickers"). The test fixture validating this had its own hand-rolled schema
  that (accidentally) DID define `active` — a fixture/production divergence that is
  exactly what let the bug's own tests pass.
- Three SQL-COALESCE occurrences were unreachable by the discovery scanner entirely
  because they lived in JSON-registered SQL templates (`snapshot_sql/*.json`), not
  Python string literals — fixed in lockstep with their Python call sites.

`FB-00181`/`FB-00187` reclassified `NOT_FALLBACK` with specific evidence (a one-time
schema-version migration WRITE, and a WRITE-preserving-existing-value UPDATE idiom —
neither is a READ masking absence).

## Group 2: `ml_training_pipeline` — **FULLY REPAIRED (0 remaining)**

**Correction (2026-09-17):** the 6 ML-imputation items in this group were originally
paused as an "irreducible product decision" needing operator sign-off on a replacement
missing-data methodology. The operator corrected this framing directly: the mandate was
never to invent a new bucketing/imputation methodology, only to stop fabricating a value
where none should exist. All 6 are now repaired, each with the design appropriate to
its actual role (research/diagnostic tooling vs. production model training):

- `lstm_data.py` (2 sites), `ml_scheduler.py`, `train_all.py`, `transformer_train.py`:
  a failed ticker-list computation used to report the identical message a
  genuinely-empty roster produces — now each site discloses which actually happened.
- `tools/feature_curation_gate.py`: Spearman-hierarchical feature-redundancy clustering
  median-imputed missing readings before computing the correlation matrix. Changed to
  complete-case rows only (`.dropna()`).
- `train_compare.py`: `_compute_baseline` mapped an unrecognized `rules_signal` value to
  `"flat"` via `fillna`. Changed to exclude unmapped rows from the metric.
- `tools/research/d2_dual_label_eval_report.py`: `run_cell` defaulted a NULL truncation
  flag to 0 (not truncated) via `fillna` before filtering. Changed to a bare `== 0`
  comparison (NaN excluded naturally, mirroring SQL NULL propagation).
- `training_cache.py`'s two `fillna(-1.0)` sites: **re-investigated and reclassified
  `NOT_FALLBACK`**, not repaired — confirmed via grep that the resulting `content_hash`
  flows only into cache-key generation (`compute_feature_cache_key`/
  `compute_scheduler_cache_key`), never into any model `.fit()`/`.predict()` call
  anywhere in the repo. `-1.0` is structurally outside `ts_utc`'s real domain (~1.7-1.9
  billion Unix epoch seconds), so it can never collide with genuine data. This is a
  hash-stability sentinel for cache fingerprinting, not model-feature imputation.
- **`ml_train.py`'s XGBoost median imputation (the last FALLBACK candidate repo-wide):**
  removed entirely. XGBoost natively handles NaN inputs (verified empirically: the
  sklearn API defaults `missing=nan`, and both `.fit()`/`.predict()` work directly with
  real NaN, learning an optimal tree-split direction for missing values internally).
  `apply_xgb_imputation_matrix` (the one function every serving path routes through --
  `ml_predict.py`, `arch_competition.ablation_bundle_inference`) was made a true
  passthrough when `impute_medians` is empty, the shape a newly-trained model always
  carries now — backward compatible, since a model carrying the prior contract's real,
  complete `impute_medians` sees byte-identical behavior. `model_contract.py`'s
  `CURRENT_MISSINGNESS_CONTRACT_VERSION` bumped (`issue7_v1_empirical_nan_impute` →
  `issue7_v2_xgb_native_nan_no_impute`) — per this contract's own established, tested
  convention ("bump when semantics change; retrain all families"), this deliberately
  makes every bundle trained under v1 fail `meta_matches_system_contract` until
  retrained. **This branch is not the production-serving branch (production runs off
  origin/main, deployed separately), so this repair has zero live effect as committed.
  Deploying it will take every currently-serving XGBoost model offline until each
  ticker is retrained — retraining is a separate, not-yet-performed operational step
  requiring live/historical data access this session does not exercise, and is owed
  before this repair can carry production authority.**

**Files:** `lstm_data.py`, `ml_scheduler.py`, `train_all.py`, `transformer_train.py`,
`tools/feature_curation_gate.py`, `train_compare.py`,
`tools/research/d2_dual_label_eval_report.py`, `training_cache.py`, `ml_train.py`,
`ml_predict.py`, `model_contract.py`, `arch_competition/ablation_bundle_inference.py`.

**Cursor overlap:** none.

## Group 3: `market_state_rendering` — **FULLY REPAIRED (0 remaining in market_state.py)**

**Correction (2026-09-17):** the original repair kept `ms.gex_magnitude = "negligible"`
on a genuine computation failure, alongside a new `state_error` disclosure — the operator
correctly identified this as still substituting a meaningful, valid-looking value for a
real failure. `ms.gex_magnitude`/`ms.dex_magnitude` are now `Optional[str] = None`
(field type changed from non-Optional `str = "negligible"`); a genuine failure or an
absent producer now reads honestly as `None`, not a specific bucket.

`ms.dex_magnitude` specifically was closed out end to end, not just at the display
field: traced the full graph `MarketState.dex_magnitude` → `SignalInput.dex_magnitude`
(already `Optional[str] = None`) → `call_engine.py`'s `dex_magnitude=inp.dex_magnitude
or "moderate"` (removed) → `math_exposure_core.greek_bias`'s own `dex_magnitude: str =
"moderate"` default and `MAG_SCALE.get(dex_magnitude, 0.7)` (both changed to exclude
that vote's score contribution entirely when the magnitude is unavailable, rather than
assuming a "moderate" 0.7 significance). `charm_magnitude`'s identical shape in the same
`greek_bias` call was fixed in the same pass (its producer was already real/Optional;
only the consumer-side fallback needed fixing).

Beyond the two magnitude fields, this pass also closed out `market_state.py`'s entire
remaining `NOT_PROVEN` surface (35 candidates originally): the `mkt_ctx` field cluster
(traced to a provably-always-real `MarketContext`), the `TheCall`/rules/micro/regime/
fusion/vol_regime/stack_decision_path/multi-horizon-decision getattr clusters (all
traced to specific `@dataclass` types with required/defaulted fields), and 11
value-level `or <default>` guards on multi-horizon-decision string fields (each traced
into `multi_horizon_decision.py`'s own construction logic and confirmed to build from an
exhaustive if/elif/else chain or a hardcoded literal — never empty by construction).
6 candidates were reclassified `NOT_FALLBACK` with specific evidence rather than
repaired: two are whitelist-validation ternaries (an invalid input maps to an honest
`None`, never a fabricated enum member); four are the deliberately tested,
version-locked `VOL_INPUT_CONTRACT 1.0.0` migration shape.

**Correction on the VOL_INPUT_CONTRACT reclassification specifically:** the first pass
cited a structural test's assertion of the exact source text as the evidence for
`NOT_FALLBACK` — backwards, since a test can encode the wrong architecture. Re-derived
correctness independently: `server.py`'s `vol_ctx` construction sets
`market_iv_level=float(mkt_ctx.vix)`, the literal same value from the literal same
single Schwab quote fetch (confirmed via grep: no second vendor call anywhere in the
chain). The `vol_ctx`-vs-`mkt_ctx.vix` ternary reads the identical underlying value
through two structurally-equivalent carriers, not an alternate vendor standing in for a
missing one — the verdict holds on independent evidence, not the test's say-so.

**Correction on checker evasion:** `ms.vix`'s assignment had been kept on
`getattr(mkt_ctx, "vix", None)` specifically because a separate, pre-existing
`[REAL-GATE:VOL-CTX-SINGLE-SOURCE]` AST-based lock (`test_market_context_fetch_fail_closed.py`)
couldn't see through `getattr()` to count it as a third, unblessed raw `mkt_ctx.vix`
read. Preserving that syntax because the checker missed it is the exact evasion pattern
the operator named. Traced every consumer of `ms.vix`: none exist (server.py always
overwrites the served "vix" field from `vol_ctx.market_iv_level` regardless) — the
assignment was dead code entirely and was deleted outright, not re-hidden.

**Also repaired (upstream of market_state.py):** `server.py`'s `_fetch_and_store_mkt_ctx`
swallowed a genuine `fetch_market_context` exception into a bare `MarketContext()` — an
object whose every field carries the same neutral-looking default as a real "nothing
computed yet" state, indistinguishable from a disclosed failure. This exact fallback had
been used as a *proof technique* ("mkt_ctx is always real, so getattr defaults are
dead") without being flagged as its own violation until the operator's rejection caught
it. Fixed: the exception path now routes through `MarketContext`'s own pre-existing
`error` field (the same channel `fetch_market_context`'s internal soft-error path
already used but which `market_state.py` never consumed); `build_market_state()` now
surfaces a non-empty `mkt_ctx.error` via `ms.state_error`/`state_error_detail`.

**Files:** `market_state.py`, `ml_predict.py`, `call_engine.py`, `math_exposure_core.py`,
`server.py` (the `_fetch_and_store_mkt_ctx` exception-path fix only).

**Cursor overlap:** none.

## Group 4: `market_data_server_core` — **FULLY REPAIRED (0 remaining)**

**Concurrency boundary:** verified `origin/main`'s HEAD (`7761792f`, PR #252's merge
commit) IS the exact merge-base between this branch and `origin/main` — no Cursor
collision; this group was always editable once that was confirmed.

**Correction (2026-09-17):** the first pass added `log.warning(...)` disclosure at all
three sites but still processed `CORE_TICKERS` as the enrolled roster on a
`_logger_lock`/`_logger_tickers` read failure — the operator correctly rejected this:
"logging the fallback is not a repair." Redesigned per-site: `_terrain_loop`/
`_bars_loop` now leave `tickers` at its pre-declared `[]` on a roster-read failure
(skipping that cycle's work — the same degrade-safely behavior a genuinely empty
enrolled board already has); `_seed_strike_geometry_from_storage`'s inner try/except was
removed entirely so a roster-read failure propagates to its caller
(`_terrain_prewarm_worker`), which already has a correct, documented, already-accepted
degrade path for the whole one-time boot seed failing outright ("first cycle uses
cold-start width").

**Files:** `server.py`.

## Genuinely ambiguous, still NOT_PROVEN pending a downstream-consumer trace

- Several `except`-handler `None`/empty-sentinel assignments (`_contract_admission`,
  `_gamma_surface`, `vendor`, `arch_state`, `regime`, and others) marked `NOT_PROVEN`
  pending a downstream-consumer trace to confirm the sentinel is always disclosed and
  never rendered as a real reading — see `reports/no_fallback_inventory.json` entries
  tagged `needs_downstream_trace`. `price_levels` (`FB-00543`, server.py) is editable
  (concurrency boundary satisfied) but not yet traced/adjudicated.

## Not yet reached (1070 of 1226 discovered candidates)

The bulk of the `OR_LADDER`, `TERNARY`, `DICT_GET_DEFAULT`, and `GETATTR_DEFAULT`
patterns outside the four repaired ownership groups above remain mechanically
discovered but not semantically adjudicated. `server.py` alone accounts for ~200 of
these. The next adjudication pass continues file-by-file through
`reports/no_fallback_inventory.json`'s remaining `NOT_PROVEN` entries. Per the mission's
closure criteria, this branch must continue to be reported as NOT_PROVEN until every
candidate is individually resolved.

## Structural corrections still owed (not yet implemented)

Beyond per-candidate adjudication, the operator's second rejection also named structural
gaps in the lock/discovery infrastructure itself, not yet addressed:
- Candidate identity is presently sequential (`FB-NNNNN`), not content-addressed —
  a fingerprint derived from file + enclosing symbol + detector pattern + normalized
  expression would survive line-number drift; sequential IDs do not.
- Discovery is extension-based (scans `.py`/`.js`/`.sql`/etc.); it does not yet
  enumerate every loader that interprets JSON/YAML/TOML/config/template/registry
  content as executable semantics (the JSON-registered SQL templates found ad hoc
  during Group 1's repair are a real, confirmed instance of this gap, but the *general*
  loader-based scanning capability was not built).
- The semantic-term population used by several detectors is a hand-maintained word
  list, not derived from the repo's actual dataclass fields / API response keys /
  DB columns / frontend bindings.
