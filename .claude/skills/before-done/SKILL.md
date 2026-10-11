---
name: before-done
description: Run before offering a pull request or reporting work done. Runs the checks the required CI jobs run, on the branch's final commit, and shows each one's output.
---

Run each step from the worktree root on the branch's final commit (`git log --oneline -1` first), with
`ED_CI_OFFLINE=1`, `SCHWAB_API_KEY=ci-not-live-placeholder`, `SCHWAB_APP_SECRET=ci-not-live-placeholder`.
Show each command's last lines in the reply. A step that fails stops the list: fix the cause (AGENTS.md
First gate 4), then start again from step 1.

1. `git fetch -q origin && git merge-base --is-ancestor origin/main HEAD` — the branch is current with
   `main` (exit 0). Otherwise merge `origin/main` and start again.
2. `.venv/Scripts/python.exe -m ruff check . --select F401,F821,E9` — no findings.
3. `npm run test:all` — Playwright, then the full pytest suite; both counts shown, no failure.
4. `.venv/Scripts/python.exe tools/check_fails_before.py --base origin/main` — "proven", naming the
   test that fails on the old code (a pull request that changes product code).
5. `.venv/Scripts/python.exe tools/check_no_new_patches.py --base origin/main` — exit 0.
6. Write the PR description to a file, then
   `.venv/Scripts/python.exe tools/check_end_to_end.py --base origin/main --body-file <file>` — exit 0.
7. Four eyes: run the `correctness-reviewer` and `requirements-reviewer` agents on the PR's final diff
   (`git diff origin/main...HEAD`, with the PR description, the operator's task and the output of
   steps 1–6). Show each verdict
   (PASS / FAIL / NOT_PROVEN) and its findings, and put both verdicts in the PR description. A FAIL is
   fixed or brought to Ed before the PR is offered.
8. End the report as CLAUDE.md shows: CONFIRMED (each step's output above), NOT VERIFIED, SEEN, NOT
   FIXED — each open item verified, fixed or brought to Ed as a decision (AGENTS.md First gate 5).
   These steps do not check the live screen, which AGENTS.md's "Done" needs: show it, or list it as
   NOT VERIFIED.
