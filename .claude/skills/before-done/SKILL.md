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
2. `.venv/Scripts/python.exe -m ruff check .` and `.venv/Scripts/python.exe -m ruff format --check .` — no findings; then
   `.venv/Scripts/python.exe -m compileall -q -x '([\\/](\.venv|venv|node_modules|__pycache__|models)[\\/])' .`
   — exit 0 (both as the `hardening` job runs them).
3. `ED_PATCH_RECORD=<a scratch folder> npm run test:all -- -p tools.patch_record` — Playwright, then
   the full pytest suite, recording each patch it applies; both counts shown, no failure.
4. `.venv/Scripts/python.exe tools/check_fails_before.py --base origin/main` — exit 0; for a pull
   request that changes product code it prints "proven", naming the end-to-end path test that fails on
   the old code, or, for a change that only removes whole undecorated Python functions or classes and
   the imports only they used, naming the files.
5. `.venv/Scripts/python.exe tools/check_no_new_patches.py --base origin/main --record <that folder>`
   — exit 0; then
   `.venv/Scripts/python.exe tools/check_one_reader.py --base origin/main` — exit 0; then
   `.venv/Scripts/python.exe tools/check_credential_leak.py --base origin/main` and
   `.venv/Scripts/python.exe tools/check_eol_style_invariant.py --base origin/main` — exit 0 each.
6. `.venv/Scripts/python.exe tools/check_end_to_end.py --base origin/main` — exit 0.
7. Four eyes: run the `correctness-reviewer` and `requirements-reviewer` agents on the PR's final
   commit (`git diff origin/main...HEAD`, with the PR description, the operator's task and the output
   of steps 1–6), naming that commit; any commit made after a review gets a new review of both before
   the PR is offered. Show each verdict
   (PASS / FAIL / NOT_PROVEN) and its findings, and put both verdicts in the PR description. A FAIL or
   NOT_PROVEN is fixed or proven, or brought to Ed, before the PR merges; the one NOT_PROVEN a merge
   may carry is the deployed-screen tier its deploy proves (AGENTS.md Authority). Before bringing Ed a
   decision, check AGENTS.md, CLAUDE.md and ACTIVE_PROGRAM.md for a rule or recorded decision that
   answers it; if one does, apply it and cite it. A decision goes to Ed only when none does.
8. Nothing left running: list each background shell, subagent (`ListAgents`) and process this session
   started (`Get-CimInstance Win32_Process`, newer than the session), and show each one finished or
   stopped. Production is what `tools/operator_yes_guard.py` `_production` says it is; it stops only
   by `python launch.py stop` (`docs/DATA_FLOW.md` §3.1), with Ed's yes when CLAUDE.md item 5 says.
9. End the report as CLAUDE.md shows: CONFIRMED (each step's output above), NOT VERIFIED, SEEN, NOT
   FIXED — each open item verified, fixed or brought to Ed as a decision (AGENTS.md First gate 5).
   These steps do not check the live screen, which AGENTS.md's "Done" needs: show it, or list it as
   NOT VERIFIED.
