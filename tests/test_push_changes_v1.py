"""The console's push: the levels producer, the stream handler and the bar writer mark what
changed for a ticker; a page on that ticker receives each kind once, and no other page does.
Stream input is Schwab's captured TSLA book and quote (tests/fixtures/real_equity_book.json)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import app.options.order_flow.streaming as ofs
import push_changes
import server
from stream_spine import bar_msg
from tests.feed_live_helper import daemon_bars
from time_et import ET

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


def test_a_kept_bar_marks_liquidity():
    """Schwab's TSLA bar of 2026-09-29 09:30 ET as the capture daemon recorded and pushed it."""
    r = next(r for r in daemon_bars("real_daemon_bars_spy_tsla_2026_09_29_30.json", TK)
             if r["bar_start_ms"] == int(datetime(2026, 9, 29, 9, 30, tzinfo=ET).timestamp() * 1000))
    msg = bar_msg(symbol=r["symbol"], bar_start_ms=r["bar_start_ms"], open=r["open"], high=r["high"], low=r["low"],
                  close=r["close"], volume=r["volume"], src=r["src"], ts_recv=r["ts_recv"], native=r["native"],
                  schwab_ts=r["schwab_ts"])
    held = server._bars.pop(TK, None)
    try:
        assert _run(lambda: server._write_streamed_bar(msg))[0] == {"liquidity"}
    finally:
        server._bars.pop(TK, None)
        if held is not None:
            server._bars[TK] = held


def test_no_change_is_an_empty_push():
    assert _run(lambda: None) == (set(), set())
