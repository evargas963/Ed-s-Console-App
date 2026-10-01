"""The console's push: the levels producer and the stream handler mark what changed for a
ticker; a page on that ticker receives each kind once, and no other page does. (Bars are the
daemon's push: tests/test_bars_pushed_v1.py.) Stream input is Schwab's captured TSLA book
(tests/fixtures/real_equity_book.json)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import app.options.order_flow.streaming as ofs
import push_changes

_FX = json.loads((Path(__file__).parent / "fixtures" / "real_equity_book.json").read_text(encoding="utf-8"))
TK = _FX["ticker"]


def _run(body):
    async def main():
        push_changes.bind(asyncio.get_running_loop())
        mine, other = push_changes.subscribe(TK, "mine"), push_changes.subscribe("ZZOTHER", "other")
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


def test_a_streamed_book_marks_flow():
    # (the equity quote's flow mark is its price row's arrival:
    # tests/test_live_ui_phases_3_7_v1.py)
    b = _FX["book"]
    assert _run(lambda: ofs._ingest_pushed(f"book.{TK}", {"symbol": TK, "ts_recv": b["ts_recv"],
                                                           "service": b["service"],
                                                           "content": b["native"]}))[0] == {"flow"}


def test_no_change_is_an_empty_push():
    assert _run(lambda: None) == (set(), set())
