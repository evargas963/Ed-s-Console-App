"""The forming 1-minute bar: built from Schwab's last trade until Schwab's own bar for the minute.

Schwab streams a minute's bar (CHART_EQUITY, Schwab Streamer API §5.1) once the minute is over;
within it, trading platforms move the newest bar with every trade (TradingView's real-time bar
updates; Lightweight Charts `series.update`): close the last trade, high and low the extremes,
open the minute's first trade. Built here from LEVELONE_EQUITIES (§3.1) LAST_PRICE,
TRADE_TIME_MILLIS and TOTAL_VOLUME, as the price row holds them (live_market_plane).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

#: the built minutes held: the forming one and the one before it, which stands until Schwab's bar
#: for it arrives (about 3 s after the minute, measured on SPY 2026-11-19)
KEPT = 2


@dataclass(frozen=True)
class BuiltMinute:
    """A minute's bar built from the trades Schwab streamed in it.

    `ts` its start (epoch s). `base` TOTAL_VOLUME as held before the minute's first trade,
    `total` as held with its newest; `trade_ts` the newest trade's TRADE_TIME (epoch s).
    """

    ts: float
    open: float
    high: float
    low: float
    close: float
    base: float | None
    total: float | None
    trade_ts: float

    @property
    def volume(self) -> float | None:
        """The minute's volume: TOTAL_VOLUME now less before its first trade; unknown: None."""
        return None if self.base is None or self.total is None else self.total - self.base


@dataclass(frozen=True)
class Built:
    """A ticker's built minutes: its newest trade's minute `ts` and the TOTAL_VOLUME held with it.

    `minutes`: the newest KEPT minutes seen from their first trade, oldest first.
    """

    ts: float
    total: float | None
    minutes: tuple[BuiltMinute, ...]


def next_built(
    prev: Built | None, price: float | None, trade_ts: float | None, total: float | None
) -> Built | None:
    """Return the built minutes after a price row: `price` LAST_PRICE, `trade_ts` its time (s).

    A row without both changes nothing. The first trade the program sees opens no bar: its
    minute's earlier trades were not seen. A later minute's first trade opens one (`base` the
    TOTAL_VOLUME held before it); a trade of the newest minute moves its high, low and close (the
    close only for a trade not older than the one it holds); a trade of an earlier minute changes
    nothing. TOTAL_VOLUME lower than held (Schwab sets it to zero at 7:28 ET, §3.1 field 8)
    leaves the minute's volume unknown.
    """
    if price is None or trade_ts is None:
        return prev
    ts = trade_ts - trade_ts % 60
    if prev is None:
        return Built(ts, total, ())
    if ts < prev.ts:
        return prev
    reset = total is not None and prev.total is not None and total < prev.total
    if ts > prev.ts:
        base = None if reset else prev.total
        opened = BuiltMinute(ts, price, price, price, price, base, total, trade_ts)
        return Built(ts, total, (*prev.minutes, opened)[-KEPT:])
    if not prev.minutes or prev.minutes[-1].ts != ts:
        return Built(ts, total, prev.minutes)
    cur = prev.minutes[-1]
    newest = trade_ts >= cur.trade_ts
    moved = replace(
        cur,
        high=max(cur.high, price),
        low=min(cur.low, price),
        close=price if newest else cur.close,
        base=None if reset else cur.base,
        total=total,
        trade_ts=trade_ts if newest else cur.trade_ts,
    )
    return Built(ts, total, (*prev.minutes[:-1], moved))
