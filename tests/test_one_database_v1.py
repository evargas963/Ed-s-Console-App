"""One database (operator 2026-11-15: "one db that has all the data we need").

The stream's messages, the chain history and the level crosses are recorded in one file,
data/ed.db (db_authority.canonical_db_path). Its three writers take turns at SQLite's one write
lock: the stream writer, the chain sweep's capture transaction and the level crosses. A chain's
history written while the stream is recording holds no stream message back past the writer's
own lock wait, and every row of all three is in the file.

Real data: captured LEVELONE_OPTIONS quotes (tests/fixtures/real_options_stream_history_samples
.json, through the daemon's own handler and bus), SPY's 2026-11-20 contracts of the capture of
2026-09-30 15:31:57 ET (tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json) and a level
cross at that capture's stored price.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import db_authority
from app.market_data.schwab.streaming import capture
from calibration.complete_chain_capture import CAPTURE_BASIS, last_capture_per_day
from db import EdDB, LevelCrossEvent
from stream_spine import LOG, CaptureWriter, HealthRegistry, MessageBus
from tests.capture_store import store_capture
from tests.test_data_path_rules_v1 import _EVENTS
from tests.test_data_path_writer_failures_v1 import _count, _publish_options, _until

SPY = json.loads(
    (Path(__file__).parent / "fixtures" / "real_spy_2026_11_20_chain_and_quotes.json").read_text(
        encoding="utf-8"
    )
)


def _cross() -> LevelCrossEvent:
    return LevelCrossEvent(
        ticker="SPY",
        ts_utc=SPY["capture_ts_utc"],
        ts_et="2026-09-30 15:31:57 ET",
        level_name="Call wall",
        level_value=766.0,
        direction="up",
        spot_at_cross=SPY["spot"],
        zone_before=None,
        zone_after=None,
        timeframe="1m",
    )


def test_the_one_database_is_ed_db_in_the_runtime_data_folder():
    p = db_authority.canonical_db_path()
    assert p.name == "ed.db"
    assert p.parent.name == "data"
    assert db_authority.is_canonical_db_path(p)


def test_a_chain_history_written_while_the_stream_records_holds_no_message_back(tmp_path):
    """The three writers take turns; the stream writer is never blocked and every row lands.

    The chain's capture transaction and the level crosses write from a thread of their own while
    the stream writer records the captured option quotes on its own thread, as in the daemon.
    The stream writer's lock wait (timeout_sec) is its production 30 s; it must never read
    blocked.
    """
    db = tmp_path / "ed.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
    edb = EdDB(db, allow_noncanonical=True)
    states: list[str] = []

    def write_history():
        store_capture(
            db,
            ticker="SPY",
            expiry=SPY["expiry"],
            contracts=SPY["chain"],
            spot=SPY["spot"],
            completeness_basis=CAPTURE_BASIS,
            ts_utc=SPY["capture_ts_utc"],
        )
        edb.record_level_crosses([_cross()])

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health)
        daemon.writer = writer
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        other = threading.Thread(target=write_history)
        other.start()
        for _ in range(20):
            _publish_options(bus, health, _EVENTS)
            states.append(writer.status()["state"])
            await asyncio.sleep(0.01)
        await _until(lambda: writer.status()["rows_written"] == 20 * len(_EVENTS))
        other.join()
        stop.set()
        await task

    asyncio.run(go())

    assert "blocked" not in states
    counts = {
        t: _count(db, t)
        for t in ("stream_options_quotes_raw", "complete_chain_captures", "level_crosses")
    }
    assert counts == {
        "stream_options_quotes_raw": 20 * len(_EVENTS),
        "complete_chain_captures": 1,
        "level_crosses": 1,
    }
    (got,) = last_capture_per_day(db, "SPY", 1)
    assert len(got.contracts) == len(SPY["chain"])
    assert edb.get_recent_crosses("SPY")[0]["spot_at_cross"] == SPY["spot"]
