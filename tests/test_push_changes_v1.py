"""The console's push: the levels producer, the stream handler and the bar writer mark what
changed for a ticker; a page on that ticker receives each kind once, and no other page does.
Stream input is Schwab's captured TSLA book and quote (tests/fixtures/real_equity_book.json)."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import app.options.order_flow.streaming as ofs
import push_changes
import server
from stream_spine import bar_msg

_FX = json.loads((Path(__file__).parent / "fixtures" / "real_equity_book.json").read_text(encoding="utf-8"))
TK = _FX["ticker"]


def _run(body):
    async def main():
        push_changes.bind(asyncio.get_running_loop())
        mine, other = push_changes.subscribe(TK), push_changes.subscribe("ZZOTHER")
        try:
            body()
            await asyncio.sleep(0)
            return (await push_changes.next_changes(mine, 1.0),
                    await push_changes.next_changes(other, 0.05))
        finally:
            push_changes.unsubscribe(TK, mine)
            push_changes.unsubscribe("ZZOTHER", other)
    return asyncio.run(main())


def test_changes_reach_only_the_tickers_page_each_kind_once():
    def body():
        for kind in (push_changes.LEVELS, push_changes.FLOW, push_changes.LEVELS):
            push_changes.changed(TK, kind)
    assert _run(body) == ({"levels", "flow"}, set())


def test_a_streamed_equity_quote_and_book_mark_flow(monkeypatch):
    # the page open on TSLA makes it viewed, and a viewed ticker's tick is also repriced (which
    # marks levels); this test is about the flow mark alone
    monkeypatch.setattr(server, "_on_stream_tick", lambda sym: None)
    q, b = _FX["quote"], _FX["book"]
    assert _run(lambda: ofs._ingest_pushed(f"quote.{TK}", {"symbol": TK, "ts_recv": q["ts_recv"],
                                                            "native": q["native"]}))[0] == {"flow"}
    assert _run(lambda: ofs._ingest_pushed(f"book.{TK}", {"symbol": TK, "ts_recv": b["ts_recv"],
                                                           "service": b["service"],
                                                           "content": b["native"]}))[0] == {"flow"}


def test_a_written_bar_marks_liquidity():
    start = 1_790_000_040.0
    msg = bar_msg(symbol=TK, bar_start_ms=int(start * 1000), open=10.0, high=11.0, low=9.5,
                  close=10.5, volume=100.0, src="schwab_chart", ts_recv=start + 60.0)
    try:
        assert _run(lambda: server._write_streamed_bar(msg))[0] == {"liquidity"}
    finally:
        con = sqlite3.connect(server.get_db().db_path)
        con.execute("DELETE FROM price_bars_1m WHERE ticker=? AND bar_start_ts_utc=?", (TK, start))
        con.commit()
        con.close()


def test_no_change_is_an_empty_push():
    assert _run(lambda: None) == (set(), set())
