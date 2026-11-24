"""The `experimental` panel: the Trade Desk's Experimental tab, the open-gap record.

Today's gap; how gaps in today's direction were followed, with the other direction for
reference; today's result once Schwab's open bar has closed; the last opens. Every word and
value served. Read from State: the ticker's open-gap record and 5-minute bars (state.bar_store)
and its price row (live_price_rows).
"""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict, overload

from instrument_identity import ticker_storage_key
from live_price_rows import price_row
from open_gap import BAR_SECONDS, LAST_OPENS, Followed, Open, OpenGapRecord, today_open
from state import bar_store
from time_et import ET, Session, ct_dated, sessions


class GapFollowed(TypedDict):
    """How one gap direction was followed, as the tab shows it.

    Its words, then the bar's band, its mark and whether the band is above the coin flip, in
    percent of the bar's width.
    """

    title: str
    share_text: str
    count_text: str
    range_text: str
    line: str
    band_left: float
    band_width: float
    mark: float
    above_half: bool


class OpenRow(TypedDict):
    """One of the last opens as the tab lists it: its day, its gap and its first five minutes."""

    day_text: str
    gap_text: str
    gap_up: bool
    five_text: str
    five_up: bool
    called: bool


class TodayResult(TypedDict):
    """Today's open once Schwab's open bar has closed: its first five minutes and the call."""

    label: str
    five_text: str
    five_up: bool
    called: bool
    called_text: str


class TodayCard(TypedDict):
    """Today's card: its gap (None while it has none), what it is against, and its result."""

    label: str
    gap_text: str | None
    gap_up: bool | None
    when_text: str
    results: list[TodayResult]


class GapRecord(TypedDict):
    """The open-gap record as the tab shows it: today's direction first, then the last opens."""

    main: GapFollowed
    others: list[GapFollowed]
    last: list[OpenRow]
    last_title: str
    footer: str


class ExperimentalTab(TypedDict):
    """The `experimental` panel: the ticker's card for today and its record (none until held)."""

    ticker: str
    today: TodayCard
    records: list[GapRecord]


@overload
def _moved_text(fraction: float) -> str: ...
@overload
def _moved_text(fraction: None) -> None: ...
def _moved_text(fraction: float | None) -> str | None:
    """Return a gap or a move as the tab shows it: its arrow and its signed percent.

    None when there is none, which the page draws as missing.
    """
    if fraction is None:
        return None
    return f"{'▲' if fraction > 0 else '▼'} {fraction:+.2%}"


def _followed_served(direction: str, f: Followed) -> GapFollowed:
    """How one gap direction was followed, as the tab shows it."""
    share = f.matched / f.opens
    return {
        "title": f"When the gap was {direction}, the first 5 minutes went {direction}",
        "share_text": f"{share:.0%}",
        "count_text": f"{f.matched} of {f.opens} opens",
        "range_text": f"95% range {f.low:.0%}-{f.high:.0%}",
        "line": (
            f"{direction.capitalize()} gaps, for reference: {direction} {f.matched} of "
            f"{f.opens} ({share:.0%}, range {f.low:.0%}-{f.high:.0%})"
        ),
        # the bar's band, its mark and the coin flip, in percent of its width
        "band_left": f.low * 100,
        "band_width": (f.high - f.low) * 100,
        "mark": share * 100,
        "above_half": f.low > 0.5,
    }


def _open_served(o: Open) -> OpenRow:
    return {
        "day_text": f"{o.day:%a %b %d}",
        "gap_text": _moved_text(o.gap),
        "gap_up": o.gap > 0,
        "five_text": _moved_text(o.first_five),
        "five_up": o.first_five > 0,
        "called": o.called,
    }


def _prior_session(day: str) -> Session | None:
    """Return the newest regular session before `day` (YYYY-MM-DD) Schwab's /markets answered."""
    held = sessions()
    before = [held[d] for d in sorted(held) if d < day and held[d].regular]
    return before[-1] if before else None


def _today_card(
    label: str, gap: float | None, when_text: str, results: list[TodayResult]
) -> TodayCard:
    """Today's card: its gap (a fraction; None while it has none) and what it is against."""
    return {
        "label": label,
        "gap_text": _moved_text(gap),
        "gap_up": None if gap is None else gap > 0,
        "when_text": when_text,
        "results": results,
    }


def _today_served(tk: str, now: float) -> TodayCard:
    """Today's gap: Schwab's live change before the open, then the open as the record defines it.

    `results` holds today's 9:30-9:35 result once Schwab's open bar has closed.
    """
    day = datetime.fromtimestamp(now, ET).date().isoformat()
    held = sessions()
    if day not in held or not held[day].regular:
        return _today_card("Today", None, "no regular session today in Schwab's market hours", [])
    today = held[day]
    if now < today.regular[0][0].timestamp():
        label = "Today's gap · before the open"
        row = price_row(tk, now)
        live = row["chg_pct"]
        if live is None:
            return _today_card(label, None, "no trade from Schwab yet", [])
        return _today_card(
            label, live / 100, f"vs. prior close · Schwab, live · {row['trade_time_ct']}", []
        )
    label = "Today's gap · at the open"
    prior = _prior_session(day)
    o = None if prior is None else today_open(bar_store.series(tk, "5m"), today, prior, now)
    if o is None:
        return _today_card(label, None, "waiting for Schwab's open bar to close", [])
    went = "up" if o.first_five > 0 else "down"
    bar_start = today.regular[0][0].timestamp()
    return _today_card(
        label,
        o.gap,
        "vs. prior close · Schwab's 5-minute bars",
        [
            {
                "label": (
                    f"Today {ct_dated(bar_start, now)}–{ct_dated(bar_start + BAR_SECONDS, now)}"
                ),
                "five_text": _moved_text(o.first_five),
                "five_up": o.first_five > 0,
                "called": o.called,
                "called_text": (
                    "✓ the open went the way the gap pointed"
                    if o.called
                    else f"✗ the gap pointed {'up' if o.gap > 0 else 'down'}, the open went {went}"
                ),
            }
        ],
    )


def experimental(tk: str, now: float) -> ExperimentalTab:
    """Return the Trade Desk's Experimental tab for the selected ticker, as its mock-up shows it.

    Today's gap; how gaps in today's direction (up, before any today) were followed, with the
    other direction for reference; today's result once Schwab's open bar has closed; the last 10
    opens. Every word and value served; `record` is absent until the ticker's two Schwab answers
    have arrived with an open that counts.
    """
    key = ticker_storage_key(tk)
    today = _today_served(key, now)
    record = bar_store.open_gap(key)
    return {
        "ticker": key,
        "today": today,
        "records": [
            _record_served(r, down_first=today["gap_up"] is False)
            for r in [record]
            if r is not None
        ],
    }


def _record_served(record: OpenGapRecord, *, down_first: bool) -> GapRecord:
    """Return the record as the tab shows it: today's direction first (up before any today)."""
    sides = [("down", record.down), ("up", record.up)]
    if not down_first:
        sides.reverse()
    blocks = [_followed_served(d, f) for d, f in sides if f is not None]
    last = list(record.opens[-LAST_OPENS:])[::-1]
    return {
        "main": blocks[0],
        "others": blocks[1:],
        "last": [_open_served(o) for o in last],
        "last_title": (
            f"Last {len(last)} opens · the gap called {sum(o.called for o in last)} of {len(last)}"
        ),
        "footer": (
            f"Schwab's 5-minute bars, {record.opens[0].day:%b %d} – "
            f"{record.opens[-1].day:%b %d} ({len(record.opens)} opens). Says how often the gap "
            "called the open, not where today's will go."
        ),
    }
