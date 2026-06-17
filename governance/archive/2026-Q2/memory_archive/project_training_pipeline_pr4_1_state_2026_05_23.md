> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: training-pipeline-pr4-1-state-2026-05-23
description: "Session bookmark for training pipeline PR1-PR4.1 — tip cd7d615/8feab6b on feature/institutional-key-levels, 133 commits ahead of origin, pytest 2619 passed, host-enable gate enforceable."
metadata: 
  node_type: memory
  type: project
  originSessionId: 874bcbca-acf8-440e-8edb-59149968cef3
---

Branch: `feature/institutional-key-levels`
Tip: `34daef4` (backup table alignment doc commit) on top of `d40e317` (docs push-ready sync) on top of `cd7d615` (PR4.1 push-review row) on top of `8feab6b` (PR4.1 code)
**Pushed to origin 2026-05-23**: 133-commit stack + docs sync (1c0ec96 → 34daef4). Local and origin in sync at 34daef4.
Last pytest: **2619 passed, 0 failed** at PR4.1 code tip (docs commits after don't change pytest baseline)
Local-only (not staged, intentionally not pushed): `.claude/settings.local.json` (bypass-permissions wildcards), `.claude/scheduled_tasks.lock` (runtime)

**Why:** Closing PR4.1 brings the auto-promote workstream to host-enable-gate readiness. Per [[feedback_no_audit_deferral_across_walks]] and [[feedback_fix_as_we_find_scope_policy]], every PR's verification slice closed adjacent issues in same turn (PR1 anti-pattern + mega4 inventory + file count; PR4.1 preflip §3C harness + rollback/verify tests + guard test rename). The 133-commit stack is reviewed via the per-commit OPEN_ITEMS rows already landed; no separate pre-push review needed.

**How to apply:** When operator references "where are we" or asks about training pipeline state, this is the snapshot. When verifying any new PR on this branch, compare against tip cd7d615 / pytest 2619 baseline.

## PR series committed locally
| PR | Code SHA | OPEN_ITEMS row | Scope |
|---|---|---|---|
| PR1 | 5886ca0 | (in code commit) | Phase 0: G3-R3 lineage sync, G3-R1 bundle contract (`active_bundle_contract.py`), P0-3 ops aggregate (`training_pipeline_status.py`) |
| PR2 | 4375c58 | 6c63054 | Phase 1: outcome enum (`training_outcome.py`), core exit-1 aggregation, P1-6 cache-skip cap |
| PR3 | 2d8208e | 21fd81b | Phase 2: canonical active layout, `scheduler_active_root`, `promote_horizon_bundle_from_candidate`, consolidate tool |
| PR4 | 51e27ce | 4d38743 | Phase 3: env policy, `execute_promotion_if_eligible`, P3-1b governed-write guard, P3-4b verify, P3-9 rollback, P3-10 reload endpoint + batch client, preflip CLI flag |
| PR4.1 | 8feab6b | cd7d615 | Preflip harness §3C hardened (4 horizons, checksums, file-level verify), 3 integration test files, governed-executor guard test rename |

## Inventory counts at tip
- mega4: 88 files / 821 rows (`tests/test_mega4_traceable_audit.py` expected matches)
- mega1: 312 rows (+ `api_internal_reload_models` endpoint)
- Touched new files in PR4: `arch_competition/scheduler_auto_promote_policy.py`, `arch_competition/promotion_execution.py`, `arch_competition/live_model_reload.py`, `tools/validate_autopromote_preflip.py`
- SPY / QQQ / IWM: COMPLIANT all four horizons per `verify_active_models.check_artifact_compliance`

## Host-enable gate (operator-only, not code)
Per plan §3C + `governance/CURSOR_V4_AGENT_BRIEF` + [[feedback_significant_runs_in_operator_powershell]]:
1. Capture: `python tools/validate_autopromote_preflip.py --freeze-and-capture --run-id <id>`
2. Replay (after PR4 path): `python ml_scheduler.py --run-now --preflip-candidate-root models/_preflip_<id> --all-horizons` with `ED_SCHEDULER_AUTO_PROMOTE=1`
3. Validate: `python tools/validate_autopromote_preflip.py --verify --run-id <id>` exit 0
4. Confirm `live_reload.succeeded: true` for promoted tuples in `models/training_report.jsonl` against actual `ED_CONSOLE_RELOAD_URL`
5. Flip env on host: `ED_SCHEDULER_AUTO_PROMOTE=1` with `ED_SCHEDULER_AUTO_PROMOTE_STRICT_CORE_FRESHNESS=0` for baseline week
6. After baseline week: flip to `STRICT_CORE_FRESHNESS=1`

Emergency stop at any time: `ED_DISABLE_AUTO_PROMOTE=1` (panic env wins over enable per `arch_competition/scheduler_auto_promote_policy.py:18-25`).

## Queued separately (not blocking host enable)
- **Phase 3a.1** (triangulation-agreed, separate commit): rename `promotion_decision_record["winner"]` → `scheduler_log_loss_winner` in scheduler/eval-proof artifacts. Diagnostic-only; no production-copy impact.
- **PR5-PR7**: Phase 4 (data quality + pre-train gate wiring), Phase 5 (observability + `/api/training/status`), Phase 6 (hardening + G3/G4 closure).
- **Governance consolidation triangulation** (Round 2 complete, awaiting operator synthesis): AGENTS.md + ACTIVE_PROGRAM.md + `.cursor/rules/00-always.mdc` + slimmed AGENT_SELF_GOVERNANCE.md + memory archive. Phase 0 prerequisites include AGENTS.md auto-load empirical test, lightweight rule-bearing classification, branch decision (push-first vs dedicated branch).

## Push readiness — TRAINING-PIPELINE-PUSH-REVIEW only covers 9 commits, not all 133

**Correction from Claude's 2026-05-23 initial summary (operator caught the error):** TRAINING-PIPELINE-PUSH-REVIEW is the umbrella gate for PR1-PR4.1 training pipeline work only. It does NOT cover the 124 pre-PR1 commits in this branch's unpushed stack.

**Covered by TRAINING-PIPELINE-PUSH-REVIEW (9 commits, push-ready as a batch once umbrella signed off):**
- PR1 code 5886ca0, PR2 code 4375c58 + row 6c63054, PR3 code 2d8208e + row 21fd81b, PR4 code 51e27ce + row 4d38743, PR4.1 code 8feab6b + row cd7d615

**Not covered — need themed push-review walks before full git push (124 commits):**
| Workstream | Approx count | Notes |
|---|---|---|
| STACK-WIRE-0..6c | 32 | Each WIRE-N has its own per-commit OPEN_ITEMS row; no umbrella push-review row exists for the WIRE series as a whole |
| AUDIT_LANE / COH-* / MADA paired fixes | 33 | Per-row sign-off recorded at landing; push-review needs themed walk |
| Mega4 inventory re-audit batches | 16 | Inventory-only; lower-risk batch but still in unpushed stack |
| REPO_SWEEP (EP, magic-thresholds) | 14 | Per-slice sign-off recorded; themed walk for push |
| Big-audit fixes | 4 | Includes critical fixes (O-54 multiplier, realized_contract bars→dict) |
| STACK-VERIFY-CAND | 2 | |
| OPEN_ITEMS doc-only | 6 | Doc commits riding the workstreams above |
| Other (Voice clock, Issue18, governance doc align, gap-audit catches) | 15 | Mixed scope |
| Pre-PR1 immediate setup (`--all-horizons`, verify_active_models.py SyntaxError) | 2 | 2924017, ef9ee58 |

Scan results that remain valid:
- 0 merge commits in the 133-commit stack
- 0 commits with suspect keywords (WIP / draft / tmp / experiment / scratch / fixme / do-not-push / revert)
- Pytest green at tip (2619 passed)

**Conclusion:** The 9 training pipeline commits are ready to push as a batch once operator signs off the umbrella TRAINING-PIPELINE-PUSH-REVIEW gate. The 124 prior commits each landed with their own per-commit reviews via OPEN_ITEMS rows, but a full `git push` of the branch ships them all together — operator must walk the themed batches separately (STACK-WIRE / AUDIT_LANE / REPO_SWEEP / mega4-reaudit / big-audit) before accepting "push entire branch" risk, or push only the training-pipeline tail as a separate operation.

Don't conflate per-commit review (landed) with push-review (operator confidence at push time).

## Push action belongs to Cursor
Per [[feedback_cursor_pushes_not_claude]]: push to `origin/feature/institutional-key-levels` is Cursor's lane via TRAINING-PIPELINE-PUSH-REVIEW gate. Claude verifies tip state at request time, does not push.
