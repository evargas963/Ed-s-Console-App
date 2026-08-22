# One-list completeness proof — 2026-08-22

**ONE-LIST PASS: NOT CLAIMED.**

Reproduce (same-turn measurement):

```
git show aea7dcfd:OPEN_ITEMS.md | python3 -c "import sys,re; t=sys.stdin.read(); print(len(re.findall(r'(?m)^\\s*[-*]\\s+\\[\\s\\]\\s+', t)), 'unchecked')"
git ls-files | wc -l
python3 -c "from tools.find_it_fix_it_lock import second_work_list_violations; print(second_work_list_violations({'_check_second_list': True}))"
```

Exact operator 1,284-line `ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1` checklist body:
not in this worktree, not in git history, not in this run's transcript, no attachment.
**operator-1284 mapped / total = 0 / 1284** (EXTERNAL_DATA_UNAVAILABLE).
PA-1..PA-47 is not treated as equivalent.

## Required totals

| Quantity | Exact |
|---|---|
| operator-1284 requirements mapped / total | **0 / 1284** (body absent) |
| old institutional-master table rows mapped / total | **175 / 175** |
| OPEN_ITEMS @ `aea7dcfd` boxes mapped / total | **1083 / 1083** |
| ACTIVE_PROGRAM @ `0e475e29` ID rows mapped / total | **94 / 94** |
| other historical `- [ ]` (reports/docs/.claude/design_history) | **26 / 26** |
| tracked files | **2867** |
| tracked text-like searched | **2618** plus `.jsonl` now in the existing scanner |
| live text-like scanned for second lists | **1152** |
| historical evidence searched then left non-authoritative | **1466** |
| vendor skipped | **0** |
| non-text excluded | **249** |
| live queue tables remaining | **0** |
| live unchecked boxes outside the master | **0** |
| material unresolved start (OPEN_ITEMS unchecked boxes) | **997** |
| genuinely new material | **3** (`P0.1-MIXED-ERA-JOIN`, `P2-V02-ORPHAN-PAYLOAD`, `P3-V02-BRANCH-PROTECTION`) |
| materially fixed this run | **0** |
| previously fixed merely reconciled | **2** (`FIND-GAMMA-FULLCHAIN-STRIKES-V1` `[ ]→[x]`; `FIND-GREEK-SANITIZATION-V1` `[~]→[x]`) |
| administrative duplicates removed | **51** (46 unique PA-46/F-alias titles + 5 duplicate RC-id boxes) |
| unresolved end (master unchecked boxes) | **948** |

## Balanced equation (unchecked boxes)

```
START + NEW - MATERIAL_PRODUCT_CLOSED_THIS_RUN - OTHER_LEGITIMATE_DISPOSITIONS = END
997   + 3   - 0                                 - 52                           = 948
```

OTHER_LEGITIMATE_DISPOSITIONS = 52 =

- PREVIOUSLY_CLOSED_RECONCILED_FROM_UNCHECKED: **1** (`FIND-GAMMA-FULLCHAIN-STRIKES-V1`)
- DUPLICATE_ADMIN_UNIQUE_TITLES_REMOVED: **46** (PA-46 Project-A recon process + F-series alias lines already present as `F10`/`F15`/…)
- DUPLICATE_RC_ID_ROWS_REMOVED: **5** (second copies of RC-282/285/297/301/329)

Side ledger (not in the 997): `FIND-GREEK-SANITIZATION-V1` was `[~]` and is now `[x]` — PREVIOUSLY_CLOSED_RECONCILED, not a this-run product fix. Tilde 2→1; checked 84→86.

The prior packet `997 + 3 - 3 - 51 = 946` was wrong: it counted FULLCHAIN+GREEK as this-run material closes and was off by two. Duplicate-queue removal does not satisfy 5:1 material-fix.

## OPEN_ITEMS @ `aea7dcfd` dispositions (1083 / 1083)

- MASTER_ITEM: remaining unchecked boxes that still exist on the sole master (raw 948 includes 3 new)
- CURRENT PASS WITH EVIDENCE: original `[x]` rows retained, plus FULLCHAIN/GREEK current-repo `[x]`
- DUPLICATE/SUBSUMED: 46 PA-46/F-alias titles + 5 duplicate RC-id boxes
- NON-ACTIONABLE WITH JUSTIFICATION: 0 of these 1083 boxes (process boxes are subsumed into one-list law, not discarded as irrelevant)

No unexplained OPEN_ITEMS omission.

## Old institutional master (`0dcdf4da^`, 381 lines, 175 table rows)

- MASTER_ITEM: **79** (open / not_proven / fail / blocked lanes sit on P0–P4 parents)
- CURRENT PASS WITH EVIDENCE: **66** (historical CLOSED_WITH_EVIDENCE / PROVEN)
- NON-ACTIONABLE WITH JUSTIFICATION: **30** (legend, alignment notes, composite status facts that are not independent work)
- DUPLICATE/SUBSUMED: 0 additional after the 79/66 split

Filename `ED_CONSOLE_INSTITUTIONAL_MASTER_CHECKLIST_v0_2.md` never existed in tree.

## Other debt sources

- ACTIVE_PROGRAM ID rows @ `0e475e29`: 63 CURRENT PASS (DONE) + 31 MASTER_ITEM (SEE_MASTER / IN PROGRESS residuals). File is now a pointer stub.
- `.claude/skills/drift-audit/SKILL.md` procedure boxes: NON-ACTIONABLE (audit protocol, not product debt)
- `docs/plans/TRAINING_PIPELINE_AUTOMATION_PLAN.md` host checkboxes: DUPLICATE/SUBSUMED into OPS-OPERABLE-SURFACE-JOB / scheduler residuals on the master
- `governance/design_history/ED_MASTER_DESIGN_CONSOLIDATED.md` leftover ML A/B boxes: DUPLICATE/SUBSUMED into P2/PA training lanes
- `reports/claude_finish_adversarial_audit_v47.md` / `v49.md` leftover boxes: historical evidence; Chart/PreToolUse residuals already on LP-01 / UI parents

## Exclusions (cannot hide actionable work)

| Exclusion | Count | Proof |
|---|---|---|
| `node_modules/` `.venv/` | 0 tracked | `git ls-files` has none |
| Non-text (`.pt` `.pkl` binaries, `.gitkeep`, Playwright stamp, CODEOWNERS, images) | 249 | no text-like suffix; cannot carry an ID/Status/Work table or `- [ ]` queue |
| Historical prefixes after search | 1466 | searched; no live queue table; leftover `- [ ]` classified above |
| Test `assert … "FAIL"` | n/a | lock does not treat the word FAIL as work; control: `test_second_work_list_does_not_treat_test_assert_fail_as_work` |

## Old work-bearing artifacts — final dispositions

| Artifact | Disposition |
|---|---|
| `OPEN_ITEMS.md` | HISTORICAL POINTER |
| `ACTIVE_PROGRAM.md` | HISTORICAL POINTER (tables removed this turn) |
| `governance/root_cause_log.md` | HISTORICAL EVIDENCE |
| `governance/unproven_register.md` | HISTORICAL EVIDENCE |
| `governance/vendor_field_discovery_register.md` | HISTORICAL EVIDENCE (INGEST = PA-5) |
| `governance/requirement_tree.json` | derived parent/child proof IDs only; `comprehensive_checklist=false` |
| `governance/docs/INSTITUTIONAL_MASTER_CHECKLIST.md` | deleted historically; recovered as input; non-authoritative |

## Negative control (existing lock, no new lock)

A second tracked Markdown file with an Operator NOW / `| ID | Status | Work item |` table and no magic marker BLOCKs via `second_work_list_violations`. Unit: `test_second_work_list_flags_queue_table_without_magic_marker`. Live inject/revert is run in the same turn and not committed.
