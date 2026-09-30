"""ATR for the terrain radar — distance measured in what price can actually travel.

WHY ATR AND NOT PERCENT (operator 2026-07-19): percent means different things on
different instruments. 0.5% is a normal hour on SPY and noise on TSLA. ATR normalises
distance into "can price get there", which is the only question the radar answers.

TWO horizons, each answering a different question:
  * DAILY ATR  -> "reachable today"        — sets the radar ring (the triage decision)
  * 15-MIN ATR -> "reachable in the next few bars" — shown only on the focused contact,
                  so the scope stays readable

Both are computed from `price_bars_1m`, which is already collected. Prototyped before
building: daily/15m ATR ratios came out 4.8x-9.2x across SPY/QQQ/IWM/NVDA/TSLA/WMT,
consistent with ~26 fifteen-minute buckets per session.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from math_volatility import compute_atr
from time_et import ET, collect_window_end_mins_for_et_date


ATR_PERIOD = 14
#: ATR(14) daily needs 15 completed daily candles; price_bars_1m holds up to 420 bars a day
#: (09:15 ET to 15 minutes after the close), so this many bars is 57 full days or more.
_MAX_1M_BARS = 24_000


@dataclass(frozen=True)
class AtrPair:
    """Daily and 15-minute ATR in price points. Either may be None, with its reason."""

    daily: float | None
    m15: float | None
    daily_reason: str | None = None
    m15_reason: str | None = None


def _aggregate(rows: list, bucket_key) -> list[dict]:
    """Roll 1-minute rows up into OHLC buckets, oldest first."""
    buckets: dict = {}
    for r in sorted(rows, key=lambda x: x["ts"]):
        k = bucket_key(datetime.fromtimestamp(r["ts"], ET))
        b = buckets.get(k)
        if b is None:
            buckets[k] = {"open": r["o"], "high": r["h"], "low": r["l"], "close": r["c"]}
            continue
        b["high"] = max(b["high"], r["h"])
        b["low"] = min(b["low"], r["l"])
        b["close"] = r["c"]
    return [buckets[k] for k in sorted(buckets)]


def _leg(candles: list, unit: str) -> tuple[float | None, str | None]:
    """ATR(ATR_PERIOD) of `candles`, or None with why: it needs ATR_PERIOD + 1 of them."""
    atr = compute_atr(candles, period=ATR_PERIOD)
    if atr is not None:
        return atr, None
    if len(candles) < ATR_PERIOD + 1:
        return None, f"{len(candles)} {unit} of 1-minute bars; ATR({ATR_PERIOD}) needs {ATR_PERIOD + 1}"
    return None, f"the {unit}' prices do not give a true range"


def compute_atr_pair(db_path: str, ticker: str, now: datetime) -> AtrPair:
    """Daily and 15-minute ATR for one ticker at `now` (ET), from completed candles only: the
    day still trading (before its stored bars end, time_et.collect_window_end_mins_for_et_date)
    and the 15-minute period still open are left out, since a candle still forming has a smaller
    range than it will close with. Each is None with its reason when it cannot be computed.
    The same rule for every ticker. Never raises."""
    from instrument_identity import ticker_storage_key
    tk = ticker_storage_key(ticker)  # RC-345/F25: ATR DB query owner consumes canonical identity (callee, not caller-masked)
    if not tk:
        return AtrPair(None, None, "no ticker", "no ticker")
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    except sqlite3.Error as e:
        return AtrPair(None, None, f"bars unreadable: {e}", f"bars unreadable: {e}")
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT bar_start_ts_utc ts, open o, high h, low l, close c "
            "FROM price_bars_1m WHERE ticker=? ORDER BY bar_start_ts_utc DESC LIMIT ?",
            (tk, _MAX_1M_BARS),
        ).fetchall()
    except sqlite3.Error as e:
        return AtrPair(None, None, f"bars unreadable: {e}", f"bars unreadable: {e}")
    finally:
        con.close()

    end_mins = collect_window_end_mins_for_et_date(now.date().isoformat())
    day_open = end_mins is not None and now.hour * 60 + now.minute < end_mins
    days = [r for r in rows if not (day_open and datetime.fromtimestamp(r["ts"], ET).date() == now.date())]
    period_start = now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0).timestamp()
    closed_periods = [r for r in rows if r["ts"] < period_start]
    daily, daily_reason = _leg(_aggregate(days, lambda d: d.date()), "trading days")
    m15, m15_reason = _leg(_aggregate(closed_periods, lambda d: (d.date(), d.hour, d.minute // 15))[-200:],
                           "15-minute periods")
    return AtrPair(daily, m15, daily_reason, m15_reason)






