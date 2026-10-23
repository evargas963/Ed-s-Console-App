"""stream_capture.db holds what the operator trades, for the newest five trading sessions
(docs/DATA_FLOW.md §2 D4): the daemon's writer records an option quote or option book only for a
contract the daemon keeps (Daemon.saves: each watchlist ticker's soonest expiration, the 5 listed
strikes each side of the price, and the Flow panel's contract), every equity message, and once
after each close of the last option market removes the rows received before the newest five
sessions began (keep_sessions, CaptureWriter.prune). The live stream and the levels are untouched.

Real data: the option chains the daemon captured 2026-10-07 (tests/real_chains.py), Schwab's
/markets answers held by tests/conftest.py, and the stream mix of 2026-10-05 (_MIX) for the keep's
place between live writes. STAND-INS, in the tests of the kept contracts and of the keep's bound
(no streamed message of the 2026-10-07 contracts is captured): the messages' contents (only their
topic, symbol and receipt time are what these prove) and the daemon's clock.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from app.market_data.schwab.streaming import capture
from calibration.complete_chain_capture import chain_messages
from stream_spine import LOG, PRUNE_ROWS, WRITER_BLOCKED, WRITER_DEAD, WRITER_RECORDING, CaptureWriter, HealthRegistry, MessageBus, book_msg, options_quote_msg, quote_msg
from tests.real_chains import MRVL, SPY_0DTE
from time_et import ET


async def _until(ok, seconds: float = 30.0) -> None:
    deadline = asyncio.get_running_loop().time() + seconds
    while not ok():
        assert asyncio.get_running_loop().time() < deadline, "timed out"
        await asyncio.sleep(0.02)


def _rows(db, sql: str) -> list:
    with sqlite3.connect(db) as conn:
        return conn.execute(sql).fetchall()


def _et(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=ET).timestamp()


def test_only_the_option_contracts_traded_are_recorded_and_every_equity_message(tmp_path):
    """SPY 2026-10-07 12:32 ET at 776.61, its same-day expiration listed: strikes 772 to 782 (777
    nearest, 5 listed each side), calls and puts. MRVL at 283.73, no same-day expiration: its
    nearest, 2026-10-09, strikes 270 to 295 (282.5 nearest). The contract selected on the Flow panel
    is recorded wherever it is. No other option quote or option book is recorded; both tickers'
    equity quotes are."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY", "MRVL"], clock=lambda: SPY_0DTE.now.timestamp())
    daemon.writer = writer
    writer.saves = daemon.saves
    flow = next(c["symbol"] for c in MRVL.chain if c["expirationDate"].startswith("2026-11-20"))
    spy_kept = {c["symbol"] for c in SPY_0DTE.chain if 772 <= c["strikePrice"] <= 782}
    mrvl_kept = {c["symbol"] for c in MRVL.chain
                 if c["expirationDate"].startswith("2026-10-09") and 270 <= c["strikePrice"] <= 295}
    every = [c["symbol"] for c in SPY_0DTE.chain + MRVL.chain]
    near, far = sorted(spy_kept)[0], next(s for s in every if s not in spy_kept | mrvl_kept | {flow})

    async def go():
        stop = asyncio.Event()
        tasks = [asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop)),
                 asyncio.create_task(daemon.follow_market(stop))]
        await asyncio.sleep(0)
        for rc in (SPY_0DTE, MRVL):
            for topic, msg in chain_messages(rc.ticker, rc.chain, rc.now.timestamp()):
                bus.publish(topic, msg)
            bus.publish(f"quote.{rc.ticker}", quote_msg(symbol=rc.ticker, last=rc.spot, src="schwab_l1",
                                                        native={"key": rc.ticker, "LAST_PRICE": rc.spot}))
        await _until(lambda: daemon.saved_options == frozenset(spy_kept | mrvl_kept))
        daemon.console_frame({"op": "flow_contract", "contract": flow}, None)
        for sym in every:
            bus.publish(f"optquote.{sym}", options_quote_msg(symbol=sym, content={"key": sym, "MARK": 1.0},
                                                             src="schwab_options_l1"))
        for sym in (near, far):
            bus.publish(f"book.{sym}", book_msg(symbol=sym, service="OPTIONS_BOOK", content={"key": sym},
                                                src="schwab_book"))
        bus.publish("quote.SPY", quote_msg(symbol="SPY", last=776.62, src="schwab_l1",
                                           native={"key": "SPY", "LAST_PRICE": 776.62}))
        await _until(lambda: writer.status()["rows_written"] == len(spy_kept | mrvl_kept) + 1 + 1 + 3)
        stop.set()
        await asyncio.gather(*tasks)
    asyncio.run(go())

    assert len(spy_kept) == len(mrvl_kept) == 22                 # 11 strikes, a call and a put each
    options = {s for (s,) in _rows(db, "SELECT symbol FROM stream_options_quotes_raw")}
    assert options == spy_kept | mrvl_kept | {flow}, "not exactly the kept contracts and the Flow panel's"
    assert [s for (s,) in _rows(db, "SELECT symbol FROM stream_book_raw")] == [near]
    assert sorted(s for (s,) in _rows(db, "SELECT symbol FROM stream_quotes_raw")) == ["MRVL", "SPY", "SPY"]


def _recorded(bus) -> None:
    """Rows on both sides of 2026-10-01 00:00 ET, as the daemon publishes them."""
    for when in ("2026-09-30 15:00", "2026-10-01 09:31"):
        bus.publish("quote.SPY", quote_msg(symbol="SPY", last=1.0, src="schwab_l1", ts_recv=_et(when),
                                           native={"key": "SPY"}))
        bus.publish("feedstatus.LEVELONE_EQUITIES", {"ts": _et(when), "service": "LEVELONE_EQUITIES",
                                                     "socket_open": True, "held": 1})
    for when in ("2026-09-30 15:00", "2026-10-07 15:00"):
        bus.publish("optquote.SPY   261007C00777000", options_quote_msg(
            symbol="SPY   261007C00777000", content={"key": "SPY   261007C00777000"}, src="schwab_options_l1",
            ts_recv=_et(when)))
    for when in ("2026-09-29 12:00", "2026-09-30 12:00"):          # both before; the newest stays
        topic, msg = capture.watchlist_message(["SPY"], op="added", ticker="SPY", request_id=when)
        bus.publish(topic, {**msg, "ts_recv": _et(when)})


def _kept_at(tmp_path, clock: str, wait: float) -> str:
    """The rows left after the daemon's keep runs at `clock` (ET) for `wait` seconds or until the
    old rows are gone: a summary per table."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"], clock=lambda: _et(clock))
    daemon.writer = writer

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        await asyncio.sleep(0)
        _recorded(bus)
        await _until(lambda: writer.status()["rows_written"] == 8)
        keep = asyncio.create_task(capture.keep_sessions(daemon, stop))
        try:
            await _until(lambda: _rows(db, "SELECT COUNT(*) FROM stream_feed_status")[0][0] == 1, wait)
        except AssertionError:
            pass                                                         # nothing was removed
        stop.set()
        await asyncio.gather(task, keep)
    asyncio.run(go())
    counts = " ".join(f"{name}:{_rows(db, f'SELECT COUNT(*) FROM {table}')[0][0]}" for name, table in (
        ("quotes", "stream_quotes_raw"), ("options", "stream_options_quotes_raw"),
        ("feed", "stream_feed_status"), ("watchlist", "stream_watchlist")))
    newest = datetime.fromtimestamp(_rows(db, "SELECT MAX(ts_recv) FROM stream_watchlist")[0][0], ET)
    return f"{counts} newest-watchlist:{newest:%m-%d %H:%M}"


def test_after_the_last_option_close_rows_before_the_newest_five_sessions_are_removed(tmp_path):
    """2026-10-07 17:00 ET, the last option market (IND) closed at 16:15: Schwab's /markets says
    the market was open 09-30, 10-01, 10-02, 10-05, 10-06 and 10-07, so the newest five sessions
    run from 2026-10-01 00:00 ET. Every row received before it is removed from each table, except
    the newest watchlist row, which the daemon reads at its start."""
    assert _kept_at(tmp_path, "2026-10-07 17:00", 30.0) == \
        "quotes:1 options:1 feed:1 watchlist:1 newest-watchlist:09-30 12:00"


#: CT, as Schwab sent it (7,420 option quotes, 152 equity quotes, 12 books; read-only from
#: stream_capture.db, provenance in the file)
_MIX = json.loads((Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json")
                  .read_text(encoding="utf-8"))
_COPIES = 54                                   # 400,680 option quotes: twenty-one parts of the keep
_FIVE_SESSIONS = "2026-10-01 00:00"            # the newest five sessions' start at 2026-10-07 17:00 ET


@pytest.fixture(scope="module")
def _old_file(tmp_path_factory) -> Path:
    """INDUCED CONDITIONS: the writer's own file, indexed as production's stream_capture.db is
    (PRAGMA index_list on it: its quote, book and option tables by receipt time), holding the mix's
    option quotes as the writer stores them, one copy for each of the 54 minutes before the mix,
    each received a week earlier (2026-09-28, before the newest five sessions began)."""
    db = tmp_path_factory.mktemp("old") / "stream_capture.db"
    writer = CaptureWriter(db)
    conn = sqlite3.connect(db)
    for copy in range(_COPIES):
        for m in _MIX["messages"]:
            if m["service"] == "LEVELONE_OPTIONS":
                key = m["item"]["key"].upper()
                kind, msg = capture._message(m["service"], key, m["item"], m["schwab_ts"])
                msg["ts_recv"] = m["ts_recv"] - 7 * 86_400 - 60.0 * copy
                writer.insert(f"{kind}.{key}", msg, conn=conn)
    conn.commit()
    conn.close()
    return db


def _publish_mix(bus: MessageBus, services: set, limit: int | None = None) -> int:
    """The mix's messages of `services`, each frame decoded from its JSON through the daemon's
    handler for its service, received now: how many were published."""
    health = HealthRegistry()
    handlers = {s: capture._publisher(s, bus, health) for s in services}
    sent = [m for m in _MIX["messages"] if m["service"] in services][:limit]
    for m in sent:
        handlers[m["service"]](json.loads(json.dumps({"content": [m["item"]], "timestamp": m["schwab_ts"]})))
    return len(sent)


def _old_rows(db) -> int:
    return _rows(db, f"SELECT COUNT(*) FROM stream_options_quotes_raw WHERE ts_recv < {_et(_FIVE_SESSIONS)}")[0][0]


def test_every_message_arriving_during_the_keep_is_written_while_old_rows_are_still_being_removed(_old_file, tmp_path):
    """The old file (_old_file: 400,680 option quotes before the newest five sessions, twenty-one
    parts of the keep), and the whole mix arriving while the keep runs: every message is written
    while old rows remain (every message queued is written in each round between parts), and the
    keep then removes every old row and nothing else."""
    db = tmp_path / "stream_capture.db"
    shutil.copy(_old_file, db)
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
    bus = MessageBus()

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        await asyncio.sleep(0)
        writer.prune(_et(_FIVE_SESSIONS))
        sent = _publish_mix(bus, {m["service"] for m in _MIX["messages"]})
        await _until(lambda: writer.status()["rows_written"] >= sent)
        old_left = _old_rows(db)
        await _until(lambda: _old_rows(db) == 0, 60)
        stop.set()
        await task
        return old_left
    old_left = asyncio.run(go())
    assert old_left > 0, "the keep had finished before the messages that arrived during it were written"
    assert {t: _rows(db, f"SELECT COUNT(*) FROM {t}")[0][0] for t in _MIX["counts"]} == _MIX["counts"]


def test_a_stop_asked_during_the_keep_writes_what_was_queued_and_removes_nothing_more(_old_file, tmp_path):
    """The keep has the old file's 400,680 option quotes to remove (twenty-one parts) when the mix's
    first ten equity quotes and the stop are handed to the writer: it writes the ten and ends,
    having run at most the one part in progress when they arrived, none after it took the stop.
    The bound holds while run() hands the ten (microseconds) within one part's time (a
    PRUNE_ROWS-row delete)."""
    db = tmp_path / "stream_capture.db"
    shutil.copy(_old_file, db)
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
    old = _old_rows(db)
    bus = MessageBus()
    sub = bus.subscribe("", policy=LOG)
    assert _publish_mix(bus, {"LEVELONE_EQUITIES"}, limit=10) == 10
    writer.prune(_et(_FIVE_SESSIONS))
    stop = asyncio.Event()
    stop.set()                                   # the stop is asked as the ten are handed over
    asyncio.run(writer.run(sub, stop=stop))
    assert _rows(db, "SELECT COUNT(*) FROM stream_quotes_raw")[0][0] == 10
    assert _old_rows(db) >= old - PRUNE_ROWS


def test_every_message_a_round_has_taken_counts_as_held_until_it_is_written(tmp_path):
    """The mix's 152 equity quotes are queued while another connection holds the database's write
    lock: the writer takes what is queued into its round and waits up to timeout_sec on the round's
    first row. While it waits, the header's held count is every one of them, queued or taken, and
    once the lock is let go every one is written. The 0.2 s pause lets the last hand-over and the
    round's take (microseconds) finish well inside the 5 s wait."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, timeout_sec=5.0)
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")
    bus = MessageBus()
    sub = bus.subscribe("", policy=LOG)
    sent = _publish_mix(bus, {"LEVELONE_EQUITIES"})

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(sub, stop=stop))
        await _until(lambda: sub.queue.empty() and writer.status()["queue_depth"] < sent)
        await asyncio.sleep(0.2)
        during = writer.status()
        holder.execute("COMMIT")
        await _until(lambda: writer.status()["rows_written"] == sent)
        stop.set()
        await task
        return during
    try:
        during = asyncio.run(go())
    finally:
        holder.close()
    assert (during["state"], during["rows_written"]) == (WRITER_RECORDING, 0), "the round was not still waiting"
    assert during["held"] == sent == 152, f"{during['held']} of {sent} taken messages counted as held"
    assert _rows(db, "SELECT COUNT(*) FROM stream_quotes_raw")[0][0] == sent


def test_messages_spilled_when_the_database_refuses_a_round_are_not_counted_as_held(tmp_path):
    """The mix's 152 equity quotes are queued while another connection holds the write lock, and
    the writer's memory cap is 1 byte (an input, STAND-IN for about 2 GB), so every held message
    goes to the spill file. Read during the pause after the first refusal: the held count is what
    memory holds (none) plus the queue, and every message is written once the lock is let go."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, timeout_sec=0.05, retry_sec=1.0, hold_cap_bytes=1)
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")
    bus = MessageBus()
    sub = bus.subscribe("", policy=LOG)
    sent = _publish_mix(bus, {"LEVELONE_EQUITIES"})

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(sub, stop=stop))
        def admitted() -> bool:        # every message spilled or queued: _admit has finished
            s = writer.status()
            return (s["state"] == WRITER_BLOCKED and s["spill"] is not None
                    and s["spill"]["messages"] + s["queue_depth"] == sent)
        await _until(admitted)
        during = writer.status()
        holder.execute("COMMIT")
        await _until(lambda: writer.status()["rows_written"] == sent)
        stop.set()
        await task
        return during
    try:
        during = asyncio.run(go())
    finally:
        holder.close()
    assert during["state"] == WRITER_BLOCKED and during["spill"]["messages"] > 0
    assert during["held"] == during["queue_depth"] + during["waiting"] == during["queue_depth"], \
        f"held {during['held']}: {during['spill']['messages']} spilled, {during['queue_depth']} queued"
    assert _rows(db, "SELECT COUNT(*) FROM stream_quotes_raw")[0][0] == sent


class _UnreadableQuote(dict):
    """STAND-IN for a defect: a captured equity quote whose fields cannot be read as items, so the
    writer can neither size it for memory nor write it to a spill record (RuntimeError)."""

    def items(self):
        raise RuntimeError("a message the writer cannot read")


class _Unprintable:
    """STAND-IN for a defect: a value no spill record can write (its repr raises RuntimeError)."""

    def __repr__(self):
        raise RuntimeError("a value no spill record can write")


def _dies_holding(db, cap: int, eleventh: dict, *, stop: bool) -> dict:
    """The writer's status once it has died holding the mix's first ten equity quotes and then the
    eleventh's message `eleventh`, the write lock held throughout; with `stop`, the stop is asked
    once all eleven are held in memory."""
    writer = CaptureWriter(db, timeout_sec=0.05, retry_sec=0.1, hold_cap_bytes=cap)
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")
    bus = MessageBus()
    sub = bus.subscribe("", policy=LOG)
    assert _publish_mix(bus, {"LEVELONE_EQUITIES"}, limit=10) == 10
    bus.publish(f"quote.{eleventh['symbol']}", eleventh)

    async def go():
        ended = asyncio.Event()
        task = asyncio.create_task(writer.run(sub, stop=ended))
        if stop:
            await _until(lambda: writer.status()["waiting"] == 11)
            ended.set()
        await _until(lambda: writer.status()["state"] == WRITER_DEAD)
        ended.set()
        await task
    try:
        asyncio.run(go())
    finally:
        holder.close()
    return writer.status()


def _eleventh() -> dict:
    m = [m for m in _MIX["messages"] if m["service"] == "LEVELONE_EQUITIES"][10]
    return capture._message(m["service"], m["item"]["key"].upper(), m["item"], m["schwab_ts"])[1]


def test_a_writer_that_dies_while_spilling_counts_as_not_recorded_only_what_was_not_yet_held(tmp_path):
    """INDUCED CONDITIONS: a 1-byte memory cap (an input, STAND-IN for about 2 GB), so the first ten
    go to the spill file, and the eleventh an _UnreadableQuote: the writer dies holding it. Not
    recorded is the eleventh alone; the ten are in the spill file, listed as left on disk; none is
    lost."""
    s = _dies_holding(tmp_path / "stream_capture.db", 1, _UnreadableQuote(_eleventh()), stop=False)
    assert s["error"] == "RuntimeError: a message the writer cannot read"
    assert (s["unrecorded"], s["lost"], [k["messages"] for k in s["left_on_disk"]]) == (1, 0, [10])


def test_a_writer_that_dies_while_holding_in_memory_counts_all_it_held_as_not_recorded(tmp_path):
    """INDUCED CONDITIONS: a 10 MB memory cap, so the first ten are held in memory, and the eleventh
    an _UnreadableQuote: the writer dies holding it. Not recorded is all eleven; nothing is on
    disk or lost."""
    s = _dies_holding(tmp_path / "stream_capture.db", 10_000_000, _UnreadableQuote(_eleventh()), stop=False)
    assert s["error"] == "RuntimeError: a message the writer cannot read"
    assert (s["unrecorded"], s["lost"], s["left_on_disk"]) == (11, 0, [])


def test_a_writer_that_dies_leaving_memory_on_disk_at_a_stop_counts_only_what_was_not_yet_written(tmp_path):
    """INDUCED CONDITIONS: a 10 MB memory cap, so all eleven are held in memory, the eleventh
    carrying an _Unprintable value; the stop is asked, and the writer dies writing the eleventh
    to the stop's file. Not recorded is the eleventh alone, none is lost, and the next writer
    writes the ten from that file into the database."""
    db = tmp_path / "stream_capture.db"
    s = _dies_holding(db, 10_000_000, {**_eleventh(), "unprintable": _Unprintable()}, stop=True)
    assert s["error"] == "RuntimeError: a value no spill record can write"
    assert (s["unrecorded"], s["lost"]) == (1, 0)
    writer = CaptureWriter(db)

    async def go():
        ended = asyncio.Event()
        task = asyncio.create_task(writer.run(MessageBus().subscribe("", policy=LOG), stop=ended))
        await _until(lambda: _rows(db, "SELECT COUNT(*) FROM stream_quotes_raw")[0][0] == 10)
        ended.set()
        await task
    asyncio.run(go())


def test_nothing_is_removed_while_the_options_trade_or_the_market_is_unknown(tmp_path):
    """2026-10-07 12:00 ET, the options open; and 2027-10-12, a date Schwab's held answers do not
    reach: no row is removed (never on a guess)."""
    untouched = "quotes:2 options:2 feed:2 watchlist:2 newest-watchlist:09-30 12:00"
    assert _kept_at(tmp_path / "open", "2026-10-07 12:00", 1.5) == untouched
    assert _kept_at(tmp_path / "unknown", "2027-10-12 17:00", 1.5) == untouched
