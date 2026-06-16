# Repo hygiene policy

**Scope:** Phase 3I — progressive repo cleanup discipline. Inventory-first; no reckless mass deletion.

**Status:** Active policy | **Mechanical lock:** `tools/check_repo_hygiene_policy.py`

## Goal

Make the repo **progressively cleaner** as we touch files — smaller, less stale, less confusing — without breaking reproducibility or evidence artifacts.

## Categories (inventory)

| Category | Meaning |
|----------|---------|
| `active_runtime` | Live production path |
| `active_test` | Paired pytest / test harness |
| `active_governance` | Binding governance source |
| `generated_artifact` | Built evidence (may not be imported) |
| `historical_artifact` | Archive / superseded evidence |
| `deprecated_candidate` | Likely superseded — review before action |
| `orphan_candidate` | Weak or zero references |
| `duplicate_candidate` | Same basename / overlapping role |
| `dead_code_candidate` | Python with zero importers (conservative) |
| `manual_review_required` | Uncertain — human Read required |
| `safe_to_remove` | **Rare** — only with removal proof in backlog |

Generated governance artifacts are **not** dead code just because nothing imports them.

## Clean as we touch `[PROMOTED]`

When modifying a file or module:

1. **Read** adjacent stale/dead/duplicate code in the same cone.
2. If cleanup is **safe and testable** → clean in the **same commit** and cite `HYGIENE: cleaned` in the commit message.
3. If cleanup is **unsafe or uncertain** → record `HYGIENE: deferred_with_reason` or `HYGIENE: manual_review_required` in the commit message and update the backlog.

The mechanical lock fails commits that touch paths intersecting **actionable** open backlog items (`orphan_candidate`, `dead_code_candidate`, `duplicate_candidate`, `deprecated_candidate`) without one of those HYGIENE dispositions. Generic `manual_review_required` inventory rows (12k+ weak-reference files) are **not** in the backlog and do **not** trigger the gate.

## Safe deletion policy

A file may only move to `safe_to_remove` when **all** hold:

- Not referenced by runtime, tests, governance artifacts, docs, CI/pre-commit/audit
- Not a historical evidence artifact or migration/safety script
- Not required for reproducibility
- Backlog row with `status: removal_proven` and paired test/checker proof

Otherwise: `manual_review_required`.

## Artifacts

| Artifact | Command |
|----------|---------|
| Inventory | `python tools/build_repo_hygiene_inventory.py` |
| Backlog JSON | (same builder) |
| Backlog MD | `governance/docs/REPO_HYGIENE_BACKLOG.md` |

## What this phase does **not** do

- Mass-delete files from static analysis alone
- Remove checks because they are slow
- Inflate maturity claims
