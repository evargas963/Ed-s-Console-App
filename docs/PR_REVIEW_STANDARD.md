> **Classification:** Policy | **Scope:** PR review — operator trust and closure

# PR review standard

A PR is **not merge-ready** if its final report contains passive **known remaining risks** without one of:

- `FIXED_IN_THIS_PR`
- `VALIDATED_IN_THIS_PR`
- `BLOCKED_BY_RTH_WITH_RUNNABLE_VALIDATION_HARNESS`
- `COMPLETION_BRANCH_REQUIRED` + named owner branch
- `ACCEPTED_WITH_EVIDENCE` + evidence cite

## Required answers (every PR)

| Question | Required |
|----------|----------|
| What changed? | Files + behavior |
| What did not change? | Model, fusion, histogram, card direction, thresholds |
| What proof was run? | Commands + exit codes |
| What failed? | CI jobs + logs |
| What was bypassed? | Admin bypass register entry if any |
| What risks remain? | `docs/OPEN_ITEMS_OPERATOR_TRUST.md` item ids |
| Where are risks tracked? | Ledger row + owner branch |
| What evidence closes them? | Harness, RTH run, or fix branch |

## Review evidence rule

Before merge recommendation, provide **actual report sections or file excerpts** — not summary-only.

## Admin bypass

`--admin` or merge with failed checks requires `docs/ADMIN_BYPASS_REGISTER.md` entry with closure criteria and follow-up branch.

## Card explainability gate

`fix/card-price-conflict-explainability` is blocked until `governance/OPERATOR_TRUST_STABILIZATION_GATE.json` status is `PASS`.
