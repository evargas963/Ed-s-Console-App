# One-list authority-repair evidence — 2026-08-22

**Not a work list. Zero work authority.** Parent mission remains NOT_PROVEN.
Technical burn-down of master items is not claimed. P0.1 product burn-down was not started.

Reproduce:

```
git rev-parse HEAD
git status --porcelain
python3 -c "from tools.find_it_fix_it_lock import second_work_list_violations, derive_active_obligations, second_authority_prose_violations, five_status_authority_violations, three_iteration_method_pivot_violations, ticker_specific_fix_scope_violations; print(second_work_list_violations({'_check_second_list': True})); print(derive_active_obligations(open('governance/root_cause_log.md').read())); print(second_authority_prose_violations()); print(five_status_authority_violations()); print(three_iteration_method_pivot_violations({})); print(ticker_specific_fix_scope_violations())"
python3 -c "import json; print(json.load(open('reports/one_list_reconciliation_counts.json')))"
```

CONTENT_HEAD = `bf24b6876558b1c0eded0a3cf3f8de9001328b8c`
origin/main = `628875ad381c209deb82a9cf0d33058ec0598352`
DIRTY (non-reports at generation) = False

## Required counts

| Quantity | Exact |
|---|---|
| TRACKED_FILES_TOTAL | 2878 |
| TEXT_FILES_INSPECTED | 2632 |
| DEBT_BEARING_ARTIFACTS_FOUND | 27 |
| DEBT_CANDIDATES_FOUND | 27 |
| DEBT_CANDIDATES_MAPPED_TO_MASTER | 0 |
| DEBT_CANDIDATES_EXACT_DUPLICATES | 0 |
| DEBT_CANDIDATES_NOT_ACTIONABLE | 27 |
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

Method: `TRACKED_FILES_TOTAL` = `git ls-files | wc -l`. `TEXT_FILES_INSPECTED` = those paths where `tools.find_it_fix_it_lock._is_text_like_work_file` is true. Master statuses = `COUNT` of checkbox lines carrying `STATUS=` on the sole master.

## Authority-repair acceptance

| Quantity | Exact |
|---|---|
| SOLE_ACTIONABLE_DEBT_AUTHORITY | MASTER |
| AGENTS_SECOND_AUTHORITY_REFERENCES | 0 |
| CURSOR_SECOND_AUTHORITY_REFERENCES | 0 |
| CLAUDE_SECOND_AUTHORITY_REFERENCES | 0 |
| RC_LOG_EXECUTION_AUTHORITY | 0 |
| ACTIVE_PROGRAM_EXECUTION_AUTHORITY | 0 |
| OPEN_ITEMS_EXECUTION_AUTHORITY | 0 |
| REQUIREMENT_TREE_EXECUTION_AUTHORITY | 0 |
| SEMANTIC_SECOND_AUTHORITIES | 0 |
| STATUS_VOCABULARY | PASS\|FAIL\|NOT_PROVEN\|UNAVAILABLE\|NOT_APPLICABLE |
| STALE_FOUR_STATUS_AUTHORITIES | 0 |
| TICKER_SPECIFIC_FIX_SCOPE_ALLOWED | 0 |
| UNIVERSAL_INPUT_SEMANTICS_REQUIRED | YES |
| THREE_ITERATION_METHOD_PIVOT_ENFORCED | YES |
| NEW_GOVERNANCE_FILES | 0 |
| NEGATIVE_CONTROLS_PASS | YES |

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

Temporary injections only (removed; never left on the branch):

- `ACTIVE_PROGRAM.md` containing `NEXT` cannot select work (`legacy_pointer_selected_work` / `derive_active_obligations` == []).
- `root_cause_log.md` containing OPEN/ACTIVE cannot select work (`derive_active_obligations` == []).
- `.cursor` / `.claude` prose saying another queue is binding FAILs `second_authority_prose_violations`.
- `AGENTS.md` saying another file is a defect/work authority FAILs the same check.
- An unresolved ACTIVE master parent still blocks completion.
- A ticker-specific implementation fix for a universal defect FAILs; representative ticker tests remain allowed.
- Stale four-status parsing FAILs; five-status parsing PASSes.
- Fourth variation of the same method without a method-pivot FAILs.

`python3 -m pytest tests/test_find_it_fix_it_lock_v1.py tests/test_requirement_proof_v1.py tests/test_universal_ticker_scope_v1.py tests/test_stop_guard_v1.py -q` → 68 passed.

# next-rth-ok: 2026-08-24 Monday
# chart-intent-ok: Collect/accrual bank is not Chart Done; Chart consumer remains an open P0/CHART_CONSUMER residual on LP-01 / UI parents.
# universal-scope-ok: enrolled universe is the default; a ticker may expose a defect but must not define the fix scope.
