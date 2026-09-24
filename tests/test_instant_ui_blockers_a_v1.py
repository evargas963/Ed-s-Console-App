"""Audit of #280, blockers fixed in PR A -- behavioural tests on the real daemon/server code.

- a service is marked alive only by a frame that parsed and published (it beat BEFORE parsing,
  so a frame shape failing on every message kept LEVELONE "RUNNING" with nothing delivered);
- a sustained run of skipped frames ends the pump (-> the watchdog recycles), while isolated
  bad frames between good ones do not;
- terrain rotation happens only inside the contention window (collection mandate).
"""
from __future__ import annotations

import asyncio

import app.market_data.schwab.streaming.capture as cap
from stream_spine import HealthRegistry, MessageBus


def _handler():
    bus, health, stats = MessageBus(), HealthRegistry(), cap.CaptureStats()
    h = cap.make_handler("LEVELONE_EQUITIES", cap.LEVELONE_FIELDS, "quote", bus, health, stats)
    return h, health


def test_an_unparsable_frame_does_not_mark_the_service_alive():
    h, health = _handler()
    h({"service": "LEVELONE_EQUITIES", "content": [{"no_key": 1}]})
    assert "LEVELONE_EQUITIES" not in health.report()


def test_a_parsed_frame_marks_the_service_alive():
    h, health = _handler()
    h({"service": "LEVELONE_EQUITIES", "content": [{"key": "ZZLIVE", "LAST_PRICE": 10.0}]})
    assert health.report()["LEVELONE_EQUITIES"]["state"] == "RUNNING"


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


def test_a_sustained_run_of_bad_frames_ends_the_pump():
    n = cap.PUMP_SKIP_STREAK_FATAL
    done, exc, calls = _run_pump([ValueError("shape changed")] * (n + 5))
    assert done and isinstance(exc, ValueError), "the pump must end so the session recycles"
    assert calls == n


def test_isolated_bad_frames_between_good_ones_do_not_end_the_pump():
    n = cap.PUMP_SKIP_STREAK_FATAL
    script = ([ValueError("one bad frame")] * (n - 1) + ["ok"]) * 3
    done, exc, calls = _run_pump(script)
    assert not done, f"pump ended on isolated bad frames: {exc!r}"
    assert calls == len(script) + 1          # every scripted frame, then blocked on the next


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
    import server as srv
    from tests.feed_live_helper import mark_feed_live

    tk = "ZZTT"
    mark_feed_live(tk)
    row = {"ticker": tk, "spot": 50.0, "quote_ingestion": "schwab_streaming_level_one",
           "quote_source_detail": {"spot": "LAST_PRICE"}, "spot_received_ts": 1_700_000_130.0,
           "server_received_ts": 1_700_000_130.0, "exchange_quote_ts": 1_700_000_130.0}
    monkeypatch.setattr(srv._lmp, "get_quote", lambda t: dict(row) if t == tk else None)
    monkeypatch.setattr(srv._candles_1m, "forming_bar", lambda t: None)
    bars = [{"t": 1_700_000_100.0, "o": 49.0, "h": 49.5, "l": 48.5, "c": 49.2, "v": 5}]
    # no TRADE_TIME: the quote clock / receive clock never stand in for the trade's minute
    assert srv.overlay_forming_bar_from_plane(bars, tk) == bars
    row["trade_ts"] = 1_700_000_130_000        # Schwab TRADE_TIME_MILLIS, in the ..100 minute
    out = srv.overlay_forming_bar_from_plane(bars, tk)
    assert len(out) == 1 and out[0]["t"] == 1_700_000_100.0
    assert (out[0]["c"], out[0]["h"], out[0]["l"]) == (50.0, 50.0, 48.5)
