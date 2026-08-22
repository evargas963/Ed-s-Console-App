# One-list consolidation evidence — 2026-08-22

**Not a work list. Zero work authority.** Parent mission remains NOT_PROVEN.
Technical burn-down of master items is not claimed.

Reproduce:

```
git rev-parse HEAD
git status --porcelain
python3 -c "from tools.find_it_fix_it_lock import second_work_list_violations, derive_active_obligations, collect_outside_master_debt_candidates; print(second_work_list_violations({'_check_second_list': True})); print(derive_active_obligations(open('governance/root_cause_log.md').read())); print(len(collect_outside_master_debt_candidates()))"
python3 -c "import json; print(json.load(open('reports/one_list_reconciliation_counts.json')))"
```

CONTENT_HEAD = `73bdc820de7d348a7550e2a1b45bd0cc21fbf79b`
origin/main = `628875ad381c209deb82a9cf0d33058ec0598352`
DIRTY (non-reports at generation) = False

## Required counts

| Quantity | Exact |
|---|---|
| TRACKED_FILES_TOTAL | 2877 |
| TEXT_FILES_INSPECTED | 2628 |
| DEBT_BEARING_ARTIFACTS_FOUND | 782 |
| DEBT_CANDIDATES_FOUND | 102 |
| DEBT_CANDIDATES_MAPPED_TO_MASTER | 53 |
| DEBT_CANDIDATES_EXACT_DUPLICATES | 0 |
| DEBT_CANDIDATES_NOT_ACTIONABLE | 49 |
| UNMAPPED_LEGITIMATE_DEBT | 0 |
| MASTER_TOTAL | 2370 |
| MASTER_PASS | 0 |
| MASTER_FAIL | 0 |
| MASTER_NOT_PROVEN | 2369 |
| MASTER_UNAVAILABLE | 0 |
| MASTER_NOT_APPLICABLE | 1 |
| MASTER_STATUS_MISSING | 0 |
| SECOND_ACTIONABLE_LISTS | 0 |
| RC_LOG_EXECUTION_AUTHORITY | 0 |
| HIDDEN_DEBT_AUTHORITIES | 0 |
| TICKER_SPECIFIC_FIX_REQUIREMENTS | 0 |
| SYMBOL_SPECIAL_CASE_REMEDIATIONS | 0 |

STATUS sum = 2370 ; equals MASTER_TOTAL = True

## Former actionable-debt files

| File | Disposition |
|---|---|
| `ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md` | MASTER |
| `OPEN_ITEMS.md` | POINTER |
| `ACTIVE_PROGRAM.md` | POINTER |
| `docs/OPEN_ITEMS_OPERATOR_TRUST.md` | HISTORY_ONLY |
| `docs/plans/TRAINING_PIPELINE_AUTOMATION_PLAN.md` | POINTER |
| `governance/root_cause_log.md` | EVIDENCE_ONLY |
| `governance/unproven_register.md` | EVIDENCE_ONLY |
| `governance/vendor_field_discovery_register.md` | EVIDENCE_ONLY |
| `governance/requirement_tree.json` | EVIDENCE_ONLY |
| `governance/design_history/ED_MASTER_DESIGN_CONSOLIDATED.md` | HISTORY_ONLY |
| `ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_SOURCE.md` | HISTORY_ONLY |
| `.claude/skills/drift-audit/SKILL.md` | POINTER |
| `reports/one_list_*` | EVIDENCE_ONLY |

No file is classified as another actionable work authority.

## Negative controls

Injected (tmp fixtures only, then removed): Markdown backlog box; Python TODO; JSON unresolved state; RC OPEN record; JS TODO; differently worded obligation with no TODO/FIXME.

Each was detected by `collect_outside_master_debt_candidates`.

Also proven: an evidence-only report under `reports/` does not become a second list; a historical RC OPEN row cannot activate work (`derive_active_obligations == []`); an unresolved ACTIVE master parent blocks completion.

# next-rth-ok: 2026-08-24 Monday
# chart-intent-ok: Collect/accrual bank is not Chart Done; Chart consumer remains an open P0/CHART_CONSUMER residual on LP-01 / UI parents.
# universal-scope-ok: enrolled universe is the default; a ticker may expose a defect but must not define the fix scope.
