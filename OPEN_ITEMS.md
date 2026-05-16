# Open items — horizon, stack, UI consistency

**Rule:** Items stay **open** until there is a merged/code-verified resolution (not just “planned”).  
**Last reviewed:** 2026-05-14 (Schwab V4 register deferred work consolidated into this file; reconciled against `fb1e84c` Schwab Field Precedence Principle commit and the A2 lifecycle landings — EOD force-exit `20a1c14`, session-calendar hardening `cac88a6`, pin-risk handler — none of which touch the ML horizon/cascade workstream items below).

---

## GOVERNANCE REBUILD STATUS

### Standard

V3.0 Institutional Standard is locked. See `governance/INSTITUTIONAL_STANDARD_V3.md` and `governance/V3_LOCK_RECORD.md`. The standard governs the entire system from the lock effective date forward. Amendments follow the V3.X / V4.0 path defined in the standard's Section 20.

### Research decision engine framework (pilot v1.1)

Research-path (non-production) specification for the replacement-core pilot: **`governance/Framework-ED-Decision-Engine-v1.1.md`**. It is **bound** to **`research/pilot_step3/prereg_v1.json`** using the prereg **`content_hash`** (must match the framework footer), **`framework_doc_id`**, and **`framework_doc_version`**. **`research/pilot_step3/pilot_config.load_prereg()`** enforces both body hash and framework binding via **`validate_prereg_integrity`** (hard-fail on mismatch). One-page rationale digest: **`governance/v1.1-rationale-summary.md`**.

### Conformance audit

Lock Condition 1 satisfied. See `governance/V3_CONFORMANCE_AUDIT.md`.

Result distribution across 32 evaluated rows:
- CONFORMS: 2
- DOES_NOT_CONFORM_TRACKED: 17
- DOES_NOT_CONFORM_NEW_GAP: 15

Four of the 15 new gaps are HIGH urgency and constitute a new infrastructure governance workstream (see below).

### Two workstreams (parallel, not sequential)

The rebuild work splits into two workstreams. They are orthogonal: different domains of risk, different failure modes, different validation paths. They run in parallel.

Governing rule: no infrastructure gap may be allowed to invalidate production claims. If an infrastructure invariant is not fully enforced, the corresponding production claim must be explicitly bounded or withdrawn. This is enforced by the V3 lock record's no-silent-non-conformance condition.

#### Workstream 1: Model Lifecycle

Goal: model correctness, feature integrity, statistical edge, training and evaluation discipline.

| Phase | Title | Status | Plan / Result |
|-------|-------|--------|---------------|
| G1 | Canonical contract draft | COMPLETE | `governance/G1_DIAGNOSIS.md`, `governance/G1_ADDENDUM_TRAINING_DEPENDENCY.md`, `governance/G1_ADDENDUM_CACHE_CONSISTENCY.md` |
| G2 | Cascade alignment | PAUSED | `governance/G2_PLAN.md` (original; paused pending v2.0 framework decision) |
| G3 | Governed path contract unification | PENDING | depends on G2 |
| G4 | Direct-write quarantine | PENDING | depends on G3 |
| G5 | End-to-end proof | PENDING | depends on G2-G4 |

G2 pause state:
- G2 is paused pending the `Framework-ED-Decision-Engine-v2.0` decision.
- If the maximum-edge v2.0 architecture is rejected, the G2 plan as written remains valid for the existing parallel/cascade architecture and may resume.
- If the maximum-edge v2.0 architecture is adopted, rewrite G2 as `G2.v2` against the new artifact contracts before implementation.

Deferred to G4 within this workstream:
- G4-1: server-side active sync helper (`server.py:4426-4453`) bypasses governance during request handling. HIGH risk.
- G4-2: five tool scripts write directly to `models/active/` outside governance.
- G4-3: scheduler fail-open behavior at `ml_scheduler.py:1701-1707` and `ml_scheduler.py:2133-2135` allows exit 0 with incomplete artifacts.
- G4-4: dormant scheduler auto-copy path at `ml_scheduler.py:1780-1783`.

G2 plan refinements (proposed during V3 standard development, not yet applied to `governance/G2_PLAN.md`):
- Architectural invariant statement (cascade meta MUST NOT read parallel paths)
- Runtime path validation in cascade meta block
- `validate_trained_candidate()` runtime contract enforcement (cascade and parallel symmetric)
- LSTM cache invariant note from `governance/G1_ADDENDUM_CACHE_CONSISTENCY.md`
- `test_parallel_vs_cascade_artifact_equivalence` test
- Manifest as REQUIRED clarification
- New sub-phase G2.0 runtime trace (resolves residual UNKNOWN about `_model_dir_for_ticker` resolution)
- Reference to `governance/G1_ADDENDUM_TRAINING_DEPENDENCY.md` in plan's architectural reference section

These refinements remain attached to the paused G2 plan. Do not apply them while G2 is paused; resume them only if the existing parallel/cascade architecture remains the governed target.

##### G3 Reconciliation Queue

Classification: RECONCILIATION (not new gap). Items where two or more existing implementations disagree about a contract, identified during G1 investigation. To be resolved as part of G3 (governed path contract unification).

- **G3-R1: Active validator vs runtime fallback completeness mismatch.** `verify_active_models.py:100-152` enforces one definition of "complete active bundle" (strict, all artifacts required). `ml_predict.py:1291-1294` enforces a different definition (tolerates missing meta with fallback). The two checks disagree on what counts as a valid active model. Invariants violated: I-01 (no silent degradation), I-05 (train-serve feature identity), I-15 (tuple health before trade impact). Status: PENDING. Resolve in G3.

- **G3-R2: `promotion_decision` field is non-authoritative.** `training_cache.py:980, 1029` writes a `promotion_decision` field into candidate manifests. No code path consumes this field as binding for promotion decisions. The field exists, implies authority, but is informational only. Invariants violated: I-02 (single promotion authority), I-14 (attributable change). Status: PENDING. Resolve in G3 by either removing the field or wiring it as authoritative.

- **G3-R3: Lineage horizon mismatch blocks governed evaluation.** Governed evaluation pass fails with `EvaluationLineageError` when manifest horizon does not match expected horizon (observed: manifest `'1c'` vs expected `'5c'`). Source: `arch_competition/lineage.py:29-87` and `arch_competition/eval_runner.py:229-236`. Consequence: `models/arch_competition/` does not exist on this installation because the governed evaluation pass has never successfully produced output. This is why peer-competitor evaluation is not currently operational. Invariants violated: I-10 (reproducible training identity), I-11 (evaluation integrity). Status: PENDING, hard blocker for governed evaluation. Resolve in G3 — unblocks the entire downstream G3-G5 chain.

#### Workstream 2: Infrastructure Governance

Goal: runtime guarantees, system integrity controls, failure containment.

First-class governance gaps. Not secondary, not supporting work. Created from V3 conformance audit findings that did not fit into the model lifecycle phase plan.

| Item | Invariant | Audit row | Urgency | Status |
|------|-----------|-----------|---------|--------|
| INF-1 | I-17 deterministic inference | DOES_NOT_CONFORM_NEW_GAP | HIGH | PENDING |
| INF-2 | I-19 clock synchronization health | DOES_NOT_CONFORM_NEW_GAP | HIGH | PENDING |
| INF-3 | I-20 dependency pinning in serving path | DOES_NOT_CONFORM_NEW_GAP | HIGH | PENDING |
| INF-4 | §14.6 kill switch tri-level halt control | DOES_NOT_CONFORM_NEW_GAP | HIGH | PENDING |

Other 11 NEW_GAP rows (medium urgency) are listed in `governance/V3_CONFORMANCE_AUDIT.md` and will be folded into future phase planning outside Workstream 2 scope (see `governance/PHASE_PLAN_INFRASTRUCTURE.md` §14).

Workstream 2 phase plans: **ACTIVE** — `governance/PHASE_PLAN_INFRASTRUCTURE.md` (INF-1–INF-4 execution, proof, closure, governance events), `governance/PHASE_PLAN_TARGET_STATE.md` (strategic P0–P7 target state and gap map), and reviewer index `governance/INFRASTRUCTURE_GOVERNANCE_LOCK_PACKAGE.md`. Implementation in this workstream must follow those documents per the working discipline (no code without a phase plan).

### Tracked concerns (do not block either workstream)

Findings from G1 investigations recorded for future review. Each is bounded as not blocking, with citation.

- TC-1: Cascade LSTM `xgb_probs_list != ds.n_samples` fallback at `ml_scheduler.py:1010-1024` may silently degrade cascade-LSTM into parallel-LSTM behavior. Frequency unknown without runtime instrumentation. Source: `governance/G1_ADDENDUM_CACHE_CONSISTENCY.md`. Not blocking G2.
- TC-2: `force_retrain` active compliance check at `ml_scheduler.py:1737-1741` runs only when `hz_sched == DEFAULT_ML_HORIZON_SLUG` (1c). Other primary horizons skip it. Promotion-related, not training-related. Source: `governance/G1_ADDENDUM_CACHE_CONSISTENCY.md`. Track for G3 review.

### Deferred items from lock record

- D-1: Regime awareness invariant. Reconciled at the vocabulary level in `governance/INSTITUTIONAL_STANDARD_V3.md` by defining `regime` as a controlled term. Any new regime-aware trade-impacting behavior still requires a governed framework/plan before implementation.
- D-2: Audience separation invariant. Deferred at V3.0 lock per `governance/V3_LOCK_RECORD.md`; reconsider in a future amendment cycle.

### Pre-existing technical debt

- Strict mode option (b) refactor: `ED_XGB_STRICT_ACTIVE_ONLY` defaults to `"1"` in `ml_predict.py:209`. Currently using option (d) wrapper in `ml_scheduler.py` for three candidate-inference sites (committed in 2524770). Coverage gap: `train_all.py:211/216/220`, `transformer_model.py:229`, `features/shared_sequence_context.py:46`, `arch_competition/stack_bundle_eval_v1.py:446`. Proper fix is option (b): thread explicit `strict_active_only` parameter through `_model_dir_for_ticker`, `_load_*`, `_predict_*`. Estimated 4-8 hours, ~140-260 LOC across ~8-12 files. To be addressed after model lifecycle workstream G4 completion.

### Tooling provenance

All commits in this rebuild authored via Cursor agent extension carry a `Made-with: Cursor` trailer in the commit message body. This is hardcoded in the Cursor application bundle (`cursor-agent/dist/main.js`) and cannot be disabled from this repository or from git config. The trailer is treated as known tooling provenance, not silent substitution. Future commits authored through Cursor will continue to carry the trailer.

## Critical — label vs presentation

- [ ] **`outcome_13c` vs product “15m”** — **Partial (2026-03-27):** `outcome_15c` / `pred_15c` columns + fill window + prediction/UI prefer **15×1m** with honest fallback to **13c** when sparse. **Still open:** retire 13c from training/UI after backfill + full retrain; **`outcome_filled` now requires 15c** — very old stuck rows may need one-time DB fix.
- [ ] **`60m` column semantics** — Today may be: MC, fusion, **duplicate 13c empirical**, or legacy **8c** (~8m) depending on code path. Resolve with **single contract**: e.g. **`outcome_60c`** (60×1m) and/or **explicit** “60m = fusion/MC only” with **no** 8c/13c standing in.
- [ ] **8c (~8m) vs product set {1,5,15,60}** — `outcome_8c` / `pred_8c` are **legacy bar counts** in DB and training (`ml_train.HORIZONS`). Either **drop from product surface**, **map to a named role**, or **retire** in favor of **60m** label. Until then: **do not** treat 8c as the long-horizon user story.
- [ ] **Prob grid fallback vs `prediction_engine`** — UI fallback row and disclaimer can describe **8c** while engine path may **reuse 13c** for the “60m” slot when MC/fusion off. **Reconcile** so disclaimer, fallback, and `horizon_prob_bars` **always agree**.

## Stack / training / UI alignment

- [ ] **Four parallel stacks (1 / 5 / 15 / 60)** — Implement **per-horizon** training targets, inference, and stack votes (not one head smeared across mismatched labels). **Retrain** after schema alignment.
- [ ] **Training horizons vs UI** — Add **`15c`** to `ml_train.HORIZONS` (and `audit_model_readiness` XGB pred columns) **when you retrain** so `rules_15c_*` match shipped model feature count; `pred_15c_*` is already persisted from the prediction card for training rows.
- [ ] **Four horizon-specific Call payloads** — Surface **one call per product horizon** (or primary + three secondaries) **after** probabilities/stack votes are **honest per H**. (Useful; depends on items above.)
- [ ] **Candidate inference strictness scope (Option D)** — `ml_scheduler.py` now uses a scoped context manager to set `ED_XGB_STRICT_ACTIVE_ONLY=0` only during candidate-model inference (parallel eval, cascade eval, parallel meta assembly), with guaranteed restore afterward. Keep live serving strict-active-only fail-closed by default; retire this scope helper if candidate prediction stops reusing `ml_predict` active-path resolution.

## MC / fusion behavior (clarity + policy)

- [ ] **Document when MC and fusion are off** — Codify: missing deps, config flag, insufficient samples, warm-up, explicit “empirical-only” mode, failure fallback. Ensure UI **shows mode** (not silent wrong horizon).
- [ ] **Decide default policy** — e.g. **prefer fusion/MC on** when healthy; **never** silently label fallback empirical bars as “60m” if they aren’t.

## Context / data

- [ ] **Index futures** — Env-based (`ED_FUTURES_*`) wired; confirm Schwab contract symbols per roll; optional: auto-roll or admin doc.

## Schwab V4 Universal Coverage (register pipeline)

**Canonical tracker for deferred Schwab register work.** (Scanner walk scope was tightened 2026-05; CI still pins a **partial** mock register — see `governance/artifacts/schwab_v4_register_build_meta.json` `scanner_flags`.)

- [ ] **Full pruned-tree rescan** — Run `python -m tools.schwab_universal_coverage_scanner_v3 --embedding-mode mock` with **no** `--max-files` once there is wall time; commit `governance/artifacts/schwab_v4_register_build_meta.json` + `governance/artifacts/schwab_v4_scoreboard.json` so pins match the **whole** repo under current walk excludes (`tools/schwab_universal_coverage_scanner_v3/paths.py`).
- [ ] **`d17.replaced_count` vs perf_proof** — Reconcile register `REPLACED` rows with `governance/artifacts/perf_proof/replacements/*.json` `register_link` (e.g. 14 vs 12 drift on partial history) on next `server.py` / D17 touch.
- [ ] **Register CSV sunset** — Program-level: move D17 invariants off the universal line-register when a scoped static gate exists; until then CSV stays gitignored (see `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.md`).

---

## Schwab repo-wide replacement — post-KEY LEVELS sweep schedule

**SUPERSEDED 2026-05-16** — day-by-day plan replaced by section-by-section structure below. Completed day commits stay in the branch as a regression safety floor (see CAPS and per-day pattern gates). They do NOT count toward section closure — see 'Why prior commits do NOT count' below.

~~**Bound to:** `governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md`. Each day below closes the cited register IDs with a real on-branch SHA.~~

- [x] **Day 1 — OHLCV / bar adapters** — DFR-009, DFR-011, MT-006, MT-007, PQ-009, PQ-010 + DFR-018 re-audit. Files: `market_data_adapter.py`, `snapshot_normalizer.py`, `liquidity_value_engine.py`. Kill zero-injection; reject incomplete Schwab candles; tag synthetic 1m bars. SHA: `03ca199`
- [x] **Day 1.5 — OHLCV pattern repo-wide** — DFR-009/011/018/MT-006/007/PQ-009/010 repo-wide. Files: `server.py`, `math_levels.py`, `math_exposure_core.py`, `math_probabilities.py`, `news_sentiment.py` + repo-wide grep test. `bucket_metric()` fail-closed; ALLOWLIST for manifest/counter paths. SHA: `17ccf30`
- [x] **Day 1.6 — silent-zero pattern family** — extends Day 1/1.5 to `.get(x) or 0`, `int(x or 0)` variants; `math_levels`/`math_exposure_core` bucket_metric completion; 30+ file allowlist. SHA: `c4825cc`
- [x] **CAPS — comprehensive anti-pattern sweep** — full silent-default family; `tools/anti_pattern_sweep.py`; register allowlist; `lstm_data` zone/vwap sentinels; Schwab chain fail-closed in `math_levels`. SHA: `cab3ef4`
- [x] **Day 2 — Order flow + spread** — DFR-019, PQ-002, PQ-005, PQ-007, PQ-008, PQ-011, PQ-012, PQ-013, OP-015, OP-017. Files: `order_flow_engine.py`, `server.py` VWAP + accumulator + fast-quote spread. RVOL unavailable not 1.0; spread units split; per-bar volume source. SHA: `92b85ff`
- [x] **Day 3 — ML feature provenance** — DFR-012, DFR-013, MT-002, MT-003, MT-005, MT-008, MT-012. Files: `features/inference_snapshot.py`, `features/fusion_model_input.py`, `features/lstm_sequence_input.py`, `ml_data_common.py`, `calibration/v2_advisory_backfill.py`, `tests/test_ml_feature_provenance.py`. Per-field lineage; fusion `unknown`; LSTM masks; `m5_source_timeframe`. SHA: `c527b82`
- [ ] ~~**Day 4 — ML training imputation**~~ — superseded by Section 10
- [ ] ~~**Day 5 — Calibration + replay**~~ — superseded by Section 11
- [ ] ~~**Day 6 — Trader-visible A2 + UI remnants**~~ — superseded by Section 17
- [ ] ~~**Day 7 — Market context + remaining PQ**~~ — superseded by Sections 2–3
- [ ] ~~**Day 8 — Final repo-wide zero-OPEN sweep**~~ — superseded by section closure cert (Section 17)

---

## Schwab Schwab-leaf replacement — section-by-section sweep

**Bound to:** `governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md`.

**CAPS (mandatory every commit):** `tests/test_anti_pattern_family_repo_wide.py` + `tools/anti_pattern_sweep.py` — zero unallowlisted production hits.

**Section rule:** Within each section, every file is walked for derivations with Schwab-leaf equivalents. Each derivation found is replaced + repo-wide-grepped for matching patterns + every repo-wide hit fixed. **One section = one commit** accumulating all that work.

### Why prior commits do NOT count toward section closure

Days 1, 1.5, 2, 3, and CAPS (`cab3ef4`) closed *pattern-shape* regression gates (silent-default substitution patterns). They did NOT perform the section-by-section Schwab-leaf-derivation audit defined here. That audit is: walk every file in the section, identify every derivation, check `schwab_field_inventory/schwab_field_dictionary.csv` for a Schwab leaf equivalent, replace the derivation when a leaf exists, then repo-wide-grep for the same derivation pattern and fix every matching hit found anywhere in the repo.

Files touched by prior commits still need to be re-walked under this method when their section comes up. Specifically:

| Prior commit | Files touched | Sections that must re-walk these files |
|---|---|---|
| Day 1 `03ca199` | `market_data_adapter.py`, `snapshot_normalizer.py`, `liquidity_value_engine.py` | §1, §12 |
| Day 1.5 `17ccf30` | `math_exposure_core.py`, `math_levels.py`, `math_probabilities.py`, `news_sentiment.py`, `server.py` | §2, §4, §16 |
| Day 2 `92b85ff` | `order_flow_engine.py`, `server.py` | §2, §5 |
| Day 3 `c527b82` | `features/inference_snapshot.py`, `features/fusion_model_input.py`, `features/lstm_sequence_input.py`, `ml_data_common.py` | §9, §10 |
| CAPS `cab3ef4` | `lstm_data.py`, `math_levels.py` | §4, §10 |

The pattern-shape regression net from these commits stays in place as a safety floor going forward. It does not substitute for the section-by-section derivation audit.

- [ ] **§1 Schwab client + adapters** — `schwab_client.py`, `reauth_schwab.py`, `websocket_adapter.py`, `polling_adapter.py`, `sse_adapter.py`, `market_data_adapter.py`, `snapshot_normalizer.py`, `snapshot_access.py`. Prior `2703c52`/`d40b537` fixes kept; full-scope AST re-walk `657d4e4` (59 rows). SHA: __________
- [ ] **§2 Server + live state** — `server.py`, `live_market_plane.py`, `live_decision_bundle.py`, `live_pipeline_diag.py`, `live_vs_replay_validation.py`. Prior `06964e5` fixes kept; function-walk re-opened. SHA: __________
- [ ] **§3 Market data + state** — `market_context.py`, `market_state.py`, `math_snapshot_derive.py`. Prior `86d4bc4` fixes kept; function-walk re-opened. SHA: __________
- [ ] **§4 Math / KEY LEVELS** — `math_exposure*.py`, `math_levels.py`, `math_volatility.py`, `math_probabilities.py`, `levels.py`. Prior `4740fa8`/`82615fa` fixes kept; full-scope AST re-walk `657d4e4` (131 rows). SHA: __________
- [ ] **§5 Order flow** — `order_flow_engine.py`, `order_flow_live_state.py`, `order_flow_streaming.py`, `debug_flow_snapshot.py`. SHA: __________
- [ ] **§6 Signals + decision** — `signals.py`, `signal_helpers.py`, `signal_types.py`, `rules_engine.py`, `prediction_engine.py`, `call_engine.py`, `multi_horizon_decision.py`, `multi_horizon_ml_bundle.py`. SHA: __________
- [ ] **§7 V2 decision + A2 lifecycle** — `v2_decision/*.py`, `lifecycle_rule_core.py`. SHA: __________
- [ ] **§8 MC + regime + volatility** — `monte_carlo.py`, `mc_fusion_adjustment.py`, `volatility_regime.py`, `regime_engine.py`. SHA: __________
- [ ] **§9 Features (ML inputs)** — `features/*.py`. SHA: __________
- [ ] **§10 ML training + predict** — `ml_*.py`, `lstm_*.py`, `xgboost_model.py`, `transformer_*.py`, `train_*.py`, `training_*.py`, `normalized_training_sync.py`, `smoke_predict_active.py`. SHA: __________
- [ ] **§11 Calibration + fusion** — `calibration/*.py`, `bayesian_fusion.py`, `governed_stack_contract.py`, `arch_competition/*.py`. SHA: __________
- [ ] **§12 Liquidity** — `liquidity_models.py`, `liquidity_value_engine.py`, `print_liquidity_value_snapshot.py`, `run_liquidity_sample.py`. SHA: __________
- [ ] **§13 Similarity** — `adaptive_similarity_engine.py`, `similarity_*.py`. SHA: __________
- [ ] **§14 DB + backfill + repair** — `db*.py`, `clean_db.py`, `eval_metrics_store.py`, `backfill_*.py`, `bar_rehydration_*.py`, `pin_neutral_outcome_repair_v1.py`, `distance_option_a_backfill_v1.py`, `patch_active_artifact_provenance.py`, `replay_bundle_coverage.py`, `realized_contract_eval.py`. SHA: __________
- [ ] **§15 Audit + verify + config + contracts** — `audit_*.py`, `verify_*.py`, `inspect_trading_data.py`, `config.py`, `setup_readiness.py`, `scheduler_user_tickers.py`, `ticker_*.py`, `production_universe.py`, `instrument_identity.py`, `timeframe_config.py`, `model_contract.py`, `feature_contract_*.py`, `horizon_outcomes.py`, `movement_target_threshold.py`, `institutional_behavior.py`, `canonical_distances.py`, `tier3_design.py`. SHA: __________
- [ ] **§16 External signals** — `news_sentiment.py`, `api_pressure.py`, `event_risk.py`. SHA: __________
- [ ] **§17 Planes + research + UI + misc** — `planes/*.py`, `research/*.py`, `static/*`, `ops_runner.py`, `crash_trace.py`, `schwab_*_inventory*.py`, `schwab_field_dictionary_builder.py`, `micro_structure.py`, `adaptive_shadow_v2_calibration.py`, `print_*.py`, `compare_clustering_modes.py`. SHA: __________

---

## Resolved (archive)

_Move rows here with date + short note when closed._

_(None yet from this list.)_
