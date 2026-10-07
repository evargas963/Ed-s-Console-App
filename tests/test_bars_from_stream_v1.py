"""Bars come from Schwab: its 1-minute price history (/pricehistory, which the capture daemon asks
for each ET date) and its streamed CHART_EQUITY 1-minute bars, which the daemon records
(stream_capture.db stream_bars_raw) and forwards. The console keeps them in memory (server._bars:
the history, each pushed bar on top); every live reader reads memory. Only completed bars are
served. A minute Schwab sent neither way stays missing."""
from __future__ import annotations

import threading
import time
from datetime import datetime

from fastapi.testclient import TestClient

import app.options.order_flow.streaming as ofs
import server
from app.market_data.schwab.streaming.live_push import is_forwarded
from stream_spine import bar_msg
from tests.feed_live_helper import price_history
from time_et import ET, ct_label

TK = "ZZBARS"
T0 = 1_790_000_040.0            # a minute boundary


def _bar(start: float, o=10.0, h=11.0, lo=9.5, c=10.5, v=100.0) -> dict:
    return bar_msg(symbol=TK, bar_start_ms=int(start * 1000), open=o, high=h, low=lo, close=c,
                   volume=v, src="schwab_chart", ts_recv=start + 60.0)


def _clear():
    server._bars.pop(TK, None)


def setup_function(_fn):
    _clear()


def teardown_function(_fn):
    _clear()


def test_the_daemon_forwards_streamed_bars_to_the_console():
    assert is_forwarded(f"bar1m.{TK}", _bar(T0))
    assert not is_forwarded(f"bar1m.{TK}", dict(_bar(T0), src="something_else"))


def test_the_feed_hands_each_streamed_bar_to_the_writer():
    while not ofs.streamed_bars.empty():
        ofs.streamed_bars.get_nowait()
    ofs._ingest_pushed(f"bar1m.{TK}", _bar(T0))
    assert ofs.streamed_bars.get_nowait()["bar_start_ms"] == int(T0 * 1000)


def test_a_streamed_bar_is_written_and_read_back_exactly():
    assert server._write_streamed_bar(_bar(T0, o=10.0, h=11.0, lo=9.5, c=10.5, v=100.0))
    (b,) = server._bars_1m(TK)
    assert (b.ts, b.open, b.high, b.low, b.close, b.volume) == (T0, 10.0, 11.0, 9.5, 10.5, 100.0)


def test_a_bar_missing_a_field_is_not_written():
    assert not server._write_streamed_bar(dict(_bar(T0), close=None))
    assert server._bars_1m(TK) == []


def test_a_price_that_is_not_a_number_is_not_written():
    """AGENTS.md rule 2: -999, text, NaN and infinity are not numbers."""
    for bad in (-999, "10.0", float("nan"), float("inf")):
        assert not server._write_streamed_bar(dict(_bar(T0), low=bad)), bad
    assert server._bars_1m(TK) == []


def test_a_reported_zero_is_written_as_sent():
    """Operator ruling 2026-09-27: take what Schwab sends; a 0 price or volume is 0."""
    assert server._write_streamed_bar(_bar(T0, lo=0.0, v=0.0))
    (b,) = server._bars_1m(TK)
    assert (b.low, b.volume) == (0.0, 0.0)


def test_a_minute_the_stream_did_not_deliver_stays_missing():
    for m in (0, 1, 3):                                   # minute 2 never arrived
        server._write_streamed_bar(_bar(T0 + 60 * m))
    assert [b.ts for b in server._bars_1m(TK)] == [T0, T0 + 60, T0 + 180]


def test_the_price_history_is_taken_promptly_and_exactly_while_options_are_priced_in_the_same_process():
    """The console prices option chains in the interpreter that takes and serves the bars. Schwab's
    SPY and TSLA 1-minute price history as /pricehistory answered it at 2026-10-07 09:57 UTC (10
    days, extended hours: ~11,000 candles each), taken by the bar writer (server._write_streamed_bars,
    as the daemon pushes it) beside a busy pure-Python thread: each minute is Schwab's candle with
    every field as sent, the pre-market and after-hours minutes included, in well under a second."""
    busy = threading.Event()

    def price_options():
        x = 0
        while not busy.is_set():
            for i in range(1000):
                x += i * i

    answers = {tk: price_history(tk, "1m") for tk in ("SPY", "TSLA")}
    for tk in answers:
        server._bars.pop(tk, None)
    t = threading.Thread(target=price_options, daemon=True)
    t.start()
    try:
        t0 = time.perf_counter()
        server._write_streamed_bars([{"src": "schwab_pricehistory", "symbol": tk, "series": "1m",
                                      "ts_recv": a["answered_utc"], "candles": a["body"]["candles"]}
                                     for tk, a in answers.items()], datetime.fromtimestamp(answers["SPY"]["answered_utc"], ET))
        read = {tk: server._bars_1m(tk, server.BARS_KEPT) for tk in answers}
        took = time.perf_counter() - t0
    finally:
        busy.set()
        t.join()
        for tk in answers:
            server._bars.pop(tk, None)
    for tk, a in answers.items():
        got = [(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in read[tk]]
        want = [(c["datetime"] / 1000, c["open"], c["high"], c["low"], c["close"], c["volume"])
                for c in a["body"]["candles"]]
        assert got == want, tk
        assert any(datetime.fromtimestamp(ts, ET).hour < 9 for ts, *_ in got), f"{tk}: no pre-market minute kept"
        assert any(datetime.fromtimestamp(ts, ET).hour >= 17 for ts, *_ in got), f"{tk}: no after-hours minute kept"
    assert took < 1.0, f"{sum(len(v) for v in read.values())} candles took {took:.2f} s beside a busy thread"


def test_the_bars_endpoint_serves_completed_schwab_bars_and_the_last_bars_minute():
    for m in (0, 1):
        server._write_streamed_bar(_bar(T0 + 60 * m))
    body = TestClient(server.app).get(f"/api/bars1m?ticker={TK}").json()
    assert [b["t"] for b in body["bars"]] == [T0, T0 + 60]
    assert not any("forming" in b for b in body["bars"])
    assert body["last_bar"] == {"t": T0 + 60, "label": ct_label(T0 + 60)}
