"""Bars come from one source: Schwab's streamed CHART_EQUITY 1-minute bars. The capture daemon
forwards them, the console writes them to price_bars_1m (its one writer), every reader reads that
table, and the forming minute comes from the live price plane. A minute the stream did not deliver
stays missing."""
from __future__ import annotations


from fastapi.testclient import TestClient

import app.options.order_flow.streaming as ofs
import server
from app.market_data.schwab.streaming.live_push import is_forwarded
from stream_spine import bar_msg

TK = "ZZBARS"
T0 = 1_790_000_040.0            # a minute boundary


def _bar(start: float, o=10.0, h=11.0, lo=9.5, c=10.5, v=100.0) -> dict:
    return bar_msg(symbol=TK, bar_start_ms=int(start * 1000), open=o, high=h, low=lo, close=c,
                   volume=v, src="schwab_chart", ts_recv=start + 60.0)


def _clear():
    import sqlite3
    con = sqlite3.connect(server.get_db().db_path)
    try:
        con.execute("DELETE FROM price_bars_1m WHERE ticker=?", (TK,))
        con.commit()
    finally:
        con.close()


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


def test_a_zero_negative_or_non_finite_price_is_not_written():
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        assert not server._write_streamed_bar(dict(_bar(T0), low=bad)), bad
    assert server._bars_1m(TK) == []


def test_a_minute_the_stream_did_not_deliver_stays_missing():
    for m in (0, 1, 3):                                   # minute 2 never arrived
        server._write_streamed_bar(_bar(T0 + 60 * m))
    assert [b.ts for b in server._bars_1m(TK)] == [T0, T0 + 60, T0 + 180]




def test_the_bars_endpoint_serves_the_table_plus_the_planes_forming_minute(monkeypatch):
    server._write_streamed_bar(_bar(T0))
    forming = {"t": T0 + 60, "o": 10.5, "h": 10.7, "l": 10.4, "c": 10.6, "forming": True}
    monkeypatch.setattr(server._lpr, "forming_bar", lambda tk: dict(forming))
    body = TestClient(server.app).get(f"/api/bars1m?ticker={TK}").json()
    assert [b["t"] for b in body["bars"]] == [T0, T0 + 60]
    assert body["bars"][-1]["forming"] is True and "source" not in body


def test_no_forming_minute_means_none_is_invented(monkeypatch):
    server._write_streamed_bar(_bar(T0))
    monkeypatch.setattr(server._lpr, "forming_bar", lambda tk: None)
    body = TestClient(server.app).get(f"/api/bars1m?ticker={TK}").json()
    assert [b["t"] for b in body["bars"]] == [T0]


def test_no_bar_path_calls_schwab_rest():
    src = open(server.__file__, encoding="utf-8").read()
    for gone in ("safe_get_price_history", "get_price_history(", "_bars_collect_one",
                 "_CandleAccumulator", "_enrollment_history_seed"):
        assert gone not in src, gone
