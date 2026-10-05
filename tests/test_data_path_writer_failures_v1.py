"""docs/DATA_FLOW.md §2 D4 (the one writer records every message Schwab sends): a message the
writer cannot store is kept as sent, and the writer's state reaches the heartbeat the console and
the browser read.

Real data: captured LEVELONE_OPTIONS quotes (tests/fixtures/real_options_stream_history_samples.json)
through the daemon's own handler (capture._publisher) and bus; the captured SPY 2026-11-20 chain and
quotes (tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json) through the real ChainSweep.
STAND-INS: the local host for Schwab's (test_data_path_rules_v1._LocalSchwab), serving a chain
envelope rebuilt from the captured contracts. Each induced failure is named in its test.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import stat
import time

import httpx
from schwab.client import Client

import live_market_plane as lmp
from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.live_ui import LiveUiServer
from calibration.complete_chain_capture import ChainSweep
from stream_spine import (LOG, WRITER_DEAD, WRITER_STOPPED, CaptureWriter, HealthRegistry,
                          MessageBus, options_quote_msg)
from tests.test_data_path_rules_v1 import _CONTRACT, _EVENTS, _LocalSchwab, _frame

_IN_WINDOW = 1790863205.0          # 2026-10-01 10:00:05 ET, inside the 10:00 capture window


def _failures(db) -> list:
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT topic, msg_json, error FROM stream_write_failures").fetchall()


def _beat(daemon: capture.Daemon) -> dict:
    """The heartbeat as the browser's price socket sends it (live_ui's feed beat), and as the
    console records it (live_market_plane.daemon_status); the console's record is cleared after."""
    beat = LiveUiServer(daemon.bus, daemon.status, {}).beat()
    try:
        assert lmp.daemon_status()["writer"] == beat["writer"]
    finally:
        lmp.record_feed_down()
    return beat


def test_a_message_the_writer_cannot_store_is_kept_as_sent_and_its_error_reaches_the_heartbeat(tmp_path):
    """The writer swallowed every insert failure into a counter nothing read: the message was
    lost and nobody was told. INDUCED CONDITION: one captured option quote published with no
    symbol, so the NOT NULL symbol column refuses its row."""
    db = tmp_path / "stream_capture.db"
    bad = options_quote_msg(symbol=None, content=_EVENTS[0]["content"], src="schwab_stream",
                            schwab_ts=_EVENTS[0]["content"].get("QUOTE_TIME_MILLIS"))

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
        task = asyncio.create_task(daemon.writer.run(bus.subscribe("", policy=LOG), stop=stop))
        h = capture._publisher("LEVELONE_OPTIONS", bus, health)
        for e in _EVENTS:
            h(_frame("LEVELONE_OPTIONS", [e["content"]], e["content"].get("QUOTE_TIME_MILLIS", 0)))
        bus.publish(f"optquote.{_CONTRACT}", bad)
        await asyncio.sleep(0.3)
        beat = _beat(daemon)
        stop.set()
        await task
        return beat, daemon.status()["writer"]
    beat, after = asyncio.run(go())

    with sqlite3.connect(db) as conn:
        stored = conn.execute("SELECT COUNT(*) FROM stream_options_quotes_raw").fetchone()[0]
    assert stored == len(_EVENTS), "a refused row cost the good rows around it"
    (topic, kept, error), = _failures(db)
    assert topic == f"optquote.{_CONTRACT}" and json.loads(kept) == bad
    assert error.startswith("IntegrityError: NOT NULL constraint failed")
    writer = beat["writer"]
    assert (writer["failures"], writer["rows_written"]) == (1, len(_EVENTS))
    assert writer["last_failure"] == f"optquote.{_CONTRACT}: {error}"
    assert after["state"] == WRITER_STOPPED and after["error"] is None


def test_a_writer_whose_database_refuses_every_write_reads_dead_with_its_error(tmp_path):
    """A refused commit (a full disk, a lock held past 30 s) ended the writer thread with no
    trace, while the daemon queued every later message for it without end. INDUCED CONDITION:
    the stream database file is made read-only, standing in for a full disk: SQLite refuses the
    first write and the failure table too. A refused commit itself is not induced (no write can
    be made to fail at commit without patching); it ends the thread through the same path."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
    os.chmod(db, stat.S_IREAD)

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer = writer
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        h = capture._publisher("LEVELONE_OPTIONS", bus, health)
        first, rest = _EVENTS[0], _EVENTS[1:]
        h(_frame("LEVELONE_OPTIONS", [first["content"]], first["content"].get("QUOTE_TIME_MILLIS", 0)))
        deadline = time.monotonic() + 10
        while writer.status()["state"] != WRITER_DEAD and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        for e in rest:
            h(_frame("LEVELONE_OPTIONS", [e["content"]], e["content"].get("QUOTE_TIME_MILLIS", 0)))
        await asyncio.sleep(0.3)
        beat = _beat(daemon)
        stop.set()
        await task
        return beat
    try:
        beat = asyncio.run(go())
    finally:
        os.chmod(db, stat.S_IREAD | stat.S_IWRITE)
    writer_state = beat["writer"]
    assert writer_state["state"] == WRITER_DEAD
    assert writer_state["error"].startswith("OperationalError: attempt to write a readonly database")
    assert writer_state["unrecorded"] == len(_EVENTS) - 1, "messages after the death were queued, not counted"
    assert writer_state["rows_written"] == 0


def test_a_chain_whose_history_write_is_refused_is_kept_as_sent_and_shown(tmp_path):
    """ChainSweep.fetch_one caught every exception from the history write and only logged it:
    a chain not saved is gone (decision 7), and nothing on the heartbeat said so. INDUCED
    CONDITION: the chain history table carries an extra NOT NULL column the writer does not
    fill, so SQLite refuses each row with IntegrityError, standing in for the refusal of a
    repeated capture key (PR #465)."""
    db = tmp_path / "ed_console.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE complete_chain_captures (ticker TEXT NOT NULL, expiry TEXT NOT NULL, "
                     "ts_utc REAL NOT NULL, spot REAL, n_contracts INTEGER NOT NULL, "
                     "completeness_basis TEXT NOT NULL, chain_json TEXT NOT NULL, source TEXT NOT NULL, "
                     "created_at TEXT, refused TEXT NOT NULL, PRIMARY KEY (ticker, expiry, ts_utc))")
    failures_db = tmp_path / "stream_capture.db"
    bus, health = MessageBus(), HealthRegistry()
    daemon = capture.Daemon(bus, health, board=["SPY"])
    daemon.writer = CaptureWriter(failures_db)
    published: list = []
    sweep = ChainSweep(db, ["SPY"], lambda topic, msg: published.append(msg),
                       clock=lambda: _IN_WINDOW, failures=daemon.writer)
    schwab = _LocalSchwab()
    client = Client("k", httpx.Client(transport=schwab.transport), enforce_enums=False)
    try:
        assert sweep.fetch_one(client, "SPY") is True, "the delivered chain stands"
    finally:
        schwab.close()

    (topic, kept, error), = _failures(failures_db)
    assert topic == "chain_history.SPY"
    assert error.startswith("IntegrityError: NOT NULL constraint failed: complete_chain_captures.refused")
    kept = json.loads(kept)
    delivered = [ct for msg in published for ct in msg["contracts"]]
    kept_contracts = [ct for side in ("callExpDateMap", "putExpDateMap")
                      for by_strike in kept[side].values() for listed in by_strike.values()
                      for ct in listed]
    assert sorted(c["symbol"] for c in kept_contracts) == sorted(c["symbol"] for c in delivered)
    assert kept_contracts and all(c in delivered for c in kept_contracts), "kept as the sweep received it"
    writer = daemon.status()["writer"]
    assert writer["failures"] == 1 and writer["last_failure"] == f"chain_history.SPY: {error}"
