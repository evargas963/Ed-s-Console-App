"""Schwab's 1-minute bars -> the price levels. The level producer is a calculator (AGENTS.md rule
11): the same bars give the same snapshot, whenever it runs. Real data: the capture daemon's
newest receipt of each SPY and TSLA minute of 2026-10-01 and 10-02, taken in by the bar writer's
own check (server._schwab_bar), valued for Friday 2026-10-02."""

from __future__ import annotations

from datetime import date

import pytest

from liquidity_value_engine import PriceLevelSnapshot, bars_from_candles, build_price_level_snapshot
from server import _schwab_bar
from tests.feed_live_helper import daemon_bars

FIXTURE = "real_daemon_bars_spy_tsla_2026_10_01_02.json"
FRIDAY = date(2026, 10, 2)


def _bars(tk: str) -> list:
    newest = {}
    for r in sorted(daemon_bars(FIXTURE, tk), key=lambda r: r["ts_recv"]):
        newest[r["bar_start_ms"]] = r
    taken = [
        _schwab_bar(ms, r["open"], r["high"], r["low"], r["close"], r["volume"])
        for ms, r in sorted(newest.items())
    ]
    return bars_from_candles([b for b in taken if b is not None])


def _state(snap: PriceLevelSnapshot) -> dict:
    out = {s: getattr(snap, s, None) for s in PriceLevelSnapshot.__slots__}
    out["levels"] = {k: v.to_contract_dict() for k, v in snap.levels.items()}
    return out


@pytest.mark.parametrize("tk", ["SPY", "TSLA"])
def test_the_same_bars_give_the_same_level_snapshot(tk):
    bars = _bars(tk)
    first = build_price_level_snapshot(tk, FRIDAY, bars, bar_source=FIXTURE)
    second = build_price_level_snapshot(tk, FRIDAY, bars, bar_source=FIXTURE)
    assert first.levels, f"{tk}: no levels from a real session's bars"
    assert _state(first) == _state(second)
