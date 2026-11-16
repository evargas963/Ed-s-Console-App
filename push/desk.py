"""The `desk` panel: the Trade Desk's attention queue, one item per event, newest first.

Read from State: the recorded level crosses (state.cross_store), the terrain panel at the live
price (push.terrain) and the book's size walls (push.book).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from numeric_contract import price_text
from push.book import order_flow_microstructure
from push.terrain import terrain
from push.verdict import LEVELS_STALE
from state import cross_store
from time_et import ct_label, last_open

#: a cross's direction as the queue words it
_CROSS_WORD = {"up": "above", "down": "below"}

#: The Trade Desk's lookback per chart timeframe: seconds, or "session" (the latest regular
#: session), with the words the page shows for it.
DESK_LOOKBACK = {
    "1": (900, "last 15 min"),
    "3": (1800, "last 30 min"),
    "5": ("session", "this session"),
    "15": (14400, "last 4 h"),
    "30": ("session", "this session"),
    "60": (172800, "last 2 days"),
    "D": (1728000, "last 20 days"),
}

#: the chart draws the newest cross at each level, for the newest this-many levels (the queue
#: lists every cross)
DESK_MARKERS = 6


def _desk_window_start(tf: str, now: datetime) -> float:
    """Start of the Trade Desk's event window for chart timeframe `tf`.

    `now` minus its lookback, or the open of the latest regular session that has begun (Schwab's
    /markets, time_et.last_open).
    """
    lb = DESK_LOOKBACK[tf][0]
    if lb != "session":
        return now.timestamp() - lb
    start = last_open(now)
    if start is None:
        raise ValueError(
            f"Schwab's /markets has sent no regular session that began by {now.isoformat()}"
        )
    return start.timestamp()


def desk_events_payload(tk: str, venue: str, tf: str, now: datetime) -> dict[str, Any]:
    """Return the Trade Desk's attention queue at `now`.

    Level crosses in the timeframe's window as recorded (level, direction, price, spot, time),
    numbered oldest first, the newest cross at each level for the newest DESK_MARKERS levels
    flagged for the chart; wall breaches and stale levels from the terrain; the book's size walls
    at the book's own time -- newest first, an item with no time last -- plus the window's up/down
    cross counts. One item is one event: the chart's marker and the queue's entry are the same
    item. The page draws it; it selects, numbers and orders nothing.
    """
    start = _desk_window_start(tf, now)
    crosses = cross_store.merged_recent(tk, 200)
    in_window = sorted(
        (c for c in crosses if c["ts_utc"] >= start),
        key=lambda c: c["ts_utc"],
    )
    items: list[dict[str, Any]] = []
    for i, c in enumerate(in_window):
        names = " + ".join(c["level_names"])
        items.append(
            {
                "key": f"x{c['cross_id']}",
                "n": i + 1,
                "ts": c["ts_utc"],
                "dom": "LEVELS",
                "price": c["level_value"],
                "dir": c["direction"],
                "marker": False,
                "title": f"Crossed {_CROSS_WORD[c['direction']]} {names}",
                "detail": f"{price_text(c['level_value'])} · spot "
                f"{price_text(c['spot_at_cross'])} at the cross",
                "src": "level_crosses",
            }
        )
    # the chart's few: the newest cross at each level, for the newest DESK_MARKERS levels
    newest_at = {it["price"]: it for it in items}
    for it in sorted(newest_at.values(), key=lambda it: it["ts"])[-DESK_MARKERS:]:
        it["marker"] = True
    t = terrain(tk, now.timestamp())  # the levels the page's terrain panel is sent
    tts = t.get("levels_ts_utc")
    for side, word, key in (("call", "call", "cw"), ("put", "put", "pw")):
        if t.get(f"{side}_wall_state") == "breached":  # at the live price (price_relations)
            items.append(
                {
                    "key": key,
                    "ts": t.get("spot_as_of_ts_utc"),
                    "dom": "OPTIONS",
                    "dir": "up" if side == "call" else "down",
                    "title": f"Spot through the {word} wall",
                    "detail": f"{word} wall {price_text(t[f'{side}_wall'])} · spot "
                    f"{price_text(t['spot'])}",
                    "src": "gamma levels",
                }
            )
    if t.get("levels_state") == LEVELS_STALE:
        items.append(
            {
                "key": "ls",
                "ts": tts,
                "dom": "DATA",
                "dir": None,
                "warn": True,
                "title": "Gamma levels are stale",
                "detail": t["levels_stale_reason"],
                "src": "gamma levels",
            }
        )
    # the book's size walls, stamped with the book's own time (BOOK_TIME); a book that is not live
    # is a past observation and says so
    micro = order_flow_microstructure(tk, venue, now.timestamp())
    book_ms = micro["provenance"]["book_time_ms"]
    live_book = micro["ages"]["book_stale"] is False
    for i, w in enumerate(micro["wall_candidates"][:3]):
        items.append(
            {
                "key": f"wall{i}",
                "ts": None if book_ms is None else book_ms / 1000.0,
                "dom": "LIQUIDITY",
                "dir": "up" if w.get("side") == "bid" else "down",
                "warn": not live_book,
                "title": f"{venue} size wall · {w['side']} {w['price_text']}"
                + ("" if live_book else " (not live)"),
                "detail": f"{w['volume_text']} shown · {w['median_mult_text']}× the median level"
                + ("" if live_book else " · a past book, not the current one"),
                "src": "equity book",
            }
        )
    # newest first; an event with no time of its own after every timed one
    items = sorted((it for it in items if it["ts"] is not None), key=lambda it: -it["ts"]) + [
        it for it in items if it["ts"] is None
    ]
    for it in items:  # each event's own time as the screen shows it
        it["time_ct"] = None if it["ts"] is None else ct_label(it["ts"])
    return {
        "ticker": tk,
        "tf": tf,
        "window_start_ts_utc": start,
        "window_label": DESK_LOOKBACK[tf][1],
        "items": items,
        "cross_counts": {
            d: sum(1 for c in in_window if c.get("direction") == d) for d in ("up", "down")
        },
    }
