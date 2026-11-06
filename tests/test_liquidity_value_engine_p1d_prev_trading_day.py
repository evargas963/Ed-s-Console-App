"""The prior session and its high, low and close are Schwab's daily candle, as sent.

Real data: Schwab's /pricehistory answers for SPY and TSLA of 2026-10-07 09:57 UTC
(fixtures/real_pricehistory_spy_tsla_2026_10_07.json): a year of daily candles and ten days of
1-minute bars, through the real bar writer (server._write_price_history) and the real level
producer. Schwab's daily close is the official close, which the last 1-minute bar's close is
not (SPY 2026-10-01: 763.99 against 764.03).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import server
from liquidity_value_engine import (
    PlaybookConfig,
    bars_from_candles,
    get_previous_day_levels,
    prior_session,
)
from time_et import ET

_FX = json.loads(
    (Path(__file__).parent / "fixtures" / "real_pricehistory_spy_tsla_2026_10_07.json").read_text(
        encoding="utf-8"
    )
)


def _held(symbol: str) -> tuple[list, list]:
    """(daily candles, 1-minute candles) of `symbol` as the bar writer holds them."""
    for a in _FX["answers"]:
        if a["symbol"] == symbol:
            series = "1m" if a["params"]["frequencyType"] == "minute" else "daily"
            if a["params"]["frequency"] == "1" or series == "daily":
                server._write_price_history(
                    {"symbol": symbol, "series": series, "answer": a["body"]}
                )
    try:
        return list(server._daily[symbol]), list(server._bars[symbol])
    finally:
        server._daily.pop(symbol, None)
        server._bars.pop(symbol, None)


def _sent(symbol: str, day: date) -> dict:
    """Schwab's daily candle for `day`, as it sent it."""
    (candle,) = [
        c
        for a in _FX["answers"]
        if a["symbol"] == symbol and a["params"]["frequencyType"] == "daily"
        for c in a["body"]["candles"]
        if datetime.fromtimestamp(c["datetime"] / 1000, ET).date() == day
    ]
    return candle


def test_the_prior_days_high_low_and_close_are_schwabs_daily_candle_as_sent():
    for symbol in ("SPY", "TSLA"):
        daily, minutes = _held(symbol)
        for session_day, prior_day in (
            (date(2026, 10, 2), date(2026, 10, 1)),
            (date(2026, 10, 6), date(2026, 10, 5)),
            (date(2026, 10, 7), date(2026, 10, 6)),
        ):
            out = get_previous_day_levels(
                bars_from_candles(minutes), prior_session(daily, session_day), PlaybookConfig()
            )
            sent = _sent(symbol, prior_day)
            assert out["prior_date"] == prior_day
            assert (out["pdh"], out["pdl"], out["pdc"]) == (
                sent["high"],
                sent["low"],
                sent["close"],
            )


def test_the_prior_close_is_schwabs_official_close_not_the_last_minutes():
    """SPY 2026-10-01: Schwab's daily close 763.99; its last regular 1-minute bar closed 764.03."""
    daily, minutes = _held("SPY")
    out = get_previous_day_levels(
        bars_from_candles(minutes), prior_session(daily, date(2026, 10, 2)), PlaybookConfig()
    )
    assert out["pdc"] == 763.99


def test_monday_s_prior_session_is_friday_schwab_sends_no_weekend_candle():
    daily, _minutes = _held("SPY")
    prior = prior_session(daily, date(2026, 10, 5))
    assert datetime.fromtimestamp(prior.ts, ET).date() == date(2026, 10, 2)


def test_no_daily_candle_before_the_session_leaves_the_prior_day_absent():
    daily, minutes = _held("SPY")
    first = min(datetime.fromtimestamp(c.ts, ET).date() for c in daily)
    assert prior_session(daily, first) is None
    assert get_previous_day_levels(bars_from_candles(minutes), None, PlaybookConfig()) == {}


def test_the_prior_value_area_is_estimated_from_that_sessions_regular_bars_only():
    """The POC and value area are ours (Schwab sends no volume profile), from the prior session's
    390 regular 1-minute bars, none before its open or after its close."""
    daily, minutes = _held("SPY")
    out = get_previous_day_levels(
        bars_from_candles(minutes), prior_session(daily, date(2026, 10, 2)), PlaybookConfig()
    )
    assert out["rth_bars"] == 390
    assert out["pd_val"] <= out["pd_poc"] <= out["pd_vah"]
    assert out["pdl"] <= out["pd_val"] and out["pd_vah"] <= out["pdh"]
