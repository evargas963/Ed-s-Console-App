"""The ATR is Wilder's (Wilder 1978, New Concepts in Technical Trading Systems).

The first ATR is the simple mean of the first 14 true ranges; each later one is
(ATR_(t-1) * 13 + TR_t) / 14. Expected values are worked out here, independently of the code,
as Wilder's recursion unrolled: ATR_n = (13/14)^(n-14) * seed + sum of (1/14) * (13/14)^(n-k) *
TR_k over the true ranges after the seed. Real daily candles Schwab sent (/pricehistory): SPY and
TSLA to 2026-10-06, and $SPX's 500 days.
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


@pytest.mark.parametrize("ticker", ["SPY", "TSLA", "$SPX"])
def test_daily_weekly_and_monthly_atr_are_wilders(ticker):
    daily = _daily()[ticker]
    atr = compute_atrs(daily)
    expected = [
        _wilder_unrolled(_period_candles(daily, key))
        for key in (lambda d: d, lambda d: d.isocalendar()[:2], lambda d: (d.year, d.month))
    ]
    assert expected[0] is not None and expected[1] is not None
    for got, want in zip((atr.daily, atr.weekly, atr.monthly), expected, strict=True):
        assert (got is None) == (want is None)
        if want is not None:
            assert got == pytest.approx(want, rel=1e-12)


def test_fewer_than_fourteen_true_ranges_is_none():
    """SPY's first 14 daily candles give 13 true ranges: no ATR. 15 give 14: the simple mean."""
    daily = _daily()["SPY"]
    assert compute_atrs(daily[:14]).daily is None
    first = _period_candles(daily[:15], lambda d: d)
    assert compute_atrs(daily[:15]).daily == pytest.approx(_wilder_unrolled(first), rel=1e-12)
