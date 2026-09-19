> **Classification:** Historical Record | **Scope:** Point-in-time audit artifact `docs/_consolidation/restore/POST_RESTORE_VERIFICATION_SUMMARY.md`. (Corrected 2026-09-18, reality-reconciliation audit: this is a pure verification summary tying together the restore batch's other logs, zero prescriptive content — mislabeled "Policy Specification," relabeled to match its sibling `FULL_PRIMARY_HORIZON_AUDIT.md`.)

# Post-Restore Verification Summary

## Pair status counts
- FULLY_LOADABLE: 12
- BASE_ONLY: 38
- BASE_PARTIAL: 6
- UNLOADABLE: 0

## Signal test result counts
- SUCCESS: 18
- EXCEPTION: 0
- TIMEOUT: 0
- attempted combinations: 18

## DB test
- result: SUCCESS
- detail: table_count=14

## Files modified during this run
- count: 0

## Unexpected behavior observed
- Uniform-prior fallback warnings observed in one or more signal tests
