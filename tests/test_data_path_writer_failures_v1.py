"""docs/DATA_FLOW.md §2 D4 (the one writer records every message Schwab sends): a message the
writer cannot store is kept as sent, a database that refuses writes holds the writer instead of
ending it, and the writer's state reaches the heartbeat the console and the browser read.

Real data: captured LEVELONE_OPTIONS quotes (tests/fixtures/real_options_stream_history_samples.json)
and a captured TSLA LEVELONE_EQUITIES item (tests/fixtures/real_equity_book.json, "quote") through
the daemon's own handler (capture._publisher) and bus; the captured SPY 2026-11-20 chain and quotes
(tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json) through the real ChainSweep.
STAND-INS: the local host for Schwab's (tests/schwab_rest_standin.py), serving a chain envelope
rebuilt from the captured contracts. Each induced failure is named in its test.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sqlite3
import stat
import sys
import threading
import time
import tracemalloc
from pathlib import Path

import launch
import live_market_plane as lmp
from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.live_push import serve_live_push
from app.market_data.schwab.streaming.live_ui import LiveUiServer
from calibration.complete_chain_capture import ChainSweep
from stream_spine import LOG, CaptureWriter, HealthRegistry, MessageBus, options_quote_msg, quote_msg
from tests.schwab_rest_standin import CHAIN, LocalSchwab
from tests.test_data_path_rules_v1 import _CONTRACT, _EVENTS, _frame

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
        deadline = time.monotonic() + 10                  # every message taken: the rows and the refused one
        while (daemon.writer.status()["rows_written"] < len(_EVENTS) or not daemon.writer.status()["failures"]) \
                and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
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


def test_a_database_read_only_when_the_writer_starts_is_written_once_it_accepts_writes(tmp_path):
    """INDUCED CONDITION: the stream database file is read-only before the writer starts
    (standing in for a disk that refuses writes) and made writable again 1.5 s later, with the
    WAL files SQLite created beside it meanwhile (SQLite gives them the database file's mode).
    Every captured quote published meanwhile is held, all of them counted as waiting, and
    written once the files accept writes."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
    os.chmod(db, stat.S_IREAD)

    def writable() -> None:
        for path in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
            if path.exists():
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer = writer
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        _publish_options(bus, health, _EVENTS)
        await asyncio.sleep(1.5)
        during = daemon.status().get("writer")
        writable()
        await _until(lambda: _count(db, "stream_options_quotes_raw") == len(_EVENTS))
        after = daemon.status().get("writer")
        stop.set()
        await task
        return during, after
    try:
        during, after = asyncio.run(go())
    finally:
        writable()

    assert _count(db, "stream_options_quotes_raw") == len(_EVENTS), "the writer never recovered"
    assert during["state"] == "blocked"
    assert during["error"].startswith("OperationalError: attempt to write a readonly database")
    assert during["waiting"] == during["held"] == len(_EVENTS) and during["queue_depth"] == 0
    assert during["held_bytes"] > 0 and during["spill"] is None
    assert (f"held in memory: {len(_EVENTS)} messages, {during['held_bytes'] / 1e6:.1f} MB "
            f"({len(_EVENTS)} waiting for the database)") in during["line"]
    assert (after["state"], after["rows_written"], after["held"]) == ("recording", len(_EVENTS), 0)


class _Defect(dict):
    """STAND-IN for a defect in the writer: a message whose row builder raises an error no row
    can raise (RuntimeError), so the writer thread ends."""

    def get(self, key, default=None):
        if key == "bid":
            raise RuntimeError("a defect in the writer")
        return dict.get(self, key, default)


def _tsla_quotes(bus, health, n: int) -> None:
    h = capture._publisher("LEVELONE_EQUITIES", bus, health)
    for i in range(n):
        h({"content": [dict(_TSLA["native"])], "timestamp": i})


def _defect() -> "_Defect":
    return _Defect(quote_msg(symbol="TSLA", src="schwab_stream", native=_TSLA["native"]))


def test_a_writer_that_dies_in_a_retry_counts_each_held_message_not_recorded_once(tmp_path):
    """INDUCED CONDITIONS: the stream database is read-only before the writer starts, holding 3
    captured TSLA quotes and one _Defect message, then made writable: the retry stores the 3 in
    its open batch and ends on the 4th. Each of the 4 is not recorded, counted once."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db)
    os.chmod(db, stat.S_IREAD)

    def writable() -> None:
        for path in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
            if path.exists():
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        _tsla_quotes(bus, health, 3)
        bus.publish("quote.TSLA", _defect())
        await asyncio.sleep(1.5)
        writable()
        await _until(lambda: writer.status()["state"] == "dead")
        dead = writer.status()
        stop.set()
        await task
        return dead, writer.status()
    try:
        dead, after = asyncio.run(go())
    finally:
        writable()

    assert dead["state"] == "dead" and dead["error"] == "RuntimeError: a defect in the writer"
    assert dead["unrecorded"] == 4 and dead["rows_written"] == 0
    assert (after["unrecorded"], after["held"]) == (4, 0)


def test_a_writer_that_dies_while_recording_counts_the_message_that_ended_it(tmp_path):
    """INDUCED CONDITION: 3 captured TSLA quotes in the open batch (no commit inside 60 s), then a
    _Defect message, then 4 more queued; after the writer dies, 6 more. Not recorded: 3 + 1 + 4,
    then 14."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1000, batch_sec=60.0)

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        _tsla_quotes(bus, health, 3)
        bus.publish("quote.TSLA", _defect())
        _tsla_quotes(bus, health, 4)
        await _until(lambda: writer.status()["state"] == "dead")
        dead = writer.status()
        _tsla_quotes(bus, health, 6)
        await asyncio.sleep(0.5)
        later = writer.status()
        stop.set()
        await task
        return dead, later, writer.status()
    dead, later, after = asyncio.run(go())

    assert dead["state"] == "dead" and dead["unrecorded"] == 8
    assert later["unrecorded"] == 14
    assert (after["unrecorded"], after["held"], _count(db, "stream_quotes_raw")) == (14, 0, 0)


def test_a_row_only_the_database_refuses_is_kept_and_the_writer_is_not_blocked(tmp_path):
    """INDUCED CONDITION: a trigger on the quotes table raises SQLite's "integer overflow"
    (OperationalError, SQLITE_ERROR) for TSLA's rows only. That refusal is the row's, not the
    database's: the captured TSLA quote is kept as sent and the captured option quotes after it
    are stored; the writer is never blocked."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TRIGGER refuse_tsla BEFORE INSERT ON stream_quotes_raw "
                     "WHEN NEW.symbol = 'TSLA' BEGIN SELECT abs(-9223372036854775808); END")

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        _tsla_quotes(bus, health, 1)
        _publish_options(bus, health, _EVENTS)
        await _until(lambda: _count(db, "stream_options_quotes_raw") == len(_EVENTS), limit=5.0)
        stop.set()
        await task
    asyncio.run(go())

    assert _count(db, "stream_options_quotes_raw") == len(_EVENTS), "one refused row blocked the writer"
    (topic, kept, error), = _failures(db)
    assert (topic, error) == ("quote.TSLA", "OperationalError: integer overflow")
    assert json.loads(kept)["native"] == _TSLA["native"]
    assert writer.status()["state"] == "stopped"


def test_a_chain_whose_history_write_fails_is_kept_as_sent_and_is_never_a_chain_failure(tmp_path):
    """INDUCED CONDITION: the chain history table carries an extra NOT NULL column the writer
    does not fill, so SQLite refuses each row with IntegrityError, standing in for the refusal of
    a repeated capture key (PR #465). The chain is delivered and never published as failed, the
    sweep fetches the next chain at once (no pause: a second chain request reaches the host), and
    the daemon's writer keeps the chain as delivered."""
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
        daemon = capture.Daemon(bus, health, ["SPY"])
        daemon.writer = CaptureWriter(failures_db, batch_rows=1, batch_sec=0.01)
        task = asyncio.create_task(daemon.writer.run(bus.subscribe("", policy=LOG), stop=stop))
        sweep = ChainSweep(db, ["SPY"], lambda topic, msg: published.append(msg),
                           clock=lambda: _IN_WINDOW, failures=daemon.writer, streamed=daemon.option_record)
        schwab = LocalSchwab()
        client = schwab.client(tmp_path)
        def chains() -> int:
            return len(schwab.asked(CHAIN))
        halt = threading.Event()
        worker = threading.Thread(target=sweep.work, args=(lambda: client, halt), daemon=True)
        try:
            worker.start()
            await _until(lambda: chains() >= 2 and daemon.writer.status()["failures"] >= 2, limit=4.0)
        finally:
            halt.set()
            await asyncio.to_thread(worker.join, 10)
            schwab.close()
        writer = _beat(daemon)["writer"]
        stop.set()
        await task
        return chains(), writer
    fetched, writer = asyncio.run(go())

    assert published and all("failed" not in m for m in published), "a delivered chain read failed"
    assert fetched >= 2, "the sweep paused after a history write failed"
    failures = _failures(failures_db)          # each fetch of the window tries the history again
    assert len(failures) == writer["failures"] >= 2
    assert {topic for topic, _k, _e in failures} == {"chain_history.SPY"}
    (topic, kept, error) = failures[0]
    assert error.startswith("IntegrityError: NOT NULL constraint failed: complete_chain_captures.refused")
    kept = json.loads(kept)
    parts = [m for m in published if m["src"] == "schwab_chain"]          # the chain's, not its price history
    received = [ct for msg in parts[:parts[0]["parts"]] for ct in msg["contracts"]]
    assert kept["spots"] == {"2026-11-20": 766.31}
    assert kept["contracts"] == received, "kept as the sweep delivered it"
    assert writer["last_failure"] == f"chain_history.SPY: {failures[-1][2]}"


#: STAND-IN for the production hold cap (about 2 GB of memory): 4,000 bytes, so the captured option
#: quotes (about 1.1 to 2.2 KB each in memory) fill memory with two or three of them and the rest
#: go to the spill file
_SMALL_CAP = 4000


async def _held_past_the_cap(writer, bus, health, daemon) -> dict:
    """The captured option quotes published while the database is locked; returns the writer's
    status, as the heartbeat carries it, once every one is held in memory or in the spill file."""
    _publish_options(bus, health, _EVENTS)

    def all_held() -> bool:
        s = writer.status()
        return s["spill"] is not None and s["spill"]["messages"] + s["waiting"] == len(_EVENTS)
    await _until(all_held)
    return _beat(daemon)["writer"]


def test_a_block_past_the_hold_cap_spills_to_disk_and_writes_back_in_arrival_order(tmp_path):
    """INDUCED CONDITION: another connection holds the stream database's write lock
    (BEGIN IMMEDIATE) while the captured option quotes arrive, against a writer whose hold cap is
    _SMALL_CAP (an input) and whose lock wait is 0.2 s; then releases it. Past the cap the quotes
    go to a spill file beside the database, the Record says so with the file's size, and once the
    lock is released every quote is in the database exactly once, in arrival order, and the spill
    file is gone once its rows are committed."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01, timeout_sec=0.2, retry_sec=0.1,
                           hold_cap_bytes=_SMALL_CAP)
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer = writer
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        during = await _held_past_the_cap(writer, bus, health, daemon)
        on_disk = Path(during["spill"]["path"]).stat().st_size
        holder.execute("COMMIT")
        await _until(lambda: writer.status()["spill"] is None
                     and _count(db, "stream_options_quotes_raw") == len(_EVENTS))
        after = _beat(daemon)["writer"]
        stop.set()
        await task
        return during, on_disk, after
    try:
        during, on_disk, after = asyncio.run(go())
    finally:
        holder.close()

    spill = during["spill"]
    path = Path(spill["path"])
    assert during["state"] == "blocked" and during["held_bytes"] <= _SMALL_CAP and during["waiting"] >= 1
    assert spill["messages"] >= 1 and spill["bytes"] == on_disk and path.parent == db.parent
    assert path.name.startswith("stream_capture.") and path.suffix == ".spill"
    assert during["line"].startswith("BLOCKED, SPILLING TO DISK · ")
    assert f"spilled to disk: {spill['messages']} messages, {on_disk:,} bytes in {path.name}" in during["line"]
    with sqlite3.connect(db) as conn:
        stored = [json.loads(r[0]) for r in conn.execute(
            "SELECT native_json FROM stream_options_quotes_raw ORDER BY rowid")]
    assert stored == [e["content"] for e in _EVENTS], "not every quote exactly once, in arrival order"
    assert not path.exists(), "the spill file outlived its committed write-back"
    assert (after["state"], after["spill"], after["rows_written"]) == ("recording", None, len(_EVENTS))


def _run_until_no_spill(writer: CaptureWriter) -> dict:
    """`writer` run until it holds no spill file, then stopped; its status."""
    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(MessageBus().subscribe("", policy=LOG), stop=stop))
        await _until(lambda: writer.status()["spill"] is None)
        stop.set()
        await task
    asyncio.run(go())
    return writer.status()


def test_a_database_refusing_writes_at_start_never_stops_the_writer_starting(tmp_path):
    """INDUCED CONDITIONS: a fully written-back spill file left beside the database (its progress
    row counts every record: a kill between its last part and its deletion), and the database
    read-only. The writer starts; once the database takes writes it deletes the file and its row
    without writing it again."""
    db = tmp_path / "stream_capture.db"
    CaptureWriter(db)
    record = json.dumps({"topic": f"optquote.{_CONTRACT}", "msg": options_quote_msg(
        symbol=_CONTRACT, content=_EVENTS[0]["content"], src="schwab_stream", ts_recv=1790863200.0)}).encode()
    spill = db.with_name("stream_capture.1.spill")
    spill.write_bytes(len(record).to_bytes(4, "big") + record)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO stream_spill_progress(spill, written_back) VALUES(?, 1)", (spill.name,))
    os.chmod(db, stat.S_IREAD)
    try:
        writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01, timeout_sec=0.2, retry_sec=0.1)
    finally:
        os.chmod(db, stat.S_IREAD | stat.S_IWRITE)
    after = _run_until_no_spill(writer)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM stream_spill_progress").fetchone()[0] == 0
    assert not spill.exists() and _count(db, "stream_options_quotes_raw") == 0
    assert after["state"] == "stopped"


def _undeletable(path: Path):
    """INDUCED CONDITION: the disk refuses to delete `path`, as Windows does while another handle
    holds the file open (a viewer, a virus scan); elsewhere its folder read-only. Returns the
    release."""
    if sys.platform == "win32":
        return open(path, "rb").close
    os.chmod(path.parent, stat.S_IREAD | stat.S_IEXEC)
    return lambda: os.chmod(path.parent, stat.S_IRWXU)


def test_a_written_back_spill_the_disk_will_not_delete_is_deleted_at_the_next_start(tmp_path):
    """INDUCED CONDITIONS: as in the spill test, and, before the lock is released, the spill file
    undeletable (_undeletable). Every quote is written back once and the writer goes on recording
    what arrives after; the file stays with its progress row. Released, the next writer's start
    deletes it and its row without writing it again."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01, timeout_sec=0.2, retry_sec=0.1,
                           hold_cap_bytes=_SMALL_CAP)
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer = writer
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        during = await _held_past_the_cap(writer, bus, health, daemon)
        release = _undeletable(Path(during["spill"]["path"]))
        try:
            holder.execute("COMMIT")
            await _until(lambda: writer.status()["spill"] is None)
            _publish_options(bus, health, _EVENTS[:1])                # arrives after the write-back
            await _until(lambda: _count(db, "stream_options_quotes_raw") == len(_EVENTS) + 1)
            after = _beat(daemon)["writer"]
            stop.set()
            await task
        finally:
            release()
        return during, after
    try:
        during, after = asyncio.run(go())
    finally:
        holder.close()

    path = Path(during["spill"]["path"])
    assert after["state"] == "recording", "the writer did not go on after the disk refused the delete"
    assert path.exists() and [Path(k["path"]) for k in after["left_on_disk"]] == [path]
    _run_until_no_spill(CaptureWriter(db, batch_rows=1, batch_sec=0.01))
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM stream_spill_progress").fetchone()[0] == 0
    assert not path.exists(), "the next start did not delete the written-back spill"
    assert _count(db, "stream_options_quotes_raw") == len(_EVENTS) + 1, "the next start wrote it again"


def test_a_spill_file_is_resumed_after_its_committed_part_and_a_crash_cut_record_is_kept(tmp_path):
    """INDUCED CONDITIONS: two spill files beside the database, as a kill leaves them, holding the
    captured option quotes: the older's first 4 records committed (its progress row says 4) and
    half a record after its last whole one; the newer fully committed (killed between its last
    part and its deletion). A new writer writes the older's other records once, in order, deletes
    it, keeps the cut record's bytes as sent in stream_write_failures, and deletes the newer
    without writing it again; no progress row is left."""
    db = tmp_path / "stream_capture.db"
    CaptureWriter(db)
    records = [json.dumps({"topic": f"optquote.{_CONTRACT}", "msg": options_quote_msg(   # DATA_FLOW §2 D4's format
        symbol=_CONTRACT, content=e["content"], src="schwab_stream", ts_recv=1790863200.0 + i)}).encode()
        for i, e in enumerate(_EVENTS)]
    older, newer = db.with_name("stream_capture.1.spill"), db.with_name("stream_capture.2.spill")
    older.write_bytes(b"".join(len(r).to_bytes(4, "big") + r for r in records) + b"\x00\x00\x01")
    newer.write_bytes(b"".join(len(r).to_bytes(4, "big") + r for r in records[:2]))
    with sqlite3.connect(db) as conn:
        conn.executemany("INSERT INTO stream_spill_progress(spill, written_back) VALUES(?,?)",
                         [(older.name, 4), (newer.name, 2)])

    async def go():
        bus, stop = MessageBus(), asyncio.Event()
        writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        await _until(lambda: writer.status()["spill"] is None)
        stop.set()
        await task
        return writer.status()
    after = asyncio.run(go())

    with sqlite3.connect(db) as conn:
        stored = [ts for (ts,) in conn.execute("SELECT ts_recv FROM stream_options_quotes_raw ORDER BY rowid")]
        progress = conn.execute("SELECT COUNT(*) FROM stream_spill_progress").fetchone()[0]
        kept = conn.execute("SELECT topic, msg_json, error FROM stream_write_failures").fetchall()
    assert stored == [1790863200.0 + i for i in range(4, len(_EVENTS))], "not the uncommitted records once, in order"
    assert not older.exists() and not newer.exists() and after["lost"] == 0
    assert [(t, json.loads(m).encode("latin-1")) for t, m, _e in kept] == [("spill", b"\x00\x00\x01")], \
        "the cut record's bytes are not kept as sent"
    assert kept[0][2].startswith(f"{older.name}: the 3 bytes from byte ")
    assert (after["left_on_disk"], progress) == ([], 0)


def test_what_arrives_while_a_found_spill_waits_is_never_written_behind_its_cut_bytes(tmp_path):
    """INDUCED CONDITIONS: a spill file left beside the database holding one captured option quote
    and 3 bytes a crash cut off after it; the database locked while the writer starts and the
    other captured quotes arrive. Released: the found quote is written, its cut bytes kept as one
    row, and every quote that arrived is written as its own row, in order (they went to a new
    spill file, not behind the cut bytes)."""
    db = tmp_path / "stream_capture.db"
    CaptureWriter(db)
    record = json.dumps({"topic": f"optquote.{_CONTRACT}", "msg": options_quote_msg(
        symbol=_CONTRACT, content=_EVENTS[0]["content"], src="schwab_stream", ts_recv=1790863200.0)}).encode()
    db.with_name("stream_capture.1.1.spill").write_bytes(len(record).to_bytes(4, "big") + record + b"\x00\x00\x01")
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01, timeout_sec=0.2, retry_sec=0.1)
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        _publish_options(bus, health, _EVENTS[1:])
        await _until(lambda: len(writer.status()["spills_after"]) == 1
                     and writer.status()["spills_after"][0]["messages"] == len(_EVENTS) - 1)
        holder.execute("COMMIT")
        await _until(lambda: writer.status()["spill"] is None)
        stop.set()
        await task
        return writer.status()
    try:
        after = asyncio.run(go())
    finally:
        holder.close()
    with sqlite3.connect(db) as conn:
        stored = [json.loads(r[0]) for r in conn.execute(
            "SELECT native_json FROM stream_options_quotes_raw ORDER BY rowid")]
        kept = conn.execute("SELECT COUNT(*) FROM stream_write_failures").fetchone()[0]
    assert stored == [e["content"] for e in _EVENTS], "a quote that arrived was not written as its own row"
    assert (kept, after["failures"], after["lost"]) == (1, 1, 0)


def test_a_found_spill_whose_cut_bytes_were_kept_is_deleted_without_keeping_them_again(tmp_path):
    """INDUCED CONDITION: a spill file left beside the database with one quote and 3 cut bytes
    after it, its progress row counting both (written back, the cut bytes kept, then the disk
    would not delete it, or a kill came between the commit and the delete). The next writer
    deletes it and its row, writing nothing again."""
    db = tmp_path / "stream_capture.db"
    CaptureWriter(db)
    record = json.dumps({"topic": f"optquote.{_CONTRACT}", "msg": options_quote_msg(
        symbol=_CONTRACT, content=_EVENTS[0]["content"], src="schwab_stream", ts_recv=1790863200.0)}).encode()
    spill = db.with_name("stream_capture.1.1.spill")
    spill.write_bytes(len(record).to_bytes(4, "big") + record + b"\x00\x00\x01")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO stream_spill_progress(spill, written_back) VALUES(?, 2)", (spill.name,))
    _run_until_no_spill(CaptureWriter(db, batch_rows=1, batch_sec=0.01))
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM stream_spill_progress").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM stream_write_failures").fetchone()[0] == 0, "the cut bytes were kept again"
    assert not spill.exists() and _count(db, "stream_options_quotes_raw") == 0


def test_a_damaged_length_found_at_start_keeps_every_byte_after_it(tmp_path):
    """INDUCED CONDITION: a spill file left beside the database whose second record's length is
    damaged (0xFFFFFFFF; STAND-IN for a damaged disk), whole records after it. A new writer writes
    the first record; every byte from the damaged length to the end is kept as sent, exactly, in
    stream_write_failures (it places no record after it), never cut from the file unrecorded."""
    db = tmp_path / "stream_capture.db"
    CaptureWriter(db)
    records = [json.dumps({"topic": f"optquote.{_CONTRACT}", "msg": options_quote_msg(
        symbol=_CONTRACT, content=e["content"], src="schwab_stream", ts_recv=1790863200.0 + i)}).encode()
        for i, e in enumerate(_EVENTS)]
    framed = [len(r).to_bytes(4, "big") + r for r in records]
    rest = b"\xff\xff\xff\xff" + framed[1][4:] + b"".join(framed[2:])
    spill = db.with_name("stream_capture.1.spill")
    spill.write_bytes(framed[0] + rest)

    async def go():
        bus, stop = MessageBus(), asyncio.Event()
        writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        await _until(lambda: writer.status()["spill"] is None)
        stop.set()
        await task
        return writer.status()
    after = asyncio.run(go())

    with sqlite3.connect(db) as conn:
        stored = [ts for (ts,) in conn.execute("SELECT ts_recv FROM stream_options_quotes_raw ORDER BY rowid")]
        kept = [json.loads(m).encode("latin-1") for (m,) in conn.execute("SELECT msg_json FROM stream_write_failures")]
    assert stored == [1790863200.0]
    assert kept == [rest], "the bytes after the damaged length are not all kept, exactly"
    assert not spill.exists() and (after["lost"], after["failures"]) == (0, 1)


def test_a_damaged_length_in_a_live_write_back_keeps_the_rest_and_the_spill_finishes(tmp_path):
    """INDUCED CONDITIONS: as in the spill tests, and, while the lock is held, the spill file's last
    record's length damaged in place (0xFFFFFFFF). On release every record before it is written,
    the bytes from the damaged length on are kept as one row, the spill finishes, and what arrives
    after is written to the database."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01, timeout_sec=0.2, retry_sec=0.1,
                           hold_cap_bytes=_SMALL_CAP)
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer = writer
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        during = await _held_past_the_cap(writer, bus, health, daemon)
        path = Path(during["spill"]["path"])
        with open(path, "r+b") as f:            # where the last record starts
            last, at = 0, 0
            while at < during["spill"]["bytes"]:
                last = at
                f.seek(at)
                at += 4 + int.from_bytes(f.read(4), "big")
            f.seek(last)
            f.write(b"\xff\xff\xff\xff")
        holder.execute("COMMIT")
        await _until(lambda: writer.status()["spill"] is None)
        _publish_options(bus, health, _EVENTS[:1])
        await _until(lambda: _count(db, "stream_options_quotes_raw") == len(_EVENTS))
        after = _beat(daemon)["writer"]
        stop.set()
        await task
        return after
    try:
        after = asyncio.run(go())
    finally:
        holder.close()
    with sqlite3.connect(db) as conn:
        stored = [json.loads(r[0]) for r in conn.execute(
            "SELECT native_json FROM stream_options_quotes_raw ORDER BY rowid")]
        kept = conn.execute("SELECT COUNT(*) FROM stream_write_failures").fetchone()[0]
    assert stored == [e["content"] for e in _EVENTS[:-1]] + [_EVENTS[0]["content"]]
    assert (kept, after["state"], after["spill"]) == (1, "recording", None)


def test_a_spill_file_is_never_opened_over_another_file(tmp_path):
    """INDUCED CONDITIONS: as in the hold-cap test, the database locked while the captured option
    quotes arrive, and a stop while it is still locked, so the writer opens the spill file and, at
    the stop, a file for what memory held; beforehand every name a spill file could take in the
    1.5 s the quotes arrive in (a millisecond each, in every form) is already taken by a file of
    its own. The writer opens neither over any of them: each stays as it was, and the writer's two
    files hold every quote, memory's file named first."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01, timeout_sec=0.2, retry_sec=0.1,
                           hold_cap_bytes=_SMALL_CAP)
    begin = int(time.time() * 1000) + 8000
    taken = [db.with_name(f"stream_capture.{ms}{n}.spill") for ms in range(begin, begin + 1500) for n in ("", ".0", ".1")]
    for path in taken:
        path.write_bytes(b"taken")
    assert time.time() * 1000 < begin, "the names were not all taken before the quotes arrive"
    time.sleep(begin / 1000 - time.time())
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer = writer
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        await _held_past_the_cap(writer, bus, health, daemon)
        stop.set()
        await task
    try:
        asyncio.run(go())
    finally:
        holder.close()

    assert [p for p in taken if p.read_bytes() != b"taken"] == [], "a spill file was opened over another file"
    left = writer.status()["left_on_disk"]
    assert len({k["path"] for k in left}) == len(left) == 2 and not set(map(str, taken)) & {k["path"] for k in left}
    assert sum(k["messages"] for k in left) == len(_EVENTS)
    assert [k["path"] for k in left] == sorted((k["path"] for k in left), key=lambda p: tuple(
        int(part) for part in Path(p).name.split(".")[1:-1])), "memory's file is not named before the spill's"


def test_a_database_made_before_the_receipt_time_indexes_is_not_reindexed_at_start(tmp_path):
    """A new database gets the receipt-time indexes on quotes, books and option quotes; a database
    made before them (its tables indexed by symbol, as production's) keeps its indexes as they are
    when a writer starts on it: the change is made by hand at the production step."""
    new = tmp_path / "new" / "stream_capture.db"
    CaptureWriter(new)
    old = tmp_path / "old" / "stream_capture.db"
    old.parent.mkdir()
    with sqlite3.connect(old) as conn:
        conn.executescript(
            "CREATE TABLE stream_quotes_raw (ts_recv REAL NOT NULL, symbol TEXT NOT NULL, bid REAL, ask REAL, "
            "last REAL, bid_size INTEGER, ask_size INTEGER, last_size INTEGER, total_volume INTEGER, "
            "quote_time_ms INTEGER, trade_time_ms INTEGER, src TEXT NOT NULL);"
            "CREATE INDEX idx_sqr_sym_ts ON stream_quotes_raw(symbol, ts_recv);"
            "CREATE TABLE stream_book_raw (ts_recv REAL NOT NULL, symbol TEXT NOT NULL, service TEXT NOT NULL, "
            "native_json TEXT NOT NULL, src TEXT NOT NULL);"
            "CREATE INDEX idx_sbkr_sym_ts ON stream_book_raw(symbol, ts_recv);"
            "CREATE TABLE stream_options_quotes_raw (ts_recv REAL NOT NULL, symbol TEXT NOT NULL, "
            "native_json TEXT NOT NULL, src TEXT NOT NULL);"
            "CREATE INDEX idx_soqr_sym_ts ON stream_options_quotes_raw(symbol, ts_recv);")
    CaptureWriter(old)

    def indexes(db) -> dict:
        with sqlite3.connect(db) as conn:
            return {t: sorted(n for (n,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?", (t,)))
                for t in ("stream_quotes_raw", "stream_book_raw", "stream_options_quotes_raw")}
    assert indexes(new) == {"stream_quotes_raw": ["idx_sqr_ts"], "stream_book_raw": ["idx_sbkr_ts"],
                            "stream_options_quotes_raw": ["idx_soqr_ts"]}
    assert indexes(old) == {"stream_quotes_raw": ["idx_sqr_sym_ts"], "stream_book_raw": ["idx_sbkr_sym_ts"],
                            "stream_options_quotes_raw": ["idx_soqr_sym_ts"]}, "a start changed an existing table's index"


#: production's stream in its real proportions: every message received 2026-10-05 14:00:00-14:00:03
#: CT, as Schwab sent it (7,420 option quotes, 152 equity quotes, 12 books; read-only from
#: stream_capture.db, provenance in the file)
_MIX = json.loads((Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json")
                  .read_text(encoding="utf-8"))
_MIX_TABLES = {"stream_options_quotes_raw": "LEVELONE_OPTIONS", "stream_quotes_raw": "LEVELONE_EQUITIES",
               "stream_book_raw": None}


def _mix_frames() -> list:
    """The mix as the wire carries it: (service, the frame's JSON), one frame per message."""
    return [(m["service"], json.dumps({"content": [m["item"]], "timestamp": m["schwab_ts"]}))
            for m in _MIX["messages"]]


def _mix_rows(db) -> int:
    return sum(_count(db, t) for t in _MIX_TABLES)


def _pages_for_the_mix(db, *, indexes: bool) -> int:
    """Database pages the writer writes for one copy of the mix (_MIX), through the daemon's
    handlers and bus, onto tables that already hold 8 copies of it: the WAL frames the burst adds,
    a reader holding its snapshot from before so no checkpoint resets the WAL. `indexes` False:
    the mix's tables without their indexes, the rows' own pages."""
    writer = CaptureWriter(db)
    with sqlite3.connect(db) as conn:
        for table in [] if indexes else _MIX_TABLES:
            for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?", (table,)):
                conn.execute(f"DROP INDEX {name}")
        for copy in range(8):                       # each copy received earlier, in order
            for m in _MIX["messages"]:
                key = m["item"]["key"].upper()
                kind, msg = capture._message(m["service"], key, m["item"], m["schwab_ts"])
                msg["ts_recv"] = m["ts_recv"] - 3.0 * (8 - copy)
                writer.insert(f"{kind}.{key}", msg, conn=conn)
        page = conn.execute("PRAGMA page_size").fetchone()[0]
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA user_version = 1")     # one page in the WAL, which the reader's snapshot needs
    reader = sqlite3.connect(db, isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT 1 FROM stream_options_quotes_raw LIMIT 1").fetchall()
    wal = db.with_name(db.name + "-wal")
    before = wal.stat().st_size if wal.exists() else 0

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        handlers = {s: capture._publisher(s, bus, health) for s in {m["service"] for m in _MIX["messages"]}}
        for service, frame in _mix_frames():
            handlers[service](json.loads(frame))
        await _until(lambda: _mix_rows(db) == 9 * sum(_MIX["counts"][t] for t in _MIX_TABLES), limit=60.0)
        stop.set()
        await task
    asyncio.run(go())
    frames = (wal.stat().st_size - before) // (page + 24)    # each WAL frame: a 24-byte header and a page
    reader.close()
    return frames


def test_the_indexes_add_no_more_pages_than_the_rows_they_index(tmp_path):
    """The pages the indexes of the mix's tables add for one copy of production's mix are no more
    than the pages of the rows themselves (an index by symbol puts each of the mix's 3,000-odd
    option symbols on a page of its own, one written per row)."""
    rows = _pages_for_the_mix(tmp_path / "rows" / "stream_capture.db", indexes=False)
    indexed = _pages_for_the_mix(tmp_path / "indexed" / "stream_capture.db", indexes=True)
    assert indexed - rows <= rows, f"the indexes wrote {indexed - rows} pages for {rows} pages of rows"


def test_the_hold_cap_holds_memory_to_its_size(tmp_path):
    """The cap counts each held message's memory once, when it is held. INDUCED CONDITIONS: the
    production mix (_MIX) is published once and written; then another connection holds the
    write lock while the mix arrives three more times, each frame decoded from its JSON as the
    stream decodes it, through the daemon's handler for its service, against a writer whose cap
    is 4 MB of memory (an input, STAND-IN for about 2 GB). tracemalloc runs from before the first
    publish. The hold fills its cap to within 5%, the memory it takes by tracemalloc is within 5%
    of what the writer counted, the rest spills, and every message reaches the database once the
    lock is released."""
    memory = 4_000_000
    frames = _mix_frames()
    n = len(frames)
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, timeout_sec=0.05, retry_sec=0.1, hold_cap_bytes=memory)
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        handlers = {s: capture._publisher(s, bus, health) for s in {s for s, _f in frames}}

        async def publish() -> None:
            for i, (service, frame) in enumerate(frames):
                handlers[service](json.loads(frame))
                if i % 500 == 0:
                    await asyncio.sleep(0)
        # each symbol's current record on the bus exists before the hold, traced, so the records
        # that replace it during the hold count only their difference
        tracemalloc.start()
        await publish()
        await _until(lambda: _mix_rows(db) == n, limit=30.0)
        holder.execute("BEGIN IMMEDIATE")
        base = tracemalloc.get_traced_memory()[0]
        for _ in range(3):
            await publish()

        def all_held() -> bool:
            s = writer.status()
            return (s["queue_depth"] == 0 and s["spill"] is not None
                    and s["spill"]["messages"] + s["waiting"] == 3 * n)
        await _until(all_held, limit=60.0)
        held_memory = tracemalloc.get_traced_memory()[0] - base
        tracemalloc.stop()
        during = writer.status()
        holder.execute("COMMIT")
        await _until(lambda: writer.status()["spill"] is None and _mix_rows(db) == 4 * n, limit=120.0)
        stop.set()
        await task
        return held_memory, during
    try:
        held_memory, during = asyncio.run(go())
    finally:
        holder.close()

    assert during["spill"]["messages"] > 0, "the cap never engaged"
    assert 0.95 * memory <= during["held_bytes"] <= memory, "the hold stopped short of its cap, or passed it"
    assert abs(held_memory - during["held_bytes"]) <= 0.05 * held_memory, \
        f"the hold took {held_memory:,} bytes; the writer counted {during['held_bytes']:,}"
    assert f"{during['held_bytes'] / 1e6:.1f} MB ({during['waiting']} waiting for the database)" in during["line"]
    assert {t: _count(db, t) for t in _MIX_TABLES} == {t: 4 * c for t, c in _MIX["counts"].items() if t in _MIX_TABLES}


class _ArmedDefect(dict):
    """STAND-IN for a defect in the writer that shows only once armed: before, its row builds as
    the captured TSLA quote's; after, its row builder raises RuntimeError."""

    def __init__(self, armed: threading.Event, *args):
        super().__init__(*args)
        self.armed = armed

    def get(self, key, default=None):
        if key == "bid" and self.armed.is_set():
            raise RuntimeError("a defect in the writer")
        return dict.get(self, key, default)


def test_a_writer_that_dies_with_a_spill_file_lists_it_and_counts_its_messages(tmp_path):
    """INDUCED CONDITIONS: the write lock held while an _ArmedDefect message (first, held in
    memory) and the 12 captured option quotes arrive, against a cap that holds it and a few
    quotes, so the rest spill; then the defect is armed and the writer ends on it at its next
    try. The Record reads DEAD; the spill file stays, listed as left on disk with its message
    count and size; not recorded counts only what memory held, not what is in the file."""
    db = tmp_path / "stream_capture.db"
    armed = threading.Event()
    defect = _ArmedDefect(armed, quote_msg(symbol="TSLA", src="schwab_stream", native=_TSLA["native"]))
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01, timeout_sec=0.2, retry_sec=0.1,
                           hold_cap_bytes=16_000)  # the TSLA quote (about 10 KB) and a few option quotes
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        bus.publish("quote.TSLA", defect)
        _publish_options(bus, health, _EVENTS)

        def all_held() -> bool:
            s = writer.status()
            return s["spill"] is not None and s["spill"]["messages"] + s["waiting"] == len(_EVENTS) + 1
        await _until(all_held)
        held = writer.status()
        armed.set()
        await _until(lambda: writer.status()["state"] == "dead")
        dead = writer.status()
        stop.set()
        await task
        return held, dead
    try:
        held, dead = asyncio.run(go())
    finally:
        holder.execute("COMMIT")
        holder.close()

    spilled = held["spill"]
    assert dead["state"] == "dead" and dead["error"] == "RuntimeError: a defect in the writer"
    assert dead["line"].startswith("DEAD · ")
    assert dead["left_on_disk"] == [{"path": spilled["path"], "messages": spilled["messages"],
                                     "bytes": spilled["bytes"], "written_back": 0}]
    assert Path(spilled["path"]).exists() and dead["spill"] is None
    assert dead["unrecorded"] == held["waiting"], "messages still in the spill file counted not recorded"
    assert (f"left on disk: {Path(spilled['path']).name} ({spilled['messages']} messages, "
            f"{spilled['bytes']:,} bytes, 0 written back)") in dead["line"]


def test_a_damaged_spill_record_is_kept_as_sent_and_every_record_after_it_is_written(tmp_path):
    """INDUCED CONDITIONS: as in the spill tests, and, while the lock is held, the spill file's
    last record damaged in place (its last two JSON bytes overwritten with 0xFF; STAND-IN for a
    damaged disk), then one more quote received, which the same spill file takes after it. On
    release memory is written, then every spill record in order: the damaged one kept as sent in
    stream_write_failures with where and why, the quote after it written; the file is deleted and
    the writer goes on recording."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01, timeout_sec=0.2, retry_sec=0.1,
                           hold_cap_bytes=_SMALL_CAP)
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer = writer
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        during = await _held_past_the_cap(writer, bus, health, daemon)
        path = Path(during["spill"]["path"])
        with open(path, "rb") as f:            # where the last record starts
            last, at = 0, 0
            while at < during["spill"]["bytes"]:
                last = at
                f.seek(at)
                at += 4 + int.from_bytes(f.read(4), "big")
        with open(path, "r+b") as f:
            f.seek(during["spill"]["bytes"] - 2)
            f.write(b"\xff\xff")
        _publish_options(bus, health, _EVENTS[:1])           # behind the damaged record
        await _until(lambda: writer.status()["spill"]["messages"] == during["spill"]["messages"] + 1)
        holder.execute("COMMIT")
        await _until(lambda: _count(db, "stream_options_quotes_raw") == len(_EVENTS) and writer.status()["spill"] is None)
        after = _beat(daemon)["writer"]
        stop.set()
        await task
        return during, after, last
    try:
        during, after, last = asyncio.run(go())
    finally:
        holder.close()

    path = Path(during["spill"]["path"])
    with sqlite3.connect(db) as conn:
        stored = [json.loads(r[0]) for r in conn.execute(
            "SELECT native_json FROM stream_options_quotes_raw ORDER BY rowid")]
        kept = conn.execute("SELECT topic, error FROM stream_write_failures").fetchall()
    assert stored == [e["content"] for e in _EVENTS[:-1]] + [_EVENTS[0]["content"]], \
        "not every good record, in order, the one received after the damaged record included"
    assert [t for t, _e in kept] == ["spill"]
    assert kept[0][1].startswith(f"{path.name}: the record at byte {last} does not decode, kept as its bytes")
    assert not path.exists(), "the written-back spill file was kept"
    assert (after["state"], after["spill"], after["failures"]) == ("recording", None, 1)


def test_spill_files_left_beside_the_database_are_written_back_at_start(tmp_path):
    """INDUCED CONDITION: a writer stopped while the database was locked leaves its held messages
    in spill files (memory's file, named for when the block began, then the spill file). A new
    writer on the same database writes them back when it runs, oldest file first: every quote
    once, in arrival order, with the receipt time it was received at, then what arrives after;
    each file is deleted once its rows are committed."""
    db = tmp_path / "stream_capture.db"
    first = CaptureWriter(db, batch_rows=1, batch_sec=0.01, timeout_sec=0.2, retry_sec=0.1,
                          hold_cap_bytes=_SMALL_CAP)
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")
    received: list = []

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer = first
        sub = bus.subscribe("", policy=LOG)
        seen = bus.subscribe("optquote.", policy=LOG)     # the receipt times as published
        task = asyncio.create_task(first.run(sub, stop=stop))
        await _held_past_the_cap(first, bus, health, daemon)
        while not seen.queue.empty():
            received.append((await seen.get())[1]["ts_recv"])
        stop.set()
        await task
    try:
        asyncio.run(go())
    finally:
        holder.execute("COMMIT")
        holder.close()
    left = first.status()["left_on_disk"]
    assert sum(k["messages"] for k in left) == len(_EVENTS) and len(left) == 2
    assert _count(db, "stream_options_quotes_raw") == 0

    async def restart():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        second = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
        task = asyncio.create_task(second.run(bus.subscribe("", policy=LOG), stop=stop))
        await _until(lambda: second.status()["spill"] is None)
        _publish_options(bus, health, _EVENTS[:1])                 # arrives after the restart
        await _until(lambda: _count(db, "stream_options_quotes_raw") == len(_EVENTS) + 1)
        stop.set()
        await task
        return second.status()
    after = asyncio.run(restart())

    with sqlite3.connect(db) as conn:
        stored = [(ts, json.loads(native)) for ts, native in conn.execute(
            "SELECT ts_recv, native_json FROM stream_options_quotes_raw ORDER BY rowid")]
        assert conn.execute("SELECT COUNT(*) FROM stream_spill_progress").fetchone()[0] == 0
    assert [item for _ts, item in stored] == [e["content"] for e in _EVENTS] + [_EVENTS[0]["content"]], \
        "not every left quote once, in arrival order, before what arrived after the restart"
    assert [ts for ts, _item in stored[:len(_EVENTS)]] == received, "a receipt time changed in the write-back"
    assert not any(Path(k["path"]).exists() for k in left), "a spill file outlived its committed write-back"
    assert (after["spill"], after["left_on_disk"], after["lost"]) == (None, [], 0)


def test_the_clean_stop_writes_what_the_daemon_holds_to_spill_files_before_it_ends(tmp_path):
    """The daemon's clean stop (launch.py stop): {"op": "stop"} sent by launch.ask_daemon_to_stop
    to a live_push server on a free port, as the daemon runs it with the daemon's console_frame,
    INDUCED CONDITION: while another connection holds the stream database's write lock and the
    captured option quotes are held in memory and the spill file. The daemon's stop is set, every
    task it ends returns, and every quote is on disk in spill files beside the database."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01, timeout_sec=0.2, retry_sec=0.1,
                           hold_cap_bytes=_SMALL_CAP)
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer, daemon.stop = writer, stop
        tasks = [asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop)),
                 asyncio.create_task(serve_live_push(bus, stop, port=port, on_request=daemon.console_frame))]
        await _held_past_the_cap(writer, bus, health, daemon)
        await asyncio.to_thread(launch.ask_daemon_to_stop, port)
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=30)
        return stop.is_set()
    try:
        stopped = asyncio.run(go())
    finally:
        holder.execute("COMMIT")
        holder.close()
    left = writer.status()["left_on_disk"]
    assert stopped and writer.status()["state"] == "stopped"
    assert sum(k["messages"] for k in left) == len(_EVENTS), "a held quote is not on disk after the clean stop"
    assert all(Path(k["path"]).exists() and Path(k["path"]).parent == db.parent for k in left)
