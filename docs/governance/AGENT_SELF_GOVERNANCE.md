> **Classification:** Active Rule Source | **Scope:** Process alternation, sign-off contract, verification matrix.

# Agent self-governance (Cursor + Claude)

**Procedural mechanics only.** Detectable behavior rules → [`AGENTS.md`](../../AGENTS.md). Current program → [`ACTIVE_PROGRAM.md`](../../ACTIVE_PROGRAM.md). Schwab methodology → [`CLAUDE.md`](../../CLAUDE.md).

Operator sign-off: 7-artifact contract. Cursor implements; Claude verifies.

## Alternation

| Rule | Requirement |
|------|-------------|
| **#1** | Track `last_slice_kind`: `AUDIT_LANE` \| `OPEN_ITEM_FIX` \| `CONSOLIDATION` \| `REPO_SWEEP`. State next slice explicitly. |
| **#2** | No "go next consolidation" appendix unless operator asks. |
| **#5–#6** | → moved to AGENTS.md §Posture rules |
| **#14** | New authority modules = `CONSOLIDATION` (not smuggled into audit commits). |

**Default cycle:** `AUDIT_LANE` → `OPEN_ITEM_FIX` → `REPO_SWEEP` → `OPEN_ITEM_FIX` → repeat. **Gate B:** no `CONSOLIDATION` until audit lane brief + paired-fix closed.

## Ledger

| Rule | Requirement |
|------|-------------|
| **#3** | Every FIND → fix same commit OR `OPEN_ITEMS` row with owner before next slice. |
| **#8–#11** | → moved to AGENTS.md §OPEN_ITEMS / §Posture rules |
| **#15** | → moved to AGENTS.md §OPEN_ITEMS rules-of-use |

## Sign-off

| Rule | Requirement |
|------|-------------|
| **#4** | Cross-cutting block mandatory in briefs; refuse sign-off if missing. |
| **#7** | → moved to AGENTS.md §Posture rules (scope disclosure) |
| **#12** | Brief schema: identity → FIND/OBS → cross-cutting → display/freshness. |
| **#13** | → moved to AGENTS.md §Banned patterns |
| **#16** | Apply verification matrix to every **touched** file (Schwab-first, fail-closed numerics, single-authority, time_et, fusion tradability, coherence lanes, live/replay parity, UI honesty, calibration integrity, stack integrity, policy tables, regression guards, operator scenarios, V4 gate, cross-cutting, complete fix, numeric_contract, wire contracts, historical bias, process compliance). |

## Adjacent findings (rule #17)

Scope artifact #7 must list adjacent patterns found by **full Read** of the producer/consumer cone (not pattern-matching search). Either fold into same `OPEN_ITEM_FIX` or `OPEN_ITEMS` row before next slice.

## Enforcement

| Layer | Mechanism |
|-------|-----------|
| **Git** | Prefix: `fix(audit-lane-N):`, `fix(open-item):`, `fix(coh-sa):`, `chore(repo-sweep):`, `docs(audit):` |
| **Tests** | `tests/test_coh_sa*.py`, `tests/test_fusion_contract.py`, `tests/test_inference_snapshot_l1_equiv_contract.py` (local/CI subset) |
| **Operator** | 7-artifact verification; refuse docs-only closure for code FINDs |
| **Pairing** | Audit commit does not close code FINDs; following `OPEN_ITEM_FIX` does |

## Additional rules

| Rule | Requirement |
|------|-------------|
| **#18** | Commit body tag: `Slice: AUDIT_LANE \| OPEN_ITEM_FIX \| …` |
| **#19** | Docs-only commits cannot close code FINDs |
| **#20** | New cross-module dict mapping: **Read all consumers same turn**; producer keys must match reader keys |
| **#21** | Cite `AGENTS.md` + this file when stating protocol |

## Independent verification

| Rule | Requirement |
|------|-------------|
| **#22** | **Independent verification** — each agent **re-Reads at tip** end-to-end; never sign off from the other agent's summary alone (see AGENTS.md §Posture rules). |
| **#23** | Retract sign-off if re-verification surfaces gaps. |
| **#24** | Audit JSON counts must equal enumerated entries; add test when feasible. |
| **#25** | → moved to AGENTS.md §Money-path module roster |
| **#26** | N-site parity: N fixes → ≥ N regression tests (or parametrized). |
| **#27** | Exhaustive verification when operator requires 100% repo discipline. |

**Authority modules (reference):** `time_et.py`, `numeric_contract.py`, `fusion_contract.py`, `replay_hold_bars.py`, `position_sizing_policy.py`.
