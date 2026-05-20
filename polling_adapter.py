"""
polling_adapter.py — REST polling transport for OHLCV bars
===========================================================
Fetches bars via REST API on a schedule. Works with any provider
that exposes price history (e.g. Schwab get_price_history).

Used as fallback when WebSocket/SSE are unavailable.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, time
from typing import Callable, Optional
from time_et import ET

from market_data_adapter import schwab_candles_to_bars
import logging

log = logging.getLogger(__name__)


BarCallback = Callable[[list[dict]], None]


def _prev_trading_day(d: date) -> date:
    """Return the previous trading day (skip weekends)."""
    out = d - timedelta(days=1)
    while out.weekday() >= 5:
        out -= timedelta(days=1)
    return out


def fetch_bars_via_schwab_for_session(
    client,
    symbol: str,
    session_date: date,
    include_extended_hours: bool = True,
) -> list[dict]:
    """
    Fetch OHLCV bars for a specific session using start_datetime/end_datetime.
    Ensures data aligns with session_date and prev trading day (no date mismatch).

    Fetches: prev_trading_day 00:00 ET through session_date 16:00 ET.
    """
    prev_date = _prev_trading_day(session_date)
    start_dt = datetime.combine(prev_date, time(0, 0), tzinfo=ET)
    end_dt = datetime.combine(session_date, time(16, 0), tzinfo=ET)

    try:
        import schwab as _schwab
        PH = _schwab.client.Client.PriceHistory
        resp = client.get_price_history(
            symbol,
            period_type=None,
            period=None,
            frequency_type=PH.FrequencyType.MINUTE,
            frequency=PH.Frequency.EVERY_MINUTE,
            start_datetime=start_dt,
            end_datetime=end_dt,
            need_extended_hours_data=include_extended_hours,
        )
    except Exception as e:
        raise ValueError(f"Schwab price history fetch failed: {e}") from e

    if resp is None or resp.status_code != 200:
        raise ValueError(f"Schwab price history failed: status={getattr(resp, 'status_code', '?')}")

    payload = resp.json()
    if "candles" not in payload:
        raise ValueError(
            f"Schwab pricehistory response missing 'candles' key (status={resp.status_code})"
        )
    candles = payload["candles"]
    return schwab_candles_to_bars(candles)


def fetch_bars_via_schwab(
    client,
    symbol: str,
    period_days: int = 2,
    include_extended_hours: bool = True,
) -> list[dict]:
    """
    Fetch OHLCV bars from Schwab price history API.
    Returns normalized bar dicts for the liquidity engine.

    Uses schwab-py get_price_history. Compatible with any ticker
    supported by the Schwab API.
    """
    try:
        import schwab as _schwab
        PH = _schwab.client.Client.PriceHistory
        period_map = {
            1: PH.Period.ONE_DAY,
            2: PH.Period.TWO_DAYS,
            3: PH.Period.THREE_DAYS,
            5: PH.Period.FIVE_DAYS,
            10: PH.Period.TEN_DAYS,
        }
        period = period_map.get(period_days, PH.Period.TWO_DAYS)
        resp = client.get_price_history(
            symbol,
            period_type=PH.PeriodType.DAY,
            period=period,
            frequency_type=PH.FrequencyType.MINUTE,
            frequency=PH.Frequency.EVERY_MINUTE,
            need_extended_hours_data=include_extended_hours,
        )
    except Exception:
        try:
            resp = client.get_price_history(
                symbol,
                periodType="day",
                period=period_days,
                frequencyType="minute",
                frequency=1,
                needExtendedHoursData=include_extended_hours,
            )
        except Exception as e:
            raise ValueError(f"Schwab price history fetch failed: {e}") from e

    if resp is None or resp.status_code != 200:
        raise ValueError(f"Schwab price history failed: status={getattr(resp, 'status_code', '?')}")

    payload = resp.json()
    if "candles" not in payload:
        raise ValueError(
            f"Schwab pricehistory response missing 'candles' key (status={resp.status_code})"
        )
    candles = payload["candles"]
    return schwab_candles_to_bars(candles)


def poll_and_callback(
    client,
    symbol: str,
    on_bars: BarCallback,
    interval_seconds: int = 60,
) -> None:
    """
    Poll Schwab periodically and invoke on_bars with latest normalized bars.
    Intended for use in a background thread; for one-shot fetch use fetch_bars_via_schwab.
    """
    import time
    while True:
        try:
            bars = fetch_bars_via_schwab(client, symbol)
            if bars:
                on_bars(bars)
        except Exception as e:
            log.debug("on_bars callback: %s", e, exc_info=True)
        time.sleep(interval_seconds)
