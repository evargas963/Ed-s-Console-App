# Retired enforced checks

RC-468 (operator right-sizing mandate, 2026-08-24). The delta gate refuses SILENT removal
of an enforced check (RC-391: deleting the check that fails is not paying the debt). Before
this manifest existed it also refused DELIBERATE removal, which made the enforced set
append-only forever - governance could only grow, never be right-sized.

A removal is legal when, and only when, the same delta ships a row here naming the check.
The gate reads this file from the CANDIDATE tree, so the declaration travels with the
removal and review sees the name and the reason in one place. An undeclared removal still
blocks exactly as before. Rows are append-only history; never delete one.

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
