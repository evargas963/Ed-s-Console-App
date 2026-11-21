"""The program runs no full garbage collection during the session, and one after each close.

docs/DATA_FLOW.md §3.1: as it starts, the program sets Python's collector so its oldest generation
is not collected by itself (capture.set_collector), and after each close of the last option market
it was running for, it runs one full collection and logs how long it took and what it freed
(capture.collect_after_close). Python's own documents say why (docs/SOURCES.md: python-gc-module,
cpython-gc-design): a full collection's cost "is proportional to the total number of long-lived
objects", and it stops every thread while it runs.

Real data: Schwab's /markets answers as tests/conftest.py holds them: 2026-10-07, 10-08 and 10-09
are market days whose last option market (IND) closes 16:15 ET, and 2026-10-10 is a Saturday with
none. INDUCED: the daemon's clock, which the tests move; the reference cycles, made here so the
count the collection frees is known; a program that has not yet been sent the day's /markets
answer.
"""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import os
import re
import socket
import subprocess
import sys
import weakref
from pathlib import Path

import pytest

import time_et
from app.market_data.schwab.streaming import capture, live_ui
from tests.conftest import MARKETS_ANSWERS
from tests.shared_helpers import et_ts

REPO = Path(__file__).resolve().parent.parent
#: the daemon's line for one collection: seconds, objects freed, objects it could not free
_LINE = re.compile(
    r"garbage collection after the close: (\d+\.\d\d) s, (\d+) objects freed, "
    r"(\d+) it could not free"
)
#: reference cycles a test makes
_RINGS = 500


class _Ring:
    """An object that refers to itself: unreachable once dropped, and freed only by a collection."""

    def __init__(self) -> None:
        self.next = self


@pytest.fixture
def collector():
    """Set the collector as the program's start sets it; give it back as it was after the test.

    Yields Python's own thresholds (the test process's, which no test leaves changed). The
    thresholds are the process's, so they are restored whatever the test did.
    """
    own = gc.get_threshold()
    capture.set_collector()
    try:
        yield own
    finally:
        gc.set_threshold(*own)


def _allocate() -> None:
    """Make and drop enough container objects for many young and middle collections."""
    kept: list[list[int]] = []
    for i in range(300_000):
        kept.append([i])
        if len(kept) > 50_000:
            del kept[:25_000]


def _in_the_oldest_generation() -> weakref.ref[_Ring]:
    """Leave _RINGS unreachable cycles in the oldest generation; return a weak hold on one.

    INDUCED: held through one full collection they move to the oldest generation; dropped, only a
    full collection frees them.
    """
    rings = [_Ring() for _ in range(_RINGS)]
    one = weakref.ref(rings[0])
    gc.collect()
    del rings
    return one


def _collections(caplog) -> list[tuple[float, int, int]]:
    """Return each collection the daemon logged: (seconds, objects freed, objects not freed)."""
    found = [_LINE.fullmatch(r.getMessage()) for r in caplog.records if r.name == capture.log.name]
    return [(float(m[1]), int(m[2]), int(m[3])) for m in found if m]


async def _looks(n: int = 20) -> None:
    """Let the daemon's loop look at the clock `n` times (it looks every 0.01 s here)."""
    await asyncio.sleep(0.01 * n)


async def _until(ok, seconds: float = 30.0) -> None:
    deadline = asyncio.get_running_loop().time() + seconds
    while not ok():
        assert asyncio.get_running_loop().time() < deadline, "never happened"
        await asyncio.sleep(0.01)


def test_the_collector_as_the_program_sets_it_runs_no_full_collection_by_itself(collector):
    """The oldest generation is left alone; the young and middle keep Python's own thresholds.

    With the collector as the program's start sets it, making and dropping 300,000 containers
    runs many young and middle collections and not one of the oldest generation, and cycles
    that live there stay until a full collection is asked for.
    """
    young, middle, _oldest = collector
    assert gc.get_threshold() == (young, middle, capture.NO_FULL_COLLECTION)
    one = _in_the_oldest_generation()
    before = gc.get_stats()
    _allocate()
    after = gc.get_stats()
    assert after[0]["collections"] - before[0]["collections"] > 10
    assert after[1]["collections"] - before[1]["collections"] > 1
    assert after[2]["collections"] == before[2]["collections"]
    assert one() is not None  # no full collection ran: the cycle is still held
    assert gc.collect() >= _RINGS and one() is None  # asked for, it frees them


def test_the_program_sets_its_collector_as_it_starts(tmp_path):
    """The real program, run as its window runs it, says in its log how its collector is set.

    Its pages' port is held by another socket, so it ends as it opens its sockets (after the
    start of its log and the setting). The line carries the thresholds read back from the
    collector: Python's own for the young and middle generations, and the oldest never reached.
    """
    young, middle, _oldest = gc.get_threshold()
    with socket.create_server((live_ui.CONSOLE_HOST, 0)) as held:
        env = {
            **os.environ,
            "ED_RUNTIME_ROOT": str(tmp_path),
            "ED_CONSOLE_PORT": str(held.getsockname()[1]),
            "SCHWAB_TOKEN_PATH": str(tmp_path / "missing_token.json"),
        }
        subprocess.run(
            [sys.executable, "-m", "app.market_data.schwab.streaming.capture_main"],
            cwd=REPO,
            env=env,
            capture_output=True,
            timeout=120,
            check=False,
        )
    (path,) = (tmp_path / "logs").glob("stream_capture.*.log")
    log = path.read_text(encoding="utf-8")
    assert (
        f"garbage collection: thresholds {young}, {middle}, {capture.NO_FULL_COLLECTION}: "
        "no full collection in the session, one after each close"
    ) in log, log


@pytest.mark.usefixtures("collector")
def test_one_full_collection_runs_after_each_close_and_none_in_the_session(caplog):
    """Wednesday 2026-10-07 15:00 ET to Saturday 10-10: one collection per close, logged.

    In the session nothing is collected from the oldest generation, however often the loop
    looks. Once the last option market has closed (16:15 ET) one full collection runs: it frees
    the cycles and its line gives the count. It does not run again for that close, nor in
    Thursday's session; Thursday's close has its own; a Saturday, with no session, has none.
    """
    at = [et_ts("2026-10-07 15:00")]
    seen: dict[str, object] = {}

    async def go() -> None:
        stop = asyncio.Event()
        loop = asyncio.create_task(capture.collect_after_close(lambda: at[0], stop, every=0.01))
        one = _in_the_oldest_generation()
        oldest = gc.get_stats()[2]["collections"]
        _allocate()
        await _looks()
        seen["in session"] = (
            gc.get_stats()[2]["collections"] - oldest,
            one() is not None,
            len(_collections(caplog)),
        )
        at[0] = et_ts("2026-10-07 16:16")
        await _until(lambda: _collections(caplog))
        await _looks()
        seen["after the close"] = (one() is None, len(_collections(caplog)))
        at[0] = et_ts("2026-10-08 10:00")
        two = _in_the_oldest_generation()
        await _looks()
        seen["next session"] = (two() is not None, len(_collections(caplog)))
        at[0] = et_ts("2026-10-08 16:16")
        await _until(lambda: len(_collections(caplog)) == 2)
        at[0] = et_ts("2026-10-09 16:20")
        await _until(lambda: len(_collections(caplog)) == 3)
        at[0] = et_ts("2026-10-10 12:00")
        await _looks()
        seen["saturday"] = (two() is None, len(_collections(caplog)))
        stop.set()
        await loop

    with caplog.at_level(logging.INFO, logger=capture.log.name):
        asyncio.run(go())
    assert seen["in session"] == (0, True, 0)
    assert seen["after the close"] == (True, 1)
    assert seen["next session"] == (True, 1)
    assert seen["saturday"] == (True, 3)
    first, second, _third = _collections(caplog)
    assert first[1] >= _RINGS and second[1] >= _RINGS  # each freed its day's cycles
    assert first[2] == second[2] == 0  # nothing it could not free


@pytest.mark.usefixtures("collector")
def test_a_start_after_the_close_runs_no_collection_for_it(caplog):
    """A program started after the day's close holds nothing a session left: no collection.

    Wednesday 2026-10-07 17:00 ET, after the 16:15 close, with Schwab's answer for the day held;
    and the same start before any /markets answer has arrived (INDUCED: none held), the answers
    arriving a moment later through the program's own intake. Neither runs a collection for the
    close that came before the start; Thursday's close, which the program runs through, does.
    """
    answers = [
        json.loads(a["body"])
        for a in json.loads(MARKETS_ANSWERS.read_text(encoding="utf-8"))["answers"].values()
        if a["status"] == 200
    ]

    async def started(held: bool) -> tuple[int, int]:
        at = [et_ts("2026-10-07 17:00")]
        if not held:
            time_et.HELD.sessions = {}  # INDUCED: a program that has just started holds none
        stop = asyncio.Event()
        loop = asyncio.create_task(capture.collect_after_close(lambda: at[0], stop, every=0.01))
        await _looks()
        for answer in answers:
            time_et.record_markets(answer)
        await _looks()
        before = len(_collections(caplog))
        at[0] = et_ts("2026-10-08 16:16")
        await _until(lambda: len(_collections(caplog)) == before + 1)
        stop.set()
        await loop
        return before, len(_collections(caplog))

    with caplog.at_level(logging.INFO, logger=capture.log.name):
        assert asyncio.run(started(held=True)) == (0, 1)
        assert asyncio.run(started(held=False)) == (1, 2)
