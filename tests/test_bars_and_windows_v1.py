"""Bars rolled up to a chart timeframe, and the windows built on them: a value is served only for
a window that has ended, and a curve point carries its chart bar's own time. Real SPY bars of
2026-09-29 from the first stored bar (09:15 ET) to 10:29 ET
(tests/fixtures/real_spy_1m_bars_2026_09_29_open.json)."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import app.options.order_flow.streaming as ofs
import liquidity_value_engine as lve
import live_price_rows
import server as srv
from app.market_data.schwab.streaming import live_ui
from app.market_data.schwab.streaming.live_push import is_forwarded
from db import EdDB
from liquidity_value_engine import _bars_to_list, build_price_level_snapshot
from micro_structure import Candle
from stream_spine import CONNECTION, CONNECTION_CLOSED, MessageBus, bar_msg, subscription_msg
from terrain_atr import compute_atr_pair
from time_et import ET

BARS = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_spy_1m_bars_2026_09_29_open.json")
                  .read_text(encoding="utf-8"))["bars"]
TUESDAY = datetime(2026, 9, 29, tzinfo=ET).date()
#: why these levels have no prior daily candle: none is given (Schwab's comes from the daemon)
NO_DAILY = "no Schwab daily candle in this test"


def _at(h: int, m: int) -> float:
    return datetime(2026, 9, 29, h, m, tzinfo=ET).timestamp()


def _before(h: int, m: int) -> list:
    return [b for b in BARS if b["timestamp"] / 1000.0 < _at(h, m)]


def test_the_opening_range_is_served_once_its_window_has_ended():
    """2026-09-30 audit: at 09:31 the "opening range" was the range of one bar, and it moved with
    every bar until 09:45. It is absent, with the reason, until the window's last minute (09:44)
    has completed; then it is the high and low of 09:30-09:44, and no bar before the open or
    after the window is in it."""
    forming = build_price_level_snapshot("SPY", TUESDAY, _bars_to_list(_before(9, 44)), bar_source="price_bars_1m",
                                         prior_day=None, prior_day_absent_reason=NO_DAILY)
    assert forming.price("ORB_HIGH") is None and forming.price("ORB_LOW") is None
    assert {"family": "opening_range", "reason": (
        "the opening range is still forming: its first 15 minutes end Tue 09/29 08:45 AM CT, "
        "and no later bar has arrived")} in forming.families_absent

    window = [b for b in BARS if _at(9, 30) <= b["timestamp"] / 1000.0 < _at(9, 45)]
    assert len(window) == 15
    for cut in (_before(9, 45), BARS):                  # the moment it ends, and an hour later
        done = build_price_level_snapshot("SPY", TUESDAY, _bars_to_list(cut), bar_source="price_bars_1m",
                                          prior_day=None, prior_day_absent_reason=NO_DAILY)
        assert done.price("ORB_HIGH") == max(b["high"] for b in window)
        assert done.price("ORB_LOW") == min(b["low"] for b in window)
        assert "opening_range" not in {f["family"] for f in done.families_absent}


def test_no_overnight_level_is_built_from_the_minutes_around_the_close():
    """The stored bars hold 09:15 ET to 15 minutes after the close (measured 2026-09-30, all 43
    board tickers, 7 days: no bar outside it), so "overnight high / low" was the range of the
    15 minutes before the open and after the prior close. It is absent, with that reason."""
    snap = build_price_level_snapshot("SPY", TUESDAY, _bars_to_list(BARS), bar_source="price_bars_1m",
                                      prior_day=None, prior_day_absent_reason=NO_DAILY)
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
        bar_times = [b["t"] for b in live_price_rows.aggregate_bars(one_minute, tf)]
        curve = json.loads(srv.get_levels(ticker="SPY", tf=tf).body)["vwap_series"]
        assert curve and {p[0] for p in curve} <= set(bar_times), tf
        assert curve[-1][1] == final_vwap, tf                   # each bar's value as of its last minute
    # a chart bar's time is its bucket's start (the chart convention), so the first hourly bar, which
    # holds 09:15-09:59, is stamped 09:00 (it was 09:15, its first stored minute)
    hourly = json.loads(srv.get_levels(ticker="SPY", tf="60").body)["vwap_series"]
    assert [p[0] for p in hourly] == [_at(9, 0), _at(10, 0)]


def test_the_session_levels_take_their_currency_from_the_daemons_coverage(monkeypatch, pin_clock):
    """The levels were called stale 2 minutes after their newest bar, but Schwab sends no bar for
    a minute with no trade (2026-09-30: TSL ~154 and MTA ~120 regular-session minutes read STALE
    on a healthy feed), and it was a second authority beside the daemon's coverage. The levels,
    the VWAP curve and every value built from today's bars take the daemon's verdict (barstate,
    pushed to the console): a quiet stretch inside the stream's unbroken coverage is current; the
    Schwab socket closing makes them stale with the daemon's reason (the minutes since its last
    bar were covered only while the stream was unbroken: they are asked of the price history,
    here empty); with no verdict from the daemon they are stale. Real SPY bars of 2026-09-29
    09:15-10:29 ET, streamed to the daemon's real live_ui; the quiet stretch after 10:29 (no more
    bars) is the stand-in for minutes with no trade."""
    import time as _time
    pin_clock(2026, 9, 29, 10, 31)
    monkeypatch.setattr(lve, "_MATERIALIZED_SNAPSHOTS", {})
    monkeypatch.setattr(srv, "_liquidity_1m_bars", lambda tk: BARS)
    monkeypatch.setattr(srv, "resolve_spot", lambda tk: (None, "none", None))
    monkeypatch.setattr(ofs, "_bar_states", {})
    srv._publish_price_levels("SPY")
    clock = {"now": 0.0}
    bus = MessageBus()
    states = bus.subscribe("barstate.", maxsize=1024, name="test_console")
    ui = live_ui.LiveUiServer(bus, lambda: {}, {}, clock=lambda: clock["now"], history_fn=lambda *a: [],
                              daily_fn=lambda *a: [])

    async def daemon(h, m, s=0, close=False):
        if close:                                                 # the Schwab socket closes
            ui.on_subscription(subscription_msg(service=CONNECTION, command=CONNECTION_CLOSED, symbols=[],
                                                code=0, reason="the Schwab socket closed", ts=clock["now"]))
        clock["now"] = datetime(2026, 9, 29, h, m, s, tzinfo=ET).timestamp()
        ui.tick(clock["now"])                                     # the daemon's clock
        while ui._asks:
            await asyncio.gather(*list(ui._asks))

    def served():
        while not states.queue.empty():
            topic, msg = states.queue.get_nowait()
            assert is_forwarded(topic, msg)                       # live_push forwards it
            ofs._ingest_pushed(topic, msg)                        # the console's ingest
        monkeypatch.setattr(_time, "time", lambda: clock["now"])
        return json.loads(srv.get_levels(ticker="SPY", tf="1").body)

    async def stream():
        clock["now"] = _at(9, 0)
        ui.on_subscription(subscription_msg(service="CHART_EQUITY", command="SUBS", symbols=["SPY"], code=0,
                                            reason="ok", ts=_at(9, 0)))
        for b in BARS:
            clock["now"] = b["timestamp"] / 1000.0 + 62.7
            ui.on_bar(bar_msg(symbol="SPY", bar_start_ms=b["timestamp"], open=b["open"], high=b["high"],
                              low=b["low"], close=b["close"], volume=b["volume"], src="schwab_chart",
                              ts_recv=clock["now"]))
        await daemon(10, 45)                                      # no bar since 10:29: no trade
    asyncio.run(stream())
    session_rows = lambda body: [r["staleness"] for r in body["levels"] if r.get("semantic_scope") == "session_rth"]  # noqa: E731
    quiet = served()
    assert quiet["session_levels"] == {"state": srv.PRICE_LEVEL_CURRENT, "stale": False, "reason": ""}
    assert session_rows(quiet) and all(s["stale"] is False for s in session_rows(quiet))
    asyncio.run(daemon(10, 48, close=True))
    stopped = served()
    assert stopped["session_levels"] == {"state": srv.PRICE_LEVEL_STALE, "stale": True, "reason": (
        "minutes Tue 09/29 09:30 AM CT – Tue 09/29 09:47 AM CT not received from Schwab "
        "(the symbol's 1-minute bar stream is not subscribed now)")}
    assert all(s["stale"] is True for s in session_rows(stopped))
    monkeypatch.setattr(ofs, "_bar_states", {})                   # the daemon gone: no verdict
    assert served()["session_levels"]["state"] == srv.PRICE_LEVEL_STALE


def _desk(monkeypatch, pin_clock, stored, streamed=BARS):
    """The daemon's real live_ui streaming `streamed` (every one of BARS) for SPY (subscribed at 09:00 ET) and
    the console: its levels published from `stored` (the bars its store holds), its ingest of the
    daemon's pushed verdicts. Returns (tick(h, m, s): the daemon's beat at that ET instant, the
    verdicts delivered to the console; served(h, m, s): /api/levels at that instant)."""
    import time as _time
    pin_clock(2026, 9, 29, 10, 31)
    monkeypatch.setattr(lve, "_MATERIALIZED_SNAPSHOTS", {})
    monkeypatch.setattr(srv, "_liquidity_1m_bars", lambda tk: stored)
    monkeypatch.setattr(srv, "resolve_spot", lambda tk: (None, "none", None))
    monkeypatch.setattr(ofs, "_bar_states", {})
    srv._publish_price_levels("SPY")
    clock = {"now": _at(9, 0)}
    bus = MessageBus()
    states = bus.subscribe("barstate.", maxsize=4096, name="test_console")
    ui = live_ui.LiveUiServer(bus, lambda: {}, {}, clock=lambda: clock["now"], history_fn=lambda *a: [],
                              daily_fn=lambda *a: [])

    async def stream():
        ui.on_subscription(subscription_msg(service="CHART_EQUITY", command="SUBS", symbols=["SPY"], code=0,
                                            reason="ok", ts=_at(9, 0)))
        for b in streamed:
            clock["now"] = b["timestamp"] / 1000.0 + 62.7
            ui.on_bar(bar_msg(symbol="SPY", bar_start_ms=b["timestamp"], open=b["open"], high=b["high"],
                              low=b["low"], close=b["close"], volume=b["volume"], src="schwab_chart",
                              ts_recv=clock["now"]))
    asyncio.run(stream())

    async def beat(h, m, s):
        clock["now"] = datetime(2026, 9, 29, h, m, s, tzinfo=ET).timestamp()
        ui.tick(clock["now"])
        while ui._asks:
            await asyncio.gather(*list(ui._asks))

    def tick(h, m, s=0, delivered=True):
        asyncio.run(beat(h, m, s))
        while not states.queue.empty():
            topic, msg = states.queue.get_nowait()
            if delivered:
                ofs._ingest_pushed(topic, msg)

    def served(h, m, s=0):
        monkeypatch.setattr(_time, "time", lambda: datetime(2026, 9, 29, h, m, s, tzinfo=ET).timestamp())
        return json.loads(srv.get_levels(ticker="SPY", tf="1").body)["session_levels"]
    return tick, served


def test_levels_built_without_minutes_the_daemon_holds_are_stale(monkeypatch, pin_clock):
    """The levels took their currency from the daemon's coverage but were built from the
    console's store: with the store holding bars only through 10:00 ET (the console's push was
    down 10:00-10:29 ET, those bars never written) they were served current at 10:45 ET, built
    from bars 29 minutes old. They are current only when built from every minute the daemon holds
    (the same count and newest minute); otherwise stale, naming both. Real SPY bars of 2026-09-29
    09:15-10:29 ET."""
    stored = [b for b in BARS if b["timestamp"] / 1000.0 <= _at(10, 0)]
    tick, served = _desk(monkeypatch, pin_clock, stored)
    tick(10, 45)
    assert served(10, 45) == {"state": srv.PRICE_LEVEL_STALE, "stale": True, "reason": (
        f"levels built from {len(stored)} bars through Tue 09/29 09:00 AM CT; the capture daemon holds "
        f"{len(BARS)} of today's minutes through Tue 09/29 09:29 AM CT: the minutes not in the store are missing")}


def test_levels_built_from_a_different_set_of_the_same_size_and_newest_are_stale(monkeypatch, pin_clock):
    """The minute check compared only the count and the newest minute: a store lacking one minute
    the daemon holds and holding one it does not read current. The sets are compared (by digest)
    and the reason says the store holds minutes the daemon does not. Real SPY bars of 2026-09-29
    09:15-10:29 ET; the daemon without 09:40 ET and the store without 09:50 ET, stand-ins."""
    daemon = [b for b in BARS if b["timestamp"] / 1000.0 != _at(9, 40)]
    stored = [b for b in BARS if b["timestamp"] / 1000.0 != _at(9, 50)]
    tick, served = _desk(monkeypatch, pin_clock, stored, streamed=daemon)
    tick(10, 45)
    assert served(10, 45) == {"state": srv.PRICE_LEVEL_STALE, "stale": True, "reason": (
        f"levels built from {len(stored)} bars through Tue 09/29 09:29 AM CT; the capture daemon holds "
        f"{len(daemon)} of today's minutes through Tue 09/29 09:29 AM CT: the store holds minutes the capture "
        f"daemon does not, so the levels are not built from the daemon's minutes")}


def test_a_bar_the_store_failed_to_write_makes_the_levels_stale_with_the_failure(monkeypatch, pin_clock):
    """A streamed bar the console failed to write (logged) left the levels built without it and
    served current. They are stale, and the reason names the failure. Real SPY bars of
    2026-09-29 09:15-10:29 ET; the store's failure on the 10:29 bar a stand-in."""
    monkeypatch.setattr(srv, "_store_problems", {})
    stored = []

    class _Store:
        def upsert_1m_bars(self, symbol, candles, backfill, source):
            if candles[0].ts == _at(10, 29):
                raise sqlite3.OperationalError("database is locked")
            stored.extend({"timestamp": int(c.ts * 1000), "open": c.open, "high": c.high, "low": c.low,
                           "close": c.close, "volume": c.volume} for c in candles)
    monkeypatch.setattr(srv, "get_db", lambda: _Store())
    monkeypatch.setattr(srv, "_publish_price_levels", lambda tk: None)        # built below, once
    for b in BARS:                                                            # each minute as it arrives
        srv._write_streamed_bars([bar_msg(symbol="SPY", bar_start_ms=b["timestamp"], open=b["open"], high=b["high"],
                                          low=b["low"], close=b["close"], volume=b["volume"], src="schwab_chart",
                                          ts_recv=b["timestamp"] / 1000.0 + 62.7)])
    problems = dict(srv._store_problems)
    monkeypatch.undo()
    monkeypatch.setattr(srv, "_store_problems", problems)
    tick, served = _desk(monkeypatch, pin_clock, stored)
    tick(10, 45)
    assert served(10, 45)["reason"] == (
        f"levels built from {len(BARS) - 1} bars through Tue 09/29 09:28 AM CT; the capture daemon holds "
        f"{len(BARS)} of today's minutes through Tue 09/29 09:29 AM CT: the minutes not in the store are missing (the bar of "
        "Tue 09/29 09:29 AM CT was not written to the store: OperationalError: database is locked)")


def test_a_verdict_the_console_stopped_receiving_is_unknown(monkeypatch, pin_clock):
    """The console kept the daemon's last bar verdict with no regard to its time: one dropped
    after it left an old "current" standing. The daemon re-sends every verdict on its beat; one
    older than the beat allows is unknown, and the levels are stale saying when it is from. Real
    SPY bars of 2026-09-29 09:15-10:29 ET; the verdicts not delivered after 10:45 the stand-in for
    a drop."""
    tick, served = _desk(monkeypatch, pin_clock, BARS)
    tick(10, 45)
    assert served(10, 45)["state"] == srv.PRICE_LEVEL_CURRENT
    tick(10, 45, 5, delivered=False)
    assert served(10, 45, 5) == {"state": srv.PRICE_LEVEL_STALE, "stale": True, "reason": (
        "the capture daemon's last report on this ticker's 1-minute bars is from Tue 09/29 09:45:00 AM CT; "
        "it reports every second")}


def test_after_the_collect_window_the_levels_are_the_sessions(monkeypatch, pin_clock):
    """After the collect window (16:15 ET) the session's levels are served as of their newest
    bar, labelled the session's (not stale, not current). Real SPY bars of 2026-09-29
    09:15-10:29 ET; the quiet stretch after 10:29 the stand-in for minutes with no trade."""
    tick, served = _desk(monkeypatch, pin_clock, BARS)
    tick(16, 20)
    assert served(16, 20) == {"state": srv.PRICE_LEVEL_SESSION_ENDED, "stale": False, "reason": (
        "the session's bars have ended; as of the bar ending Tue 09/29 09:30 AM CT")}


def test_before_the_sessions_first_bar_the_levels_say_it_has_not_started():
    """At a premarket instant the session levels read "the session's bars have ended", as if the
    day were over. Before today's first bar the session has not started, and the reason says when
    its first bar ends. Stated instant: Wednesday 2026-09-30 08:00 ET; the levels are the prior
    session's (Tuesday's bars to 10:29 ET), a stand-in."""
    now = datetime(2026, 9, 30, 8, 0, tzinfo=ET).timestamp()
    snap = build_price_level_snapshot("SPY", TUESDAY, _bars_to_list(BARS), bar_source="price_bars_1m",
                                      prior_day=None, prior_day_absent_reason=NO_DAILY)
    st = srv.price_level_staleness("session_rth", snap, now, None, None)
    assert st == {"state": srv.PRICE_LEVEL_SESSION_NOT_STARTED, "stale": False,
                  "reason": "today's session has not started: its first 1-minute bar ends Wed 09/30 08:16 AM CT"}
    # after 09:15 ET with no verdict from the daemon on its bars the levels are stale
    assert srv.price_level_staleness("session_rth", snap, now + 78 * 60, None, None)["state"] == srv.PRICE_LEVEL_STALE


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
    """2026-09-30 audit: the 15-minute ATR took in the period still open: a candle still forming
    has a smaller range than it closes with, so it read low early in each period. Completed
    candles only. The daily ATR is Schwab's daily candles' (never minutes rolled into days,
    operator 2026-10-01): without them it is absent with the reason given."""
    with_today = round((13 * 10.0 + 1.0) / 14, 4)
    early = compute_atr_pair(atr_db, "ATRX", datetime(2026, 9, 30, 9, 40, tzinfo=ET), None, NO_DAILY)
    assert (early.daily, early.daily_reason, early.m15) == (None, NO_DAILY, 10.0)
    period_closed = compute_atr_pair(atr_db, "ATRX", datetime(2026, 9, 30, 9, 46, tzinfo=ET), None, NO_DAILY)
    assert period_closed.m15 == with_today


def test_the_published_atr_is_judged_at_the_instant_its_entry_point_passes(atr_db, monkeypatch):
    """The levels' ATR read the wall clock below its entry point (now_et for the candles,
    time.time for the cache), so one publication was judged at two clocks. It is computed at the
    `now` the levels producer was given, and kept for ATR_TTL_SEC of that clock. Stated instants:
    Wednesday 2026-09-30 09:40, 09:46 and 09:56 ET."""
    class _Db:
        db_path = atr_db
    monkeypatch.setattr(srv, "get_db", lambda: _Db())
    monkeypatch.setattr(srv, "_atr_cache", {})
    with_today = round(round((13 * 10.0 + 1.0) / 14, 4), 3)
    at = lambda h, m: datetime(2026, 9, 30, h, m, tzinfo=ET).timestamp()   # noqa: E731
    assert srv._atr_fields("ATRX", at(9, 40))["atr_15m"] == 10.0
    assert srv._atr_fields("ATRX", at(9, 46))["atr_15m"] == 10.0          # within ATR_TTL_SEC of 09:40
    assert srv._atr_fields("ATRX", at(9, 56))["atr_15m"] == with_today    # recomputed at 09:56
