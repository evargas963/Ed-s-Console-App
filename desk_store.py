"""Desk fact store — bitemporal, so the Desk tab can be replayed without lying about it.

Every other surface in this console answers "what is true now". The Desk has to answer a
harder question — "what was knowable at 09:15 on Tuesday" — because that is the only form in
which a candidate screen can be judged. A screen scored against facts that arrived after the
decision is not a screen, it is a memoir.

So every row here carries TWO clocks:

  event_time_utc      when the thing happened in the world
  knowledge_time_utc  the first moment WE could have acted on it

They are routinely days apart. MEASURED 2026-07-31 on this repo's own data: FINRA short-volume
rows for event date 2026-07-15 carry `fetched_at` 2026-07-21 13:02:27 — a six-day availability
lag. A study that joined those on event date would be reading the future, and would look
brilliant doing it. Reads therefore filter on knowledge time, never on event time.

Two rules make that guarantee real rather than decorative:

1. A knowledge time is never invented. `put_fact` requires one; there is no default, no
   `or time.time()`, no fallback to the event time. A source that cannot say when we learned
   something does not get a row (RC-68's failure class: a 09:47 capture served at 11:31 as
   current).
2. When a source stamps a naive timestamp with no timezone, we resolve it to the LATEST
   plausible instant rather than the earliest (`_naive_text_to_utc_conservative`). Being wrong
   in that direction costs a few hours of visibility; being wrong the other way silently
   licenses lookahead.
"""
from __future__ import annotations


# RC-274: every read of a nullable column goes through these. `float(x or 0.0)` turns an absent
# measurement into the number zero, and a fact table cannot tell the two apart afterwards.



































# ---------------------------------------------------------------------------
# Materializers — turn tables this repo ALREADY fills into bitemporal facts.
#
# Nothing here invents a knowledge time. Each source is used only because it carries one:
# world_* tables stamp `fetched_at`; price bars close at `bar_end_ts_utc`; chain snapshots
# stamp `ts_utc`. A source without such a stamp is skipped, and says so in the return value.
# ---------------------------------------------------------------------------







































