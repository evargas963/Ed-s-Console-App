"""Schwab's chain -> the stored capture -> the console.

A capture is found whole or not at all, and it is stored before the console hears of its chain,
by the Recorder, the database's one writer (CaptureWriter.store_capture): while the database
refuses writes it is held and written once it takes them, the chain meanwhile going to the
console as no capture; a dead writer writes none. MRVL's real chain, every expiry.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime
from pathlib import Path

import calibration.complete_chain_capture as cch
from feed import chain_sweep as cs
from feed import schwab_client as sc
from stream_spine import (
    CAPTURE_HELD,
    CAPTURE_REFUSED,
    CAPTURE_STORED,
    LOG,
    CaptureWriter,
    MessageBus,
    quote_msg,
)
from time_et import ET

#: after MRVL's option close (16:00 ET): the day's close capture
_BEGUN = datetime(2026, 9, 30, 16, 1, 57, tzinfo=ET).timestamp()
_MRVL = sc.flatten_chain_contracts(
    json.loads(
        (
            Path(__file__).resolve().parent
            / "fixtures"
            / "real_mrvl_full_chain_vs_strike_window.json"
        ).read_text(encoding="utf-8")
    )["full"]
)


def _chain() -> cs._Chain:
    """Inside a capture window, each contract with the sweep's mark that no quote came back."""
    by_expiry: dict[str, list[dict]] = {}
    for ct in _MRVL:
        by_expiry.setdefault(ct["expirationDate"][:10], []).append({**ct, "greeksTime": None})
    assert len(by_expiry) > 1
    return cs._Chain("MRVL", _BEGUN, dict.fromkeys(by_expiry), by_expiry=by_expiry)


def _sweep(tmp_path, publish) -> cs.ChainSweep:
    sqlite3.connect(tmp_path / "ed_console.db").close()  # the daemon's database exists
    return cs.ChainSweep(
        tmp_path / "ed_console.db",
        ["MRVL"],
        publish,
        clock=lambda: _BEGUN,
        failures=CaptureWriter(tmp_path / "ed_console.db"),  # the daemon's one database
        streamed=lambda _symbol: None,
    )


def _stored(db) -> list:
    return [c for capture in cch.last_capture_per_day(db, "MRVL", 1) for c in capture["contracts"]]


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
    sweep = _sweep(tmp_path, lambda topic, _msg: published.append(topic))
    chain = _chain()
    _refuse(db, list(chain.by_expiry)[-1])
    sweep.deliver(chain)
    assert published
    assert cch.last_capture_per_day(db, "MRVL", 1) == []
    assert cch.newest_capture_ts(db, "MRVL") is None
    with closing(sqlite3.connect(db)) as read, read:
        kept = read.execute("SELECT topic, msg_json FROM stream_write_failures").fetchall()
    assert [topic for topic, _msg in kept] == ["capture.MRVL"]
    assert json.loads(kept[0][1])["ts_utc"] == _BEGUN


def test_the_console_hears_of_a_chain_after_its_capture_is_stored(tmp_path):
    """A read on the chain's arrival finds the capture it belongs to, whole."""
    db = tmp_path / "ed_console.db"
    stored_at_each_message: list = []
    sweep = _sweep(tmp_path, lambda _topic, _msg: stored_at_each_message.append(len(_stored(db))))
    chain = _chain()
    sweep.deliver(chain)
    assert set(stored_at_each_message) == {len(chain.contracts())}


def _capture() -> dict:
    """MRVL's chain as the sweep hands it to the Recorder: every expiry, at no spot."""
    return cch.capture_message(
        "MRVL",
        _BEGUN,
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
        outcome = w.store_capture(_capture(), 10.0)
        return outcome, _symbols(db)  # read the moment it answers, as the console would

    outcome, stored = asyncio.run(_running(writer, store))
    assert outcome == CAPTURE_STORED
    assert stored == sorted(c["symbol"] for c in _MRVL), "every expiry, committed together"


def test_a_capture_the_database_does_not_take_in_time_is_held_and_written_after(tmp_path):
    """INDUCED CONDITION: another connection holds the database's write lock.

    The sweep's wait ends with the capture held (the chain goes to the console as no capture);
    once the lock is released the writer writes it, whole, once.
    """
    db = tmp_path / "ed.db"
    writer = CaptureWriter(db, timeout_sec=0.05, retry_sec=0.05)
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
    held.wait(10)

    def store(w: CaptureWriter) -> str:
        outcome = w.store_capture(_capture(), 0.5)
        release.set()
        return outcome

    outcome = asyncio.run(_running(writer, store))  # the stop writes what is held, then returns
    holder.join(10)
    assert outcome == CAPTURE_HELD
    assert _symbols(db) == sorted(c["symbol"] for c in _MRVL)
    assert writer.status()["rows_written"] == 1, "the capture, written once"


class _Defect(dict):
    """STAND-IN for a defect in the writer: a row builder that raises what no row raises."""

    def __getitem__(self, key):
        if key == "native":
            raise RuntimeError("a defect in the writer")
        return dict.__getitem__(self, key)


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
        outcome = await asyncio.to_thread(writer.store_capture, _capture(), 1.0)
        stop.set()
        await task
        return outcome, writer.status()["unrecorded"] - before

    outcome, unrecorded = asyncio.run(go())
    assert (outcome, unrecorded) == (CAPTURE_REFUSED, 1)
    assert _symbols(db) == []
