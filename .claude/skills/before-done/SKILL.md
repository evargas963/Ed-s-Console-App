---
name: before-done
description: Run before offering a pull request or reporting work done. Runs the checks the required CI jobs run, on the branch's final commit, and shows each one's output.
---

Run each step from the worktree root on the branch's final commit (`git log --oneline -1` first), with
`ED_CI_OFFLINE=1`, `SCHWAB_API_KEY=ci-not-live-placeholder`, `SCHWAB_APP_SECRET=ci-not-live-placeholder`.
Show each command's last lines in the reply. A step that fails stops the list: fix the cause (AGENTS.md
First gate 4), then start again from step 1. After two failed fixes of the same step, go to bedrock,
report what was tried, and take a different approach (CLAUDE.md item 6).

1. `git fetch -q origin && git merge-base --is-ancestor origin/main HEAD` — the branch is current with
   `main` (exit 0). Otherwise merge `origin/main` and start again.
2. `.venv/Scripts/python.exe -P -m ruff check .` and `.venv/Scripts/python.exe -P -m ruff format --check .` — no findings; then
   `.venv/Scripts/python.exe -m compileall -q -x '([\\/](\.venv|venv|node_modules|__pycache__)[\\/])' .`
   — exit 0 (both as the `hardening` job runs them).
3. The full suite on the final commit: the required CI jobs `pytest-full` (Playwright and the full
   pytest, side by side), `pytest-windows` (the same two on Windows as production runs) and `hardening` green, shown
   by `gh pr checks <pr>` on the final commit (operator 2026-10-30: "Yes, CI proves it"). The suites
   run here only while a test is written or a failure is chased: `npm run test:all`, one at a time.
4. `.venv/Scripts/python.exe -m tools.check_one_reader --base origin/main` — exit 0; then
   `.venv/Scripts/python.exe -m tools.check_credential_leak --base origin/main` and
   `.venv/Scripts/python.exe -m tools.check_eol_style_invariant --base origin/main` — exit 0 each.
5. `.venv/Scripts/python.exe -m tools.check_end_to_end --base origin/main` — exit 0; then
   `.venv/Scripts/python.exe tools/check_locks.py --base origin/main` — exit 0; `locks` also runs
   both of them and `tools/check_integrity.py` from the base.
6. The builder's audit (AGENTS.md rule 14): the change read end to end, Schwab to the screen, against
   the First gate; no patch, no second copy, what it replaces deleted.
7. Nothing left running: list each background shell, subagent (`ListAgents`) and process this session
   started (`Get-CimInstance Win32_Process`, newer than the session), and show each one finished or
   stopped. Production is what `tools/operator_yes_guard.py` `_production` says it is; it stops only
   by `python launch.py stop` (`docs/DATA_FLOW.md` §3.1), with a notice in chat (CLAUDE.md item 5).
8. End the report as CLAUDE.md shows: CONFIRMED (each step's output above), NOT VERIFIED, SEEN, NOT
   FIXED — each open item verified, fixed or brought to Ed as a decision (AGENTS.md First gate 5).
   These steps do not check the live screen, which AGENTS.md's "Done" needs: show it, or list it as
   NOT VERIFIED.
