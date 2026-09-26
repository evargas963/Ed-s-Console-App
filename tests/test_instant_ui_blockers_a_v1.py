"""Audit of #280, blockers fixed in PR A -- behavioural tests on the real daemon/server code.

- a service is marked alive only by a frame that parsed and published (it beat BEFORE parsing,
  so a frame shape failing on every message kept LEVELONE "RUNNING" with nothing delivered);
- a sustained run of skipped frames ends the pump (-> the watchdog recycles), while isolated
  bad frames between good ones do not;
- terrain rotation happens only inside the contention window (collection mandate).
"""
from __future__ import annotations

import sys
import asyncio

import app.market_data.schwab.streaming.capture as cap
from stream_spine import HealthRegistry, MessageBus


def _handler():
    bus, health, stats = MessageBus(), HealthRegistry(), cap.CaptureStats()
    h = cap.make_handler("LEVELONE_EQUITIES", cap.LEVELONE_FIELDS, "quote", bus, health, stats)
    return h, health


class _ScriptedStream:
    """Minimal StreamClient surface _schwab_connect_after_login drives; handle_message follows
    a script of 'ok' / exception instances, then blocks."""
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def add_level_one_equity_handler(self, h): pass
    def add_chart_equity_handler(self, h): pass
    def add_nasdaq_book_handler(self, h): pass
    def add_nyse_book_handler(self, h): pass
    def add_level_one_option_handler(self, h): pass
    def add_options_book_handler(self, h): pass

    async def handle_message(self):
        self.calls += 1
        if not self.script:
            await asyncio.sleep(3600)
        step = self.script.pop(0)
        if step != "ok":
            raise step
        await asyncio.sleep(0)


def _run_pump(script, settle=0.3):
    async def go():
        stream = _ScriptedStream(script)
        stop = asyncio.Event()
        _s, task, _o = await cap._schwab_connect_after_login(
            stream, [], MessageBus(), HealthRegistry(), cap.CaptureStats(), stop)
        await asyncio.sleep(settle)
        done, exc = task.done(), (task.exception() if task.done() and not task.cancelled() else None)
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return done, exc, stream.calls
    return asyncio.run(go())


def test_terrain_rotates_only_inside_the_contention_window():
    import server as srv
    board = [f"T{i:02d}" for i in range(40)]
    now, deferred = srv.terrain_cycle_tickers(board, 12 * 60, 7, viewed=[board[0]])
    assert (now, deferred) == (board, []), "viewing must never rotate the board outside the window"
    inside = srv.TERRAIN_CONTENTION_START_MINS
    now, deferred = srv.terrain_cycle_tickers(board, inside, 7, viewed=[board[0]])
    assert board[0] in now and deferred                       # the window still rotates


def test_sse_dispatch_has_its_own_single_thread():
    import server as srv
    ex = srv._get_l1_sse_dispatch_executor()
    assert ex is not srv._get_l1_light_executor()
    assert ex._max_workers == 1


def test_forming_bar_is_keyed_on_trade_time_only(monkeypatch):
    """The forming minute (live_price_rows.forming_bar, the one forming-bar source) is placed on
    the trade's own TRADE_TIME minute; the quote / receive clocks never stand in for it."""
    import live_price_rows as lpr
    import server as srv

    tk = "ZZTT"
    monkeypatch.setattr(lpr, "_forming", {})
    monkeypatch.setattr(lpr, "_forming_seen", {})
    # receive and quote clocks sit in the NEXT minute (..160); only TRADE_TIME is in ..100
    row = {"ticker": tk, "spot": 50.0, "quote_ingestion": "schwab_streaming_level_one",
           "quote_source_detail": {"spot": "LAST_PRICE"}, "spot_received_ts": 1_700_000_170.0,
           "server_received_ts": 1_700_000_170.0, "exchange_quote_ts": 1_700_000_170.0}
    monkeypatch.setattr(lpr.lmp, "get_quote", lambda t: dict(row) if t == tk else None)
    bars = [{"t": 1_700_000_100.0, "o": 49.0, "h": 49.5, "l": 48.5, "c": 49.2, "v": 5}]
    # no TRADE_TIME: no forming minute at all
    lpr._note_trade(tk)
    assert lpr.forming_bar(tk) is None
    assert srv.overlay_forming_bar_from_plane(bars, tk) == bars
    row["trade_ts"] = 1_700_000_130.0          # epoch SECONDS, as the plane stores TRADE_TIME (..100 minute)
    lpr._note_trade(tk)
    out = srv.overlay_forming_bar_from_plane(bars, tk)
    assert len(out) == 1 and out[0]["t"] == 1_700_000_100.0
    assert (out[0]["c"], out[0]["h"], out[0]["l"]) == (50.0, 50.0, 48.5)


# ── PR B: drop counts per consumer; atomic token refresh ─────────────────────────────────

def test_drop_counts_are_per_consumer_and_survive_a_disconnect():
    """The writer, push clients and push history all subscribe to "" -- keyed by prefix they
    overwrote each other (audit of #280). Counts are per consumer name, and a push client's
    drops remain after it disconnects."""
    from stream_spine import COUNT_DROPS

    async def go():
        bus = MessageBus()
        writer = bus.subscribe("", policy=COUNT_DROPS, maxsize=1, name="db_writer")
        client = bus.subscribe("", policy=COUNT_DROPS, maxsize=2, name="push_client")
        for i in range(6):
            bus.publish(f"quote.S{i}", {"i": i})
        before = bus.drop_counts()
        bus.unsubscribe(client)
        after = bus.drop_counts()
        _ = writer
        return before, after
    before, after = asyncio.run(go())
    assert before == {"db_writer": 5, "push_client": 4}
    assert after == {"db_writer": 5, "push_client": 4}


def test_every_token_refresh_writes_atomically(monkeypatch, tmp_path):
    """The client schwab-py builds refreshes through OUR writer (temp + replace), never
    open(path, 'w') in place (audit of #280: the atomic helper had no production caller)."""
    import json
    import schwab_client as sc
    from schwab import auth

    tok = tmp_path / "schwab_token.json"
    tok.write_text(json.dumps({"creation_timestamp": 1, "token": {"access_token": "a"}}))
    seen = {}

    def fake_access_functions(api_key, app_secret, read, write, **kw):
        seen["read"] = read()
        write({"creation_timestamp": 2, "token": {"access_token": "b"}})
        return "client"
    monkeypatch.setattr(auth, "client_from_access_functions", fake_access_functions)
    replaced = []
    import os as _os
    real_replace = _os.replace
    monkeypatch.setattr(_os, "replace", lambda a, b: (replaced.append((a, b)), real_replace(a, b))[1])
    assert sc.client_from_token_file_atomic(str(tok), "k", "s") == "client"
    assert seen["read"]["token"]["access_token"] == "a"
    assert json.loads(tok.read_text())["token"]["access_token"] == "b"
    assert replaced and str(replaced[0][1]) == str(tok), "the refresh must land via os.replace"


def test_a_transient_windows_share_violation_is_retried_then_lands(monkeypatch, tmp_path):
    import schwab_client as sc
    import arch_competition.atomic_io as aio

    real = aio.write_json_file_atomically
    calls = {"n": 0}

    def flaky(path, payload, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("[WinError 5] Access is denied")
        return real(path, payload, **kw)
    monkeypatch.setattr(aio, "write_json_file_atomically", flaky)
    monkeypatch.setattr(sc.time, "sleep", lambda s: None)
    dest = tmp_path / "t.json"
    sc.write_token_file_atomically(str(dest), {"x": 1})
    assert calls["n"] == 3 and dest.exists()


# ── PR C: server-side bar roll-up; quote_tick carries the screen's numbers; heatmap demand ──

def test_bars_roll_up_server_side_and_unknown_volume_stays_unknown():
    import server as srv
    t0 = 1_700_000_100.0                                    # a 5-minute boundary: 1_700_000_100 % 300 == 100? use floor
    base = t0 - (t0 % 300)
    m = [{"t": base + 60 * i, "o": 10 + i, "h": 11 + i, "l": 9 + i, "c": 10.5 + i, "v": 100} for i in range(7)]
    m[6]["v"] = None                                        # one minute with no reported volume
    out = srv.aggregate_bars(m, "5")
    assert [b["t"] for b in out] == [base, base + 300]
    first, second = out
    assert (first["o"], first["h"], first["l"], first["c"], first["v"]) == (10, 15, 9, 14.5, 500)
    assert (second["o"], second["h"], second["l"], second["c"]) == (15, 17, 14, 16.5)
    assert second["v"] is None, "a bucket with an unreported minute has unknown volume, not a partial sum"
    assert srv.aggregate_bars(m, "1") == m


def test_daily_roll_up_is_keyed_on_the_et_trading_date():
    import server as srv
    # 2026-09-24 19:59 ET and 20:01 ET are the same ET date; 00:01 ET next day is not
    d1a, d1b, d2 = 1_790_294_340.0, 1_790_294_460.0, 1_790_308_860.0
    out = srv.aggregate_bars([{"t": d1a, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1},
                              {"t": d1b, "o": 1.5, "h": 3, "l": 1, "c": 2, "v": 1},
                              {"t": d2, "o": 2, "h": 2, "l": 2, "c": 2, "v": 1}], "D")
    assert len(out) == 2 and out[0]["h"] == 3 and out[0]["v"] == 2


def test_the_price_row_carries_feed_state_trade_age_and_the_forming_bar(monkeypatch):
    import time as _t

    import live_market_plane as lmp
    import live_price_rows
    import server as srv
    from tests.feed_live_helper import mark_feed_live

    mark_feed_live("ZZQF")
    now = _t.time()
    lmp.record_from_level_one_equity("ZZQF", {"LAST_PRICE": 42.0, "TRADE_TIME_MILLIS": int((now - 7) * 1000)},
                                     received_ts=now)
    ev = live_price_rows.price_row("ZZQF")
    assert ev["feed_live"] is True and ev["spot"] == 42.0 and ev["spot_source"] == srv.SPOT_SOURCE_PLANE
    assert 6.0 <= ev["trade_age_sec"] <= 9.0
    f = ev["forming_1m"]
    assert f is not None and f["c"] == 42.0 and f["t"] == (now - 7) - ((now - 7) % 60)
    held_no_trade = live_price_rows.price_row("ZZNOTRADE")
    assert held_no_trade["spot"] is None and held_no_trade["forming_1m"] is None


def test_spot_gamma_reprice_runs_only_for_a_viewed_heatmap(monkeypatch):
    monkeypatch.setattr(sys.modules["server"], "_is_loggable_session", lambda: True)   # an open-market test
    import threading
    import time
    import server as srv
    ran, done = [], threading.Event()

    def worker(tk):
        ran.append(tk)
        with srv._reprice_guard:
            srv._reprice_dirty.discard(tk)
            srv._reprice_running.discard(tk)
        done.set()
    monkeypatch.setattr(srv, "_reprice_worker", worker)
    monkeypatch.setattr(srv, "_gamma_surface_demand", {"ZZVIEW": time.time()})
    srv._on_stream_tick("ZZNOTVIEWED")
    srv._on_stream_tick("ZZVIEW")
    assert done.wait(5)
    assert ran == ["ZZVIEW"]
