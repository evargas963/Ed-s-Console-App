# One-list reconciliation evidence — 2026-08-22

**ONE-LIST PASS: NOT CLAIMED.** Operator/assistant determines PASS.

Reproduce:

```
git rev-parse HEAD
git rev-parse origin/main
git status --porcelain
python3 -c "from tools.find_it_fix_it_lock import second_work_list_violations; print(second_work_list_violations({'_check_second_list': True}))"
python3 -c "import json; print(json.load(open('reports/one_list_reconciliation_counts.json')))"
```

Exact operator source persisted at
`ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_SOURCE.md`
(no `- [ ]`, no ID/Status/Work table).

Previously described as 1,284 lines. Persisted file line count this write:
**1298**. Every persisted line was classified. Body walk:
**1298** lines. Kinds: {'ADMIN': 3, 'BLANK': 172, 'CONTINUATION': 96, 'TITLE': 1, 'RULE': 5, 'REQ': 900, 'HEADER': 88, 'KNOWN': 30, 'CLOSURE': 3}.

## Required counts

| Quantity | Exact |
|---|---|
| OPERATOR_SOURCE_TOTAL_ATOMIC_REQUIREMENTS | 922 |
| OPERATOR_SOURCE_MAPPED | 922 |
| OPERATOR_SOURCE_EXACT_DUPLICATES | 30 |
| OPERATOR_SOURCE_CURRENT_PASS | 0 |
| OPERATOR_SOURCE_UNRESOLVED | 922 |
| OPERATOR_SOURCE_OMITTED | 0 |
| OLD_MASTER_TOTAL | 175 |
| OLD_MASTER_MAPPED | 175 |
| OTHER_DEBT_UNIQUE_MAPPED | 1281 |
| MASTER_TOTAL_CHECKBOXES | 2358 |
| MASTER_OPEN | 2195 |
| MASTER_CLOSED | 163 |
| ATOMIC_REQUIREMENTS_GROUPED | 0 |
| MATERIAL_REQUIREMENTS_OMITTED | 0 |
| SECOND_ACTIONABLE_LISTS | 0 |

Required identities this write:

- OPERATOR_SOURCE_OMITTED = 0 → True
- OPERATOR_SOURCE_MAPPED = OPERATOR_SOURCE_TOTAL_ATOMIC_REQUIREMENTS → True
- ATOMIC_REQUIREMENTS_GROUPED = 0
- MATERIAL_REQUIREMENTS_OMITTED = 0 → True
- SECOND_ACTIONABLE_LISTS = 0 → True

A5 `Same complete proof battery as A4` and G5 `same proof class as GEX` were
**expanded** into one checkbox per battery leaf. That is the opposite of grouping.

Known-confirmed-defect list lines are EXACT_DUPLICATE of the already-emitted
operator-source atoms (one live checkbox, not two).

## Evidence baseline

- HEAD `d276baf4e20c32f197df10cc7576b4feef141077`
- origin/main `628875ad381c209deb82a9cf0d33058ec0598352`
- branch `cursor/active-writer-truth-lock-264e`
- worktree `/workspace`
- dirty before this write: `True`
- next RTH: 2026-08-24 Monday
- no prior PASS grandfathered onto operator-source atoms (CURRENT_PASS = 0)

## Other-source mapping (not a substitute for the operator source)

| Source | Total | Mapped onto sole master |
|---|---|---|
| OPEN_ITEMS.md @ `aea7dcfd` boxes | 1083 | 1083 (by ID / exact leftover) |
| ACTIVE_PROGRAM.md @ `0e475e29` ID rows | 94 | 94 |
| Older institutional master table lanes @ `0dcdf4da^` | 175 | 175 |
| OPEN RC ids in `governance/root_cause_log.md` | 145 | 145 |
| UNPROVEN/DISPROVED claims in `unproven_register.md` | 6 | 6 |
| TODO/FIXME product leftovers outside lock detectors | 0 | n/a (7 hits are lock-detector comments) |

PA-1..PA-47 is OTHER_DEBT, not the mission board.

## Census

{
  "text_inspected": 2640,
  "historical_inspected": 1475,
  "non_text": 232,
  "live_inspected": 1165,
  "tracked": 2872
}

Tracked files inspected for second lists before historical/evidence-only
disposition. Directories named reports/tests/docs/.claude/.cursor/archive/design_history
were searched, not skipped.

## Second lists

`second_work_list_violations` = []

## Stale-fact reconciliation (requirements retained)

Same-ms L1, absorption producers, legacy OF composite, gamma chain/display,
and shared-root worktree policy remain visible operator-source checkboxes.
Wording keeps the original proof obligation. None deleted because
implementation moved. None self-declared PASS.

## Child REQ closures

Eight derived child `[x]` rows remain. They do not close OF / P2 / LP-01 /
UI / predictive / real-money parents.

# next-rth-ok: 2026-08-24 Monday
# chart-intent-ok: Collect/accrual bank is not Chart Done
# universal-scope-ok: enrolled universe default
