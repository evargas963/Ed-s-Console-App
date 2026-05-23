> **Classification:** Policy Specification | **Scope:** Governance documentation `REBUILD_CONTEXT.md`.

# EdWebConsole Governance Rebuild — Master Context

## Purpose of This Document
This file is the durable handoff document for the governance rebuild effort. It is intended to survive loss of assistant chat history and still restore full project context. If Cursor or ChatGPT conversation history is unavailable, a new reader should be able to use this document as the starting point, then follow referenced code citations and governance documents to continue work safely and consistently.

## System Overview
EdWebConsole is a FastAPI-based 0DTE trading dashboard with SQLite persistence, a model training scheduler, and governed promotion controls. Training is orchestrated through `ml_scheduler.py` (CLI entry), web and serving are hosted through `server.py`, and live model inference paths flow through `signals.py` and `ml_predict.py`. Governance and manual promotion controls are implemented in `arch_competition/manual_control.py` (including explicit promotion/rollback entry points), while architecture evaluation and promotion decision artifacts are produced in `arch_competition` modules.

## The Core Problem
The system currently contains two parallel operational realities: a governance lifecycle defined in code and a separate practical workflow that historically populated `models/active/` outside that lifecycle. The governance path (governed evaluation/promotion artifacts plus manual promotion controls) exists, but on this installation there is no `models/arch_competition/` directory present, which is consistent with no successful governed artifact writes having occurred yet (governed writers create parent directories before writing: `arch_competition/eval_runner.py:365-367`, `arch_competition/promotion_engine.py:275-277`, `arch_competition/scheduler_integration.py:122-124`). In parallel, multiple scripts and runtime helpers can write directly to `models/active/` outside manual governance (documented in `governance/G1_DIAGNOSIS.md` direct-active writer inventory). Also, cascade training does not currently produce `meta_<ticker>_<hz>.pkl` even though the artifact contract requires it (`ml_scheduler.py:816-1201` vs `training_cache.py:904-919`). This is a structural condition to resolve, not a single isolated bug.

## Architectural Decision (G1)
Parallel and cascade are PEER COMPETITORS. Both must produce a full stack (xgb + lstm + transformer + meta). Governance evaluates the pair and selects a winner.

Supporting code evidence:
- `arch_competition/eval_runner.py:208-280` (`run_architecture_pair_evaluation`) evaluates parallel and cascade side-by-side.
- `arch_competition/promotion_engine.py:17-19, 60-67` (`decide_promotion`) models incumbent parallel vs challenger cascade.
- `arch_competition/manual_control.py:136-144` (`manual_promote_to_active_explicit`) accepts `target_architecture`.
- `ml_scheduler.py:1585-1647` scheduler path trains/evaluates both architectures per cycle.

## Contract Authority Decision (G1)
A new module `governance/artifact_contract.py` (planned — pending G2 unpause) is designated as the single source of truth for lifecycle artifact contracts. Producers, validators, and tests will import from this module to avoid duplicated definitions.

Lifecycle tiers:
- `TRAINED_CANDIDATE`: training pipeline reports success
- `EVALUATABLE_CANDIDATE`: governed competition pass can run
- `PROMOTABLE_CANDIDATE`: `manual_promote_to_active_explicit` accepts promotion inputs
- `ACTIVE_SERVING_CANDIDATE`: live runtime can load and serve models

## Phase Plan

| Phase | Title | Status | Deliverable |
|-------|-------|--------|-------------|
| G1 | Canonical Contract Draft | COMPLETE | governance/G1_DIAGNOSIS.md |
| G2 | Cascade Alignment | PAUSED | governance/artifact_contract.py + cascade meta writer |
| G3 | Governed Path Contract Unification | PENDING | reconcile validators with contract |
| G4 | Direct-Write Quarantine | PENDING | block governance bypass paths |
| G5 | End-to-End Proof | PENDING | full lifecycle test for one (ticker, horizon) |

Dependencies: G2 depends on G1. G3 depends on G2. G4 depends on G3. G5 depends on G2-G4 all complete.

## G2 Pause State

As of 2026-05-04, G2 is paused pending the `Framework-ED-Decision-Engine-v2.0` decision. The pause is conditional, not indefinite:

- If the maximum-edge v2.0 architecture is rejected, `governance/G2_PLAN.md` remains valid for the existing parallel/cascade architecture and may resume as written.
- If the maximum-edge v2.0 architecture is adopted, rewrite G2 as `G2.v2` against the new artifact contracts before implementation.
- Do not implement `governance/artifact_contract.py` or the cascade meta writer from the original G2 plan while this pause is active.

## Working Discipline

For every phase:
1. Write phase plan in `governance/G<N>_PLAN.md` before code changes.
2. Implement via Cursor strict execution discipline: complete file delivery, no scope expansion, and `test_centralization.py` pass before delivery.
3. Record completion in `governance/G<N>_RESULT.md`.
4. Update `OPEN_ITEMS.md` with phase status.
5. Triangulate structural decisions across Claude (architect/consultant), Cursor (codebase ground truth), and ChatGPT (independent pressure-test) before finalizing architecture-level changes.

## Deferred Items

The following were identified in G1 and explicitly deferred to G4:

- **G4-1**: Server-side active sync helper (`server.py:4426-4453`) can copy binaries into `models/active/` during request handling (env-gated). Risk class: HIGH.
- **G4-2**: Five direct-active writers outside governance path: `tools/train_all_movement_heads_v1.py`, `tools/train_missing_movement_heads_v1.py`, `tools/clone_sibling_dir_heads_v1.py`, `patch_active_artifact_provenance.py`, and dormant copy logic in `ml_scheduler.py`.
- **G4-3**: Scheduler fail-open behavior at `ml_scheduler.py:1701-1707` and `ml_scheduler.py:2133-2135` continues after exceptions; CLI block `ml_scheduler.py:2230-2263` does not force non-zero exit for contract failures.
- **G4-4**: Dormant scheduler auto-copy path at `ml_scheduler.py:1780-1783` must be removed or explicitly formalized.

## Pre-Existing Technical Debt (from prior work)

- **Strict mode refactor**: `ED_XGB_STRICT_ACTIVE_ONLY` defaults to strict in `ml_predict.py:209`. Live serving requires strict-on behavior; training/evaluation candidate inference requires strict-off behavior in scoped contexts. Current partial workaround is Option (d), a context manager in `ml_scheduler.py` wrapping three candidate-inference sites. Coverage is incomplete: `train_all.py:211/216/220` plus other callers (`transformer_model.py:229`, `features/shared_sequence_context.py:46`, `arch_competition/stack_bundle_eval_v1.py:446`) are outside that wrapper scope. Target long-term correction is Option (b): explicit strictness parameter threading across predict/load/model-dir path. Estimated 4-8 hours, roughly 140-260 LOC. Sequencing: after G2-G4 governance rebuild phases.

## How To Continue This Project

If this file is being used because assistant conversation history was lost:

1. Read this document completely.
2. Read `governance/G1_DIAGNOSIS.md` for detailed evidence and drift findings.
3. Read `OPEN_ITEMS.md` for active task status.
4. Identify the next incomplete phase from the phase plan above.
5. Check for `governance/G<NEXT>_PLAN.md`; if absent, write that plan first before code work.
6. Resume execution from the next incomplete phase under the working discipline defined here.

## File Inventory

```text
governance/
  REBUILD_CONTEXT.md          (this file)
  G1_DIAGNOSIS.md             (full G1 findings)
  G2_PLAN.md                  (when written)
  G2_RESULT.md                (planned — pending G2 unpause)
  artifact_contract.py        (planned — pending G2 unpause; the canonical contract — created in G2)
  ...
OPEN_ITEMS.md                 (live status tracker)
```
