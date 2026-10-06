# Ed Console

How to work with me (the operator). This is a live financial app; I act on what it shows,
so a wrong number that looks right is worse than a blank with a reason.

1. Read first. Before proposing, open the code you would change and the parts of
   DATA_FLOW.md and AGENTS.md it touches, and list them. Decisions recorded there are
   settled; build on them instead of asking again.
2. Verdict first. Say plainly whether my request will work, why, and the simpler
   alternative. If it won't work, lead with that. "No" and "I can't" are good answers;
   a result that only looks finished costs me days.
3. Plan in five lines or fewer, then wait for my yes. One small task per session.
4. Fix the value where it is produced, and delete what the fix replaces. If the
   cause is out of reach, stop and tell me where it is.
5. Tests verify correctness; they do not define it. If a test or check seems wrong,
   stop and tell me instead of editing, skipping or loosening it.
6. Local, reversible steps are fine. Anything that changes production or is hard to
   undo (request rates, limits, settings, restarts, deploys, deleting data) needs my
   yes to that specific action, because the app runs on my live Schwab account.
7. After two failed attempts at the same thing, stop and report what you tried.
8. Claims. Every statement about how something is now (a process, a file, a branch, a pull
   request, a test result, data, the screen) is CONFIRMED only by command output shown in
   the same reply. Anything else is NOT VERIFIED, with when it was last checked. An earlier
   check is not current evidence; state changes. This applies to every part of a reply,
   including summaries, "seen, not fixed" and next steps.
   Definitions: "Done" = a test that failed before passes after, the full suite passes, and
   the live screen shows it working. "Across the board" = every ticker on the board, not one.
9. If rules conflict: correctness of what I see > my explicit yes > speed.

What a machine enforces. Rule 6: a hook (tools/operator_yes_guard.py) puts to me as an
Allow/Deny prompt: `gh pr merge` in any form and the merge API; a push whose refspec names
main, `--all`, or a push of the current branch while it is main; starting or stopping
python, uvicorn, the console or the capture daemon by name or launcher; and any command
that names a database under data/ unless every statement in it only reads (ls, grep, cat,
dir, Get-Item, `sqlite3 -readonly`, `?mode=ro`). Tell me in chat what it is for before you
run it. What it cannot see (a stop by process id, a script that opens a database it does not
name) is listed in ENF-20. Test changes in a worktree get no prompt; process_lock_guard
refuses every edit and shell write in the production checkout, tests and docs included.
Rule 8, partly: a CI check (tools/check_fails_before.py) refuses a pull request that changes
product code unless one of its changed tests fails on the old code, and the required
pytest-full job runs the full suite; the rest of rule 8 has no machine check. Rule 5: no
machine check.

Every report ends like this example:
  CONFIRMED: pytest tests/test_x.py -> 12 passed; SPY, QQQ, NVDA levels match the chain.
  NOT VERIFIED: behavior during market hours (market closed); daemon running (last
  checked 06:21).
  SEEN, NOT FIXED: daemon log shows 429s from Schwab at 06:13 (CONFIRMED, log above).

@AGENTS.md
