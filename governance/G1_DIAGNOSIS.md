# G1 Diagnosis — Canonical Contract Drift Report

## Purpose
This document is the durable evidence record for G1 (Canonical Contract Draft). It captures the architectural conclusion, lifecycle contract definitions, drift inventory, strict-mode footprint, and direct-active mutation surface with code citations. Later phases (G2-G5) are expected to cite this file as the proof base for decisions and implementation scope.

## Method
Diagnosis was performed as read-only code inspection across the repository, with independent pressure-testing from multiple assistants and final grounding in current repository state. Findings are anchored to code citations (file path + line numbers) and, where relevant, explicit read-only verification outputs (filesystem and log inspection). No code was modified during diagnosis.

## Architectural Decision: PEER COMPETITORS

Conclusion: parallel and cascade are intended to be **peer competitors**. Governance evaluates both and selects a winner.

Supporting code paths:
1. **Governed evaluation compares both architectures side-by-side**
   - `arch_competition/eval_runner.py:208-280`
2. **Promotion engine models incumbent parallel vs challenger cascade**
   - `arch_competition/promotion_engine.py:17-19`
   - `arch_competition/promotion_engine.py:60-67`
3. **Manual promotion accepts target architecture**
   - `arch_competition/manual_control.py:136-144`
4. **Scheduler trains/evaluates both each cycle**
   - `ml_scheduler.py:1586-1603` (parallel)
   - `ml_scheduler.py:1631-1647` (cascade)

Implementation gap:
- `train_cascade_candidate` does not write `meta_<ticker>_<hz>.pkl`.
- Function range confirms no cascade meta writer:
  - `ml_scheduler.py:816-1201`
- Parallel meta writer exists:
  - `ml_scheduler.py:772-775`

## Lifecycle Tier Contracts

### TRAINED_CANDIDATE

Path templates:
- Parallel candidate dir: `models/parallel/<TICKER>/` (`ml_scheduler.py:1385`)
- Cascade candidate dir: `models/cascade/<TICKER>/` (`ml_scheduler.py:1386`)
- Candidate manifest filename: `scheduler_run_manifest.json` (`training_cache.py:33`, `training_cache.py:870`)

Required artifact name templates (current declared contract):
- `training_cache.py:904-915` (`parallel_artifact_basenames`)
- `training_cache.py:918-919` (`cascade_artifact_basenames` aliases parallel list)

Writers:
- XGB model + meta written by `ml_train.train_ticker`:
  - writer: `ml_train.py:759-761`, `ml_train.py:785-788`
  - called from scheduler:
    - parallel: `ml_scheduler.py:594-601`
    - cascade: `ml_scheduler.py:926-933`
- LSTM model + meta:
  - writer: `lstm_model.py:560-573`
  - called from scheduler:
    - parallel: `ml_scheduler.py:623-646`
    - cascade: `ml_scheduler.py:1014-1038`
- Transformer model + meta:
  - writer: `transformer_train.py:521-536`
  - called from scheduler:
    - parallel: `ml_scheduler.py:666-716`
    - cascade: `ml_scheduler.py:1179-1191`
- Meta model:
  - parallel conditional writer: `ml_scheduler.py:771-775` (condition `len(X_meta) >= 10` at `ml_scheduler.py:771`)
  - cascade: no writer in `ml_scheduler.py:816-1201`
- Candidate manifests:
  - scheduler calls `save_run_manifest`: `ml_scheduler.py:2044-2129`
  - writer function: `training_cache.py:884-888`

Required metadata fields in candidate manifest:
- `training_cache.py:968-1043` (`build_manifest`)

Validators:
- Hash + key-set validator:
  - `training_cache.py:656-681`
- Presence validator:
  - `training_cache.py:922-930`
- Full skip gate uses both:
  - `training_cache.py:698-766`

Failure behavior:
- Current: mostly skip/continue/fail-open at scheduler level (`ml_scheduler.py:1701-1707`, `ml_scheduler.py:2133-2135`).
- Intended (contract): complete artifact set and manifest integrity before declaring trained candidate usable.

#### Parallel vs Cascade side-by-side

| Artifact | Parallel writes? | Cascade writes? | Citation |
|---|---:|---:|---|
| `xgb_<T>_<HZ>.pkl` | Yes | Yes | `ml_train.py:759-761`, calls at `ml_scheduler.py:594-601`, `ml_scheduler.py:926-933` |
| `xgb_<T>_<HZ>_meta.json` | Yes | Yes | `ml_train.py:785-788` |
| `lstm_<T>_<HZ>.pt` | Yes | Yes | `lstm_model.py:560-571` |
| `lstm_<T>_<HZ>_meta.json` | Yes | Yes | `lstm_model.py:572-573` |
| `transformer_<T>_<HZ>.pt` | Yes | Yes | `transformer_train.py:521-534` |
| `transformer_<T>_<HZ>_meta.json` | Yes | Yes | `transformer_train.py:535-536` |
| `meta_<T>_<HZ>.pkl` | Conditional yes | No | parallel `ml_scheduler.py:771-775`; cascade no writer in `ml_scheduler.py:816-1201` |
| `scheduler_run_manifest.json` | Yes | Yes | `ml_scheduler.py:2044-2129`, `training_cache.py:884-888` |

Explicit divergence:
- Declared required set includes meta for both (`training_cache.py:904-919`), but cascade training does not produce it (`ml_scheduler.py:816-1201`).

### EVALUATABLE_CANDIDATE

Required inputs:
- Parallel + cascade `scheduler_run_manifest.json` must exist and align:
  - `arch_competition/lineage.py:42-47`, `arch_competition/lineage.py:49-77`

Required schema/lineage checks:
- Evaluation manifest required keys/schema:
  - `arch_competition/eval_runner.py:35-56`
  - generated + checked at `arch_competition/eval_runner.py:321-361`
- Horizon and lineage parity:
  - `arch_competition/lineage.py:65-73`

Short-circuit / raise / fail-closed conditions:
- Missing manifests / lineage mismatches raise `EvaluationLineageError`:
  - `arch_competition/lineage.py:45-47`, `52-56`, `60-63`, `67-68`, `73`, `76`
- Eval row-count mismatch raises:
  - `arch_competition/eval_runner.py:270-274`
- Missing probability detail raises:
  - `arch_competition/eval_runner.py:62-74`
- Governed pass invocation and schema checks:
  - `arch_competition/scheduler_integration.py:76-113`

Horizon validation source of `'1c'` vs `'5c'` lineage error:
- `arch_competition/lineage.py:70-73` compares manifest horizon to expected horizon.

### PROMOTABLE_CANDIDATE

Required input files:
- Governed artifacts under canonical governed paths:
  - path builders: `arch_competition/scheduler_integration.py:58-63`
  - manual control references: `arch_competition/manual_control.py:155-156`

Required schema versions:
- `validate_persisted_governed_artifacts_or_raise` checks both files and schemas:
  - `arch_competition/scheduler_integration.py:290-310`

Required `promotion_decision.json` content for cascade promotion:
- `promotion_decision == "promote_cascade"`:
  - `arch_competition/manual_control.py:182-183`
- `would_promote_challenger == true`:
  - `arch_competition/manual_control.py:184-185`

Required intent tokens:
- constants:
  - `arch_competition/manual_control.py:33-35`
- enforcement:
  - cascade: `arch_competition/manual_control.py:159-162`
  - parallel: `arch_competition/manual_control.py:164-167`

Additional promotion gates:
- Manifest/record lineage consistency:
  - `arch_competition/manual_control.py:62-71` (validator), called at `175`
- Candidate path canonicalization:
  - `arch_competition/manual_control.py:79-86` (validator), called at `176`
- Candidate manifest lineage revalidation:
  - `arch_competition/manual_control.py:179`

### ACTIVE_SERVING_CANDIDATE

Required directory resolver:
- Strict active-only roots:
  - `ml_predict.py:203-255`
  - candidate roots list `ml_predict.py:218`

Strict mode enforcement:
- strict env default on:
  - `ml_predict.py:209-214`
- fail-closed raise:
  - `ml_predict.py:251-254`

Serving load behavior:
- Meta loader:
  - `ml_predict.py:1023-1033`
- Meta-missing fallback to weighted average:
  - `ml_predict.py:1291-1294`
- Availability/status helpers:
  - `ml_predict.py:1579-1587`
  - `ml_predict.py:1590-1611`

Compliance validator contract:
- `verify_active_models.py` enforces per-primary-horizon triple and metadata/provenance:
  - bundle structure: `verify_active_models.py:62-75`
  - horizon loop: `verify_active_models.py:101`
  - required triple: `verify_active_models.py:108-112`
  - contract/provenance checks: `verify_active_models.py:127-152`

Difference vs runtime:
- Runtime can serve degraded without meta via fallback (`ml_predict.py:1291-1294`), while compliance checker enforces stricter artifact/provenance expectations (`verify_active_models.py:100-152`).

## Drift Inventory

1. **Cascade meta required but not produced**
   - Contract A: `training_cache.py:904-919`
   - Contract B: cascade writer absent `ml_scheduler.py:816-1201`
   - Effect: cascade can be "trained" but not artifact-complete by declared contract.
   - Phase: G2

2. **Governed artifacts written under governed tree, not candidate dirs**
   - Writer location: `arch_competition/scheduler_integration.py:58-63`, writes at `110-113`
   - Effect: checking candidate dirs for governed files yields false negatives.
   - Phase: G3

3. **Promotion completeness vs serving completeness mismatch**
   - Promotion copies whole candidate dir: `arch_competition/manual_control.py:89-93`, `222-223`
   - Runtime tolerates missing meta fallback: `ml_predict.py:1291-1294`
   - Effect: "servable" does not imply "promotable-complete" (or vice versa).
   - Phase: G3

4. **Direct-active scripts bypass governance**
   - Writers listed in Direct-Active inventory section below.
   - Effect: active state can diverge from governed lineage.
   - Phase: G4

5. **Scheduler fail-open behavior**
   - Governed pass exception swallowed: `ml_scheduler.py:1701-1707`
   - Per-ticker exception swallowed: `ml_scheduler.py:2133-2135`
   - CLI does not force non-zero on contract failure paths: `ml_scheduler.py:2230-2263`
   - Effect: process can exit success while promotable outputs are missing.
   - Phase: G4

6. **Strict-mode boundary issue (training/eval vs serving)**
   - Strict default: `ml_predict.py:209`
   - Partial wrapper fix in scheduler only: `ml_scheduler.py:93`, `290`, `422`, `725`
   - Effect: uncovered callers remain outside strict-off scope.
   - Phase: post-G4 strict refactor track

7. **Dormant scheduler auto-copy path contradicts manual-only policy**
   - Manual-only policy function returns false: `ml_scheduler.py:87-89`
   - Dormant copy implementation remains: `ml_scheduler.py:1761-1783`
   - Effect: latent bypass risk if gate toggled.
   - Phase: G4

8. **Server endpoint can mutate active during request handling**
   - Sync helper + copy: `server.py:4426-4453`
   - Called in live request path: `server.py:4465`
   - Effect: active mutation outside manual governance path.
   - Phase: G4

9. **Active compliance validator and runtime serving contract disagree**
   - Compliance strict checks: `verify_active_models.py:100-152`
   - Runtime fallback and partial availability: `ml_predict.py:1291-1294`, `1579-1611`
   - Effect: mixed definitions of "healthy active bundle."
   - Phase: G3

10. **Candidate manifest `promotion_decision` field is informational**
    - Field populated in candidate manifests: `training_cache.py:980`, `1029`
    - Authoritative promotion gates use governed artifacts in `arch_competition`: `arch_competition/manual_control.py:155-156`, `171`
    - Effect: duplicated non-authoritative decision surface.
    - Phase: G3

Additional drift found:
11. **Scheduler docstring/policy vs implementation mismatch**
    - Policy text says scheduler should not write active: `ml_scheduler.py:87-89`
    - Copy logic exists in `_promote_candidate`: `ml_scheduler.py:1780-1783`
    - Phase: G4

## Direct-Active Writer Inventory

1. **Sanctioned governance path**
   - File: `arch_competition/manual_control.py`
   - Lines: `_copy_candidate_to_active` `89-93`; call `222-223`; rollback restore `354-360`
   - Writes: copies candidate/rollback files into active bundle dir.
   - Governance: YES
   - Reachability: manual API/CLI path (`manual_promote_to_active_explicit`)
   - Risk: LOW (intended path)

2. **Dormant scheduler copy path**
   - File: `ml_scheduler.py`
   - Lines: `_promote_candidate` copy `1780-1783`; gate function `87-89`; gate usage `1869`, `1905`
   - Writes: candidate files into active dir.
   - Governance: NO
   - Reachability: currently gated off (`_scheduler_auto_promote_to_active() == False`)
   - Risk: MEDIUM/HIGH latent

3. **Server request-path sync helper**
   - File: `server.py`
   - Lines: helper `4426-4453`; env gate `4428-4431`; call `4465`
   - Writes: missing binaries into `models/active/<ticker>/`.
   - Governance: NO
   - Reachability: web request path, env-gated
   - Risk: HIGH

4. **Direct training tool (movement heads)**
   - File: `tools/train_all_movement_heads_v1.py`
   - Lines: active out_dir `65-67`; train/write call `90-103`
   - Writes: model artifacts into active tree.
   - Governance: NO
   - Reachability: CLI tool
   - Risk: HIGH

5. **Direct training tool (missing movement heads)**
   - File: `tools/train_missing_movement_heads_v1.py`
   - Lines: active out_dir `74-76`; train/write call `110-123`
   - Writes: model artifacts into active tree.
   - Governance: NO
   - Reachability: CLI tool
   - Risk: HIGH

6. **Direct clone utility**
   - File: `tools/clone_sibling_dir_heads_v1.py`
   - Lines: active base `19`; copy `26`; meta write `33`
   - Writes: cloned model + meta into active tree.
   - Governance: NO
   - Reachability: CLI script
   - Risk: HIGH

7. **Direct metadata patcher**
   - File: `patch_active_artifact_provenance.py`
   - Lines: active scope `63-69`; write `57-59`
   - Writes: mutates active meta json files.
   - Governance: NO
   - Reachability: CLI script
   - Risk: MEDIUM/HIGH

No additional active writers were confirmed beyond the seven above in G1 read-only inventory.

## Strict Mode Caller Inventory

Strict source:
- `ml_predict.py:209-214` (`ED_XGB_STRICT_ACTIVE_ONLY` read)
- `ml_predict.py:251-254` strict fail-closed raise
- scheduler Option-d wrapper: `ml_scheduler.py:93-104`

Callers of strict-sensitive functions (`_predict_*`, `_load_*`, `_model_dir_for_ticker`) in runtime code:

1. `ml_scheduler.py:_evaluate_parallel_on_full_rth` (`315`, `319`, `322`)
   - Class: TRAINING_OR_EVAL
   - In strict-off scope: YES (`290`)

2. `ml_scheduler.py:_evaluate_cascade_on_full_rth` (`449`)
   - Class: TRAINING_OR_EVAL
   - In strict-off scope: YES (`422`)

3. `ml_scheduler.py:train_parallel_candidate` meta assembly (`741`, `748`, `753`)
   - Class: TRAINING_OR_EVAL
   - In strict-off scope: YES (`725`)

4. `train_all.py:run_meta` (`143`, calls at `211`, `216`, `220`)
   - Class: TRAINING_OR_EVAL
   - In strict-off scope: NO

5. `transformer_model.py:predict` (`166`, call at `229`)
   - Class: DUAL_USE
   - In strict-off scope: NO

6. `features/shared_sequence_context.py:_max_transformer_seq_len_for_ticker` (`33`, call at `46`)
   - Class: DUAL_USE (serving support utility)
   - In strict-off scope: NO

7. `arch_competition/stack_bundle_eval_v1.py` call to `run_base_models_once` (`446`)
   - Class: TRAINING_OR_EVAL
   - In strict-off scope: NO

8. `signals.py` call to `run_base_models_once` (`368`)
   - Class: LIVE_SERVING
   - In strict-off scope: NO (expected)

9. `ml_predict.py` internal serving/eval helpers:
   - `_model_dir_for_ticker` `203`
   - `_load_xgb` `343` -> `_model_dir_for_ticker` `349`
   - `_predict_xgb` `391` -> `_load_xgb` `406`
   - `_load_lstm` `614` -> `_model_dir_for_ticker` `620`
   - `_predict_lstm` `653` -> `_load_lstm` `664`
   - `_load_transformer` `814` -> `_model_dir_for_ticker` `820`
   - `_predict_transformer` `870` -> `_load_transformer` `882`
   - `run_base_models_once` `1142` calls predictors at `1188`, `1194`, `1203` (LIVE_SERVING)
   - `run_cascade_models_once` `1319` calls predictors at `1395`, `1400`, `1412` (DUAL_USE)
   - `is_available` `1579` uses `_model_dir_for_ticker` `1582` (LIVE_SERVING)
   - `get_model_version` `1590` uses `_model_dir_for_ticker` `1593` (LIVE_SERVING)
   - `get_component_status` `1604` calls `_load_*` at `1607-1609` (LIVE_SERVING)

UNREACHED status cannot be proven from static code alone; runtime tracing would be required.

## Historical Evidence

- Filesystem verification (read-only): `models/arch_competition/` is absent on this installation (glob search under `models` returned no `arch_competition` paths).
- Successful governed writes would create parent directories:
  - `arch_competition/eval_runner.py:365-367`
  - `arch_competition/promotion_engine.py:275-277`
  - `arch_competition/scheduler_integration.py:122-124`
- Benchmark log evidence (read-only): AAPL/5c run invoked governed pass but failed lineage validation with `EvaluationLineageError: manifest horizon '1c' != expected '5c'` (see `benchmark_logs/benchmark_AAPL_5c_postfix_2026-04-30_033946.err`).
- Therefore active population plausibly came from direct-active writers listed in this report (Direct-Active Writer Inventory section), not from completed governed promotion flow.

## Contract Authority Finding

There is no single canonical artifact contract source in current code. Competing authorities:

1. Candidate artifact list authority:
   - `training_cache.py:904-919`
2. Governed artifact persistence/schema authority:
   - `arch_competition/scheduler_integration.py:290-310`
3. Serving resolver strict/path authority:
   - `ml_predict.py:203-255`
4. Active compliance authority:
   - `verify_active_models.py:100-152`

These definitions do not import a shared contract constant/module and can drift independently.

Decision from G1: create `governance/artifact_contract.py` (planned — pending G2 unpause) in G2 as the single source of truth.

## Open Strategic Questions Deferred to G4

G4-1. Server-side active sync helper disposition:
- `server.py:4426-4453` (reachable via `server.py:4465`)

G4-2. Direct-active script policy (exception vs governance-only path):
- `tools/train_all_movement_heads_v1.py:65-67`, `90-103`
- `tools/train_missing_movement_heads_v1.py:74-76`, `110-123`
- `tools/clone_sibling_dir_heads_v1.py:19`, `26`, `33`
- `patch_active_artifact_provenance.py:57-59`, `63-69`

G4-3. Scheduler fail-open and exit semantics:
- `ml_scheduler.py:1701-1707`
- `ml_scheduler.py:2133-2135`
- `ml_scheduler.py:2230-2263`

G4-4. Dormant scheduler auto-copy path:
- `ml_scheduler.py:1780-1783` (gated by `ml_scheduler.py:87-89`)

## Verification Steps That Confirmed Findings

Read-only checks performed in G1:
- Filesystem check: no `models/arch_competition/` path found under repository `models` tree.
- Benchmark log inspection: `benchmark_logs/benchmark_AAPL_5c_postfix_2026-04-30_033946.err` shows governed pass invoked and failed with horizon lineage mismatch (`'1c'` vs expected `'5c'`).
- Code inspection triangulation: independent diagnostic passes converged on the same architecture and drift findings, then citations were re-verified directly against current code lines listed in this file.
