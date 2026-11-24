"""Schwab's chain -> the stored capture -> the console.

A capture is found whole or not at all, and it is stored before the console hears of its chain,
by the Recorder, the database's one writer (CaptureWriter.store_capture): while the database
refuses writes it is held and written once it takes them, the chain meanwhile going to the
console as no capture, and again as the capture once the Recorder commits it
(ChainSweep.publish_held); a dead writer writes none, and one lost or not recorded is refused,
never left held. MRVL's real chain, every expiry.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import stat
import sys
import threading
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import NoReturn

import calibration.complete_chain_capture as cch
import server
from app.market_data.schwab.streaming import capture
from app.options.order_flow import streaming as ofs
from feed import chain_sweep as cs
from feed import schwab_client as sc
from state import capture_store
from stream_spine import (
    CAPTURE_HELD,
    CAPTURE_REFUSED,
    CAPTURE_STORED,
    LOG,
    CaptureWriter,
    HealthRegistry,
    MessageBus,
    StoredFirst,
    quote_msg,
)
from tests.test_data_path_writer_failures_v1 import _Defect, _until
from time_et import ET, ct_label

#: after MRVL's option close (16:00 ET): the day's close capture
_BEGUN = datetime(2026, 9, 30, 16, 1, 57, tzinfo=ET).timestamp()
#: MRVL's option close that day, the window the capture is of
_CLOSE = datetime(2026, 9, 30, 16, 0, tzinfo=ET).timestamp()
#: INDUCED: the sweep's wait for a capture's commit, short, so a test holds the database's write
#: lock past it at once (production's is chain_sweep.CAPTURE_WAIT_SEC)
_WAIT = 0.5
_MRVL = sc.flatten_chain_contracts(
    json.loads(
        (
            Path(__file__).resolve().parent
            / "fixtures"
            / "real_mrvl_full_chain_vs_strike_window.json"
        ).read_text(encoding="utf-8")
    )["full"]
)


def _chain(started: float = _BEGUN) -> cs._Chain:
    """Inside a capture window, each contract with the sweep's mark that no quote came back."""
    by_expiry: dict[str, list[dict]] = {}
    for ct in _MRVL:
        by_expiry.setdefault(ct["expirationDate"][:10], []).append({**ct, "greeksTime": None})
    assert len(by_expiry) > 1
    return cs._Chain("MRVL", started, dict.fromkeys(by_expiry), by_expiry=by_expiry)


def _sweep(tmp_path, publish, writer: CaptureWriter) -> cs.ChainSweep:
    """Return the daemon's sweep of MRVL after its close, on `writer`, the daemon's one database."""
    sqlite3.connect(tmp_path / "ed_console.db").close()  # the daemon's database exists
    return cs.ChainSweep(
        tmp_path / "ed_console.db",
        ["MRVL"],
        publish,
        clock=lambda: _BEGUN,
        failures=writer,
        streamed=lambda _symbol: None,
        capture_wait_sec=_WAIT,
    )


def _no_sign_in() -> NoReturn:
    raise ConnectionError("this test holds no Schwab sign-in: the sweep asks Schwab for nothing")


def _one_pass(sweep: cs.ChainSweep) -> None:
    """Run one pass of the sweep's loop (work), on this thread.

    The pass holds no Schwab sign-in (waits), so it asks Schwab for nothing; it takes the
    Recorder's answers for the held captures first (publish_held).
    """
    stop = threading.Event()

    def client() -> NoReturn:
        stop.set()  # the loop ends after this pass
        _no_sign_in()

    sweep.work(client, stop)


def _until_counted(writer: CaptureWriter, counter: str) -> None:
    """Wait on this thread, up to 10 s, until the Recorder's `counter` has counted one message."""
    pause = threading.Event()
    for _ in range(200):
        if writer.status()[counter]:
            return
        pause.wait(0.05)
    raise AssertionError(f"the Recorder counted nothing as {counter} in 10 s")


def _hold_write_lock(db) -> tuple[threading.Event, threading.Thread]:
    """INDUCED CONDITION: another connection takes the database's write lock and holds it.

    Until the event returned is set, as a backup or a second writer would; with it, the thread
    holding it.
    """
    release, held = threading.Event(), threading.Event()

    def hold() -> None:
        other = sqlite3.connect(str(db))
        try:
            other.execute("BEGIN EXCLUSIVE")
            held.set()
            release.wait(10)
            other.commit()
        finally:
            other.close()

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert held.wait(10)
    return release, holder


def _stored(db) -> list:
    return [c for capture in cch.last_capture_per_day(db, "MRVL", 1) for c in capture.contracts]


def _refuse(db, expiry: str) -> None:
    """Induced test condition: a trigger refuses this expiry, as a locked or full database would."""
    conn = sqlite3.connect(db)
    cch.ensure_schema(conn)
    conn.execute(
        "CREATE TRIGGER refuse BEFORE INSERT ON complete_chain_captures "
        f"WHEN NEW.expiry = '{expiry}' BEGIN SELECT RAISE(ABORT, 'refused'); END"
    )
    conn.commit()
    conn.close()


def test_a_capture_the_database_refuses_partway_is_kept_and_leaves_nothing_stored(tmp_path):
    """The expiries before the refused one are not left standing as the day's capture.

    And the chain still reaches the console, and the Recorder keeps the capture as sent.
    """
    db = tmp_path / "ed_console.db"
    published: list = []
    sweep = _sweep(tmp_path, lambda topic, _msg: published.append(topic), CaptureWriter(db))
    chain = _chain()
    _refuse(db, list(chain.by_expiry)[-1])
    sweep.deliver(chain)
    assert published
    assert cch.last_capture_per_day(db, "MRVL", 1) == []
    with closing(sqlite3.connect(db)) as read, read:
        kept = read.execute("SELECT topic, msg_json FROM stream_write_failures").fetchall()
    assert [topic for topic, _msg in kept] == ["capture.MRVL"]
    assert json.loads(kept[0][1])["ts_utc"] == _BEGUN


def test_the_console_hears_of_a_chain_after_its_capture_is_stored(tmp_path):
    """A read on the chain's arrival finds the capture it belongs to, whole.

    Committed in its wait, the chain is published once, as the capture: the sweep's next pass
    publishes nothing more, so the console keeps it once.
    """
    db = tmp_path / "ed_console.db"
    stored_at_each_message: list = []
    published: list = []

    def publish(topic, msg) -> None:
        stored_at_each_message.append(len(_stored(db)))
        published.append((topic, msg))

    sweep = _sweep(tmp_path, publish, CaptureWriter(db))
    chain = _chain()
    sweep.deliver(chain)
    assert set(stored_at_each_message) == {len(chain.contracts())}
    _one_pass(sweep)
    parts = [m for topic, m in published if topic == "chain.MRVL"]
    assert [(m["part"], m["capture"]) for m in parts] == [
        (i, True) for i in range(parts[0]["parts"])
    ], "every part once, as the capture"


def _capture(started: float = _BEGUN) -> dict:
    """MRVL's chain as the sweep hands it to the Recorder: every expiry, at no spot."""
    return cch.capture_message(
        "MRVL",
        started,
        (None, None),
        [
            {"expiry": e, "spot": None, "contracts": cts, "chains_answer": None}
            for e, cts in _chain().by_expiry.items()
        ],
    )


def _symbols(db) -> list[str]:
    return sorted(c.symbol for c in _stored(db))


async def _running(writer: CaptureWriter, body) -> object:
    """Run `body(writer)` on a thread of its own while the writer runs; stop it after."""
    stop = asyncio.Event()
    task = asyncio.create_task(writer.run(MessageBus().subscribe("", policy=LOG), stop=stop))
    await asyncio.sleep(0)  # the writer starts, as the daemon starts it before its sweep
    assert writer.status()["state"] == "recording"
    try:
        return await asyncio.to_thread(body, writer)
    finally:
        stop.set()
        await task


def test_the_running_writer_commits_a_capture_whole_before_it_answers(tmp_path):
    db = tmp_path / "ed.db"
    writer = CaptureWriter(db)

    def store(w: CaptureWriter) -> tuple[str, list[str]]:
        outcome = w.store_capture(_capture()).outcome(10.0)
        return outcome, _symbols(db)  # read the moment it answers, as the console would

    outcome, stored = asyncio.run(_running(writer, store))
    assert outcome == CAPTURE_STORED
    assert stored == sorted(c["symbol"] for c in _MRVL), "every expiry, committed together"


def test_a_capture_is_stored_with_the_recorders_batch_and_never_before_it(tmp_path):
    """While the Recorder says the capture is held, the database holds none of it.

    INDUCED CONDITION: the writer's batch is 60 s (an input; production's is 0.25 s), so MRVL's
    capture, the batch's first write, waits in the open batch past the sweep's wait. Read from
    another connection then, the database holds none of its rows; the stop commits the batch,
    and the capture is stored once.
    """
    db = tmp_path / "ed.db"
    writer = CaptureWriter(db, batch_sec=60.0)

    def store(w: CaptureWriter) -> tuple[StoredFirst, str, list[str]]:
        told = w.store_capture(_capture())
        return told, told.outcome(0.5), _symbols(db)

    told, outcome, during = asyncio.run(_running(writer, store))
    assert (outcome, during) == (CAPTURE_HELD, [])
    assert told.outcome() == CAPTURE_STORED
    assert _symbols(db) == sorted(c["symbol"] for c in _MRVL)
    assert writer.status()["rows_written"] == 1, "the capture, written once"


def test_a_capture_the_database_does_not_take_in_time_is_held_and_written_after(tmp_path):
    """INDUCED CONDITION: another connection holds the database's write lock.

    The sweep's wait ends with the capture held (the chain goes to the console as no capture);
    once the lock is released the writer writes it, whole, once.
    """
    db = tmp_path / "ed.db"
    writer = CaptureWriter(db, timeout_sec=0.05, retry_sec=0.05)
    release, holder = _hold_write_lock(db)

    def store(w: CaptureWriter) -> str:
        outcome = w.store_capture(_capture()).outcome(0.5)
        release.set()
        return outcome

    outcome = asyncio.run(_running(writer, store))  # the stop writes what is held, then returns
    holder.join(10)
    assert outcome == CAPTURE_HELD
    assert _symbols(db) == sorted(c["symbol"] for c in _MRVL)
    assert writer.status()["rows_written"] == 1, "the capture, written once"


def test_a_close_capture_held_past_its_wait_reaches_the_console_once_the_recorder_commits_it(
    tmp_path, caplog
):
    """The day's close values reach the console's captures without a restart.

    INDUCED CONDITION: another connection holds the database's write lock past the sweep's wait.
    MRVL's chain after its close is held by the Recorder: it goes to the console as no capture.
    Once the lock is released the Recorder commits it, and the sweep's next pass publishes the
    same chain again as the day's capture, on the daemon's bus as the daemon wires the sweep
    (capture.run_chains: loop.call_soon_threadsafe), through the console's reader
    (order_flow.streaming, server.FEED_CALLBACKS) to server._on_chain, which keeps it
    (state.capture_store). After the close no later chain is asked (ChainSweep.chain_due), so
    without that pass the console's newest capture stayed the day before until a restart.
    """
    db = tmp_path / "ed_console.db"
    writer = CaptureWriter(db, timeout_sec=0.05, retry_sec=0.05)
    assert capture_store.captures(db, "MRVL") == [], "the console's captures, read at its start"
    bus = MessageBus()
    published: list = []

    async def go() -> list:
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        record = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        ofs.bind_daemon(capture.Daemon(bus, HealthRegistry(), []))  # as capture.run binds it
        assert ofs.start_order_flow_stream(**server.FEED_CALLBACKS)

        def publish(topic, msg) -> None:
            published.append((topic, msg))
            loop.call_soon_threadsafe(bus.publish, topic, msg)

        def sweep_thread() -> None:
            sweep = _sweep(tmp_path, publish, writer)
            release, holder = _hold_write_lock(db)
            sweep.deliver(_chain())  # its capture held past the wait
            release.set()
            holder.join(10)
            _until_counted(writer, "rows_written")  # the Recorder commits it
            _one_pass(sweep)

        try:
            await asyncio.sleep(0)  # the writer and the console's reader start
            await asyncio.to_thread(sweep_thread)
            await _until(lambda: capture_store.captures(db, "MRVL") != [])
            return capture_store.captures(db, "MRVL")
        finally:
            ofs.stop_order_flow_stream()
            ofs.bind_daemon(None)
            stop.set()
            await record

    try:
        kept = asyncio.run(go())
    finally:
        server.chain_pricing.submit(lambda: None).result(timeout=120)
        server.stop_terrain_loop()  # drops what waits; MRVL's levels are this test's
    assert [c.ts_utc for c in kept] == [_BEGUN], "the day's close capture, kept by the console"
    assert sorted(c.symbol for c in kept[0].contracts) == sorted(c["symbol"] for c in _MRVL)
    chains = [m for topic, m in published if topic == "chain.MRVL"]
    first, again = chains[: len(chains) // 2], chains[len(chains) // 2 :]
    assert [m["capture"] for m in first] == [False] * first[0]["parts"], "held: no capture"
    assert again == [{**m, "capture": True} for m in first], "the same chain, once, as the capture"
    assert writer.status()["rows_written"] == 1, "the capture, written once"
    warned = [r.getMessage() for r in caplog.records if r.name == "chain_history"]
    assert [m for m in warned if "close capture of MRVL" in m] == [
        f"close capture of MRVL for the close at {ct_label(_CLOSE)} not committed by the "
        f"Recorder in {_WAIT:g} s: held until it is, its chain going to the console as no "
        "capture meanwhile",
        f"close capture of MRVL for the close at {ct_label(_CLOSE)} committed by the Recorder "
        "0 s after its chain began: published to the console as the day's capture",
    ]


def test_a_close_capture_refused_after_its_wait_gives_its_window_to_the_next_chain(tmp_path):
    """INDUCED CONDITIONS: the write lock held past the wait, and a trigger refusing one expiry.

    MRVL's close capture is held past its wait, then refused once the lock is released: none of
    its rows written, kept as sent. The sweep's next pass gives its window back, as a capture
    refused in its wait does, so the window's next chain is stored as the day's capture and
    reaches the console as one.
    """
    db = tmp_path / "ed_console.db"
    writer = CaptureWriter(db, timeout_sec=0.05, retry_sec=0.05)
    _refuse(db, list(_chain().by_expiry)[-1])
    published: list = []

    def sweep_thread(w: CaptureWriter) -> None:
        sweep = _sweep(tmp_path, lambda topic, msg: published.append((topic, msg)), w)
        release, holder = _hold_write_lock(db)
        sweep.deliver(_chain())  # its capture held past the wait
        release.set()
        holder.join(10)
        _until_counted(w, "failures")  # the Recorder refuses it, kept as sent
        _one_pass(sweep)
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("DROP TRIGGER refuse")  # the database takes the capture again
        sweep.deliver(_chain(_BEGUN + 60))  # the window's next chain
        _until_counted(w, "rows_written")
        _one_pass(sweep)  # committed in its wait or after: it reaches the console once

    asyncio.run(_running(writer, sweep_thread))
    began = [
        (m["ts_recv"], m["capture"]) for t, m in published if t == "chain.MRVL" and not m["part"]
    ]
    assert [capture for ts, capture in began if ts == _BEGUN] == [False], "refused: no capture"
    after = [capture for ts, capture in began if ts == _BEGUN + 60]
    assert after[-1] is True and after.count(True) == 1, "the next chain, once as the capture"
    assert {c.ts_utc for c in cch.last_capture_per_day(db, "MRVL", 1)} == {_BEGUN + 60}
    with closing(sqlite3.connect(db)) as read, read:
        kept = read.execute("SELECT topic, msg_json FROM stream_write_failures").fetchall()
    assert [(topic, json.loads(msg)["ts_utc"]) for topic, msg in kept] == [("capture.MRVL", _BEGUN)]


def test_a_dead_writer_refuses_the_capture_and_counts_it_not_recorded(tmp_path):
    """INDUCED CONDITION: a _Defect message ends the writer thread before the capture comes."""
    db = tmp_path / "ed.db"
    writer = CaptureWriter(db)

    async def go() -> tuple[str, int]:
        bus, stop = MessageBus(), asyncio.Event()
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        bus.publish("quote.TSLA", _Defect(quote_msg(symbol="TSLA", src="t", ts_recv=1.0)))
        while writer.status()["state"] != "dead":
            await asyncio.sleep(0.01)
        before = writer.status()["unrecorded"]
        outcome = writer.store_capture(_capture()).outcome()  # told at once: nothing to wait for
        stop.set()
        await task
        return outcome, writer.status()["unrecorded"] - before

    outcome, unrecorded = asyncio.run(go())
    assert (outcome, unrecorded) == (CAPTURE_REFUSED, 1)
    assert _symbols(db) == []


def test_a_capture_held_when_the_writer_dies_is_refused_and_counted_not_recorded(tmp_path):
    """The sweep waiting on it hears it refused; it is never left held.

    INDUCED CONDITIONS: another connection holds the database's write lock, so the Recorder holds
    MRVL's capture and then a _Defect message; once the lock is released the writer writes the
    capture's rows and the _Defect ends its thread before the commit, so neither is recorded.
    """
    db = tmp_path / "ed.db"
    writer = CaptureWriter(db, timeout_sec=0.05, retry_sec=0.05)
    release, holder = _hold_write_lock(db)

    async def go() -> tuple[str, int]:
        bus, stop = MessageBus(), asyncio.Event()
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        await _until(lambda: writer.status()["state"] == "recording")
        stored = writer.store_capture(_capture())
        await _until(lambda: writer.status()["waiting"] == 1)
        bus.publish("quote.TSLA", _Defect(quote_msg(symbol="TSLA", src="t", ts_recv=1.0)))
        await _until(lambda: writer.status()["waiting"] == 2)
        release.set()
        await _until(lambda: writer.status()["state"] == "dead")
        stop.set()
        await task
        return stored.outcome(), writer.status()["unrecorded"]

    try:
        outcome, unrecorded = asyncio.run(go())
    finally:
        release.set()
        holder.join(10)
    assert (outcome, unrecorded) == (CAPTURE_REFUSED, 2)
    assert _symbols(db) == []


def _spill_refused(db: Path, at: float):
    """INDUCED CONDITION: the disk refuses the spill file the writer opens at `at`, its clock.

    On Windows a folder holds that file's name (the disk answers PermissionError); elsewhere the
    database's folder is read-only. Returns the release.
    """
    if sys.platform == "win32":
        taken = db.with_name(f"{db.stem}.{int(at * 1000)}.1.spill")
        taken.mkdir()
        return taken.rmdir
    os.chmod(db.parent, stat.S_IREAD | stat.S_IEXEC)
    return lambda: os.chmod(db.parent, stat.S_IRWXU)


def test_a_capture_the_disk_refuses_to_hold_is_refused_and_counted_lost(tmp_path):
    """The sweep waiting on it hears it refused; it is never left held.

    INDUCED CONDITIONS: another connection holds the database's write lock and a 1-byte memory
    cap (an input, STAND-IN for about 2 GB), so the Recorder holds MRVL's capture in a spill
    file, which the disk refuses (_spill_refused): the capture is lost, neither the database nor
    a file holding it.
    """
    db = tmp_path / "ed.db"
    writer = CaptureWriter(
        db, timeout_sec=0.05, retry_sec=0.05, hold_cap_bytes=1, clock=lambda: _BEGUN
    )
    release, holder = _hold_write_lock(db)

    def store(w: CaptureWriter) -> str:
        allow = _spill_refused(db, _BEGUN)
        try:
            return w.store_capture(_capture()).outcome(10.0)
        finally:
            allow()

    try:
        outcome = asyncio.run(_running(writer, store))
    finally:
        release.set()
        holder.join(10)
    s = writer.status()
    assert (outcome, s["lost"], s["rows_written"]) == (CAPTURE_REFUSED, 1, 0)
    assert _symbols(db) == []


def test_a_capture_handed_to_the_writer_after_its_stop_is_refused_and_counted_not_recorded(
    tmp_path,
):
    """The sweep waiting on it hears it refused; it is never left held.

    INDUCED CONDITIONS: another connection holds the database's write lock and the writer's retry
    is 2 s (an input), so the Recorder holds MRVL's capture and waits to try again; the stop is
    asked then, and the window's next capture comes after the stop is queued. The writer ends
    without it: the held capture is left on disk for the next start, still held, and the next
    is not recorded.
    """
    db = tmp_path / "ed.db"
    writer = CaptureWriter(db, timeout_sec=0.05, retry_sec=2.0)
    release, holder = _hold_write_lock(db)

    async def go() -> tuple[str, str, int]:
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(MessageBus().subscribe("", policy=LOG), stop=stop))
        await _until(lambda: writer.status()["state"] == "recording")
        first = writer.store_capture(_capture())
        await _until(lambda: writer.status()["waiting"] == 1)  # held; its retry waits 2 s
        stop.set()
        await _until(lambda: writer.status()["queue_depth"] == 1)  # the stop, queued
        after = writer.store_capture(_capture(_BEGUN + 60))
        await task
        return first.outcome(), after.outcome(), writer.status()["unrecorded"]

    try:
        held, after, unrecorded = asyncio.run(go())
    finally:
        release.set()
        holder.join(10)
    assert (held, after, unrecorded) == (CAPTURE_HELD, CAPTURE_REFUSED, 1)
    assert [k["messages"] for k in writer.status()["left_on_disk"]] == [1]
