"""Bars rolled up to a chart timeframe, and the windows built on them: a value is served only for
a window that has ended, and a curve point carries its chart bar's own time. Real SPY bars of
2026-09-29 from the first stored bar (09:15 ET) to 10:29 ET
(tests/fixtures/real_spy_1m_bars_2026_09_29_open.json)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import liquidity_value_engine as lve
import server as srv
from db import EdDB
from liquidity_value_engine import _bars_to_list, build_price_level_snapshot
from micro_structure import Candle
from terrain_atr import compute_atr_pair
from time_et import ET

BARS = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_spy_1m_bars_2026_09_29_open.json")
                  .read_text(encoding="utf-8"))["bars"]
TUESDAY = datetime(2026, 9, 29, tzinfo=ET).date()


def _at(h: int, m: int) -> float:
    return datetime(2026, 9, 29, h, m, tzinfo=ET).timestamp()


def _before(h: int, m: int) -> list:
    return [b for b in BARS if b["timestamp"] / 1000.0 < _at(h, m)]


def test_the_opening_range_is_served_once_its_window_has_ended():
    """2026-09-30 audit: at 09:31 the "opening range" was the range of one bar, and it moved with
    every bar until 09:45. It is absent, with the reason, until the window's last minute (09:44)
    has completed; then it is the high and low of 09:30-09:44, and no bar before the open or
    after the window is in it."""
    forming = build_price_level_snapshot("SPY", TUESDAY, _bars_to_list(_before(9, 44)), bar_source="price_bars_1m")
    assert forming.price("ORB_HIGH") is None and forming.price("ORB_LOW") is None
    assert {"family": "opening_range", "reason": (
        "the opening range is still forming: its first 15 minutes end Tue 09/29 08:45 AM CT, "
        "and no later bar has arrived")} in forming.families_absent

    window = [b for b in BARS if _at(9, 30) <= b["timestamp"] / 1000.0 < _at(9, 45)]
    assert len(window) == 15
    for cut in (_before(9, 45), BARS):                  # the moment it ends, and an hour later
        done = build_price_level_snapshot("SPY", TUESDAY, _bars_to_list(cut), bar_source="price_bars_1m")
        assert done.price("ORB_HIGH") == max(b["high"] for b in window)
        assert done.price("ORB_LOW") == min(b["low"] for b in window)
        assert "opening_range" not in {f["family"] for f in done.families_absent}


def test_no_overnight_level_is_built_from_the_minutes_around_the_close():
    """The stored bars hold 09:15 ET to 15 minutes after the close (measured 2026-09-30, all 43
    board tickers, 7 days: no bar outside it), so "overnight high / low" was the range of the
    15 minutes before the open and after the prior close. It is absent, with that reason."""
    snap = build_price_level_snapshot("SPY", TUESDAY, _bars_to_list(BARS), bar_source="price_bars_1m")
    assert not [lid for lid in snap.levels if "OVERNIGHT" in lid]
    assert {"family": "overnight", "reason": lve.OVERNIGHT_ABSENT_REASON} in snap.families_absent


def test_the_vwap_curve_is_stamped_with_its_chart_bars_own_time(monkeypatch, pin_clock):
    """2026-09-30 audit: on the 60-minute and daily charts the VWAP point was stamped 09:30 (its
    own first minute) while its chart bar is stamped 09:15 (the bar's first stored minute), so the
    point sat at a time no bar has. Every point carries the time of the chart bar it belongs to."""
    pin_clock(2026, 9, 29, 10, 31)
    monkeypatch.setattr(lve, "_MATERIALIZED_SNAPSHOTS", {})
    monkeypatch.setattr(srv, "_liquidity_1m_bars", lambda tk: BARS)
    monkeypatch.setattr(srv, "resolve_spot", lambda tk: (None, "none", None))
    srv._publish_price_levels("SPY")
    one_minute = [{"t": b["timestamp"] / 1000.0, "o": b["open"], "h": b["high"], "l": b["low"],
                   "c": b["close"], "v": b["volume"]} for b in BARS]
    final_vwap = json.loads(srv.get_levels(ticker="SPY", tf="1").body)["vwap_series"][-1][1]
    for tf in ("3", "5", "15", "30", "60", "D"):
        bar_times = [b["t"] for b in srv.aggregate_bars(one_minute, tf)]
        curve = json.loads(srv.get_levels(ticker="SPY", tf=tf).body)["vwap_series"]
        assert curve and {p[0] for p in curve} <= set(bar_times), tf
        assert curve[-1][1] == final_vwap, tf                   # each bar's value as of its last minute
    hourly = json.loads(srv.get_levels(ticker="SPY", tf="60").body)["vwap_series"]
    assert [p[0] for p in hourly] == [_at(9, 15), _at(10, 0)]


def test_a_rolled_up_bar_cut_by_the_limit_is_not_served(monkeypatch, tmp_path):
    """`limit` counts 1-minute bars. The newest 20 of these end 10:29, so they start 10:10: the
    10:00 fifteen-minute bar was served built from 10:10-10:14 alone, with 10:10's open as its
    open. A rolled bar the cut may have shortened is not served."""
    db = EdDB(tmp_path / "bars.db", allow_noncanonical=True)
    monkeypatch.setattr(srv, "get_db", lambda: db)
    db.upsert_1m_bars("SPY", [Candle(ts=b["timestamp"] / 1000.0, open=b["open"], high=b["high"], low=b["low"],
                                     close=b["close"], volume=b["volume"]) for b in BARS])
    cut = json.loads(srv.get_bars1m(ticker="SPY", limit=20, tf="15").body)["bars"]
    by_minute = {b["timestamp"] / 1000.0: b for b in BARS}
    assert [b["t"] for b in cut] == [_at(10, 15)]
    assert cut[0]["o"] == by_minute[_at(10, 15)]["open"]
    # a read that holds every stored bar cuts nothing
    whole = json.loads(srv.get_bars1m(ticker="SPY", limit=500, tf="15").body)["bars"]
    assert [b["t"] for b in whole] == [_at(9, 15), _at(9, 30), _at(9, 45), _at(10, 0), _at(10, 15)]
    # 1-minute bars are never cut by their own limit
    assert len(json.loads(srv.get_bars1m(ticker="SPY", limit=20, tf="1").body)["bars"]) == 20


@pytest.fixture
def atr_db(tmp_path):
    """Stand-in (named): 16 past days, each with a 10:00 and a 15:00 bar 10.00 wide closing at
    105, and today (Wednesday 2026-09-30) with one 09:31 bar 1.00 wide."""
    path = tmp_path / "atr.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, open REAL, high REAL, "
                "low REAL, close REAL)")
    day = datetime(2026, 9, 14, tzinfo=ET)
    for i in range(16):
        for hh in (10, 15):
            ts = (day + timedelta(days=i)).replace(hour=hh).timestamp()
            con.execute("INSERT INTO price_bars_1m VALUES ('ATRX', ?, 105, 110, 100, 105)", (ts,))
    con.execute("INSERT INTO price_bars_1m VALUES ('ATRX', ?, 105, 105.5, 104.5, 105)",
                (datetime(2026, 9, 30, 9, 31, tzinfo=ET).timestamp(),))
    con.commit()
    con.close()
    return str(path)


def test_the_atr_leaves_out_the_candle_still_forming(atr_db):
    """2026-09-30 audit: the daily ATR took in today's candle from its first bar, and the
    15-minute ATR the period still open: a candle still forming has a smaller range than it
    closes with, so both read low early in the day and early in each period. Completed candles
    only."""
    with_today = round((13 * 10.0 + 1.0) / 14, 4)
    early = compute_atr_pair(atr_db, "ATRX", datetime(2026, 9, 30, 9, 40, tzinfo=ET))
    assert (early.daily, early.m15) == (10.0, 10.0)
    period_closed = compute_atr_pair(atr_db, "ATRX", datetime(2026, 9, 30, 9, 46, tzinfo=ET))
    assert (period_closed.daily, period_closed.m15) == (10.0, with_today)
    # today's stored bars end 16:15 ET: the day's candle is complete from then
    assert compute_atr_pair(atr_db, "ATRX", datetime(2026, 9, 30, 16, 14, tzinfo=ET)).daily == 10.0
    assert compute_atr_pair(atr_db, "ATRX", datetime(2026, 9, 30, 16, 15, tzinfo=ET)).daily == with_today
