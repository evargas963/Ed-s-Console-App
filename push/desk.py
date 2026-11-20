"""The `desk` panel: the Trade Desk's attention queue, one item per event, newest first.

Read from State: the recorded level crosses (state.cross_store), the terrain panel at the live
price (push.terrain) and the chart's bars (push.bars).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from numeric_contract import count_text, price_text
from push.bars import chart_bars, held_minutes
from push.terrain import terrain
from push.verdict import LEVELS_STALE
from state import cross_store
from state.cross_store import MergedCross
from time_et import ct_label, last_open

#: a cross's direction as the queue words it
_CROSS_WORD = {"up": "above", "down": "below"}

#: The Trade Desk's lookback per chart timeframe: seconds, or "session" (the latest regular
#: session), with the words the page shows for it.
DESK_LOOKBACK: dict[str, tuple[int | Literal["session"], str]] = {
    "1": (900, "last 15 min"),
    "3": (1800, "last 30 min"),
    "5": ("session", "this session"),
    "15": (14400, "last 4 h"),
    "30": ("session", "this session"),
    "60": (172800, "last 2 days"),
    "D": (cross_store.CROSSES_HELD_SEC, "last 20 days"),
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


def desk_events_payload(tk: str, tf: str, now: datetime, limit: object) -> dict[str, Any]:
    """Return the Trade Desk's attention queue at `now`.

    Level crosses in the timeframe's window as recorded (level, direction, price, spot, time),
    numbered oldest first, the newest cross at each level for the newest DESK_MARKERS levels
    flagged for the chart; wall breaches and stale levels from the terrain -- newest first, an
    item with no time last -- plus the window's up/down cross counts. One item is one event: the
    chart's marker and the queue's entry are the same item. The page draws it; it selects,
    numbers and orders nothing. `limit` is the 1-minute bars the desk's chart asks for at `tf`
    (the `bars` panel's): a marker before the first of those chart bars has no bar to stand on,
    and those are counted with their words (`markers_off_chart`, `markers_off_chart_text`).
    """
    start = _desk_window_start(tf, now)
    in_window = sorted(cross_store.merged_since(tk, start), key=lambda c: c.cross.ts_utc)
    cross_items = _cross_items(in_window)
    marked = [it for it in cross_items if it["marker"]]
    chart = chart_bars(tk, tf, held_minutes(tk, limit), now)
    off_chart = [it for it in marked if not chart or it["ts"] < chart[0]["t"]]
    items = [
        *cross_items,
        *_terrain_items(tk, now),
    ]
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
            d: sum(1 for c in in_window if c.cross.direction == d) for d in ("up", "down")
        },
        "markers_off_chart": len(off_chart),
        "markers_off_chart_text": _off_chart_text(len(off_chart), len(marked), chart),
    }


def _off_chart_text(off: int, marked: int, chart: list[dict[str, Any]]) -> str:
    """Return the words for the chart's markers with no bar: empty when every marker has one."""
    if not off:
        return ""
    where = (
        f"their crosses are before the chart's first bar, {ct_label(chart[0]['t'])}"
        if chart
        else "the chart holds no bars"
    )
    return f"{count_text(off)} of {count_text(marked)} chart markers not drawn: {where}"


def _item(
    key: str,
    ts: float | None,
    dom: str,
    direction: str | None,
    title: str,
    detail: str,
    src: str,
    *,
    warn: bool = False,
) -> dict[str, Any]:
    """Return one item of the desk's queue as the page draws it: its time, domain and words."""
    return {
        "key": key,
        "ts": ts,
        "dom": dom,
        "dir": direction,
        "warn": warn,
        "title": title,
        "detail": detail,
        "src": src,
    }


def _cross_items(in_window: list[MergedCross]) -> list[dict[str, Any]]:
    """Return the window's level crosses, numbered oldest first (cross_store's, oldest first).

    The newest cross at each level, for the newest DESK_MARKERS levels, is flagged for the chart.
    """
    items: list[dict[str, Any]] = []
    for i, merged in enumerate(in_window):
        c = merged.cross
        items.append(
            {
                **_item(
                    f"x{c.cross_id}",
                    c.ts_utc,
                    "LEVELS",
                    c.direction,
                    f"Crossed {_CROSS_WORD[c.direction]} {' + '.join(merged.level_names)}",
                    f"{price_text(c.level_value)} · spot "
                    f"{price_text(c.spot_at_cross)} at the cross",
                    "level_crosses",
                ),
                "n": i + 1,
                "price": c.level_value,
                "marker": False,
            }
        )
    # the chart's few: the newest cross at each level, for the newest DESK_MARKERS levels
    newest_at = {it["price"]: it for it in items}
    for it in sorted(newest_at.values(), key=lambda it: it["ts"])[-DESK_MARKERS:]:
        it["marker"] = True
    return items


def _terrain_items(tk: str, now: datetime) -> list[dict[str, Any]]:
    """Return a wall the live price is through, and stale levels: the terrain panel's words."""
    items: list[dict[str, Any]] = []
    t = terrain(tk, now.timestamp())  # the levels the page's terrain panel is sent
    tts = t.get("levels_ts_utc")
    for side, word, key in (("call", "call", "cw"), ("put", "put", "pw")):
        if t.get(f"{side}_wall_state") == "breached":  # at the live price (price_relations)
            items.append(
                _item(
                    key,
                    t.get("spot_as_of_ts_utc"),
                    "OPTIONS",
                    "up" if side == "call" else "down",
                    f"Spot through the {word} wall",
                    f"{word} wall {price_text(t[f'{side}_wall'])} · spot {price_text(t['spot'])}",
                    "gamma levels",
                )
            )
    if t.get("levels_state") == LEVELS_STALE:
        items.append(
            _item(
                "ls",
                tts,
                "DATA",
                None,
                "Gamma levels are stale",
                t["levels_stale_reason"],
                "gamma levels",
                warn=True,
            )
        )
    return items
