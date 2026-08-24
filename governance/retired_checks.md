# Retired enforced checks

RC-468 (operator right-sizing mandate, 2026-08-24). The delta gate refuses SILENT removal
of an enforced check (RC-391: deleting the check that fails is not paying the debt). Before
this manifest existed it also refused DELIBERATE removal, which made the enforced set
append-only forever - governance could only grow, never be right-sized.

TWO-STEP CONTRACT (operator, 2026-08-24 teardown — closes the self-authorization hole):
a removal is legal when, and only when, a row here naming the check is ALREADY ON MAIN
before the removing delta. Both gates (check_delta_adds_no_debt and the commit seam in
precommit_institutional) read this file from the BASE ref, never the candidate — so a
change can no longer declare a protection retired and spend that declaration in the same
delta. Step 1: an ordinary delta adds the row (nothing removed; the row is plainly
visible in review). Step 2: a later delta removes the check, legalized by the merged
row. An undeclared removal still blocks exactly as before. Rows are append-only
history; never delete one.

Ledger-scale figures quoted in rationales below were measured 2026-08-24 (433 rows, 124
OPEN, 1412 KiB at declaration time; the rounded pre-RC-467 census read 430 / 124 / 1.4MB).
Reproduce: `python -c "import re,pathlib; t=pathlib.Path('governance/root_cause_log.md').read_text(encoding='utf-8'); rows=re.findall(r'^\| (RC-\d+) \| (\w+)',t,re.M); print(len(rows), sum(1 for _,s in rows if s=='OPEN'), len(t)//1024)"`.
The 18-of-39 inert-document figure reproduces with a git grep per governance/*.md name
over *.py, *.yaml, *.mdc, tools/, tests/ and AGENTS.md (zero referencing files = inert).

| check | retired | rationale |
|---|---|---|
| five_why_recursive_lock | 2026-08-24 | grammar police over ledger prose (ROOT tokens, TERMINAL vocabulary, banned-phrase lists); the substance - a five-level why-chain on every row and measured evidence on every CLOSED row - is enforced by root_cause_log, and closures pointing at real code by closed_rows_ship_their_code |
| recursive_five_why_front_loaded | 2026-08-24 | required a co-staged RC row for EVERY staged .py change, so ordinary feature work wrote ~1,400-word defect rows; measured consequence: 430 rows / 1.4MB / 124 OPEN. Defects still require rows (root_cause_log); ordinary work is documented by commits and PRs |
| five_why_reaches_bedrock | 2026-08-24 | regex judgment of chain-ending terminology - machine-forcing a judgment call; chain presence and depth stay enforced by root_cause_log |
| rc_document_without_resolve | 2026-08-24 | resolve-path token on new OPEN rows; backlog growth (the RC-228 defect it targeted) is enforced by open_item_cap, and unfinished same-day rows still block turn end (stop_guard RC-72) |
| log_law | 2026-08-24 | two-homes ledger topology; a third queue describing the same item is enforced by no_governance_duplication, ledger schema by rc_log_rows_keep_schema, epistemic closure by unproven_register |
| plus_player_law | 2026-08-24 | policed the catalog's own registration flags; an enforced check silently demoted or deleted is exactly what the delta gate roster comparison + this manifest now catch (RC-468, negative-controlled) |
| plus_player_cursor_hooks | 2026-08-24 | wiring assertion on .cursor/hooks.json; that file is CODEOWNERS-owned with require_code_owner_reviews and enforce_admins live, so an unwiring cannot merge without operator approval - same protection, machine-forced server-side |
| claude_cursor_guard_parity | 2026-08-24 | wiring assertion across .claude/settings.json + .cursor/hooks.json; both files are CODEOWNERS-owned (same equivalence as plus_player_cursor_hooks) |
| honesty_guard_wired | 2026-08-24 | wiring assertion that honesty_guard.py is registered on Stop; .claude/settings.json is CODEOWNERS-owned (same equivalence); the guard itself stays |
| writer_no_drift | 2026-08-24 | commit-time rail over control-authority files keyed on a session env var - measured: not run by the commit hook (RC-406), abstains in CI (RC-396, no role), fires only in local verification shells. The operator ruled 2026-08-24: authority approval binds at MERGE - CODEOWNERS + require_code_owner_reviews + enforce_admins cover every who-is-in-charge file; quality gates are not authority |
| no_governance_duplication | 2026-08-24 | SIMPLICITY REHAB. A >12-shared-6-letter-words heuristic between two markdown ledgers with a 60-term hand-grown stoplist; its own comments record two false positives and zero true catches - every documented firing was wrong. Ledger shape stays enforced by rc_log_rows_keep_schema; the epistemic ledger by unproven_register. NOTE: the log_law row above cited this check as an equivalence - its surviving equivalences are rc_log_rows_keep_schema + unproven_register (amended here rather than editing the append-only row) |
| checks_are_justified | 2026-08-24 | SIMPLICITY REHAB. Docstring-shape policing of the gate file against itself with a frozen grandfather set - regulates prose in tools/check_institutional_correctness.py, no product defect class. A NEW check that misbehaves is blocked by the delta gate regardless of its docstring; PR review reads docstrings |
| rc_citations_resolve | 2026-08-24 | SIMPLICITY REHAB T2-2. same file, one validator — substance folded into root_cause_log, which now runs rc_citations_resolve's validation as _rc_citations_resolve_violations |
| rc_status_vocabulary | 2026-08-24 | SIMPLICITY REHAB T2-2. same file, one validator — substance folded into root_cause_log, which now runs rc_status_vocabulary's validation as _rc_status_vocabulary_violations |
| rc_log_rows_keep_schema | 2026-08-24 | SIMPLICITY REHAB T2-2. same file, one validator — substance folded into root_cause_log, which now runs rc_log_rows_keep_schema's validation as _rc_log_rows_keep_schema_violations |
| rc_numeric_claims_cite_a_command | 2026-08-24 | SIMPLICITY REHAB T2-2. same file, one validator — substance folded into root_cause_log, which now runs rc_numeric_claims_cite_a_command's validation as _rc_numeric_claims_cite_a_command_violations |
| rc_mechanism_claims_cite_a_source | 2026-08-24 | SIMPLICITY REHAB T2-2. same file, one validator — substance folded into root_cause_log, which now runs rc_mechanism_claims_cite_a_source's validation as _rc_mechanism_claims_cite_a_source_violations |
| root_cause_recurrence_declared | 2026-08-24 | SIMPLICITY REHAB T2-2. same file, one validator — substance folded into root_cause_log, which now runs root_cause_recurrence_declared's validation as _root_cause_recurrence_declared_violations |
| fix_crosswalks_to_violated_lock | 2026-08-24 | SIMPLICITY REHAB T2-2. same file, one validator — substance folded into root_cause_log, which now runs fix_crosswalks_to_violated_lock's validation as _fix_crosswalks_to_violated_lock_violations |
| closed_rows_ship_their_code | 2026-08-24 | SIMPLICITY REHAB T2-2. same file, one validator — substance folded into root_cause_log, which now runs closed_rows_ship_their_code's validation as _closed_rows_ship_their_code_violations |
| adversarial_audits_are_answered | 2026-08-24 | SIMPLICITY REHAB T2-2. same file, one validator — substance folded into root_cause_log, which now runs adversarial_audits_are_answered's validation as _adversarial_audits_are_answered_violations |
| verdicts_declare_their_power | 2026-08-24 | SIMPLICITY REHAB T2-3. same file, one validator — substance folded into measured_claims_cite_evidence, which now runs verdicts_declare_their_power's validation as _verdicts_declare_their_power_violations |
| unproven_register | 2026-08-24 | SIMPLICITY REHAB T2-3. same file, one validator — substance folded into measured_claims_cite_evidence, which now runs unproven_register's validation as _unproven_register_violations |
| find_it_fix_it | 2026-08-24 | ARCHITECTURE TEARDOWN (operator, 2026-08-24 evening): the ledger+gate framework built around the fix-what-you-find principle was itself overbuilt governance. The PRINCIPLE survives as a plain instruction in AGENTS.md; enforcement is operator review in session + required CI (pytest-full, hardening) at merge. governance/active_defects.json is deleted with it |
| research_before_act | 2026-08-24 | ARCHITECTURE TEARDOWN. Commit-time policing of a research-artifact token in a per-turn scratch log; measured abstaining in CI by construction (RC-396) and fabricating findings on clean checkouts (PR #127). Research-then-act survives as instruction; operator review in session + CI at merge |
| adversarial_audit_test_lock | 2026-08-24 | ARCHITECTURE TEARDOWN. Required every fix to co-ship a named locking test — mandate-to-mechanism machinery that overlaps ordinary engineering hygiene the operator reviews in session; CI (pytest-full) remains the regression authority |
| agents_laws_name_their_enforcer | 2026-08-24 | ARCHITECTURE TEARDOWN. Forced every bold AGENTS.md law heading to name a mechanical enforcer — the exact governance-regrowth recipe the operator ordered removed ("law/mandate/non-negotiable requires a lock" rebuilds the sprawl). Laws are instructions; the charter is prose the operator owns |
| enforced_checks_have_negative_controls | 2026-08-24 | ARCHITECTURE TEARDOWN. Substring name-presence proxy over a concatenated tests corpus (its own docstring conceded it proves nothing about injection); the actual negative controls run in required CI, and enforced-check removal is blocked by the delta gate + this manifest (base-side, two-step) |

TEARDOWN NOTES (2026-08-24, appended — rows above are append-only history):
- Rows at lines 32-35 cite `require_code_owner_reviews`/`enforce_admins` as live equivalences; SUPERSEDED by RC-475 (operator ruling): the review requirement was removed by the operator, and the operator's conversational GO is the approval channel. The surviving machine gate at merge is required CI (pytest-full + hardening).
- Rows citing CODEOWNERS ownership as an equivalence (lines 32-34): CODEOWNERS is removed with the Architecture A authority model; those equivalences now rest on the operator's conversational control of each session plus required CI.
- fix_crosswalks_to_violated_lock (line 44): the folded validator `_fix_crosswalks_to_violated_lock_violations` was REMOVED ENTIRELY in the 2026-08-24 teardown, not merely folded — it required every fix row to name a violated lock plus a "TIGHTENED:" statement, which is the mandate-to-mechanism regrowth recipe the operator ordered out. Fix rows still require the five-why chain, measured evidence, and shipped code (root_cause_log).
