"""Bars come from one source: Schwab's streamed CHART_EQUITY 1-minute bars. The capture daemon
forwards them, the console writes them to price_bars_1m (its one writer), every reader reads that
table. Only completed bars are served. A minute the stream did not deliver stays missing."""
from __future__ import annotations


from fastapi.testclient import TestClient

import app.options.order_flow.streaming as ofs
import server
from app.market_data.schwab.streaming.live_push import is_forwarded
from stream_spine import bar_msg
from time_et import ct_label

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




def test_the_bars_endpoint_serves_completed_schwab_bars_and_the_last_bars_minute():
    for m in (0, 1):
        server._write_streamed_bar(_bar(T0 + 60 * m))
    body = TestClient(server.app).get(f"/api/bars1m?ticker={TK}").json()
    assert [b["t"] for b in body["bars"]] == [T0, T0 + 60]
    assert not any("forming" in b for b in body["bars"])
    assert body["last_bar"] == {"t": T0 + 60, "label": ct_label(T0 + 60)}
