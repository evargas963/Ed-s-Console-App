"""The `experimental` panel: the Trade Desk's Experimental tab, the open-gap record.

Today's gap; how gaps in today's direction were followed, with the other direction for
reference; today's result once Schwab's open bar has closed; the last opens. Every word and
value served. Read from State: the ticker's open-gap record and 5-minute bars (state.bar_store)
and its price row (live_price_rows).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from instrument_identity import ticker_storage_key
from live_price_rows import price_row
from open_gap import BAR_SECONDS, LAST_OPENS, Followed, Open, OpenGapRecord, today_open
from state import bar_store
from time_et import ET, Session, sessions


def _moved_text(fraction: float) -> str:
    """Return a gap or a move as the tab shows it: its arrow and its signed percent."""
    return f"{'▲' if fraction > 0 else '▼'} {fraction:+.2%}"


def _followed_served(direction: str, f: Followed) -> dict[str, Any]:
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


def _open_served(o: Open) -> dict[str, Any]:
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
    label: str,
    when_text: str,
    gap_text: str = "-",
    gap_up: bool | None = None,
    results: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """Return today's card; with no gap, `when_text` says why."""
    return {
        "label": label,
        "gap_text": gap_text,
        "gap_up": gap_up,
        "when_text": when_text,
        "results": list(results),
    }


def _today_served(tk: str, now: float) -> dict[str, Any]:
    """Today's gap: Schwab's live change before the open, then the open as the record defines it.

    `results` holds today's 9:30-9:35 result once Schwab's open bar has closed.
    """
    day = datetime.fromtimestamp(now, ET).date().isoformat()
    held = sessions()
    if day not in held or not held[day].regular:
        return _today_card("Today", "no regular session today in Schwab's market hours")
    today = held[day]
    if now < today.regular[0][0].timestamp():
        row = price_row(tk, now)
        live = row["chg_pct"]
        if live is None:
            return _today_card("Today's gap · before the open", "no trade from Schwab yet")
        return _today_card(
            "Today's gap · before the open",
            f"vs. prior close · Schwab, live · {row['trade_time_ct']}",
            _moved_text(live / 100),
            live > 0,
        )
    prior = _prior_session(day)
    candles = bar_store.series(tk, "5m")
    opened = [today_open(candles, today, p, now) for p in [prior] if p is not None]
    if not opened or opened[0] is None:
        return _today_card("Today's gap · at the open", "waiting for Schwab's open bar to close")
    o = opened[0]
    went = "up" if o.first_five > 0 else "down"
    bar_start = today.regular[0][0]
    bar_end = datetime.fromtimestamp(bar_start.timestamp() + BAR_SECONDS, ET)
    return _today_card(
        "Today's gap · at the open",
        "vs. prior close · Schwab's 5-minute bars",
        _moved_text(o.gap),
        o.gap > 0,
        (
            {
                "label": f"Today {bar_start:%H:%M}–{bar_end:%H:%M} ET",
                "five_text": _moved_text(o.first_five),
                "five_up": o.first_five > 0,
                "called": o.called,
                "called_text": (
                    "✓ the open went the way the gap pointed"
                    if o.called
                    else f"✗ the gap pointed {'up' if o.gap > 0 else 'down'}, the open went {went}"
                ),
            },
        ),
    )


def experimental(tk: str, now: float) -> dict[str, Any]:
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


def _record_served(record: OpenGapRecord, *, down_first: bool) -> dict[str, Any]:
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
