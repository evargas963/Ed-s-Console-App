> **Classification:** Operational Ledger | **Scope:** Governance register/inventory `ACTIVE_DIRECTORY_WRITER_INVENTORY.md`.

# Active Directory Writer Inventory

**Audit date:** 2026-05-21 (post-PR4 refresh)  
**Slice:** PR1 / P0-0 + PR4 governed auto-promote (`OPEN_ITEM_FIX` — training pipeline automation)  
**Method:** Repo grep for `models/active`, `active_{`, `_replace_active_dir`, `shutil.copy` into active trees; reconciled with `governance/G1_DIAGNOSIS.md` § Direct-Active Writer Inventory.

## Summary

| # | Writer | File | Lines (approx) | Governance | Reachability | Phase action |
|---|--------|------|----------------|------------|--------------|--------------|
| 1 | Governed promote / rollback | `arch_competition/promotion_execution.py` | `execute_promotion_if_eligible`, `governed_active_write_scope` | YES | Scheduler (env-gated), `manual_control` CLI | **PR4 shipped** — sole promotion executor |
| 2 | Manual promote / rollback (thin) | `arch_competition/manual_control.py` | delegates to `promotion_execution` | YES | CLI | Keep; no direct `_copy_candidate_to_active` on scheduler path |
| 3 | Scheduler legacy `_promote_candidate` | `ml_scheduler.py` | — | — | **REMOVED PR4** | Grep guard: `tests/test_no_promote_candidate_in_scheduler.py` |
| 4 | Server request-path sync | `server.py` | ~5156–5197 | NO | `ED_ALLOW_ACTIVE_SYNC=1` on dashboard path | G4-1 quarantine (PR6) |
| 5 | Movement heads train-all | `tools/train_all_movement_heads_v1.py` | out_dir `models/active/{T}/` | NO | CLI | G4-2 candidate-only (PR6) |
| 6 | Movement heads missing | `tools/train_missing_movement_heads_v1.py` | same | NO | CLI | G4-2 |
| 7 | Clone sibling heads | `tools/clone_sibling_dir_heads_v1.py` | copies into active | NO | CLI | G4-2 |
| 8 | Meta provenance patcher | `patch_active_artifact_provenance.py` | mutates active meta JSON | NO | CLI | G4-2 policy |
| 9 | Quarantine scanner | `tools/quarantine_dirty_xgb_artifacts.py` | read-only scan | N/A | CLI audit | No write |
| 10 | Phase11 reconciliation | `tools/run_phase11_artifact_reconciliation_v1.py` | references paths only | N/A | CLI report | No write |

## Read-only / inference (not writers)

- `verify_active_models.py` — compliance read
- `ml_predict.py` — load from active; `_model_dir_for_ticker` (strict mode); `invalidate_model_registry` on reload (PR4)
- `smoke_predict_active.py`, `audit_model_readiness.py` — read/check
- `feature_contracts.py`, `feature_contract_validation.py` — glob scan

## Pre-flip freeze (§3C — PR4.1 harness)

Copy before harness replay (no active write):

```text
models/_preflip_{run_id}/{T}/parallel/  ← models/parallel/{T}/
models/_preflip_{run_id}/{T}/cascade/   ← models/cascade/{T}/
```

Tool: `tools/validate_autopromote_preflip.py` (all horizons, checksums, active-tree verify).

Between freeze-and-capture and verify: **do not** run `ml_scheduler.run_once`, `train_all.py`, or other training against live `models/parallel/` or `models/cascade/`.

## Re-grep before PR5+

```powershell
Select-String -Path *.py,tools\*.py -Pattern "models/active|active_\{|_replace_active_dir|shutil\.copy"
```

Any new writer → update this file before enabling additional automation.
