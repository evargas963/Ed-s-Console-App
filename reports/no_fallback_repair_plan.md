# No-fallback mechanical lock — grouped production repair plan

Generated from `reports/no_fallback_inventory.json`. **Status 2026-09-17 (operator
correction + repair cycle in progress):** the first-pass "confirmed-safe SQL idiom" and
"deferred ML imputation" classifications were REJECTED by the operator and reclassified
FALLBACK (see `tools/apply_adjudication.py`'s own `_apply_operator_correction_2026_09_17`).
Current counts: 9 `FALLBACK`, 1105 `NOT_PROVEN`, 27 `NOT_FALLBACK`, 85 `REPAIRED`, of 1226
candidates. Repair is proceeding continuously group-by-group (adjudicate → repair → test →
lock → reconcile → commit → next group), not gated behind full census completion.

## Group 1: `calibration_ml_governance` — **FULLY REPAIRED (0 remaining)**

All 64 originally-flagged FALLBACK candidates in this group are now REPAIRED, across a
sequence of commits (`b8c98ee6`, `40516745`, `2c1536bd`, `008f83fc`, `e29eee79`, `a3f8ff48`,
`5204a95a`) covering: `calibration/anchor_audit.py`, `calibration/backfill_outcomes.py`,
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
  (the query always raised `sqlite3.OperationalError`, silently swallowed into a fabricated
  "0 enrolled tickers" on every call). The test fixture that had been validating this code
  path had its own hand-rolled schema that (accidentally) DID define `active`, a fixture/
  production schema divergence that is exactly what let the bug's own tests pass. Both the
  production query and the fixture are now fixed to match the real schema.
- `calibration/run_production_accumulation_validation.py`'s "unsafe join" gate was silently
  treating unrecorded (NULL) join provenance as safe by folding it into an exempted blank
  sentinel — reinvestigated on its own evidence (not the blanket SQL ruling) after
  initially being reclassified NOT_FALLBACK, and confirmed as a genuine repair target.
- Three SQL-COALESCE occurrences were unreachable by the discovery scanner entirely because
  they lived in JSON-registered SQL templates (`snapshot_sql/*.json`), not Python string
  literals — fixed in lockstep with their Python call sites, including two placeholder-count
  corrections this required.

Two items originally in this group's census were investigated and reclassified `NOT_FALLBACK`
with specific, evidenced justification (not a blanket "safe idiom" pass): `FB-00181` (the
one-time schema-version migration WRITE, not a masking READ) and `FB-00187`
(`enrollment_source = COALESCE(enrollment_source, ?)`, a WRITE-preserving-existing-value UPDATE
idiom, not a READ-side substitution) — see `tools/apply_adjudication.py` for both.

## Group 2: `ml_training_pipeline` — **5 of 11 REPAIRED; 6 IMPUTATION items
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

`market_state.py:1147` and `ml_predict.py:2298` — see prior detail below, unchanged this
cycle. **Files:** `market_state.py`, `ml_predict.py`. **Cursor overlap:** none.

**Acknowledged remaining gap:** `ms.gex_magnitude`/`ms.dex_magnitude` are typed
`str = "negligible"` (non-`Optional`) dataclass fields with 41 files referencing the
magnitude-label vocabulary (including `call_engine.py`'s own `dex_magnitude=inp.dex_magnitude
or "moderate"`, a sibling instance of the identical shape, NOT_PROVEN, not yet adjudicated).
A full fix (an `Optional[str]` field genuinely distinguishing "confirmed negligible" from
"unavailable" across every consumer) is a larger, separate-scope refactor; this repair closes
the ADJUDICATED except-handler substitution without destabilizing the wider typed consumer
graph. No new mechanical lock rule was added for this exact shape, a real acknowledged gap.

## Group 4: `market_data_server_core` — **2 of 3 fixed and uncommitted, 1 held**

**Concurrency boundary UPDATE (2026-09-17):** this group was originally deferred as
Cursor-overlapping. Verified directly: `origin/main`'s current HEAD (`7761792f`, PR #252's
merge commit) IS the exact merge-base between this branch and `origin/main` — no new Cursor
commits have landed since PR #252 merged, and this branch was created from that same SHA.
There is no live Cursor collision on `server.py` anymore; the wait condition is satisfied.

`server.py:13712`/`13844`/`13940` (`_terrain_loop`, `_seed_strike_geometry_from_storage`,
`_bars_loop`) — three identical sites: `tickers = list(CORE_TICKERS)` inside an `except`
handler, substituting the static default roster for a failed DYNAMIC ticker-list
computation, with **zero disclosure**, unlike every other `except` handler in the same
region of the file (which all `log.warning(...)` the degraded path).

**Repair applied:** add a `log.warning(...)` matching the file's own established
convention at each site, disclosing that the dynamic roster read failed and `CORE_TICKERS`
is being used as a fallback, before falling through to the same degraded roster. Two of the
three sites (`_seed_strike_geometry_from_storage`, `_terrain_loop`) have this fix applied in
the working tree but **not yet committed**. The third (`_bars_loop`) is blocked: an
auto-mode permission classifier denied the identical edit as a "Modify Shared Resources"
action after allowing the first two through. Awaiting the operator's explicit go-ahead to
either complete the third edit or apply it themselves — this is a tooling/permission
barrier, not a product or Cursor-collision judgment call, so it is being surfaced rather
than worked around.

**Files:** `server.py`.

## Genuinely ambiguous, still NOT_PROVEN pending a downstream-consumer trace

- Several `except`-handler `None`/empty-sentinel assignments (`_contract_admission`,
  `_gamma_surface`, `vendor`, `arch_state`, `price_levels`, `regime`, and others) marked
  `NOT_PROVEN` pending a downstream-consumer trace to confirm the sentinel is always disclosed
  and never rendered as a real reading — see `reports/no_fallback_inventory.json` entries
  tagged `needs_downstream_trace`. `price_levels` (`FB-00543`, server.py) is now editable
  under the same concurrency-boundary update as Group 4, but not yet traced/adjudicated.
- `training_cache.py`'s two `fillna(-1.0)` sites (reclassified FALLBACK per the operator's
  blanket imputation ruling, paused with Group 2) still carry an open factual question worth
  re-confirming during repair: is -1.0 genuinely outside the series' real value domain (an
  impossible-value sentinel, like the schema-version -1 case found and fixed in
  `tools/_multi_timeframe_audit_v1.py`) — this doesn't change the FALLBACK verdict, but
  affects what the honest replacement disclosure should look like.

## Not yet reached (1105 of 1226 discovered candidates)

The `OR_LADDER`, `TERNARY`, `DICT_GET_DEFAULT`, and `GETATTR_DEFAULT` patterns (the bulk of
the repo-wide discovery census) remain mechanically discovered but not semantically
adjudicated — this branch has so far prioritized the patterns the mission's own PROHIBITED
list names most explicitly (SQL substitution, exception-driven substitution, model/training
substitution) to a real, evidenced depth across the `calibration_ml_governance`,
`market_state_rendering`, and (now, partially) `market_data_server_core` groups, rather than
shallow-passing the full 1226. The next adjudication pass continues file-by-file or
pattern-by-pattern through `reports/no_fallback_inventory.json`'s remaining `NOT_PROVEN`
entries, in parallel with any remaining repair work.
