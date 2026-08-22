# One-list reconciliation evidence — 2026-08-22

**ONE-LIST PASS: NOT CLAIMED.** Evidence only.

Reproduce:

```
git rev-parse HEAD
git status --porcelain
python3 -c "from tools.find_it_fix_it_lock import second_work_list_violations, derive_active_obligations; print('second', second_work_list_violations({'_check_second_list': True})); print('rc_auth', derive_active_obligations(open('governance/root_cause_log.md').read()))"
python3 -c "import json; print(json.load(open('reports/one_list_reconciliation_counts.json')))"
```

## Source fidelity

Exact supplied paste persisted at
`ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_SOURCE.md`.

- SOURCE_LINE_COUNT (measured `wc -l` / splitlines) = **2068**
- SOURCE_LINE_COUNT_OPERATOR_ASSERTED = 1284
- SOURCE_CONTENT_MATCH (sha256 vs transcript-4407 extract) = **True**
- SOURCE_HAS_HEADER = False
- SOURCE_HAS_CHECKBOX = False
- SOURCE_SHA256 = `f5e5614bab1d90026346de2595519f0b3e2efacf0e708219644f193ee96d659c`

The operator-asserted 1284 does not equal any measured count of the only
supplied body (2068 physical lines / 1040 nonempty / 1029 paragraphs). The
source was not rewritten or rewrapped to manufacture 1284.

## Required counts

| Quantity | Exact |
|---|---|
| SOURCE_LINE_COUNT | 2068 |
| SOURCE_CONTENT_MATCH | True |
| OPERATOR_ATOMIC_TOTAL | 935 |
| OPERATOR_MAPPED | 935 |
| OPERATOR_OMITTED | 0 |
| OLD_MASTER_TOTAL | 175 |
| OLD_MASTER_MAPPED | 175 |
| OTHER_DEBT_UNIQUE_TOTAL | 1284 |
| OTHER_DEBT_MAPPED | 1284 |
| MASTER_TOTAL | 2362 |
| MASTER_PASS | 0 |
| MASTER_FAIL | 0 |
| MASTER_NOT_PROVEN | 2362 |
| MASTER_UNAVAILABLE | 0 |
| MASTER_NOT_APPLICABLE | 0 |
| MASTER_CHECKED | 0 |
| CHECKED_WITHOUT_CURRENT_EVIDENCE | 0 |
| ATOMIC_REQUIREMENTS_GROUPED | 0 |
| MATERIAL_REQUIREMENTS_OMITTED | 0 |
| SECOND_ACTIONABLE_LISTS | 0 |
| RC_LOG_EXECUTION_AUTHORITY | 0 |
| FINAL_HEAD_SHA | `a26d0dff41bfef38f4494bf4055d653bc947d30f` |
| DIRTY | False |

STATUS sum = 2362 ; equals MASTER_TOTAL = True

A5/G5 batteries remain exploded (one checkbox per leaf). Known-confirmed-defect
source lines are EXACT_DUPLICATE of already-emitted atoms.

No prior `[x]` / DONE / CLOSED / PASS was grandfathered. Every box is
`[ ] STATUS=NOT_PROVEN` until current complete proof exists.

# next-rth-ok: 2026-08-24 Monday
# chart-intent-ok: Collect/accrual bank is not Chart Done; Chart consumer remains
an open P0/CHART_CONSUMER residual on LP-01 / UI parents.
# universal-scope-ok: enrolled universe is the default; SPY-only never closes a parent.
