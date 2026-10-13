"""stream_capture.db holds everything Schwab sends, as sent, for the newest five trading sessions
(docs/DATA_FLOW.md §2 D4): the daemon's writer records every message, and once after each close of
the last option market removes the rows received before the newest five sessions began
(keep_sessions, CaptureWriter.prune). The live stream and the levels are untouched.

Real data: the messages Schwab sent 2026-10-05 14:00:00-14:00:03 CT and Schwab's /markets answers
held by tests/conftest.py. STAND-INS (the keep's tests): the messages' contents (only their topic,
symbol and receipt time are what the keep reads) and the daemon's clock.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.market_data.schwab.streaming import capture
from stream_spine import LOG, CaptureWriter, HealthRegistry, MessageBus, options_quote_msg, quote_msg
from time_et import ET


async def _until(ok, seconds: float = 30.0) -> None:
    deadline = asyncio.get_running_loop().time() + seconds
    while not ok():
        assert asyncio.get_running_loop().time() < deadline, "timed out"
        await asyncio.sleep(0.02)


def _rows(db, sql: str) -> list:
    with sqlite3.connect(db) as conn:
        return conn.execute(sql).fetchall()


def _et(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=ET).timestamp()


def test_every_message_schwab_sends_is_recorded_as_sent(tmp_path):
    """Operator 2026-10-13: "Save everything Schwab sends, as sent." Every message Schwab sent
    2026-10-05 14:00:00-14:00:03 CT (tests/fixtures/real_stream_mix_2026_10_05_1400ct.json: 7,420
    LEVELONE_OPTIONS of 2,755 contracts, 152 LEVELONE_EQUITIES, 12 book messages), through the
    daemon's own handler and its writer: each is a row, its item as Schwab sent it -- every option
    contract's, not a kept few."""
    mix = json.loads((Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json")
                     .read_text(encoding="utf-8"))["messages"]
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=500, batch_sec=0.01)
    bus = MessageBus()

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        await asyncio.sleep(0)
        for m in mix:
            capture._publisher(m["service"], bus, HealthRegistry())({"timestamp": m["schwab_ts"], "content": [m["item"]]})
        await _until(lambda: writer.status()["rows_written"] == len(mix))
        stop.set()
        await task
    asyncio.run(go())

    def sent(*services):
        return sorted(json.dumps(m["item"], sort_keys=True) for m in mix if m["service"] in services)

    def rows(table):
        return sorted(json.dumps(json.loads(j), sort_keys=True) for (j,) in _rows(db, f"SELECT native_json FROM {table}"))
    assert rows("stream_options_quotes_raw") == sent("LEVELONE_OPTIONS")
    assert rows("stream_quotes_raw") == sent("LEVELONE_EQUITIES")
    assert rows("stream_book_raw") == sent("NYSE_BOOK", "NASDAQ_BOOK", "OPTIONS_BOOK")


def _recorded(bus) -> None:
    """Rows on both sides of 2026-10-01 00:00 ET, as the daemon publishes them."""
    for when in ("2026-09-30 15:00", "2026-10-01 09:31"):
        bus.publish("quote.SPY", quote_msg(symbol="SPY", last=1.0, src="schwab_l1", ts_recv=_et(when),
                                           native={"key": "SPY"}))
        bus.publish("feedstatus.LEVELONE_EQUITIES", {"ts": _et(when), "service": "LEVELONE_EQUITIES",
                                                     "socket_open": True, "held": 1})
    for when in ("2026-09-30 15:00", "2026-10-07 15:00"):
        bus.publish("optquote.SPY   261007C00777000", options_quote_msg(
            symbol="SPY   261007C00777000", content={"key": "SPY   261007C00777000"}, src="schwab_options_l1",
            ts_recv=_et(when)))
    for when in ("2026-09-29 12:00", "2026-09-30 12:00"):          # both before; the newest stays
        topic, msg = capture.watchlist_message(["SPY"], op="added", ticker="SPY", request_id=when)
        bus.publish(topic, {**msg, "ts_recv": _et(when)})


def _kept_at(tmp_path, clock: str, wait: float) -> str:
    """The rows left after the daemon's keep runs at `clock` (ET) for `wait` seconds or until the
    old rows are gone: a summary per table."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"], clock=lambda: _et(clock))
    daemon.writer = writer

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        await asyncio.sleep(0)
        _recorded(bus)
        await _until(lambda: writer.status()["rows_written"] == 8)
        keep = asyncio.create_task(capture.keep_sessions(daemon, stop))
        try:
            await _until(lambda: _rows(db, "SELECT COUNT(*) FROM stream_feed_status")[0][0] == 1, wait)
        except AssertionError:
            pass                                                         # nothing was removed
        stop.set()
        await asyncio.gather(task, keep)
    asyncio.run(go())
    counts = " ".join(f"{name}:{_rows(db, f'SELECT COUNT(*) FROM {table}')[0][0]}" for name, table in (
        ("quotes", "stream_quotes_raw"), ("options", "stream_options_quotes_raw"),
        ("feed", "stream_feed_status"), ("watchlist", "stream_watchlist")))
    newest = datetime.fromtimestamp(_rows(db, "SELECT MAX(ts_recv) FROM stream_watchlist")[0][0], ET)
    return f"{counts} newest-watchlist:{newest:%m-%d %H:%M}"


def test_after_the_last_option_close_rows_before_the_newest_five_sessions_are_removed(tmp_path):
    """2026-10-07 17:00 ET, the last option market (IND) closed at 16:15: Schwab's /markets says
    the market was open 09-30, 10-01, 10-02, 10-05, 10-06 and 10-07, so the newest five sessions
    run from 2026-10-01 00:00 ET. Every row received before it is removed from each table, except
    the newest watchlist row, which the daemon reads at its start."""
    assert _kept_at(tmp_path, "2026-10-07 17:00", 30.0) == \
        "quotes:1 options:1 feed:1 watchlist:1 newest-watchlist:09-30 12:00"


def test_nothing_is_removed_while_the_options_trade_or_the_market_is_unknown(tmp_path):
    """2026-10-07 12:00 ET, the options open; and 2027-10-12, a date Schwab's held answers do not
    reach: no row is removed (never on a guess)."""
    untouched = "quotes:2 options:2 feed:2 watchlist:2 newest-watchlist:09-30 12:00"
    assert _kept_at(tmp_path / "open", "2026-10-07 12:00", 1.5) == untouched
    assert _kept_at(tmp_path / "unknown", "2027-10-12 17:00", 1.5) == untouched
