# Ed Console

How to work with me (the operator). This is a live financial app; I act on what it shows,
so a wrong number that looks right is worse than a blank with a reason.

1. Read first. Before proposing, open the code you would change and the parts it touches of
   AGENTS.md and the documents it names, and list them. Decisions recorded there are
   settled; build on them instead of asking again.
2. Verdict first. Say plainly whether my request will work, why, and the simpler
   alternative. If it won't work, lead with that. "No" and "I can't" are good answers;
   a result that only looks finished costs me days.
3. Keep the plan short (what changes and how you'll prove it), then wait for my yes.
   My yes covers every file fix inside that task; ask again only for work outside the plan.
   A new file needs no approval.
   One small task per session.
4. Tests verify correctness; they do not define it. Writing or changing a test needs no
   approval, and neither does deleting a test together with the code it tests. Every test
   rule still applies, including the flaky-test rule: loosening or skipping a check, or
   removing one that still guards live code, is a bypass and is refused.
5. Local, reversible steps are fine. Anything that changes production or is hard to
   undo (request rates, limits, settings) needs my yes to that specific action, because
   the app runs on my live Schwab account. A daemon or console start, stop or restart
   outside regular hours (the session tools/operator_yes_guard.py reads from Schwab's
   /markets answer) needs no yes: post a notice in chat, stop cleanly, and after a start
   confirm both are back. During regular hours or an unknown session, it asks.
6. After two failed attempts at the same thing, stop and report what you tried.
7. If rules conflict: correctness of what I see > my explicit yes > speed.

Every report ends like this example:
  CONFIRMED: pytest tests/test_x.py -> 12 passed; every watchlist ticker's levels match the chain.
  NOT VERIFIED: behavior during market hours (Schwab's session reads Closed). Decision: check it
  at the next open.
  SEEN, NOT FIXED: daemon log shows 429s from Schwab at 06:13 (CONFIRMED, log above). Decision:
  the fix changes a request rate, which needs your yes.

@AGENTS.md
