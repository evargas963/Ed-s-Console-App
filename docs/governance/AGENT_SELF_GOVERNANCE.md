# Agent self-governance (Cursor + Claude)

**Binding for both agents.** Operator sign-off uses the 7-artifact contract. Cursor implements; Claude verifies. Disputes defer to operator.

## Alternation (no drift)

| Rule | Requirement |
|------|-------------|
| **#1** | Track `last_slice_kind`: `AUDIT_LANE` \| `OPEN_ITEM_FIX` \| `CONSOLIDATION` \| `REPO_SWEEP`. State next required slice explicitly. |
| **#2** | No "go next consolidation" appendix unless operator asks. |
| **#14** | New authority modules = `CONSOLIDATION` (not smuggled into audit commits). |

**Default cycle:** `AUDIT_LANE` → `OPEN_ITEM_FIX` (all lane FINDs) → `REPO_SWEEP` (one category) → `OPEN_ITEM_FIX` (sweep FINDs) → repeat.

**Gate B:** No `CONSOLIDATION` until the current audit lane has brief + paired-fix closed.

## Ledger (no third mention)

| Rule | Requirement |
|------|-------------|
| **#3** | Every noted FIND → fix same commit OR `OPEN_ITEMS` row with owner before next slice. |
| **#15** | Report **session-relevant** open count + **full** `OPEN_ITEMS` unchecked count each turn. |

## Sign-off (no rubber stamp)

| Rule | Requirement |
|------|-------------|
| **#4** | Cross-cutting block mandatory in implementation briefs. Refuse sign-off if missing. |
| **#12** | Brief schema: identity → FIND/OBS → cross-cutting → display/freshness. |
| **#7** | Scope disclosure: what was NOT verified (by name). |
| **#16** | Apply the verification matrix (below) to every **touched** file. |

## Verification matrix (rule #16)

For each touched file, check applicable rows:

1. Schwab-first / derivation  
2. Fail-closed numerics (no silent 0 / 0.33 / `"flat"`)  
3. Single-authority (COH-SA + rglob guards)  
4. Time / session / DST (`time_et`)  
5. Fusion / canonical tradability  
6. Coherence audit lanes (full Read queue)  
7. Live vs replay parity  
8. UI honesty / transport / bundle age  
9. Calibration timestamp integrity  
10. Stack integrity / degradation visibility  
11. Magic thresholds → policy table (when in scope)  
12. Regression grep (pattern must not reappear)  
13. Operator scenario tests (when built)  
14. V4 governance gate (register / scanner)  
15. Cross-cutting block in brief  
16. Complete fix vs patch (contract + tests)  
17. `def _f` / `_float_or_none` → `numeric_contract`  
18. **Field-name wire contracts** (producer dict keys = reader keys)  
19. Historical data bias (document; backfill optional)  
20. Process / alternation compliance  

## Adjacent findings (rule #17)

Scope artifact #7 must list adjacent patterns (e.g. grep hits outside slice). Either fold into same `OPEN_ITEM_FIX` (fix-as-we-find) or `OPEN_ITEMS` row before next slice.

## Enforcement (how drift stops)

| Layer | Mechanism |
|-------|-----------|
| **Git** | Commit prefix: `fix(audit-lane-N):`, `fix(open-item):`, `fix(coh-sa):`, `chore(repo-sweep):`, `docs(audit):` only for ledger |
| **Tests** | Repo-wide guards: `tests/test_coh_sa*.py`, `tests/test_fusion_contract.py`, `tests/test_*_l1_equiv*.py`, etc. — **CI must run** `pytest tests/test_coh_sa1_float_consolidation.py tests/test_fusion_contract.py tests/test_inference_snapshot_l1_equiv_contract.py` on every PR |
| **Operator** | 7-artifact verification; refuse docs-only closure for code FINDs |
| **OPEN_ITEMS** | Single backlog; `[x]` only with commit SHA |
| **Pairing** | Audit commit does not close code FINDs; following `OPEN_ITEM_FIX` does |

## Additional rules (recommended)

| Rule | Requirement |
|------|-------------|
| **#18** | Commit tag in message body: `Slice: AUDIT_LANE \| OPEN_ITEM_FIX \| …` |
| **#19** | Docs-only commits cannot close code FINDs (ledger-only ok) |
| **#20** | Any new `dict` mapping between modules: grep consumer keys same turn |
| **#21** | Both agents cite this file path when stating protocol |

## Current authority modules (reference)

- `time_et.py`, `numeric_contract.py`, `fusion_contract.py`, `replay_hold_bars.py`, `position_sizing_policy.py`
