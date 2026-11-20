"""The `bars` panel: a ticker's chart bars at the chart's timeframe, each with its texts.

Read from State: the bars and candles the bar writer holds (state.bar_store) and the price row
(live_market_plane). Its daily candles are the ATR's own (daily_candles).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

import live_market_plane as lmp
import live_price_rows as _lpr  # with_change: the bar-change computation
from calc.micro_structure import Candle
from numeric_contract import count_text, price_text
from push.asked import tf_asked
from state import bar_store
from time_et import ET, ct_label, ct_ticks, session

#: the most 1-minute bars one `bars` panel spans
BARS_LIMIT_MAX = 12000

#: the chart timeframes Schwab sends as a /pricehistory series of their own (the daemon's
#: PRICE_HISTORY): chart timeframe -> series
SCHWAB_SERIES = {"5": "5m", "15": "15m", "30": "30m", "D": "1d"}


def _bar_dict(c: Candle) -> dict[str, Any]:
    return {"t": float(c.ts), "o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume}


def todays_candles(tk: str, now: datetime) -> list[Candle]:
    """Today's daily candle as Schwab pushes it: one candle, or none yet.

    LEVELONE_EQUITIES OPEN_PRICE, HIGH_PRICE, LOW_PRICE, REGULAR_MARKET_LAST_PRICE and
    TOTAL_VOLUME, as the price row holds them (live_market_plane.get_quote). Only regular session
    trades set the first three, and each is 0 until one does (Schwab Streamer API §3.1, fields
    17, 10 and 11); the last stands from the session's close while the extended hours trade on.
    None before today's regular session Schwab sent (/markets) opens, on a day without one, and
    until the ticker's first regular trade. Its time is the session's open.
    """
    s = session(now.astimezone(ET).date().isoformat())
    row = lmp.get_quote(tk)
    if s is None or not s.regular or now < s.regular[0][0]:
        return []
    o, h, lo, c = row.open_price, row.high_price, row.low_price, row.regular_last
    if o is None or h is None or lo is None or c is None or o == 0:
        return []
    return [Candle(s.regular[0][0].timestamp(), o, h, lo, c, row.total_volume)]


def daily_candles(tk: str, now: datetime) -> list[Candle]:
    """`tk`'s daily candles through today, every one Schwab's: the ATR's and the daily chart's.

    Schwab's /pricehistory series as the bar writer holds it (state.bar_store; none from Schwab
    yet: none held), today's candle of it once Schwab's regular window for today has ended and
    Schwab has sent it. Until then today's is the one Schwab pushes (todays_candles).
    """
    today = now.astimezone(ET).date()
    s = session(today.isoformat())
    ended = s is not None and bool(s.regular) and now >= s.regular[-1][1]
    sent = bar_store.series(tk, "1d")
    daily = [
        c
        for day, c in ((datetime.fromtimestamp(c.ts, ET).date(), c) for c in sent)
        if day < today or (ended and day == today)
    ]
    if daily and datetime.fromtimestamp(daily[-1].ts, ET).date() == today:
        return daily
    return daily + todays_candles(tk, now)


def bars(ticker: str, now: float, params: dict[str, Any]) -> dict[str, Any]:
    """Return the `bars` panel at `now`: the ticker's bars at chart timeframe `tf`, newest-last.

    The page's socket sends it (live_ui, PAGE_PANELS) to every chart, at once and with each new
    bar (BARS_PANELS). [{t,o,h,l,c,v}] epoch-seconds bar starts (chart_bars), over the span of its
    newest `limit` 1-minute bars, from the bars the console holds (state.bar_store): no database, no
    Schwab call; each bar with its start as the screen shows it (`time_ct`, the chart's readout
    and crosshair) and as its time axis marks it (`ticks`, time_et.ct_ticks).
    `last_bar`: the newest completed minute and its label. A `tf` not in
    LEVEL_TIMEFRAMES or a `limit` not a count up to BARS_LIMIT_MAX raises: the socket sends that
    panel's words. `ticker` is the levels' own key.
    """
    tf = tf_asked(params)
    held = held_minutes(ticker, params.get("limit"))
    shown = chart_bars(ticker, tf, held, datetime.fromtimestamp(now, ET))
    return {
        "bars": [
            {
                **_lpr.with_change(b),
                "time_ct": ct_label(b["t"]),
                "ticks": ct_ticks(b["t"]),
                "v_text": count_text(b["v"]),
                **{f"{k}_text": price_text(b[k]) for k in "ohlc"},
            }
            for b in shown
        ],
        "tf": tf,
        "last_bar": {"t": held[-1]["t"], "label": ct_label(held[-1]["t"])} if held else None,
    }


def held_minutes(ticker: str, limit: object) -> list[dict[str, Any]]:
    """`ticker`'s newest `limit` 1-minute bars the console holds, oldest first: a chart's span.

    From state.bar_store. A `limit` not a count from 1 to BARS_LIMIT_MAX raises.
    """
    if type(limit) is not int or not 1 <= limit <= BARS_LIMIT_MAX:
        raise ValueError(f"limit {limit!r} is not a count from 1 to {BARS_LIMIT_MAX}")
    return [_bar_dict(c) for c in bar_store.bars_1m(ticker, limit)]


def _tf_bucket_key(t: float, tf: str) -> date | int:
    """Return the chart bar a timestamp belongs to.

    Its ET trading date ("D") or its tf-minute bucket.
    """
    return datetime.fromtimestamp(t, ET).date() if tf == "D" else int(t // (int(tf) * 60))


def aggregate_vwap(rows: Sequence[Sequence[float]], tf: str) -> list[list[float]]:
    """VWAP rows [t, vwap] rolled up to the chart timeframe.

    Exactly as aggregate_bars rolls the bars: each bar takes the value as of its last minute,
    stamped with the bar's first minute (the bar's own `t`).
    """
    if tf == "1":
        return [list(r) for r in rows]
    out: list[list[float]]
    out, cur_key = [], None
    for r in rows:
        k = _tf_bucket_key(float(r[0]), tf)
        if k != cur_key:
            out.append([r[0]] + list(r[1:]))
            cur_key = k
        else:
            out[-1] = [out[-1][0]] + list(r[1:])
    return out


def chart_bars(
    tk: str, tf: str, minutes: list[dict[str, Any]], now: datetime
) -> list[dict[str, Any]]:
    """`tk`'s bars at chart timeframe `tf` over the span of `minutes` (its 1-minute bars).

    A timeframe Schwab sends (SCHWAB_SERIES) is Schwab's series as the bar writer holds it, but
    for the bar Schwab has not sent whole yet: a minute series' newest bar (forming, or not asked
    again yet; the daemon asks as each completes), which is rolled up (aggregate_bars) from
    Schwab's 1-minute bars; and today's daily candle (daily_candles). Every other timeframe (3
    and 60 minutes, which Schwab does not send), or one whose series is not held yet, is rolled
    up from the 1-minute bars. The daily bars are always daily_candles', the ATR's own.
    """
    if tf == "D":
        first_day = datetime.fromtimestamp(minutes[0]["t"], ET).date() if minutes else None
        return [
            _bar_dict(c)
            for c in daily_candles(tk, now)
            if first_day is None or first_day <= datetime.fromtimestamp(c.ts, ET).date()
        ]
    sent = bar_store.series(tk, SCHWAB_SERIES[tf]) if tf in SCHWAB_SERIES else []
    if not sent:
        return aggregate_bars(minutes, tf)
    newest = sent[-1].ts
    first = minutes[0]["t"] if minutes else sent[0].ts
    schwab = [_bar_dict(c) for c in sent if first <= c.ts < newest]
    return schwab + aggregate_bars([m for m in minutes if m["t"] >= newest], tf)


def aggregate_bars(bars: list[dict[str, Any]], tf: str) -> list[dict[str, Any]]:
    """Roll up 1m bars to a chart timeframe: THE chart-timeframe roll-up.

    The timeframe is "1", "3", "5", "15", "30", "60" minutes, or "D" = the ET trading date: first
    open, max high, min low, last close. Volume is the sum only when every minute in the bucket
    reported one -- otherwise None (unknown), never a partial sum or a 0.
    """
    if tf == "1":
        return list(bars)

    def key(t: float) -> date | int:
        return _tf_bucket_key(t, tf)

    out: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    cur_key = None
    for b in bars:
        k = key(float(b["t"]))
        if cur is None or k != cur_key:
            if cur is not None:
                out.append(cur)
            cur = dict(b)
            cur_key = k
            continue
        cur["h"] = max(cur["h"], b["h"])
        cur["l"] = min(cur["l"], b["l"])
        cur["c"] = b["c"]
        cur["v"] = None if (cur["v"] is None or b["v"] is None) else cur["v"] + b["v"]
    if cur is not None:
        out.append(cur)
    return out
