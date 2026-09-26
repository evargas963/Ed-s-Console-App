"""CR-01 spine contracts: cache-then-publish, bounded queues, RC-6 guard, health states."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

import json

from stream_spine import (
    COALESCE,
    COUNT_DROPS,
    CaptureWriter,
    HealthRegistry,
    MessageBus,
    bar_msg,
    book_msg,
    options_quote_msg,
    quote_msg,
)


def test_cache_written_before_subscribers_and_snapshot_hydrates():
    async def go():
        bus = MessageBus()
        seen_at_delivery = {}

        sub = bus.subscribe("quote.", policy=COUNT_DROPS)
        bus.publish("quote.SPY", {"last": 747.63})
        # cache-then-publish: by the time the message is readable, the cache has it
        topic, msg = await sub.get()
        seen_at_delivery["cache"] = bus.cache.get("quote.SPY")
        assert topic == "quote.SPY" and msg["last"] == 747.63
        assert seen_at_delivery["cache"] == {"last": 747.63}
        # a late consumer hydrates from snapshot without any poll
        assert bus.snapshot("quote.")["quote.SPY"]["last"] == 747.63
    asyncio.run(go())


def test_coalesce_keeps_newest_only_and_counts_nothing_lost_as_drops():
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("quote.", policy=COALESCE, maxsize=4)
        for px in (1.0, 2.0, 3.0):
            bus.publish("quote.SPY", {"last": px})
        topic, msg = await sub.get()
        assert msg["last"] == 3.0, "coalesce must deliver the NEWEST pending quote"
        assert sub.queue.empty(), "one topic key, not three"
        assert sub.dropped == 0, "coalescing is not a drop"
    asyncio.run(go())


def test_messages_never_coalesce_and_overflow_counts_loudly():
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("quote.", policy=COUNT_DROPS, maxsize=2)
        for i in range(5):
            bus.publish("quote.SPY", {"size": i})
        # first two kept in order, three counted dropped — never silently merged
        t0, m0 = await sub.get()
        t1, m1 = await sub.get()
        assert (m0["size"], m1["size"]) == (0, 1)
        assert sub.dropped == 3
        assert bus.drop_counts() == {"quote.": 3}
    asyncio.run(go())


def test_writer_refuses_operational_db():
    with pytest.raises(ValueError):
        CaptureWriter("data/ed_console.db")


def test_writer_batches_into_stream_capture_db(tmp_path):
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=2, batch_sec=10.0)
    w.insert("quote.SPY", quote_msg(symbol="SPY", bid=1, ask=2, last=1.5, bid_size=10,
                                    ask_size=20, last_size=1, total_volume=100,
                                    quote_time_ms=5, trade_time_ms=6, src="t", ts_recv=1.0))
    w.insert("bar1m.SPY", bar_msg(symbol="SPY", bar_start_ms=0, open=1, high=2, low=0.5,
                                  close=1.5, volume=999, src="t", ts_recv=2.0))
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM stream_quotes_raw").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM stream_bars_raw").fetchone()[0] == 1
    assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_quote_native_content_stored_with_field_fidelity(tmp_path):
    """The daemon's flattened columns cannot carry BID_TIME_MILLIS / REGULAR_MARKET_
    CHANGE_PERCENT — fields the live-plane hydrator needs. `native` must round-trip
    losslessly through the same INSERT the flattened columns use."""
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    native = {"key": "SPY", "BID_PRICE": 1.0, "BID_TIME_MILLIS": 123,
             "REGULAR_MARKET_CHANGE_PERCENT": 0.42}
    w.insert("quote.SPY", quote_msg(symbol="SPY", bid=1.0, src="schwab_l1", ts_recv=1.0,
                                    native=native))
    con = sqlite3.connect(db)
    row = con.execute("SELECT native_json FROM stream_quotes_raw").fetchone()
    assert json.loads(row[0]) == native


def test_quote_without_native_stores_null_not_a_fabricated_value(tmp_path):
    """Quote producers that pass no native dict (tests) — must stay NULL,
    never an empty-dict placeholder that would misrepresent 'no data' as 'measured empty'."""
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert("quote.SPY", quote_msg(symbol="SPY", bid=1.0, src="t", ts_recv=1.0))
    con = sqlite3.connect(db)
    assert con.execute("SELECT native_json FROM stream_quotes_raw").fetchone()[0] is None


def test_existing_stream_capture_db_migrates_native_json_column(tmp_path):
    """A daemon restart against a DB written by the PRE-repair schema must not crash —
    ALTER TABLE ADD COLUMN is idempotent forward migration, not a fresh-DB assumption."""
    db = tmp_path / "stream_capture.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE stream_quotes_raw (
            ts_recv REAL NOT NULL, symbol TEXT NOT NULL,
            bid REAL, ask REAL, last REAL,
            bid_size INTEGER, ask_size INTEGER, last_size INTEGER,
            total_volume INTEGER, quote_time_ms INTEGER, trade_time_ms INTEGER,
            src TEXT NOT NULL
        );
    """)
    con.commit()
    con.close()
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert("quote.SPY", quote_msg(symbol="SPY", bid=1.0, src="t", ts_recv=1.0,
                                    native={"key": "SPY"}))
    con = sqlite3.connect(db)
    assert con.execute("SELECT native_json FROM stream_quotes_raw").fetchone()[0] is not None


def test_book_content_stored_verbatim_never_flattened(tmp_path):
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    content = {"key": "SPY", "BIDS": [{"BID_PRICE": 1.0}], "ASKS": [{"ASK_PRICE": 1.1}],
              "BOOK_TIME": 999}
    w.insert("book.SPY", book_msg(symbol="SPY", service="NASDAQ_BOOK", content=content,
                                  src="schwab_book", ts_recv=1.0))
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT symbol, service, native_json, src FROM stream_book_raw").fetchone()
    assert row[0] == "SPY" and row[1] == "NASDAQ_BOOK" and row[3] == "schwab_book"
    assert json.loads(row[2]) == content


def test_book_msg_with_no_content_is_not_inserted(tmp_path):
    """insert() on kind 'book' with no content must not write a row that get_content_for_symbol
    would then treat as a valid empty book snapshot."""
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert("book.SPY", {"ts_recv": 1.0, "symbol": "SPY", "service": "NASDAQ_BOOK",
                          "content": None, "src": "t"})
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM stream_book_raw").fetchone()[0] == 0


#: Real content shape from the live-proven probe (reports/of_capability_probe/
#: options_20260820T1354Z/frames/LEVELONE_OPTIONS_001_decoded.json) — not invented.
_REAL_LEVELONE_OPTIONS_CONTENT = {
    "key": "SPY   260820C00767000", "delayed": False, "assetMainType": "OPTION",
    "DESCRIPTION": "SPY 08/20/2026 767.00 C", "BID_PRICE": 1.26, "ASK_PRICE": 1.28,
    "LAST_PRICE": 1.27, "OPEN_INTEREST": 2097, "VOLATILITY": 16.50358958,
    "DELTA": 0.45644607, "GAMMA": 0.1165604, "THETA": -1.17543886, "VEGA": 0.08171809,
    "DAYS_TO_EXPIRATION": 0, "CONTRACT_TYPE": "C", "UNDERLYING": "SPY",
}

#: Real content shape from OPTIONS_BOOK_001_decoded.json — per-MM/exchange depth.
_REAL_OPTIONS_BOOK_CONTENT = {
    "key": "SPY   260820C00767000", "BOOK_TIME": 1787234093764,
    "BIDS": [{"BID_PRICE": 1.28, "TOTAL_VOLUME": 1746, "NUM_BIDS": 12,
             "BIDS": [{"EXCHANGE": "NYSE", "BID_VOLUME": 262, "SEQUENCE": 35693547}]}],
    "ASKS": [{"ASK_PRICE": 1.3, "TOTAL_VOLUME": 1533, "NUM_ASKS": 10,
             "ASKS": [{"EXCHANGE": "EDGX", "ASK_VOLUME": 346, "SEQUENCE": 35693726}]}],
}


def test_options_quote_content_stored_verbatim_never_flattened(tmp_path):
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert("optquote.SPY   260820C00767000", options_quote_msg(
        symbol="SPY   260820C00767000", content=_REAL_LEVELONE_OPTIONS_CONTENT,
        src="schwab_options_l1", ts_recv=1.0))
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT symbol, native_json, src FROM stream_options_quotes_raw").fetchone()
    assert row[0] == "SPY   260820C00767000" and row[2] == "schwab_options_l1"
    assert json.loads(row[1]) == _REAL_LEVELONE_OPTIONS_CONTENT


def test_options_quote_with_no_content_is_not_inserted(tmp_path):
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert("optquote.SPY", {"ts_recv": 1.0, "symbol": "SPY", "content": None, "src": "t"})
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM stream_options_quotes_raw").fetchone()[0] == 0


def test_options_book_reuses_the_generic_book_table_by_service(tmp_path):
    """OPTIONS_BOOK needs no new table — stream_book_raw is already service-discriminated
    (NASDAQ_BOOK/NYSE_BOOK/OPTIONS_BOOK all coexist by `service` value)."""
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert("book.SPY   260820C00767000", book_msg(
        symbol="SPY   260820C00767000", service="OPTIONS_BOOK",
        content=_REAL_OPTIONS_BOOK_CONTENT, src="schwab_options_book", ts_recv=1.0))
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT symbol, service, native_json FROM stream_book_raw").fetchone()
    assert row[1] == "OPTIONS_BOOK"
    assert json.loads(row[2]) == _REAL_OPTIONS_BOOK_CONTENT


def test_health_states_progress_running_degraded_stale():
    h = HealthRegistry()
    assert h.state("schwab_l1") == "DOWN"          # never seen != quiet market
    h.beat("schwab_l1", ts=1000.0)
    assert h.state("schwab_l1", now=1002.0) == "RUNNING"
    assert h.state("schwab_l1", now=1010.0) == "DEGRADED"
    assert h.state("schwab_l1", now=1031.0) == "STALE"
    rep = h.report(now=1010.0)
    assert rep["schwab_l1"]["state"] == "DEGRADED" and rep["schwab_l1"]["age_sec"] == 10.0


def test_writer_drains_full_queue_on_stop(tmp_path):
    """Cursor review HIGH: stop must not vaporize buffered rows."""
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("", policy=COUNT_DROPS, maxsize=8192)
        w = CaptureWriter(tmp_path / "s.db", batch_rows=10_000, batch_sec=60.0)
        for i in range(50):
            bus.publish("quote.SPY", quote_msg(symbol="SPY", bid=1.0, last_size=i, src="t"))
        stop = asyncio.Event()
        stop.set()                      # stop BEFORE the writer ever runs
        await w.run(sub, stop=stop)
        con = sqlite3.connect(tmp_path / "s.db")
        n = con.execute("SELECT COUNT(*) FROM stream_quotes_raw").fetchone()[0]
        assert n == 50, f"drain lost rows: {n}/50"
        assert w.insert_errors == 0
    asyncio.run(go())


def test_insert_failure_is_counted_never_kills_writer(tmp_path):
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("", policy=COUNT_DROPS)
        w = CaptureWriter(tmp_path / "s.db", batch_rows=10_000, batch_sec=60.0)
        bus.publish("quote.SPY", object())      # not a dict -> insert raises inside
        bus.publish("quote.SPY", quote_msg(symbol="SPY", bid=2.0, src="t"))
        stop = asyncio.Event(); stop.set()
        await w.run(sub, stop=stop)
        assert w.insert_errors == 1
        con = sqlite3.connect(tmp_path / "s.db")
        assert con.execute("SELECT COUNT(*) FROM stream_quotes_raw").fetchone()[0] == 1
    asyncio.run(go())


def test_rc6_guard_survives_path_tricks():
    """Cursor review MEDIUM: `data/x/../ed_console.db` must not slip past the guard."""
    with pytest.raises(ValueError):
        CaptureWriter("data/nosuchdir/../ed_console.db")


def test_writer_init_closes_conn_if_schema_setup_fails(tmp_path, monkeypatch):
    """Bugbot HIGH: connect-then-fail must not leak the SQLite handle."""
    real_connect = __import__("sqlite3").connect
    closed = {"n": 0}

    class TrackingConn:
        def __init__(self, inner):
            self._inner = inner

        def executescript(self, *_a, **_k):
            raise RuntimeError("schema boom")

        def commit(self):
            return self._inner.commit()

        def close(self):
            closed["n"] += 1
            return self._inner.close()

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def wrap(path, *a, **k):
        return TrackingConn(real_connect(path, *a, **k))

    monkeypatch.setattr("stream_spine.sqlite3.connect", wrap)
    with pytest.raises(RuntimeError, match="schema boom"):
        CaptureWriter(tmp_path / "s.db")
    assert closed["n"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# PR214_RTH_DEFECT_REMEDIATION_V1 (2026-08-31) — ONE canonical stream DB path
# authority. Live RTH proof: the daemon was launched with an explicit --db against
# the PRODUCTION checkout's stream_capture.db and was healthy; the server, run
# from the DEV checkout, defaulted to STREAM_DB_DEFAULT (checkout-relative, no
# override) and was ALSO healthy -- both processes reported RUNNING while
# attached to two different files, and the API truthfully returned `no_book`
# because they never shared an actual data plane. resolve_stream_db_path is the
# RC-534 removes that override after runtime_layout learned to resolve every linked
# worktree through Git's primary worktree. Production now has no process-local path
# switch; explicit paths exist only on direct test/recovery APIs.
# ─────────────────────────────────────────────────────────────────────────────

def test_db_path_a_resolves_the_canonical_default():
    import stream_spine as ss
    assert ss.resolve_stream_db_path() == ss.canonical_stream_db_path()


def test_db_path_b_ambient_override_cannot_move_production(monkeypatch, tmp_path):
    target = (tmp_path / "override.db").resolve()
    monkeypatch.setenv("STREAM_CAPTURE_DB_PATH", str(target))
    import stream_spine as ss
    assert ss.resolve_stream_db_path() == ss.canonical_stream_db_path()


def test_db_path_c_reader_test_default_is_explicit(tmp_path):
    import stream_spine as ss
    target = tmp_path / "reader-test.db"
    assert ss.resolve_stream_db_path(target) == target.resolve()


def test_db_path_d_capture_writer_default_resolves_fresh(monkeypatch, tmp_path):
    import stream_spine as ss
    target = (tmp_path / "fresh_each_call.db").resolve()
    monkeypatch.setattr(ss, "canonical_stream_db_path", lambda: target)
    w = CaptureWriter()  # no explicit db_path -- must go through resolve_stream_db_path NOW
    assert w.db_path == target


def test_db_path_e_explicit_test_path_still_bypasses_the_resolver(tmp_path):
    explicit = tmp_path / "explicit.db"
    w = CaptureWriter(explicit)
    assert w.db_path == explicit.resolve()


def test_production_stream_daemon_exposes_no_database_path_switch(monkeypatch, tmp_path):
    import sys

    from app.market_data.schwab.streaming import capture

    monkeypatch.setattr(
        sys,
        "argv",
        ["capture.py", "--db", str(tmp_path / "fork.db")],
    )
    ran = []
    monkeypatch.setattr(capture, "run", lambda *a, **k: ran.append(a))
    assert capture.main() == 2, "any argument, a database path included, is refused"
    assert ran == []


# ─────────────────────────────────────────────────────────────────────────────
# PR214_FINAL_MERGE_BLOCKERS_V2 — Blocker 2: COVERAGE EPOCH CRASH/RESTART TRUTH.
# stream_coverage_epochs separates "NOT SUBSCRIBED" from "SUBSCRIBED BUT VENDOR
# SILENT". A clean shutdown closes epochs; a HARD death never runs that cleanup, so
# `ended_ts IS NULL` rows survive into the next lifetime and read as indefinitely
# subscribed across a window the daemon was not even running. 2A reconciles them at
# startup; 2B refuses a second concurrently-open epoch for one (symbol, service).
# ─────────────────────────────────────────────────────────────────────────────

def _epoch_rows(db):
    con = sqlite3.connect(db)
    try:
        return con.execute(
            "SELECT symbol, service, started_ts, ended_ts, reason "
            "FROM stream_coverage_epochs ORDER BY id").fetchall()
    finally:
        con.close()


