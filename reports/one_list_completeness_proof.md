# One-list register/RC work-authority neutralization evidence — 2026-08-22

**Not a work list. Zero work authority.** Parent mission remains NOT_PROVEN.
Technical burn-down of master items is not claimed. P0.1 product burn-down was not started.

Reproduce:

```
git rev-parse HEAD
git status --porcelain
python3 -c "from tools.find_it_fix_it_lock import second_work_list_violations, derive_active_obligations, second_authority_prose_violations, five_status_authority_violations, three_iteration_method_pivot_violations, ticker_specific_fix_scope_violations; print(second_work_list_violations({'_check_second_list': True})); print(derive_active_obligations(open('governance/root_cause_log.md').read())); print(second_authority_prose_violations()); print(five_status_authority_violations()); print(three_iteration_method_pivot_violations({})); print(ticker_specific_fix_scope_violations())"
python3 -c "import tools.check_institutional_correctness as C; print(C.check_unproven_register()); print(C.check_open_item_cap()); print(C.unmapped_live_unproven_rows(open('governance/unproven_register.md').read(), open('ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md').read())); print(C.unmapped_open_rc_ids(open('governance/root_cause_log.md').read(), open('ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md').read()))"
python3 -c "import json; print(json.load(open('reports/one_list_reconciliation_counts.json')))"
```

CONTENT_HEAD = `4c2290f2af43778a8b8f58fcc947b890bb0109a5`
origin/main = `628875ad381c209deb82a9cf0d33058ec0598352`
DIRTY (non-reports at generation) = False

## Required counts

| Quantity | Exact |
|---|---|
| TRACKED_FILES_TOTAL | 2878 |
| TEXT_FILES_INSPECTED | 2632 |
| DEBT_BEARING_ARTIFACTS_FOUND | 24 |
| DEBT_CANDIDATES_FOUND | 24 |
| DEBT_CANDIDATES_MAPPED_TO_MASTER | 0 |
| DEBT_CANDIDATES_EXACT_DUPLICATES | 0 |
| DEBT_CANDIDATES_NOT_ACTIONABLE | 24 |
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

## Acceptance (this pass)

| Quantity | Exact |
|---|---|
| SOLE_ACTIONABLE_DEBT_AUTHORITY | MASTER |
| UNPROVEN_REGISTER_WORK_AUTHORITY | 0 |
| UNPROVEN_REGISTER_COMMIT_BLOCK_AUTHORITY | 0 |
| RC_LOG_WORK_AUTHORITY | 0 |
| LEGACY_DUE_DATE_WORK_AUTHORITY | 0 |
| LIVE_UNPROVEN_ROWS_FOUND | 6 |
| LIVE_UNPROVEN_ROWS_MAPPED_TO_MASTER | 6 |
| UNMAPPED_LIVE_UNPROVEN_ROWS | 0 |
| LIVE_RC_WORK_STATE_ROWS_FOUND | 146 |
| UNMAPPED_LIVE_RC_OBLIGATIONS | 0 |
| MASTER_UNRESOLVED_BLOCKS_COMPLETION | YES |
| LEGACY_EVIDENCE_INTEGRITY_CHECKS_MAY_REMAIN | YES |
| SECOND_ACTIONABLE_LISTS | 0 |
| SEMANTIC_SECOND_AUTHORITIES | 0 |
| NEW_GOVERNANCE_FILES | 0 |
| NEGATIVE_CONTROLS_PASS | YES |
| FINAL_WORKTREE_CLEAN | YES |

## Mapping (live UNPROVEN register rows)

| Register claim (abbrev) | Master |
|---|---|
| dealer gamma sign predicts intraday range beyond RV | `OD-1276` |
| wide-chain gamma pin vs close | `OD-1277` |
| single-name +call/−put / prior-night OI | `OD-1278` |
| wall-BREAK follow-through | `OD-1279` |
| four untested display levels (KDS / MAX PAIN / HVP-LVP / NET Γ PEAK) | `OD-1280` |
| exposure-overlay five-factor confluence | `OD-1281` |

Zero live DISPROVED rows. Unique debt was mapped, not deleted.

## Negative controls

Temporary injections only (removed; never left on the branch):

- Future-due UNPROVEN row in `unproven_register.md` does not select or block (`check_unproven_register` / `derive_active_obligations` / `legacy_pointer_selected_work` == []).
- Overdue UNPROVEN row there does not independently block.
- DISPROVED row there does not independently activate work.
- Equivalent unresolved ACTIVE master parent still blocks completion.
- OPEN/ACTIVE RC evidence row does not select work (`derive_active_obligations` == []; `check_open_item_cap` == []).
- Broken RC evidence structure (shallow why-chain) still fails evidence-integrity validation.
- `.cursor` / `.claude` prose saying another queue is binding FAILs `second_authority_prose_violations`.
- Register due-date commit-block prose and RC-status completion-block prose FAIL the same check.

`python3 -m pytest tests/test_find_it_fix_it_lock_v1.py tests/test_requirement_proof_v1.py tests/test_universal_ticker_scope_v1.py tests/test_stop_guard_v1.py tests/test_open_item_law_not_ratchet_v1.py tests/test_log_law_v1.py tests/test_rc_document_without_resolve_v1.py tests/test_five_why_recursive_lock_v1.py tests/test_rehab_plan_v1.py -q` → 151 passed.

# next-rth-ok: 2026-08-24 Monday
# chart-intent-ok: Collect/accrual bank is not Chart Done; Chart consumer remains an open P0/CHART_CONSUMER residual on LP-01 / UI parents.
# universal-scope-ok: enrolled universe is the default; a ticker may expose a defect but must not define the fix scope.
