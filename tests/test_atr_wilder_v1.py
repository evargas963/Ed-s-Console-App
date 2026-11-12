"""The ATR is Wilder's (Wilder 1978, New Concepts in Technical Trading Systems).

The first ATR is the simple mean of the first 14 true ranges; each later one is
(ATR_(t-1) * 13 + TR_t) / 14. Expected values are worked out here, independently of the code,
as Wilder's recursion unrolled: ATR_n = (13/14)^(n-14) * seed + sum of (1/14) * (13/14)^(n-k) *
TR_k over the true ranges after the seed. Real candles Schwab sent (/pricehistory): the daily of
SPY and TSLA to 2026-10-06 and $SPX's 500 days; the weekly and monthly of SPY and AMD, 2026-11-12.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from micro_structure import Candle
from terrain_atr import compute_atrs
from time_et import ET

_FX = Path(__file__).resolve().parent / "fixtures"


def _candles(rows: list[dict]) -> list[Candle]:
    return [Candle(c["datetime"] / 1000, c["open"], c["high"], c["low"], c["close"]) for c in rows]


def _daily() -> dict[str, list[Candle]]:
    answers = json.loads((_FX / "real_pricehistory_spy_tsla_2026_10_07.json").read_text())
    out = {
        a["symbol"]: _candles(a["body"]["candles"])
        for a in answers["answers"]
        if a["series"] == "1d"
    }
    spx = json.loads((_FX / "real_schwab_daily_spx_2026_10.json").read_text())
    out["$SPX"] = _candles(spx["message"]["candles"])
    return out


def _period_candles(daily: list[Candle], key) -> list[tuple[float, float, float]]:
    """(high, low, close) of each period, by `key` of each candle's ET date, oldest first."""
    groups: dict = {}
    for c in daily:
        groups.setdefault(key(datetime.fromtimestamp(c.ts, ET).date()), []).append(c)
    return [(max(c.high for c in g), min(c.low for c in g), g[-1].close) for g in groups.values()]


def _wilder_unrolled(hlc: list[tuple[float, float, float]], n: int = 14) -> float | None:
    tr = [
        max(h - lo, abs(h - prev[2]), abs(lo - prev[2]))
        for prev, (h, lo, _c) in zip(hlc, hlc[1:], strict=False)
    ]
    if len(tr) < n:
        return None
    later = tr[n:]
    m = len(later)
    keep = (n - 1) / n
    return keep**m * (sum(tr[:n]) / n) + sum(
        (1 / n) * keep ** (m - 1 - i) * x for i, x in enumerate(later)
    )


def _weekly_monthly() -> dict[str, dict[str, list[Candle]]]:
    """Schwab's own weekly and monthly candles of SPY, AMD and TSLA, asked 2026-11-12."""
    answers = json.loads((_FX / "real_pricehistory_weekly_monthly_2026_11_12.json").read_text())
    out: dict[str, dict[str, list[Candle]]] = {}
    for a in answers["answers"]:
        out.setdefault(a["symbol"], {})[a["series"]] = _candles(a["body"]["candles"])
    return out


@pytest.mark.parametrize("ticker", ["SPY", "TSLA", "$SPX"])
def test_daily_weekly_and_monthly_atr_are_wilders(ticker):
    """Each ATR is Wilder's on Schwab's own candles of that length; none sent: none."""
    daily = _daily()[ticker]
    sent = _weekly_monthly()[ticker] if ticker != "$SPX" else {"1w": [], "1mo": []}
    series = (daily, sent["1w"], sent["1mo"])
    atr = compute_atrs(*series)
    expected = [_wilder_unrolled(_period_candles(candles, lambda d: d)) for candles in series]
    assert expected[0] is not None and (ticker == "$SPX" or None not in expected)
    for got, want in zip((atr.daily, atr.weekly, atr.monthly), expected, strict=True):
        assert (got is None) == (want is None)
        if want is not None:
            assert got == pytest.approx(want, rel=1e-12)


@pytest.mark.parametrize("ticker", ["SPY", "AMD", "TSLA"])
def test_weekly_and_monthly_atr_are_of_schwabs_weekly_and_monthly_candles(ticker):
    """104 weekly and 24 monthly candles as Schwab sent them: Wilder's ATR(14) of each."""
    sent = _weekly_monthly()[ticker]
    atr = compute_atrs([], sent["1w"], sent["1mo"])
    assert (len(sent["1w"]), len(sent["1mo"]), atr.daily) == (104, 24, None)
    for got, candles in ((atr.weekly, sent["1w"]), (atr.monthly, sent["1mo"])):
        want = _wilder_unrolled([(c.high, c.low, c.close) for c in candles])
        assert want is not None and got == pytest.approx(want, rel=1e-12)


def test_fewer_than_fourteen_true_ranges_is_none():
    """SPY's first 14 daily candles give 13 true ranges: no ATR. 15 give 14: the simple mean."""
    daily = _daily()["SPY"]
    assert compute_atrs(daily[:14], [], []).daily is None
    first = _period_candles(daily[:15], lambda d: d)
    assert compute_atrs(daily[:15], [], []).daily == pytest.approx(
        _wilder_unrolled(first), rel=1e-12
    )
