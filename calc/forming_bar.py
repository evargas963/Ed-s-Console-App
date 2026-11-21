"""The forming 1-minute bar: built from Schwab's last trade until Schwab's own bar for the minute.

Schwab streams a minute's bar (CHART_EQUITY, Schwab Streamer API §5.1) once the minute is over;
within it, trading platforms move the newest bar with every trade (TradingView's real-time bar
updates; Lightweight Charts `series.update`): close the last trade, high and low the extremes,
open the minute's first trade. Built here from LEVELONE_EQUITIES (§3.1) LAST_PRICE and
TRADE_TIME_MILLIS, as the price row holds them (live_market_plane). Its volume is not built:
Schwab's bar brings it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

#: the built minutes held: the forming one and the one before it, which stands until Schwab's bar
#: for it arrives (about 3 s after the minute)
KEPT = 2


@dataclass(frozen=True)
class BuiltMinute:
    """A minute's bar built from the trades Schwab streamed in it.

    `ts` its start (epoch s); `trade_ts` the newest trade's TRADE_TIME (epoch s).
    """

    ts: float
    open: float
    high: float
    low: float
    close: float
    trade_ts: float


@dataclass(frozen=True)
class Built:
    """A ticker's built minutes: its newest trade's minute `ts`.

    `minutes`: the newest KEPT minutes seen from their first trade, oldest first.
    """

    ts: float
    minutes: tuple[BuiltMinute, ...]


def next_built(prev: Built | None, price: float | None, trade_ts: float | None) -> Built | None:
    """Return the built minutes after a price row: `price` LAST_PRICE, `trade_ts` its time (s).

    A row without both changes nothing. The first trade the program sees opens no bar: its
    minute's earlier trades were not seen. A later minute's first trade opens one; a trade of the
    newest minute moves its high, low and close (the close only for a trade not older than the
    one it holds); a trade of an earlier minute changes nothing.
    """
    if price is None or trade_ts is None:
        return prev
    ts = trade_ts - trade_ts % 60
    if prev is None:
        return Built(ts, ())
    if ts < prev.ts:
        return prev
    if ts > prev.ts:
        opened = BuiltMinute(ts, price, price, price, price, trade_ts)
        return Built(ts, (*prev.minutes, opened)[-KEPT:])
    if not prev.minutes or prev.minutes[-1].ts != ts:
        return prev
    cur = prev.minutes[-1]
    newest = trade_ts >= cur.trade_ts
    moved = replace(
        cur,
        high=max(cur.high, price),
        low=min(cur.low, price),
        close=price if newest else cur.close,
        trade_ts=trade_ts if newest else cur.trade_ts,
    )
    return Built(ts, (*prev.minutes[:-1], moved))
