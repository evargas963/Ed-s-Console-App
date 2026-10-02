"""ATR for the terrain radar — distance measured in what price can actually travel.

WHY ATR AND NOT PERCENT (operator 2026-07-19): percent means different things on
different instruments. 0.5% is a normal hour on SPY and noise on TSLA. ATR normalises
distance into "can price get there", which is the only question the radar answers.

TWO horizons, each answering a different question:
  * DAILY ATR  -> "reachable today"        — sets the radar ring (the triage decision)
  * 15-MIN ATR -> "reachable in the next few bars" — shown only on the focused contact,
                  so the scope stays readable

Both are computed from the console's 1-minute bars (Schwab's streamed bars). Prototyped before
building: daily/15m ATR ratios came out 4.8x-9.2x across SPY/QQQ/IWM/NVDA/TSLA/WMT,
consistent with ~26 fifteen-minute buckets per session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from math_volatility import compute_atr


#: ATR(14) daily needs 15 daily candles; the bars carry extended hours (~1,000 a session), so
#: the console keeps 24,000 of each ticker's (server.BARS_KEPT: ~23 sessions)
ATR_PERIOD = 14


@dataclass(frozen=True)
class AtrPair:
    """Daily and 15-minute ATR in price points. Either may be None, with its reason."""

    daily: float | None
    m15: float | None
    daily_reason: str | None = None
    m15_reason: str | None = None


def _aggregate(bars: list, bucket_key) -> list[dict]:
    """Roll 1-minute bars (oldest first) up into OHLC buckets, oldest first."""
    buckets: dict = {}
    for r in bars:
        k = bucket_key(datetime.fromtimestamp(r.ts, _et()))
        b = buckets.get(k)
        if b is None:
            buckets[k] = {"open": r.open, "high": r.high, "low": r.low, "close": r.close}
            continue
        b["high"] = max(b["high"], r.high)
        b["low"] = min(b["low"], r.low)
        b["close"] = r.close
    return [buckets[k] for k in sorted(buckets)]


def _et():
    from time_et import ET  # single ET authority (COH-SA2)

    return ET


def _leg(candles: list, unit: str) -> tuple[float | None, str | None]:
    """ATR(ATR_PERIOD) of `candles`, or None with why: it needs ATR_PERIOD + 1 of them."""
    atr = compute_atr(candles, period=ATR_PERIOD)
    if atr is not None:
        return atr, None
    if len(candles) < ATR_PERIOD + 1:
        return None, f"{len(candles)} {unit} of 1-minute bars; ATR({ATR_PERIOD}) needs {ATR_PERIOD + 1}"
    return None, f"the {unit}' prices do not give a true range"


def compute_atr_pair(bars: list) -> AtrPair:
    """Daily and 15-minute ATR of one ticker's 1-minute bars (oldest first), each None with its
    reason when it cannot be computed. The same rule for every ticker."""
    daily, daily_reason = _leg(_aggregate(bars, lambda d: d.date()), "trading days")
    m15, m15_reason = _leg(_aggregate(bars, lambda d: (d.date(), d.hour, d.minute // 15))[-200:],
                           "15-minute periods")
    return AtrPair(daily, m15, daily_reason, m15_reason)






