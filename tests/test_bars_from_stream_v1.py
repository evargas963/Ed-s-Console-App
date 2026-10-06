"""Bars come from one source: Schwab's streamed CHART_EQUITY 1-minute bars. The capture daemon
records them (stream_capture.db stream_bars_raw, its one writer, the history) and forwards them;
the console keeps them in memory (server._bars, loaded from the daemon's record once at startup,
then each pushed bar); every live reader reads memory. Only completed bars are served. A minute
the stream did not deliver stays missing."""
from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime

from fastapi.testclient import TestClient

import app.options.order_flow.streaming as ofs
import server
from app.market_data.schwab.streaming.live_push import is_forwarded
from db_authority import canonical_stream_db_path
from stream_spine import bar_msg
from tests.feed_live_helper import daemon_bars, forget_daemon_bars, record_daemon_bars
from time_et import ET, ct_label

TK = "ZZBARS"
T0 = 1_790_000_040.0            # a minute boundary


@dataclass
class _SqliteWork:
    """What this thread asks of SQLite while watched (sys.setprofile, each call into a sqlite3
    connection or cursor before it runs): every statement SQLite runs (the connection's trace
    callback) and every row handed back to Python (a row factory that returns the row exactly as
    SQLite built it)."""
    statements: list = field(default_factory=list)
    rows: int = 0

    def row(self, _cursor, row):
        self.rows += 1
        return row

    def watch(self, _frame, event, arg):
        owner = getattr(arg, "__self__", None)
        if event == "c_call" and isinstance(owner, (sqlite3.Connection, sqlite3.Cursor)) and owner.row_factory != self.row:
            con = owner.connection if isinstance(owner, sqlite3.Cursor) else owner
            con.set_trace_callback(self.statements.append)
            con.row_factory = owner.row_factory = self.row


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


def test_bars_are_loaded_exactly_in_one_read_per_symbol():
    """The console prices option chains in the interpreter that loads and serves the bars, and
    every row SQLite hands back to Python hands that interpreter's lock to the pricing thread.
    Schwab's SPY and TSLA bars as the capture daemon recorded them (2026-09-29/30, each receipt,
    every hour Schwab sent), loaded at startup (server._load_bars): each minute is Schwab's newest
    bar for it with every field as sent, the pre-market and after-hours bars included, and the
    load's statements and rows grow with the symbols recorded, never with the bars."""
    rows = daemon_bars("real_daemon_bars_spy_tsla_2026_09_29_30.json")
    lo, hi = min(r["bar_start_ms"] for r in rows), max(r["bar_start_ms"] for r in rows)
    newest = {}
    for r in sorted(rows, key=lambda r: r["ts_recv"]):
        newest[(r["symbol"], r["bar_start_ms"])] = r
    record_daemon_bars(rows)
    con = sqlite3.connect(str(canonical_stream_db_path()))
    (symbols,) = con.execute("SELECT COUNT(DISTINCT symbol) FROM stream_bars_raw").fetchone()
    con.close()
    work, profiler = _SqliteWork(), sys.getprofile()
    sys.setprofile(work.watch)
    try:
        server._load_bars()
        sys.setprofile(profiler)
        read = {tk: server._bars_1m(tk, server.BARS_KEPT) for tk in ("SPY", "TSLA")}
    finally:
        sys.setprofile(profiler)
        forget_daemon_bars(rows)
        for tk in ("SPY", "TSLA"):
            server._bars.pop(tk, None)
    for tk in ("SPY", "TSLA"):
        got = [(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in read[tk] if lo / 1000 <= b.ts <= hi / 1000]
        want = [(ms / 1000, r["open"], r["high"], r["low"], r["close"], r["volume"])
                for (sym, ms), r in sorted(newest.items()) if sym == tk]
        assert got == want, tk
        assert any(datetime.fromtimestamp(ts, ET).hour < 9 for ts, *_ in got), f"{tk}: no pre-market bar kept"
        assert any(datetime.fromtimestamp(ts, ET).hour >= 17 for ts, *_ in got), f"{tk}: no after-hours bar kept"
    bars = sum(len(v) for v in read.values())
    assert work.statements, "the load ran no statement on a connection it opened"
    assert len(work.statements) <= 1 + symbols, (
        f"{len(work.statements)} statements for {bars} bars of {symbols} symbols: {work.statements[:3]}")
    assert work.rows <= 2 * symbols, f"{work.rows} rows handed to Python for {bars} bars of {symbols} symbols"


def test_the_bars_endpoint_serves_completed_schwab_bars_and_the_last_bars_minute():
    for m in (0, 1):
        server._write_streamed_bar(_bar(T0 + 60 * m))
    body = TestClient(server.app).get(f"/api/bars1m?ticker={TK}").json()
    assert [b["t"] for b in body["bars"]] == [T0, T0 + 60]
    assert not any("forming" in b for b in body["bars"])
    assert body["last_bar"] == {"t": T0 + 60, "label": ct_label(T0 + 60)}
