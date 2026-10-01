"""ATR for the terrain radar — distance measured in what price can actually travel.

WHY ATR AND NOT PERCENT (operator 2026-07-19): percent means different things on
different instruments. 0.5% is a normal hour on SPY and noise on TSLA. ATR normalises
distance into "can price get there", which is the only question the radar answers.

TWO horizons, each answering a different question:
  * DAILY ATR  -> "reachable today"        — sets the radar ring (the triage decision)
  * 15-MIN ATR -> "reachable in the next few bars" — shown only on the focused contact,
                  so the scope stays readable

The daily one is computed from Schwab's own daily candles (its daily price history, carried from
the capture daemon), never rolled up from minutes (operator 2026-10-01: "lets use what schwab
gives us"); the 15-minute one from `price_bars_1m`. Prototyped before building: daily/15m ATR
ratios came out 4.8x-9.2x across SPY/QQQ/IWM/NVDA/TSLA/WMT, consistent with ~26 fifteen-minute
buckets per session.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from math_volatility import compute_atr
from time_et import ET


ATR_PERIOD = 14
#: the 15-minute ATR's 1-minute bars (its 200 periods are under 8 sessions of up to 420 bars)
_MAX_1M_BARS = 4_000


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
        return None, f"{len(candles)} {unit}; ATR({ATR_PERIOD}) needs {ATR_PERIOD + 1}"
    return None, f"the {unit}' prices do not give a true range"


def compute_atr_pair(db_path: str, ticker: str, now: datetime, daily_candles: "list[dict] | None",
                     daily_absent_reason: str | None) -> AtrPair:
    """Daily and 15-minute ATR for one ticker at `now` (ET), from completed candles only. Daily:
    Schwab's daily candles of the days before today (`daily_candles`, served bars {o, h, l, c};
    None: not received, with `daily_absent_reason`). 15-minute: price_bars_1m's minutes, the
    period still open left out, since a candle still forming has a smaller range than it will
    close with. Each is None with its reason when it cannot be computed. The same rule for every
    ticker. Never raises."""
    from instrument_identity import ticker_storage_key
    tk = ticker_storage_key(ticker)  # RC-345/F25: ATR DB query owner consumes canonical identity (callee, not caller-masked)
    if not tk:
        return AtrPair(None, None, "no ticker", "no ticker")
    if daily_candles is None:
        daily, daily_reason = None, daily_absent_reason
    else:
        daily, daily_reason = _leg([{"open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"]}
                                    for b in daily_candles], "Schwab daily candles")
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    except sqlite3.Error as e:
        return AtrPair(daily, None, daily_reason, f"bars unreadable: {e}")
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT bar_start_ts_utc ts, open o, high h, low l, close c "
            "FROM price_bars_1m WHERE ticker=? ORDER BY bar_start_ts_utc DESC LIMIT ?",
            (tk, _MAX_1M_BARS),
        ).fetchall()
    except sqlite3.Error as e:
        return AtrPair(daily, None, daily_reason, f"bars unreadable: {e}")
    finally:
        con.close()

    period_start = now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0).timestamp()
    closed_periods = [r for r in rows if r["ts"] < period_start]
    m15, m15_reason = _leg(_aggregate(closed_periods, lambda d: (d.date(), d.hour, d.minute // 15))[-200:],
                           "15-minute periods of 1-minute bars")
    return AtrPair(daily, m15, daily_reason, m15_reason)






