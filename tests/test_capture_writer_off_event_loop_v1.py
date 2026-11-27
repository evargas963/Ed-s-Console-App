"""The capture writer never blocks the event loop that reads the Schwab websocket.

MEASURED 2026-09-23: CaptureWriter.run executed every SQLite insert and commit on the same
asyncio loop as the websocket reads, so a slow commit stalled the socket (writer queue
6,565, 9,784 drops). The writer now runs on its own thread with its own connection. These
tests prove it at the real seam: a commit made artificially slow must not stop the loop
from ticking, and every delivered message is still written before run() returns.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

from feed import connection
from stream_spine import LOG, CaptureWriter, KeptFailure, MessageBus, RowWritten, quote_msg
from tests.shared_helpers import TimerCountingLoop, until

#: production's stream of 2026-10-05 14:00:00-14:00:03 CT (RTH): every LEVELONE_EQUITIES and
#: LEVELONE_OPTIONS item Schwab sent, in receive order, as stored
_MIX = json.loads(
    (Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json").read_text(
        encoding="utf-8"
    )
)
_BURST = [
    connection._message(m["service"], m["item"]["key"], m["item"], m["schwab_ts"], m["ts_recv"])
    for m in _MIX["messages"]
    if m["service"] in ("LEVELONE_EQUITIES", "LEVELONE_OPTIONS")
]


def _rows(path, table: str) -> int:
    with closing(sqlite3.connect(str(path))) as conn, conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_the_writer_takes_each_message_with_no_timer_and_writes_all_delivered_before_the_stop(
    tmp_path,
):
    """A real burst, 3 s of production's RTH stream (7,572 messages), through the real writer.

    The writer awaited each message with a 0.25 s timeout to look at its stop: a timer made and
    cancelled on the event loop for every message (2026-11-09: 26% of the program's interpreter
    lock). It now awaits each one as it comes, and the stop follows the messages delivered
    before it: none is scheduled, and the stop, set the moment the burst is published, still
    leaves every one written and committed when run() returns.
    """
    writer = CaptureWriter(tmp_path / "cap.db")
    bus = MessageBus()
    sub = bus.subscribe("", policy=LOG)
    loop = TimerCountingLoop()

    async def go() -> int:
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(sub, stop=stop))
        await asyncio.sleep(0)  # the writer waits on its first message
        before = loop.timers
        for kind, msg in _BURST:
            bus.publish(f"{kind}.{msg['symbol']}", msg)
        while not sub.queue.empty():
            await asyncio.sleep(0)  # the writer takes the burst
        scheduled = loop.timers - before
        for kind, msg in _BURST:  # a second burst, the stop set as it is delivered
            bus.publish(f"{kind}.{msg['symbol']}", msg)
        stop.set()
        await task
        return scheduled

    try:
        scheduled = loop.run_until_complete(go())
    finally:
        loop.close()
    assert scheduled == 0, f"{scheduled} timers scheduled for {len(_BURST)} messages"
    quotes = sum(kind == "quote" for kind, _m in _BURST)
    assert _rows(tmp_path / "cap.db", "stream_quotes_raw") == 2 * quotes
    assert _rows(tmp_path / "cap.db", "stream_options_quotes_raw") == 2 * (len(_BURST) - quotes)


def _quote(i: int) -> dict:
    return quote_msg(symbol="SPY", bid=1.0, ask=1.1, last=1.05, ts_recv=1000.0 + i, src="schwab_l1")


def _hold_the_database(path, release: threading.Event) -> threading.Thread:
    """Another connection holds the database's write lock until `release` is set.

    It holds it as a reader of the file, a backup or the daily keep can: every write the writer
    makes meanwhile waits on it.
    """
    held = threading.Event()

    def hold():
        other = sqlite3.connect(str(path))
        try:
            other.execute("BEGIN EXCLUSIVE")
            held.set()
            release.wait(10)
            other.commit()
        finally:
            other.close()

    t = threading.Thread(target=hold, daemon=True)
    t.start()
    held.wait(10)
    return t


def test_a_slow_commit_does_not_stall_the_event_loop(tmp_path):
    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=1, batch_sec=0.05)
    bus = MessageBus()
    sub = bus.subscribe("", policy=LOG)
    release = threading.Event()
    holder = _hold_the_database(tmp_path / "cap.db", release)

    def handed_over() -> bool:
        """Every message is with the writer, none committed: its commit waits on the lock."""
        now = writer.status()
        return now["held"] == 40 and now["rows_written"] == 0

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(sub, stop=stop))
        for i in range(40):  # the lock is held through every one: each commit waits on it
            bus.publish("quote.SPY", _quote(i))
        # the loop runs on while the commit waits: a commit on the loop would hold this wait
        # until the lock was let go, and every message would be written by then
        handed = await until(handed_over, 5, writer.status)
        release.set()
        stop.set()
        await task
        return handed

    handed = asyncio.run(go())
    holder.join(10)
    assert handed, "the event loop stalled behind a held commit"
    n = (
        sqlite3.connect(str(tmp_path / "cap.db"))
        .execute("SELECT count(*) FROM stream_quotes_raw")
        .fetchone()[0]
    )
    assert n == 40, "every delivered message must still be written before run() returns"


def test_a_writer_that_is_behind_commits_a_batch_at_a_time(tmp_path):
    """A writer that starts with a burst already queued commits it `batch_rows` rows at a time.

    Production 2026-11-12: the writer, starved at the open, took everything queued as one round
    and committed only after writing all of it, so the journal showed no new row for over an
    hour while 12 GB waited in memory. The burst is production's real messages (_BURST), all
    handed to the writer before its thread starts.
    """
    committed: list[int] = []
    counted = CaptureWriter._committed.__code__

    def profile(frame, event, _arg):  # the interpreter's profiler: sees calls, changes nothing
        if event == "call" and frame.f_code is counted:
            committed.append(len(frame.f_locals["batch"]))

    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=5, batch_sec=60.0)
    burst = [item for item in _BURST if writer.saves(*item)]
    for item in burst:
        writer._hand(item)
    sub = MessageBus().subscribe("", policy=LOG)

    async def go():
        stop = asyncio.Event()
        stop.set()
        await writer.run(sub, stop=stop)

    threading.setprofile_all_threads(profile)
    try:
        asyncio.run(go())
    finally:
        threading.setprofile_all_threads(None)
    assert len(burst) > 50, "a burst many batches long"
    assert sum(committed) == len(burst), "every message handed over is committed"
    assert max(committed) == 5, f"the largest commit held {max(committed)} messages"


def _table(path, table: str) -> list[tuple]:
    with closing(sqlite3.connect(str(path))) as conn:
        return conn.execute(f"SELECT rowid, * FROM {table} ORDER BY rowid").fetchall()


def test_a_rounds_rows_of_one_table_go_to_sqlite_in_one_statement(tmp_path):
    """A round of production's real stream is one INSERT per table, its rows as one by one.

    SQLite gives up Python's interpreter lock for each statement, and the writer waits to take
    it back from the program's busy threads, up to the switch interval (5 ms) each time. A round
    (batch_rows messages of _BURST, equity and option quotes) is one statement for each of its
    two tables, and every row is the one the one-row insert writes, in the same order.
    """
    many, one = CaptureWriter(tmp_path / "many.db"), CaptureWriter(tmp_path / "one.db")
    burst = _BURST[: many.batch_rows]
    statements: list[str] = []
    with closing(sqlite3.connect(str(tmp_path / "many.db"))) as conn:
        conn.set_trace_callback(statements.append)
        stored = many._stored_all(conn, burst)
        conn.commit()
    for item in burst:
        one.insert(*item)
    inserts = [s.split("(", 1)[0] for s in statements if s.startswith("INSERT")]
    assert inserts == ["INSERT INTO stream_quotes_raw", "INSERT INTO stream_options_quotes_raw"]
    assert [item for item, _out in stored] == [i for i in burst if i[0] == "quote"] + [
        i for i in burst if i[0] == "optquote"
    ]
    assert all(isinstance(out, RowWritten) for _item, out in stored)
    for table in ("stream_quotes_raw", "stream_options_quotes_raw"):
        assert _table(tmp_path / "many.db", table) == _table(tmp_path / "one.db", table)


def test_a_message_that_cannot_be_a_row_is_kept_and_its_tables_other_rows_written(tmp_path):
    """Induced: one real option quote with its Schwab time taken out, in the middle of a round.

    SQLite undoes the refused statement whole; each of the table's messages is then written by
    itself: every other row stands and that one is kept as sent (stream_write_failures).
    """
    writer = CaptureWriter(tmp_path / "cap.db")
    burst = _BURST[: writer.batch_rows]
    bad = next(i for i, (kind, _m) in enumerate(burst) if kind == "optquote")
    kind, msg = burst[bad]
    burst = [*burst[:bad], (kind, {k: v for k, v in msg.items() if k != "schwab_ts"})]
    burst += _BURST[bad + 1 : writer.batch_rows]
    with closing(sqlite3.connect(str(tmp_path / "cap.db"))) as conn:
        stored = [out for _item, out in writer._stored_all(conn, burst)]
        conn.commit()
    kept = [out for out in stored if isinstance(out, KeptFailure)]
    assert [k.topic for k in kept] == ["optquote"]
    assert _rows(tmp_path / "cap.db", "stream_write_failures") == 1
    options = sum(kind == "optquote" for kind, _m in burst)
    assert _rows(tmp_path / "cap.db", "stream_options_quotes_raw") == options - 1
    assert _rows(tmp_path / "cap.db", "stream_quotes_raw") == len(burst) - options


def test_writes_happen_on_the_writer_thread_not_the_loop(tmp_path):
    seen: set = set()
    write = CaptureWriter._many.__code__

    def profile(frame, event, _arg):  # the interpreter's profiler: sees calls, changes nothing
        if event == "call" and frame.f_code is write:
            seen.add(threading.current_thread().name)

    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=5, batch_sec=0.05)
    bus = MessageBus()
    sub = bus.subscribe("", policy=LOG)

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(sub, stop=stop))
        for i in range(10):
            bus.publish("quote.SPY", _quote(i))
        # written while the writer runs, before any stop
        await until(lambda: writer.status()["rows_written"] >= 10, seconds=10)
        stop.set()
        await task

    threading.setprofile_all_threads(profile)
    try:
        asyncio.run(go())
    finally:
        threading.setprofile_all_threads(None)
    assert seen == {"stream-capture-writer"}
