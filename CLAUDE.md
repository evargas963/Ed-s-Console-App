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
4. Tests verify correctness; they do not define it. If a test or check seems wrong,
   stop and tell me instead of editing, skipping or loosening it.
5. Local, reversible steps are fine. Anything that changes production or is hard to
   undo (request rates, limits, settings, restarts, deploys, deleting data) needs my
   yes to that specific action, because the app runs on my live Schwab account.
6. After two failed attempts at the same thing, stop and report what you tried.
7. If rules conflict: correctness of what I see > my explicit yes > speed.

Every report ends like this example:
  CONFIRMED: pytest tests/test_x.py -> 12 passed; SPY, QQQ, NVDA levels match the chain.
  NOT VERIFIED: behavior during market hours (market closed); daemon running (last
  checked 06:21).
  SEEN, NOT FIXED: daemon log shows 429s from Schwab at 06:13 (CONFIRMED, log above).

@AGENTS.md
