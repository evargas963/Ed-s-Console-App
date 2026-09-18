# No-fallback mechanical lock — grouped production repair plan

Generated from `reports/no_fallback_inventory.json`. **Status 2026-09-18 (post-JSON-SQL-
registry discovery, PR #254 point 7 / original mission point 6):** current counts: 3
`REPAIRED`, 41 `NOT_FALLBACK`, **23 `FALLBACK`**, 1088 `NOT_PROVEN`, of 1155 candidates
(`REPAIRED + NOT_FALLBACK + FALLBACK + NOT_PROVEN == candidate_count`, checked
mechanically by `tools/apply_adjudication.py`'s own invariant assertion — it refuses to
write the inventory if this ever fails to hold). **Currently adjudicated FALLBACK: 23.
NOT_PROVEN: 1088. Overall: NOT_PROVEN, and now also FALLBACK-positive — repair owed.**

**Why FALLBACK went from 0 to 23 — a real, previously-invisible defect surfaced by
closing a discovery gap, not a regression (PR #254 point 7, "the discovery-completeness
proof validates the scanner using its own planted example... does not independently
prove all executable and loader-interpreted surfaces were discovered"):** the discovery
scanner treated every `.json` file as a declared no-op by extension. Confirmed via
direct trace that this is false: `db.py`'s `get_snapshot_sql()` loads every
`snapshot_sql/*.json` file and returns its string VALUES as literal SQL text, executed
as-is by 60+ callers across the repo — a JSON value here is exactly as executable as a
Python string literal passed to `conn.execute()`. `tools/fallback_discovery.py` now
parses every `.json` file and walks its string values (not keys) for the same
COALESCE/IFNULL/NVL check already applied to Python/SQL/JS source. Regenerating the
census against the REAL repo (not a planted fixture) found 23 genuine COALESCE
occurrences in `snapshot_sql/registry_full_a.json` / `_b.json` / `_c.json` /
`_auto_extracted.json`, auto-classified FALLBACK by the same blanket operator
correction that already governs every SQL_COALESCE_STYLE candidate repo-wide (see
below) — **these have NOT yet been individually repaired; point 7's closure is the
discovery capability, not yet the repair of what it found.**

**A second, genuine self-reference hazard was found and fixed in the same pass:**
scanning ALL `.json` files unconditionally at first produced ~90 additional "candidates"
that were not real — this mission's own governance artifacts
(`reports/no_fallback_inventory.json`, `reports/no_fallback_inventory_lineage_*.json`,
`reports/no_fallback_discovery_raw.json`) quote real COALESCE findings as human-readable
evidence prose, and other tools' run-output snapshots (`reports/operable_surface_gate_
latest.json`, `reports/rc6_preflight_*.json`) record a query that executed elsewhere as
a logged string, not one the JSON file itself causes to execute. `reports/` is this
repo's established generated-OUTPUT directory (RC-523 `runtime_layout`) — nothing under
it is ever `json.load()`-ed back into a live SQL string the way `snapshot_sql/*.json`
genuinely is. JSON files under `reports/` are now excluded from the SQL-registry scan
specifically (not from scanning generally — `.py`/`.sql`/`.jsx` files that happen to
live under `reports/`, e.g. `reports/audit_round2_scripts/*.py`, are unaffected), and
the exclusion is counted and reported (`reports_dir_json_excluded_from_sql_scan`), never
silently dropped. Proof: `tests/test_fallback_discovery_json_sql_registry.py`.

**Why REPAIRED dropped from a previously-reported 115 to 3, and total candidates from
1226 to 1125 — a candidate-identity correction, not a regression (operator point 5,
2026-09-17):** the discovery scanner previously assigned each candidate a sequential
`FB-NNNNN` id purely from file/scan order. The operator identified this as unstable:
"Line number may be metadata but cannot be the sole identity... Never apply an old
verdict to a shifted candidate." Inserting or deleting one candidate anywhere earlier in
the scan order silently renumbered every later one, so a verdict recorded against
"FB-00519" could point at a completely different piece of code after the next
regeneration, with nothing to detect the mismatch. `tools/fallback_discovery.py` now
assigns each candidate a deterministic id derived from a SHA-256 fingerprint of (file,
enclosing symbol/context, detector pattern, a position-independent `ast.dump` of the
matched expression, and the guessed semantic field) — content that only changes when the
candidate's own code changes, never when unrelated code is edited. A full inventory
regeneration under this scheme, migrated via a content-based (file/pattern/snippet/line)
match from every previously-recorded verdict, found:
- **94 of the 115 previously-REPAIRED candidates' exact syntactic shape is simply GONE
  from a fresh scan** — direct, mechanical proof that those repairs were real deletions
  of fallback-shaped code, not relabelings. A deleted candidate cannot appear in any
  fresh census, REPAIRED or otherwise; only 4 previously-recorded REPAIRED old ids still
  match a current candidate's syntactic *shape* (the underlying behavior was fixed by
  adding disclosure, without removing the exact matched `tickers = []` construct in
  `lstm_data.py`/`train_all.py`/`transformer_train.py` — see Group 2 below), collapsing
  onto 3 distinct fingerprints (two of the four old ids pointed at what is now a single
  consolidated site in `lstm_data.py`) — hence 3 REPAIRED entries in the live inventory.
- **A confirmed discovery-tool precision defect, found and fixed during this same
  migration:** the SQL_COALESCE_STYLE detector matched ANY string constant containing
  `COALESCE(`/`IFNULL(`/`NVL(`, including this mission's own governance-tooling evidence
  strings (`tools/fallback_discovery.py` and `tools/apply_adjudication.py` quoting real
  banned syntax as human-readable explanation, self-matching 22 times) and this repo's
  own regression-proof tests, which assert a repair by searching for the banned
  pattern's ABSENCE in real source (`assert "COALESCE(...)" not in code_only`) —
  necessarily quoting the banned syntax as a string to search FOR, never to execute as
  SQL (13 false positives across `tests/test_horizon_bar_outcomes.py`,
  `tests/test_operable_surface_gate.py`, and the `tests/test_no_fallback_lock_v1.py`
  mutation-proof namespace, the last of which is now excluded from the census the same
  way `check_no_fallback_lock.py`'s regression gate already excludes it). Fixed by (a)
  reusing the enforcement gate's existing `_META_TOOLING_EXCLUDED_FROM_CONTENT_RULES`
  and `_TEST_PROOF_NAMESPACE_PREFIX` constants in the discovery scanner instead of
  re-declaring a divergent list, and (b) excluding a COALESCE-shaped string literal when
  it is the operand of an `in`/`not in` membership test rather than passed to something
  that could execute it as SQL. Proof: `tests/test_fallback_discovery_fingerprint_identity.py`.
- **55 previously-unadjudicated (NOT_PROVEN) old ids could not be resolved 1:1 to a new
  candidate** (multiple structurally-identical expressions on one line, e.g. two
  `.get(key, default)` calls in the same statement) — confirmed via direct source-level
  cross-reference that NONE of these 55 had ever received a FALLBACK/NOT_FALLBACK/
  REPAIRED verdict (all were still NOT_PROVEN), so no real adjudication was at risk;
  they remain NOT_PROVEN under their new, individually fingerprinted ids and will be
  reached by ordinary continued adjudication like any other candidate.
`tools/apply_adjudication.py` now also hard-fails (`SystemExit`) if any recorded verdict
references a NEW-format (fingerprint) id that no longer matches any current candidate —
the "shifted candidate" failure mode is now mechanically impossible to apply silently,
going forward. A LEGACY-format (`FB-NNNNN`) id with no match is expected and reported for
visibility only (the underlying code was deleted by a real repair), never a failure.
Proof: `tests/test_fallback_discovery_fingerprint_identity.py::test_adjudication_target_validation_distinguishes_legacy_from_shifted`.

**Point 12 remains NOT_PROVEN.** Deleting tests that referenced deleted code is not
retirement proof. See `reports/point12_deleted_responsibility_lineage.json`. Prior note: auditing
`tools/legacy/horizon_7/`'s deletion and `tools/_fusion_backfill_shared.py`'s necessity
claim did not confirm a clean bill of health — it surfaced two real, previously-
unverified defects:
- `tests/test_batch_movement_backfill_contract_v1.py` and one test inside
  `tests/test_pred_1c_eddb_and_audit_contract_v1.py` were still reading/loading files
  from the deleted `tools/legacy/horizon_7/` directory and had been failing with
  `FileNotFoundError` ever since it was deleted — a real, currently-red regression a
  prior "zero references" claim never caught, because these tests were never actually
  run against the post-deletion tree until now. Confirmed via repo-wide grep that
  neither `_sanitize_snapshot_dict_for_mvp` nor the `governed_rows_with_pred_1c_nonnull`
  audit metric these tests pinned has any other definition or consumer anywhere in the
  current codebase — both were genuinely retired with the directory, not relocated.
  Deleted the dead-legacy-pinning test file and test; kept the unrelated, still-passing
  real-schema test in the second file.
- `tools/_fusion_backfill_shared.py`'s own docstring claimed all three fusion-backfill
  tools shared `_classify_failure`, but `tools/backfill_fusion_policy_complete_v1.py`
  never actually imported it — it kept a pre-existing local `_classify_failure_complete`
  already drifted from the shared version (a different label for the identical
  `MonteCarloStackInputError` case, plus a finer history-vs-reconstruction message check
  the shared version lacked). Folded the finer distinction into the shared function as
  the single canonical classifier and deleted the local duplicate — now genuinely one
  producer for all three consumers.
- Also removed an orphaned grandfather-exemption entry in
  `tools/check_institutional_correctness.py` naming a horizon_7 file that can never
  match anything post-deletion — inert, but stale clutter that looked like a live
  carve-out.
Proof: `tests/test_fusion_backfill_shared_v1.py` (extended), `tests/test_pred_1c_eddb_and_audit_contract_v1.py`, `tests/test_audit_snapshot_columns.py`.

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
