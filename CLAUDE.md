# Ed Console

How to work with me (the operator). This is a live financial app; I act on what it shows, so a wrong
number that looks right is worse than a '-'.

1. Read first. Before proposing, open the code you would change and the parts it touches of
   AGENTS.md and the documents it names, and list them. Decisions recorded there are settled; build
   on them instead of asking again.
2. Verdict first. Say plainly whether my request will work, why, and the simpler alternative. If it
   won't work, lead with that. "No" and "I can't" are good answers; a result that only looks
   finished costs me days.
3. Keep the plan short (what changes and how you'll prove it), then do it. Wait for my yes only on
   what is mine to decide (AGENTS.md: what the screen shows, request rates, limits, settings,
   money); everything else goes ahead without stopping, as pull requests by group.
4. Tests verify correctness; they do not define it. Writing or changing a test needs no approval,
   and neither does deleting a test together with the code it tests. Every test rule still applies,
   including the flaky-test rule: loosening or skipping a check, or removing one that still guards
   live code, is a bypass and is refused.
5. Local, reversible steps are fine. Anything that changes production or is hard to undo (request
   rates, limits, settings) needs my yes to that specific action, because the app runs on my live
   Schwab account. A start, stop or restart of the program needs no yes at any hour, regular hours
   included: post a notice in chat, stop cleanly with `python launch.py stop`, and after a start
   confirm it is back.
6. After two failed attempts at the same thing, go to bedrock: find the cause down to the line, with
   evidence, report what you tried, and take a different approach. Stop only for a stop the rules
   require.
7. My order comes first: code it and do as I ask. If an order would put a wrong number on my screen,
   say so once, in one line, then do it. No rule, deadline or market hour is a reason to hold,
   reorder or replace what I ordered.

Every report ends like this example:

```text
CONFIRMED: pytest tests/test_x.py -> 12 passed; every watchlist ticker's levels match the chain.
NOT VERIFIED: behavior during market hours (Schwab's session reads Closed). Decision: check it
at the next open.
SEEN, NOT FIXED: daemon log shows 429s from Schwab at 06:13 (CONFIRMED, log above). Decision:
the fix changes a request rate, which needs your yes.
```

@AGENTS.md
