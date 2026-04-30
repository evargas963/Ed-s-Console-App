# Open items — horizon, stack, UI consistency

**Rule:** Items stay **open** until there is a merged/code-verified resolution (not just “planned”).  
**Last reviewed:** 2026-03-27

---

## GOVERNANCE REBUILD STATUS

### G1 — Canonical Contract Draft (COMPLETE)

Status: Diagnosis complete. Decisions made.

**Architectural decision:** Parallel and cascade are PEER COMPETITORS. Both must produce a full stack (xgb + lstm + transformer + meta). Governance evaluates the pair and selects a winner.

Evidence:
- run_architecture_pair_evaluation evaluates both side-by-side (arch_competition/eval_runner.py:208-280)
- decide_promotion models incumbent parallel vs challenger cascade (arch_competition/promotion_engine.py:17-19, 60-67)
- manual_promote_to_active_explicit accepts target_architecture parameter (arch_competition/manual_control.py:136-144)
- Scheduler trains both every cycle (ml_scheduler.py:1585-1647)

**Implementation gap:** train_cascade_candidate (ml_scheduler.py:816-1201) does not produce meta_<ticker>_<hz>.pkl. This blocks all cascade promotion.

**Contract authority decision:** A new module governance/artifact_contract.py will become the single source of truth for the artifact contract across all four lifecycle tiers (TRAINED_CANDIDATE, EVALUATABLE_CANDIDATE, PROMOTABLE_CANDIDATE, ACTIVE_SERVING_CANDIDATE). All producers, validators, and tests will import from this module.

### Phase Plan

- G1 Canonical contract draft — COMPLETE
- G2 Cascade alignment — NEXT
- G3 Governed path contract unification — PENDING (depends on G2)
- G4 Direct-write quarantine — PENDING (depends on G3)
- G5 End-to-end proof — PENDING (depends on G2-G4)

### Deferred to G4 (do not address before G2-G3 complete)

**G4-1: Decide fate of server-side active sync helper.**
_sync_missing_binaries_to_active in server.py:4426-4453 copies model files into models/active/ during request handling, env-gated. Decision required: keep, gate harder behind manual governance, or remove. This is a governance bypass currently reachable from a live web request path. Risk class: HIGH.

**G4-2: Quarantine/refactor/prohibit direct-active tool scripts.**
Five tool scripts write directly to models/active/ outside of the manual governance path:
- tools/train_all_movement_heads_v1.py:65-67, 90-103
- tools/train_missing_movement_heads_v1.py:74-76, 110-123
- tools/clone_sibling_dir_heads_v1.py:19, 26, 33
- patch_active_artifact_provenance.py:57-59, 63-70
- (plus manual_control.py which is the sanctioned path — not a violation)
Decision required per tool: keep as exception with audit trail, refactor to use governance, or prohibit. These scripts are how models/active/ has historically been populated; removing them without replacement breaks the actual production workflow.

**G4-3: Change scheduler fail-open behavior to contract-aware failure reporting.**
ml_scheduler.py:1701-1707 catches governed pass exceptions and continues. ml_scheduler.py:2133-2135 catches per-ticker exceptions and continues. ml_scheduler.py:2230-2263 (CLI block) does not propagate failure as non-zero exit code. Result: training can exit 0 while producing zero promotable artifacts. Canonical behavior: contract violation must surface as non-zero exit and explicit per-tier status report.

**G4-4: Disable or remove dormant scheduler auto-copy path.**
ml_scheduler.py:1780-1783 contains _promote_candidate which copies candidate files directly into models/active/. Currently disabled by _scheduler_auto_promote_to_active() returning False (ml_scheduler.py:87-89). Decision required: remove the dormant code, or formalize when it should be reachable. Dormant code creates risk that a future change re-enables a governance bypass.

### Drifts Found in G1 Beyond the Initial Six (for reference)

- Server sync endpoint (server.py:4426-4465) bypasses manual governance — escalated to G4-1.
- Dormant scheduler auto-copy path — escalated to G4-4.
- Active compliance validator (verify_active_models.py:100-152) and runtime fallback (ml_predict.py:1291-1294) have different completeness expectations — to be reconciled in G3.
- Manifest "promotion_decision" field in candidate manifest (training_cache.py:980, 1029) is informational, not authoritative — to be removed or marked non-authoritative in G3.

### Existing Strict-Mode Refactor TO DO (from prior work)

Refactor strict_active_only into explicit parameter passing. Currently using option (d) — ml_scheduler.py wraps three candidate-inference sites with a context manager. Coverage gap identified: train_all.py:211/216/220 and other callers (transformer_model.py:229, features/shared_sequence_context.py:46, arch_competition/stack_bundle_eval_v1.py:446) are not within the wrapper scope. Proper fix is option (b): thread an explicit strict_active_only parameter through _model_dir_for_ticker, _load_xgb, _load_lstm, _load_transformer, _predict_xgb, _predict_lstm, _predict_transformer and all callers. Estimated 4-8 hours, ~140-260 LOC across ~8-12 files. To be addressed after G2-G4. Reference: ml_predict.py:209.

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

---

## Resolved (archive)

_Move rows here with date + short note when closed._

_(None yet from this list.)_
