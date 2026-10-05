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
6. Local, reversible steps are fine. No change reaches production without my approval of
   that change, naming what it covers (merge, restart, data); request rates, limits and
   settings are changes too. The app runs on my live Schwab account (AGENTS.md Change control).
7. After two failed attempts at the same thing, stop and report what you tried.
8. If rules conflict: correctness of what I see > my explicit yes > speed.

Claims, labels and verdicts are AGENTS.md's (Shared rules; Enforcement map, "Labels").

Rule 6 is also enforced by machine. A hook (tools/operator_yes_guard.py) puts starting or
stopping the daemon or console, a merge, a push to main, and the database writes its tests
cover (tests/test_operator_yes_guard_v1.py) to me as an Allow/Deny prompt. For database writes
it is not a complete barrier; its known gaps are listed in ENF-20 (ACTIVE_PROGRAM.md).
Writing, changing or deleting a test needs no approval; tests follow AGENTS.md's test rules and
both reviewers check them.
Tell me in chat what it is for before you run it. A CI check (tools/check_fails_before.py) refuses a
pull request that changes product code unless one of its changed tests fails on the old code,
except a pull request that only removes code (the exemption in AGENTS.md "Before writing code").

Every report ends like this example:
  CONFIRMED: pytest tests/test_x.py -> 12 passed; SPY, QQQ, NVDA levels match the chain.
  INDUCED: feed-down absence shown with its reason (tests/test_x.py, feed stopped on purpose).
  HYPOTHESIS: the 06:13 429s came from the chain sweep's bursts (not yet measured).
  NOT_PROVEN: behavior during market hours (market closed); daemon running (last checked 06:21).
  Verdict: NOT_PROVEN (the screen in market hours is not yet checked).

@AGENTS.md
