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

Rules 5, 6 and 8 are also enforced by machine. A hook (tools/operator_yes_guard.py) puts
starting or stopping the daemon or console while the market is open (or its session is
unknown), a restart of the machine and a merge to me as an Allow/Deny prompt; tell me in chat
what it is for before you run it. While the market is Closed a clean restart (`python launch.py
stop`, then `start_ed_console.bat`) needs no prompt: post a notice in chat first and confirm
both came back. Killing the daemon or console and a push to main are refused. A change to a test, a
file fix or a new file needs no approval from me. A CI check (tools/check_fails_before.py) refuses a pull request that changes
product code unless one of its changed tests fails on the old code.

Every report ends like this example:
  CONFIRMED: pytest tests/test_x.py -> 12 passed; SPY, QQQ, NVDA levels match the chain.
  NOT VERIFIED: behavior during market hours (market closed); daemon running (last
  checked 06:21).
  SEEN, NOT FIXED: daemon log shows 429s from Schwab at 06:13 (CONFIRMED, log above).

@AGENTS.md
