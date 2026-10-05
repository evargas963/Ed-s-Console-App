"""docs/DATA_FLOW.md §2 D4 (the one writer records every message Schwab sends): a message the
writer cannot store is kept as sent, a database that refuses writes holds the writer instead of
ending it, and the writer's state reaches the heartbeat the console and the browser read.

Real data: captured LEVELONE_OPTIONS quotes (tests/fixtures/real_options_stream_history_samples.json)
and a captured TSLA LEVELONE_EQUITIES item (tests/fixtures/real_equity_book.json, "quote") through
the daemon's own handler (capture._publisher) and bus; the captured SPY 2026-11-20 chain and quotes
(tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json) through the real ChainSweep.
STAND-INS: the local host for Schwab's (test_data_path_rules_v1._LocalSchwab), serving a chain
envelope rebuilt from the captured contracts. Each induced failure is named in its test.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path

import httpx
from schwab.client import Client

import live_market_plane as lmp
from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.live_ui import LiveUiServer
from calibration.complete_chain_capture import ChainSweep
from stream_spine import LOG, CaptureWriter, HealthRegistry, MessageBus, options_quote_msg
from tests.test_data_path_rules_v1 import _CONTRACT, _EVENTS, _LocalSchwab, _frame

_IN_WINDOW = 1790863205.0          # 2026-10-01 10:00:05 ET, inside the 10:00 capture window
_TSLA = json.loads((Path(__file__).parent / "fixtures" / "real_equity_book.json")
                   .read_text(encoding="utf-8"))["quote"]


def _failures(db) -> list:
    """The kept failures, (topic, message as stored, error); none where no table keeps them."""
    with sqlite3.connect(db) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='stream_write_failures'").fetchone():
            return []
        return conn.execute("SELECT topic, msg_json, error FROM stream_write_failures").fetchall()


def _count(db, table: str) -> int:
    with sqlite3.connect(db) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _beat(daemon: capture.Daemon) -> dict:
    """The heartbeat as the browser's price socket sends it (live_ui's feed beat) and as the
    console records it (live_market_plane.daemon_status); the console's record is cleared after."""
    beat = LiveUiServer(daemon.bus, daemon.status, {}).beat()
    try:
        assert lmp.daemon_status()["writer"] == beat["writer"]
    finally:
        lmp.record_feed_down()
    return beat


def _publish_options(bus, health, events) -> None:
    h = capture._publisher("LEVELONE_OPTIONS", bus, health)
    for e in events:
        h(_frame("LEVELONE_OPTIONS", [e["content"]], e["content"].get("QUOTE_TIME_MILLIS", 0)))


async def _until(pred, limit: float = 10.0) -> None:
    deadline = time.monotonic() + limit
    while not pred() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)


def test_a_message_the_writer_cannot_store_is_kept_as_sent_and_its_error_reaches_the_heartbeat(tmp_path):
    """INDUCED CONDITION: one captured option quote published with no symbol, so the NOT NULL
    symbol column refuses its row."""
    db = tmp_path / "stream_capture.db"
    bad = options_quote_msg(symbol=None, content=_EVENTS[0]["content"], src="schwab_stream",
                            schwab_ts=_EVENTS[0]["content"].get("QUOTE_TIME_MILLIS"))

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
        task = asyncio.create_task(daemon.writer.run(bus.subscribe("", policy=LOG), stop=stop))
        _publish_options(bus, health, _EVENTS)
        bus.publish(f"optquote.{_CONTRACT}", bad)
        await asyncio.sleep(0.3)
        beat = _beat(daemon)
        stop.set()
        await task
        return beat
    beat = asyncio.run(go())

    assert _count(db, "stream_options_quotes_raw") == len(_EVENTS), "a refused row cost the good rows"
    (topic, kept, error), = _failures(db)
    assert topic == f"optquote.{_CONTRACT}" and json.loads(kept) == bad
    assert error.startswith("IntegrityError: NOT NULL constraint failed")
    writer = beat["writer"]
    assert (writer["state"], writer["failures"], writer["rows_written"]) == ("recording", 1, len(_EVENTS))
    assert writer["last_failure"] == f"optquote.{_CONTRACT}: {error}"
    assert writer["line"].startswith("RECORDING · ") and writer["last_failure_ct"].endswith(" CT")
    assert f"last {writer['last_failure_ct']}: {writer['last_failure']}" in writer["line"]
    assert writer["cls"] == "neg"


def test_one_value_the_database_cannot_hold_is_kept_and_the_writer_goes_on(tmp_path):
    """INDUCED CONDITION: the captured TSLA quote's TOTAL_VOLUME set to 2**64, more than SQLite's
    64-bit INTEGER holds (OverflowError while binding). The captured quote after it is stored."""
    db = tmp_path / "stream_capture.db"
    big = {**_TSLA["native"], "TOTAL_VOLUME": 2 ** 64}

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        h = capture._publisher("LEVELONE_EQUITIES", bus, health)
        h({"content": [big], "timestamp": 1})
        await asyncio.sleep(0.3)
        h({"content": [_TSLA["native"]], "timestamp": 2})
        await asyncio.sleep(0.3)
        stop.set()
        await task
    asyncio.run(go())

    assert _count(db, "stream_quotes_raw") == 1, "the writer stopped after one oversized value"
    (topic, kept, error), = _failures(db)
    assert topic == "quote.TSLA" and json.loads(kept)["native"] == big
    assert error.startswith("OverflowError")


def test_a_database_locked_by_another_connection_holds_the_writer_and_it_goes_on_after(tmp_path):
    """INDUCED CONDITION: another connection holds the stream database's write lock
    (BEGIN IMMEDIATE) for 1.5 s, longer than the writer's lock wait (timeout_sec 0.2 s, an
    input). The writer reads blocked with SQLite's refusal, holds the captured quotes, and
    writes every one of them once the lock is released."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01, timeout_sec=0.2, retry_sec=0.1)
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")
    release = threading.Timer(1.5, lambda: holder.execute("COMMIT"))

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer = writer
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        release.start()
        _publish_options(bus, health, _EVENTS)
        await _until(lambda: writer.status()["state"] == "blocked")
        during = _beat(daemon)["writer"]
        await _until(lambda: writer.status()["rows_written"] == len(_EVENTS))
        after = _beat(daemon)["writer"]
        stop.set()
        await task
        return during, after
    try:
        during, after = asyncio.run(go())
    finally:
        release.join()
        holder.close()

    assert during["state"] == "blocked" and during["error"] == "OperationalError: database is locked"
    assert during["line"].startswith(f"BLOCKED · since {during['error_ct']}: OperationalError")
    assert (after["state"], after["error"], after["rows_written"]) == ("recording", None, len(_EVENTS))
    assert _count(db, "stream_options_quotes_raw") == len(_EVENTS)


def test_a_chain_whose_history_write_fails_is_kept_as_sent_and_is_never_a_chain_failure(tmp_path):
    """INDUCED CONDITION: the chain history table carries an extra NOT NULL column the writer
    does not fill, so SQLite refuses each row with IntegrityError, standing in for the refusal of
    a repeated capture key (PR #465). The chain is delivered, never published as failed and never
    pauses the sweep; the daemon's writer keeps it."""
    db = tmp_path / "ed_console.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE complete_chain_captures (ticker TEXT NOT NULL, expiry TEXT NOT NULL, "
                     "ts_utc REAL NOT NULL, spot REAL, n_contracts INTEGER NOT NULL, "
                     "completeness_basis TEXT NOT NULL, chain_json TEXT NOT NULL, source TEXT NOT NULL, "
                     "created_at TEXT, refused TEXT NOT NULL, PRIMARY KEY (ticker, expiry, ts_utc))")
    failures_db = tmp_path / "stream_capture.db"
    published: list = []

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health, board=["SPY"])
        daemon.writer = CaptureWriter(failures_db, batch_rows=1, batch_sec=0.01)
        task = asyncio.create_task(daemon.writer.run(bus.subscribe("", policy=LOG), stop=stop))
        sweep = ChainSweep(db, ["SPY"], lambda topic, msg: published.append(msg),
                           clock=lambda: _IN_WINDOW, failures=daemon.writer)
        schwab = _LocalSchwab()
        client = Client("k", httpx.Client(transport=schwab.transport), enforce_enums=False)
        try:
            delivered = await asyncio.to_thread(sweep.fetch_one, client, "SPY")
        finally:
            schwab.close()
        await _until(lambda: daemon.writer.status()["failures"] == 1)
        writer = _beat(daemon)["writer"]
        stop.set()
        await task
        return delivered, sweep, writer
    delivered, sweep, writer = asyncio.run(go())

    assert delivered is True and all("failed" not in m for m in published), "a delivered chain read failed"
    assert sweep._paused_until == 0.0, "a history write paused the sweep"
    (topic, kept, error), = _failures(failures_db)
    assert topic == "chain_history.SPY"
    assert error.startswith("IntegrityError: NOT NULL constraint failed: complete_chain_captures.refused")
    kept = json.loads(kept)
    received = [ct for msg in published for ct in msg["contracts"]]
    kept_contracts = [ct for side in ("callExpDateMap", "putExpDateMap")
                      for by_strike in kept[side].values() for listed in by_strike.values()
                      for ct in listed]
    assert sorted(c["symbol"] for c in kept_contracts) == sorted(c["symbol"] for c in received)
    assert all(c in received for c in kept_contracts), "kept as the sweep received it"
    assert writer["failures"] == 1 and writer["last_failure"] == f"chain_history.SPY: {error}"
