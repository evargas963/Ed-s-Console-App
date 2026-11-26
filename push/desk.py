"""The `desk` panel: the Trade Desk's alerts, one item per event, newest first.

Read from State: the recorded level crosses (state.cross_store), the terrain panel at the live
price (push.terrain), the live price itself (push.spot.resolve_spot, the price row's) and the
chart's bars (push.bars).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

from calc.micro_structure import Candle
from calc.terrain_engine import OPTION_LEVELS, WALL_BREACHED
from numeric_contract import count_text, price_text
from push.bars import chart_bars, held_minutes
from push.spot import resolve_spot
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


class QueueItem(TypedDict):
    """One event of the desk's queue as the page draws it: its time, domain and words.

    `time_ct` is the event's own time as the screen shows it; None for an event with no time.
    """

    key: str
    ts: float | None
    dom: str
    dir: str | None
    warn: bool
    title: str
    detail: str | None
    src: str
    time_ct: str | None


class CrossItem(TypedDict):
    """A level cross in the queue, numbered oldest first.

    It carries its level's price, whether the chart marks it (the newest cross at each level, for
    the newest DESK_MARKERS levels) and the marker's words. Its keys are a QueueItem's, `time_ct`
    last.
    """

    key: str
    ts: float
    dom: str
    dir: str
    warn: bool
    title: str
    detail: str
    src: str
    n: int
    price: float
    marker: bool
    marker_said: str
    time_ct: str


class CrossCounts(TypedDict):
    """The window's level crosses by direction."""

    up: int
    down: int


class DeskQueue(TypedDict):
    """The `desk` panel: the Trade Desk's alerts in a timeframe's window, newest first."""

    ticker: str
    tf: str
    window_start_ts_utc: float
    window_label: str
    items: list[CrossItem | QueueItem]
    cross_counts: CrossCounts
    markers_off_chart: int
    markers_off_chart_text: str
    none_said: str | None


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


def desk_events_payload(tk: str, tf: str, now: datetime, limit: object) -> DeskQueue:
    """Return the Trade Desk's alerts at `now`.

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
    off_chart = [it for it in marked if not chart or it["ts"] < chart[0].ts]
    terrain_items = _terrain_items(tk, now)
    timed: list[tuple[float, CrossItem | QueueItem]] = [(it["ts"], it) for it in cross_items]
    timed += [(ts, it) for it in terrain_items if (ts := it["ts"]) is not None]
    # newest first; an event with no time of its own after every timed one
    items = [it for _, it in sorted(timed, key=lambda pair: -pair[0])]
    items += [it for it in terrain_items if it["ts"] is None]
    return {
        "ticker": tk,
        "tf": tf,
        "window_start_ts_utc": start,
        "window_label": DESK_LOOKBACK[tf][1],
        "items": items,
        "cross_counts": {
            "up": sum(1 for c in in_window if c.cross.direction == "up"),
            "down": sum(1 for c in in_window if c.cross.direction == "down"),
        },
        "markers_off_chart": len(off_chart),
        "markers_off_chart_text": _off_chart_text(len(off_chart), len(marked), chart),
        # what the queue says with nothing in the window, a whole sentence (AGENTS.md rule 4)
        "none_said": None
        if items
        else f"Nothing in the {DESK_LOOKBACK[tf][1]}. Level crosses and wall breaches land here.",
    }


def _off_chart_text(off: int, marked: int, chart: list[Candle]) -> str:
    """Return the words for the chart's markers with no bar: empty when every marker has one."""
    if not off:
        return ""
    where = (
        f"their crosses are before the chart's first bar, {ct_label(chart[0].ts)}"
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
    detail: str | None,
    src: str,
    *,
    warn: bool = False,
) -> QueueItem:
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
        "time_ct": None if ts is None else ct_label(ts),
    }


def _cross_items(in_window: list[MergedCross]) -> list[CrossItem]:
    """Return the window's level crosses, numbered oldest first (cross_store's, oldest first).

    The newest cross at each level, for the newest DESK_MARKERS levels, is flagged for the chart.
    """
    items: list[CrossItem] = []
    for i, merged in enumerate(in_window):
        c = merged.cross
        items.append(
            {
                "key": f"x{c.cross_id}",
                "ts": c.ts_utc,
                "dom": "LEVELS",
                "dir": c.direction,
                "warn": False,
                "title": f"Crossed {_CROSS_WORD[c.direction]} {' + '.join(merged.level_names)}",
                "detail": f"{price_text(c.level_value)} · spot "
                f"{price_text(c.spot_at_cross)} at the cross",
                "src": "level_crosses",
                "n": i + 1,
                "price": c.level_value,
                "marker": False,
                "marker_said": f"Crossed {_CROSS_WORD[c.direction]}",
                "time_ct": ct_label(c.ts_utc),
            }
        )
    # the chart's few: the newest cross at each level, for the newest DESK_MARKERS levels
    newest_at = {it["price"]: it for it in items}
    for it in sorted(newest_at.values(), key=lambda it: it["ts"])[-DESK_MARKERS:]:
        it["marker"] = True
    return items


def _terrain_items(tk: str, now: datetime) -> list[QueueItem]:
    """Return Gamma Call or Gamma Put when the live price is through it, and stale levels.

    In the terrain panel's words, each level by its name in the one list (OPTION_LEVELS).
    """
    items: list[QueueItem] = []
    t = terrain(tk, now.timestamp())  # the levels the page's terrain panel is sent
    spot, _src, spot_ts = resolve_spot(tk, now=now.timestamp())  # the price they are through
    names = dict(OPTION_LEVELS)
    walls = (
        ("call_wall", "cw", "up", t["call_wall_state"], t["call_wall"]),
        ("put_wall", "pw", "down", t["put_wall_state"], t["put_wall"]),
    )
    for level, key, way, state, wall in walls:
        if state == WALL_BREACHED:  # at the live price (price_relations)
            items.append(
                _item(
                    key,
                    spot_ts,
                    "OPTIONS",
                    way,
                    f"Spot through {names[level]}",
                    f"{names[level]} {price_text(wall)} · spot {price_text(spot)}",
                    "gamma levels",
                )
            )
    if t["levels_state"] == LEVELS_STALE:
        items.append(
            _item(
                "ls",
                t.get("levels_ts_utc"),
                "DATA",
                None,
                "Gamma levels are stale",
                t["levels_stale_reason"],
                "gamma levels",
                warn=True,
            )
        )
    return items
