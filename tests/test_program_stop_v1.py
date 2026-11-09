"""The program's clean stop by name, through the real code (program_lock.StopRequest,
ask_to_stop; capture.stop_on_request): on Windows a named event in this user's session, elsewhere
SIGTERM to the process holding the lock. The whole path, launch.py stop against the real program,
is tests/test_data_path_startup_v1.py; the stop with held writes,
tests/test_data_path_writer_failures_v1.py.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

import time_et
from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.program_lock import (
    StopRequest,
    acquire_owner_lock,
    ask_to_stop,
    release_owner_lock,
    stop_event_name,
)


def test_each_runtime_has_its_own_stop_and_a_stop_reaches_only_its_own(tmp_path):
    """Two runtimes, as production's and a test's: their stop events are named apart, in the
    session namespace; a stop asked in the runtime where no program runs is an error, and the
    other runtime's program is not asked; asked in its own, it is.
    """
    ours, theirs = (tmp_path / name / "stream_capture.db" for name in ("ours", "theirs"))
    ours.parent.mkdir()
    assert stop_event_name(ours) != stop_event_name(theirs)
    assert stop_event_name(ours).startswith("Local\\")
    request = StopRequest(ours)
    fd, lock = acquire_owner_lock(ours)
    try:
        with pytest.raises(OSError):
            ask_to_stop(theirs)
        asked_elsewhere = request.wait(0.2)
        ask_to_stop(ours)
        asked_here = request.wait(5)
    finally:
        release_owner_lock(fd, lock)
        request.close()
    assert not asked_elsewhere, "a stop in another runtime reached this program"
    assert asked_here


def test_a_stop_with_no_program_running_is_an_error_to_report(tmp_path):
    """No program runs in the runtime (no lock, no stop event): the stop cannot ask, and says why
    with an OSError, which launch.py stop reports ("not asked to stop") instead of crashing."""
    with pytest.raises(OSError):
        ask_to_stop(tmp_path / "stream_capture.db")


def test_a_stop_asked_twice_stops_the_program_once(tmp_path, caplog):
    """launch.py stop run twice: the request stays set, and the program's one waiter sets the
    program's stop once and ends."""
    db = tmp_path / "stream_capture.db"
    request = StopRequest(db)
    fd, lock = acquire_owner_lock(db)

    async def go():
        stop = asyncio.Event()
        waiter = asyncio.create_task(capture.stop_on_request(stop, request))
        await asyncio.to_thread(ask_to_stop, db)
        await asyncio.to_thread(ask_to_stop, db)
        await asyncio.wait_for(waiter, timeout=10)
        return stop.is_set()

    try:
        with caplog.at_level(logging.INFO, logger=capture.log.name):
            stopped = asyncio.run(go())
    finally:
        release_owner_lock(fd, lock)
        request.close()
    said = [r.getMessage() for r in caplog.records if "stop requested" in r.getMessage()]
    assert stopped
    assert said == ["capture daemon: stop requested (launch.py stop)"], said


def test_the_programs_own_stop_ends_the_waiter_at_once(tmp_path):
    """The program stops for another reason (Ctrl+C, a part that ended) while the waiter waits:
    the waiter ends within its wait (capture.STOP_WAIT_SEC), so the program's shutdown never
    waits on it, and nothing was asked."""
    request = StopRequest(tmp_path / "stream_capture.db")

    async def go():
        stop = asyncio.Event()
        waiter = asyncio.create_task(capture.stop_on_request(stop, request))
        await asyncio.sleep(0.1)  # the waiter is waiting
        stop.set()
        started = time_et.elapsed()
        await asyncio.wait_for(waiter, timeout=10)
        return time_et.elapsed() - started

    try:
        took = asyncio.run(go())
        asked = request.wait(0)
    finally:
        request.close()
    assert took < capture.STOP_WAIT_SEC + 1.0, f"the waiter held the stop {took:.2f} s"
    assert not asked
