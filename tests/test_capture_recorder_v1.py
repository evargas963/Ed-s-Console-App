"""The chain history's captures are written by the Recorder, the database's one writer.

MRVL's real chain (every expiry) handed to the running writer (stream_spine.CaptureWriter
.store_capture) as the chain sweep hands it: committed whole before the sweep tells the console
(store first); while the database refuses writes, held and written once it takes them, the chain
meanwhile going to the console as no capture; never written by a dead writer.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import calibration.complete_chain_capture as cch
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

_BEGUN = datetime(2026, 9, 30, 15, 31, 57, tzinfo=ET).timestamp()
_MRVL = sc.flatten_chain_contracts(
    json.loads(
        (
            Path(__file__).resolve().parent
            / "fixtures"
            / "real_mrvl_full_chain_vs_strike_window.json"
        ).read_text(encoding="utf-8")
    )["full"]
)


def _capture() -> dict:
    """MRVL's chain as the sweep hands it to the Recorder: every expiry, at no spot."""
    by_expiry: dict[str, list[dict]] = {}
    for ct in _MRVL:
        by_expiry.setdefault(ct["expirationDate"][:10], []).append(ct)
    assert len(by_expiry) > 1
    return cch.capture_message(
        "MRVL",
        _BEGUN,
        (None, None),
        [
            {"expiry": e, "spot": None, "contracts": cts, "chains_answer": None}
            for e, cts in by_expiry.items()
        ],
    )


def _stored(db) -> list[str]:
    return sorted(c.symbol for d in cch.last_capture_per_day(db, "MRVL", 1) for c in d["contracts"])


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
        return outcome, _stored(db)  # read the moment it answers, as the console would

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
    assert _stored(db) == sorted(c["symbol"] for c in _MRVL)
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
    assert _stored(db) == []
