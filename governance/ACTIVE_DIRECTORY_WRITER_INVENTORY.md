# Active Directory Writer Inventory

**Audit date:** 2026-05-22  
**Slice:** PR1 / P0-0 (`OPEN_ITEM_FIX` — training pipeline automation)  
**Method:** Repo grep for `models/active`, `active_{`, `_replace_active_dir`, `shutil.copy` into active trees; reconciled with `governance/G1_DIAGNOSIS.md` § Direct-Active Writer Inventory.

## Summary

| # | Writer | File | Lines (approx) | Governance | Reachability | Phase action |
|---|--------|------|----------------|------------|--------------|--------------|
| 1 | Manual promote / rollback | `arch_competition/manual_control.py` | `_copy_candidate_to_active`, `_replace_active_dir_from_source` | YES | CLI / future scheduler executor | Shared `execute_promotion_if_eligible` (PR4) |
| 2 | Scheduler `_promote_candidate` | `ml_scheduler.py` | ~1783–1804 | NO (dormant) | Gated off; `_scheduler_auto_promote_to_active()` False | Remove PR4; grep guard test |
| 3 | Server request-path sync | `server.py` | ~5156–5197 | NO | `ED_ALLOW_ACTIVE_SYNC=1` on dashboard path | G4-1 quarantine (PR6) |
| 4 | Movement heads train-all | `tools/train_all_movement_heads_v1.py` | out_dir `models/active/{T}/` | NO | CLI | G4-2 candidate-only (PR6) |
| 5 | Movement heads missing | `tools/train_missing_movement_heads_v1.py` | same | NO | CLI | G4-2 |
| 6 | Clone sibling heads | `tools/clone_sibling_dir_heads_v1.py` | copies into active | NO | CLI | G4-2 |
| 7 | Meta provenance patcher | `patch_active_artifact_provenance.py` | mutates active meta JSON | NO | CLI | G4-2 policy |
| 8 | Quarantine scanner | `tools/quarantine_dirty_xgb_artifacts.py` | read-only scan | N/A | CLI audit | No write |
| 9 | Phase11 reconciliation | `tools/run_phase11_artifact_reconciliation_v1.py` | references paths only | N/A | CLI report | No write |

## Read-only / inference (not writers)

- `verify_active_models.py` — compliance read
- `ml_predict.py` — load from active; `_model_dir_for_ticker` (strict mode)
- `smoke_predict_active.py`, `audit_model_readiness.py` — read/check
- `feature_contracts.py`, `feature_contract_validation.py` — glob scan

## Pre-flip freeze (§3C plan)

Copy before harness replay (no active write):

```text
models/_preflip_{run_id}/{T}/parallel/  ← models/parallel/{T}/
models/_preflip_{run_id}/{T}/cascade/   ← models/cascade/{T}/
```

Between freeze-and-capture and verify: **do not** run `ml_scheduler.run_once`, `train_all.py`, or other training against live `models/parallel/` or `models/cascade/`.

## Re-grep before PR4

```powershell
Select-String -Path *.py,tools\*.py -Pattern "models/active|active_\{|_replace_active_dir|shutil\.copy"
```

Any new writer → update this file before PR4 merge gate.
