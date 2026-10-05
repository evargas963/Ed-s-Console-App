"""Session VWAP semantic fidelity -- RTH availability, on Schwab's CHART_EQUITY 1-minute bars as the
capture daemon recorded them (tests/fixtures/real_daemon_bars_spy_tsla_spx_2026_10_01_02.json,
every receipt), loaded by the console (server._load_bars) and handed to the producer the way the
console hands them (server._liquidity_1m_bars). The definition the producer states
(liquidity_value_engine.compute_session_vwap_series): over the session's RTH bars in time order,
the running sum(tp * v) / sum(v), tp = (high + low + close) / 3, one point after each bar once the
volume sum is above 0; a bar with no volume adds nothing and makes no point."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

import server
from instrument_identity import ticker_storage_key
from liquidity_value_engine import (
    _bars_to_list,
    compute_session_vwap_series,
    count_session_rth_positive_volume_bars,
)
from tests.feed_live_helper import daemon_bars, forget_daemon_bars, record_daemon_bars
from time_et import ET, is_trading_day_et

FRIDAY = date(2026, 8, 28)
SATURDAY = date(2026, 8, 29)
FX = "real_daemon_bars_spy_tsla_spx_2026_10_01_02.json"
SESSION = date(2026, 10, 1)                 # a whole regular session in the record
ROWS = daemon_bars(FX)


@pytest.fixture(scope="module")
def console_bars():
    """Each recorded symbol's bars as the console holds them after loading the daemon's record."""
    record_daemon_bars(ROWS)
    symbols = sorted({r["symbol"] for r in ROWS})
    try:
        server._load_bars()
        yield {tk: _bars_to_list(server._liquidity_1m_bars(tk)) for tk in symbols}
    finally:
        forget_daemon_bars(ROWS)
        for tk in symbols:
            server._bars.pop(ticker_storage_key(tk), None)


def _schwab_rth_bars(symbol: str) -> list[dict]:
    """Schwab's newest bar for each regular-session minute (09:30-16:00 ET) of SESSION, as recorded."""
    newest = {}
    for r in sorted(ROWS, key=lambda r: r["ts_recv"]):
        if r["symbol"] == symbol:
            newest[r["bar_start_ms"]] = r
    out = []
    for ms, r in sorted(newest.items()):
        t = datetime.fromtimestamp(ms / 1000, ET)
        if t.date() == SESSION and (9, 30) <= (t.hour, t.minute) < (16, 0):
            out.append(r)
    return out


def _vwap_by_definition(bars: list[dict]) -> list[tuple]:
    out, tpv, v, tp2v = [], 0.0, 0.0, 0.0
    for b in bars:
        if b["volume"] is None:
            continue
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        tpv, v, tp2v = tpv + tp * b["volume"], v + b["volume"], tp2v + tp * tp * b["volume"]
        if v > 0:
            w = tpv / v
            sd = max(0.0, tp2v / v - w * w) ** 0.5
            out.append((b["bar_start_ms"] / 1000, w, w + sd, w - sd, w + 2 * sd, w - 2 * sd))
    return out


def test_friday_is_trading_day_saturday_is_not() -> None:
    assert is_trading_day_et(FRIDAY.isoformat()) is True
    assert is_trading_day_et(SATURDAY.isoformat()) is False


@pytest.mark.parametrize("symbol", ["SPY", "TSLA"])
def test_first_positive_volume_rth_bar_produces_session_vwap(console_bars, symbol) -> None:
    """From Schwab's first RTH bar with volume the session VWAP exists, and every point is the
    definition's over Schwab's recorded bars (the newest receipt of each minute)."""
    schwab = _schwab_rth_bars(symbol)
    first = next(b for b in schwab if b["volume"])
    series = compute_session_vwap_series(console_bars[symbol], SESSION)
    assert series[0][0] == first["bar_start_ms"] / 1000
    assert series[0][1] == pytest.approx((first["high"] + first["low"] + first["close"]) / 3.0, abs=1e-4)
    want = _vwap_by_definition(schwab)
    assert [p[0] for p in series] == [p[0] for p in want]
    for got, exp in zip(series, want):
        assert got[1:] == pytest.approx(exp[1:], abs=1e-4), (symbol, got[0])
    assert count_session_rth_positive_volume_bars(console_bars[symbol], SESSION) == sum(
        1 for b in schwab if b["volume"])


def test_zero_volume_rth_bar_does_not_create_session_vwap(console_bars) -> None:
    """Schwab sends the index $SPX's CHART_EQUITY bars with volume 0 every minute: a 0 is a
    reported 0 (AGENTS.md rule 2), so the session has bars and no VWAP."""
    schwab = _schwab_rth_bars("$SPX")
    assert schwab and all(b["volume"] == 0 for b in schwab)
    assert compute_session_vwap_series(console_bars["$SPX"], SESSION) == []
    assert count_session_rth_positive_volume_bars(console_bars["$SPX"], SESSION) == 0


def test_next_rth_after_saturday_2026_08_29_is_monday_2026_08_31() -> None:
    d = SATURDAY + timedelta(days=1)
    while not is_trading_day_et(d.isoformat()):
        d += timedelta(days=1)
    assert d == date(2026, 8, 31)
    assert d.strftime("%A") == "Monday"
