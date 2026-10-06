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
import os
import sqlite3
import stat
import threading
import time
import tracemalloc
from pathlib import Path

import httpx
from schwab.client import Client

import live_market_plane as lmp
from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.live_ui import LiveUiServer
from calibration.complete_chain_capture import ChainSweep
from stream_spine import LOG, CaptureWriter, HealthRegistry, MessageBus, options_quote_msg, quote_msg
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
    sweep's workers fetch the next chain at once (no pause: a second chain request reaches the
    host), and the daemon's writer keeps the chain."""
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
        def chains() -> int:
            return sum(1 for _t, method, path, _a in schwab.requests
                       if method == "GET" and path == "/marketdata/v1/chains")
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
    received = [ct for msg in published[:published[0]["parts"]] for ct in msg["contracts"]]
    kept_contracts = [ct for side in ("callExpDateMap", "putExpDateMap")
                      for by_strike in kept[side].values() for listed in by_strike.values()
                      for ct in listed]
    assert sorted(c["symbol"] for c in kept_contracts) == sorted(c["symbol"] for c in received)
    assert all(c in received for c in kept_contracts), "kept as the sweep received it"
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
    file is gone after its write-back verified."""
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
    assert not path.exists(), "the spill file outlived its verified write-back"
    assert (after["state"], after["spill"], after["spills_kept"], after["rows_written"]) == (
        "recording", None, [], len(_EVENTS))


def test_a_spill_whose_write_back_does_not_verify_is_kept(tmp_path):
    """INDUCED CONDITIONS: as above, and, in the same transaction that releases the lock, a
    trigger that deletes each option quote row written back from the spill (every row after the
    ones held in memory), standing in for rows lost after their write. The write-back does not
    verify: the spill file stays, and the Record says so."""
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
        holder.execute(f"CREATE TRIGGER lose_written_back AFTER INSERT ON stream_options_quotes_raw "
                       f"WHEN NEW.rowid > {during['waiting']} "
                       f"BEGIN DELETE FROM stream_options_quotes_raw WHERE rowid = NEW.rowid; END")
        holder.execute("COMMIT")
        await _until(lambda: writer.status()["spills_kept"] != [])
        after = _beat(daemon)["writer"]
        stop.set()
        await task
        return during, after
    try:
        during, after = asyncio.run(go())
    finally:
        holder.close()

    path = Path(during["spill"]["path"])
    assert path.exists(), "a spill whose write-back did not verify was deleted"
    (kept,) = after["spills_kept"]
    assert kept["path"] == str(path) and kept["reason"].startswith("stream_options_quotes_raw: 1 topics differ")
    assert kept["written_back"] == kept["messages"] == during["spill"]["messages"]
    assert (f"spill kept: {kept['reason']} ({path.name}, {kept['written_back']} of {kept['messages']} "
            f"written back)") in after["line"]
    assert after["cls"] == "neg" and after["spill"] is None and after["state"] == "recording"
    # how far its write-back got is recorded in the database, for a writer that finds the file
    (found,) = CaptureWriter(db).status()["left_on_disk"]
    assert (found["path"], found["written_back"]) == (str(path), kept["messages"])


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
    assert (f"left on disk, not written back: {Path(spilled['path']).name} ({spilled['messages']} messages, "
            f"{spilled['bytes']:,} bytes, 0 written back)") in dead["line"]


def test_a_spill_with_a_damaged_record_is_kept_and_recording_goes_on(tmp_path):
    """INDUCED CONDITIONS: as in the spill tests, and, while the lock is held, the spill file's
    last record damaged in place (its last two JSON bytes overwritten with 0xFF; STAND-IN for a
    damaged disk). On release memory is written and every good spill record before the damaged
    one; the file is kept with the reason and how far it got, and the writer goes on recording."""
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
        holder.execute("COMMIT")
        await _until(lambda: writer.status()["spills_kept"] != [])
        _publish_options(bus, health, _EVENTS[:1])
        good = len(_EVENTS) - 1
        await _until(lambda: _count(db, "stream_options_quotes_raw") == good + 1)
        after = _beat(daemon)["writer"]
        stop.set()
        await task
        return during, after, last
    try:
        during, after, last = asyncio.run(go())
    finally:
        holder.close()

    path = Path(during["spill"]["path"])
    (kept,) = after["spills_kept"]
    assert path.exists() and kept["path"] == str(path)
    assert kept["reason"].startswith(f"the record at byte {last} does not decode: ")
    assert (kept["messages"], kept["written_back"]) == (during["spill"]["messages"], during["spill"]["messages"] - 1)
    assert after["state"] == "recording" and after["spill"] is None
    with sqlite3.connect(db) as conn:
        stored = [json.loads(r[0]) for r in conn.execute(
            "SELECT native_json FROM stream_options_quotes_raw ORDER BY rowid")]
    assert stored == [e["content"] for e in _EVENTS[:-1]] + [_EVENTS[0]["content"]], \
        "not every good record before the damaged one, in order, then recording"


def test_spill_files_left_beside_the_database_are_shown_at_start(tmp_path):
    """INDUCED CONDITION: a writer stopped while the database was locked leaves its held messages
    in spill files; a new writer on the same database lists them on its Record, with their
    messages and sizes, before it runs."""
    db = tmp_path / "stream_capture.db"
    first = CaptureWriter(db, batch_rows=1, batch_sec=0.01, timeout_sec=0.2, retry_sec=0.1,
                          hold_cap_bytes=_SMALL_CAP)
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer = first
        task = asyncio.create_task(first.run(bus.subscribe("", policy=LOG), stop=stop))
        await _held_past_the_cap(first, bus, health, daemon)
        stop.set()
        await task
    try:
        asyncio.run(go())
    finally:
        holder.execute("COMMIT")
        holder.close()
    left = first.status()["left_on_disk"]
    assert sum(k["messages"] for k in left) == len(_EVENTS) and len(left) == 2

    shown = CaptureWriter(db).status()
    assert [(k["path"], k["messages"], k["bytes"]) for k in shown["left_on_disk"]] == \
        [(k["path"], k["messages"], k["bytes"]) for k in left]
    for k in left:
        assert (f"left on disk, not written back: {Path(k['path']).name} ({k['messages']} messages, "
                f"{k['bytes']:,} bytes, 0 written back)") in shown["line"]
    assert _count(db, "stream_options_quotes_raw") == 0


def _left_by_a_stop(db) -> list:
    """INDUCED CONDITION: a writer stopped while another connection held the database's write
    lock, with the 12 captured option quotes held past _SMALL_CAP: the spill files it left
    (what memory held, then the spill), oldest first."""
    first = CaptureWriter(db, batch_rows=1, batch_sec=0.01, timeout_sec=0.2, retry_sec=0.1,
                          hold_cap_bytes=_SMALL_CAP)
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer = first
        task = asyncio.create_task(first.run(bus.subscribe("", policy=LOG), stop=stop))
        await _held_past_the_cap(first, bus, health, daemon)
        stop.set()
        await task
    try:
        asyncio.run(go())
    finally:
        holder.execute("COMMIT")
        holder.close()
    return [Path(k["path"]) for k in first.status()["left_on_disk"]]


def _next_start(db, live: list, done) -> dict:
    """A new writer on the same database runs while `live` captured option quotes arrive, until
    `done(writer)`; returns its status as the heartbeat carries it."""
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer = writer
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        _publish_options(bus, health, live)
        await _until(lambda: done(writer))
        status = _beat(daemon)["writer"]
        stop.set()
        await task
        return status
    return asyncio.run(go())


def _stored_quotes(db) -> list:
    with sqlite3.connect(db) as conn:
        return [json.loads(r[0]) for r in conn.execute(
            "SELECT native_json FROM stream_options_quotes_raw ORDER BY rowid")]


def _damage_last_record(path: Path) -> bytes:
    """STAND-IN for a damaged disk: the file's last two bytes overwritten with 0xFF; the bytes
    they held are returned."""
    with open(path, "r+b") as f:
        f.seek(-2, os.SEEK_END)
        held = f.read(2)
        f.seek(-2, os.SEEK_END)
        f.write(b"\xff\xff")
    return held


def test_files_left_by_a_stop_are_written_back_at_the_next_start_in_order(tmp_path):
    """The files a stop left (_left_by_a_stop) are written back by the next writer before the
    live quotes that arrive meanwhile (3 captured ones, held until then): every quote once, in
    arrival order; both files verified and deleted; the Record says so."""
    db = tmp_path / "stream_capture.db"
    left = _left_by_a_stop(db)
    assert len(left) == 2 and all(p.exists() for p in left)

    status = _next_start(db, _EVENTS[:3], lambda w: _count(db, "stream_options_quotes_raw") == len(_EVENTS) + 3
                         and not any(p.exists() for p in left))

    assert _stored_quotes(db) == [e["content"] for e in _EVENTS] + [e["content"] for e in _EVENTS[:3]], \
        "not every quote once, the left files' first, in arrival order"
    assert not any(p.exists() for p in left), "a verified left file was not deleted"
    assert (status["left_written_back"], status["left_on_disk"], status["spills_kept"]) == (2, [], [])
    assert "2 left files written back and verified" in status["line"]


def test_a_left_file_partly_written_back_resumes_at_its_progress_row(tmp_path):
    """INDUCED CONDITIONS: the spill's last record damaged (_damage_last_record) while the lock is
    held; on release the writer writes back every good record before it, keeps the file and
    records its progress (n-1 of n written back); the writer stops; the damaged bytes are put
    back. The next writer resumes at that progress row: only the last record is written, so every
    quote is in the database once, in order, and the file is verified and deleted."""
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
        good = _damage_last_record(Path(during["spill"]["path"]))
        holder.execute("COMMIT")
        await _until(lambda: writer.status()["spills_kept"] != [])
        stop.set()
        await task
        return during, good
    try:
        during, good = asyncio.run(go())
    finally:
        holder.close()
    path = Path(during["spill"]["path"])
    (kept,) = writer.status()["spills_kept"]
    assert kept["written_back"] == during["spill"]["messages"] - 1
    assert _stored_quotes(db) == [e["content"] for e in _EVENTS[:-1]]
    with open(path, "r+b") as f:                 # the damage undone
        f.seek(-2, os.SEEK_END)
        f.write(good)

    status = _next_start(db, [], lambda w: not path.exists())

    assert _stored_quotes(db) == [e["content"] for e in _EVENTS], "a resumed file wrote a record twice or not at all"
    assert not path.exists() and (status["left_written_back"], status["spills_kept"]) == (1, [])


def test_a_damaged_left_file_is_kept_and_recording_goes_on(tmp_path):
    """INDUCED CONDITIONS: the files a stop left (_left_by_a_stop), the spill's last record
    damaged on disk (_damage_last_record). The next writer writes back the memory file, then
    every good record of the spill before the damaged one; it keeps that file with the reason,
    and the live quote that arrived meanwhile follows."""
    db = tmp_path / "stream_capture.db"
    memory_file, spill_file = _left_by_a_stop(db)
    _damage_last_record(spill_file)

    status = _next_start(db, _EVENTS[:1], lambda w: not memory_file.exists()
                         and _count(db, "stream_options_quotes_raw") == len(_EVENTS))

    assert _stored_quotes(db) == [e["content"] for e in _EVENTS[:-1]] + [_EVENTS[0]["content"]]
    assert not memory_file.exists() and spill_file.exists()
    (kept,) = status["spills_kept"]
    assert kept["path"] == str(spill_file) and kept["reason"].startswith("the record at byte ")
    assert status["left_written_back"] == 1 and status["state"] == "recording"
