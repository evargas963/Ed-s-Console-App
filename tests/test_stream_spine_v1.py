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
    CoverageWriteError,
    HealthRegistry,
    MessageBus,
    bar_msg,
    book_msg,
    options_quote_msg,
    print_msg,
    quote_msg,
    read_active_option_contract_signal,
    read_active_ticker_signal,
    write_active_option_contract_signal,
    write_active_ticker_signal,
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


def test_prints_never_coalesce_and_overflow_counts_loudly():
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("print.", policy=COUNT_DROPS, maxsize=2)
        for i in range(5):
            bus.publish("print.SPY", {"size": i})
        # first two kept in order, three counted dropped — never silently merged
        t0, m0 = await sub.get()
        t1, m1 = await sub.get()
        assert (m0["size"], m1["size"]) == (0, 1)
        assert sub.dropped == 3
        assert bus.drop_counts() == {"print.": 3}
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
    w.insert("print.SPY", print_msg(symbol="SPY", price=1.5, size=100, exchange="IEX",
                                    conditions="@", trade_ts_ms=7, src="t", ts_recv=1.1))
    w.insert("bar1m.SPY", bar_msg(symbol="SPY", bar_start_ms=0, open=1, high=2, low=0.5,
                                  close=1.5, volume=999, src="t", ts_recv=2.0))
    w.commit()
    w.close()
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM stream_quotes_raw").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM stream_prints_raw").fetchone()[0] == 1
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
    w.commit()
    w.close()
    con = sqlite3.connect(db)
    row = con.execute("SELECT native_json FROM stream_quotes_raw").fetchone()
    assert json.loads(row[0]) == native


def test_quote_without_native_stores_null_not_a_fabricated_value(tmp_path):
    """Existing quote producers (Alpaca, tests) pass no native dict — must stay NULL,
    never an empty-dict placeholder that would misrepresent 'no data' as 'measured empty'."""
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert("quote.SPY", quote_msg(symbol="SPY", bid=1.0, src="alpaca_iex", ts_recv=1.0))
    w.commit()
    w.close()
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
    w.commit()
    w.close()
    con = sqlite3.connect(db)
    assert con.execute("SELECT native_json FROM stream_quotes_raw").fetchone()[0] is not None


def test_book_content_stored_verbatim_never_flattened(tmp_path):
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    content = {"key": "SPY", "BIDS": [{"BID_PRICE": 1.0}], "ASKS": [{"ASK_PRICE": 1.1}],
              "BOOK_TIME": 999}
    w.insert("book.SPY", book_msg(symbol="SPY", service="NASDAQ_BOOK", content=content,
                                  src="schwab_book", ts_recv=1.0))
    w.commit()
    w.close()
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
    w.commit()
    w.close()
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
    w.commit()
    w.close()
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT symbol, native_json, src FROM stream_options_quotes_raw").fetchone()
    assert row[0] == "SPY   260820C00767000" and row[2] == "schwab_options_l1"
    assert json.loads(row[1]) == _REAL_LEVELONE_OPTIONS_CONTENT


def test_options_quote_with_no_content_is_not_inserted(tmp_path):
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert("optquote.SPY", {"ts_recv": 1.0, "symbol": "SPY", "content": None, "src": "t"})
    w.commit()
    w.close()
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
    w.commit()
    w.close()
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT symbol, service, native_json FROM stream_book_raw").fetchone()
    assert row[1] == "OPTIONS_BOOK"
    assert json.loads(row[2]) == _REAL_OPTIONS_BOOK_CONTENT


def test_coverage_epoch_open_then_close_records_both_timestamps(tmp_path):
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    epoch_id = w.open_coverage_epoch("SPY   260820C00767000", "LEVELONE_OPTIONS",
                                     reason="active_contract_set", ts=1.0)
    w.close_coverage_epoch(epoch_id, reason="active_contract_switched", ts=5.0)
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT symbol, service, started_ts, ended_ts, reason "
        "FROM stream_coverage_epochs WHERE id=?", (epoch_id,)).fetchone()
    w.close()
    assert row == ("SPY   260820C00767000", "LEVELONE_OPTIONS", 1.0, 5.0,
                   "active_contract_switched")


def test_coverage_epoch_open_leaves_ended_ts_null(tmp_path):
    """A gap after an OPEN epoch with no close is interpretable as 'still subscribed,
    vendor silent' — never confused with 'not subscribed' (NULL ended_ts is the marker)."""
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    epoch_id = w.open_coverage_epoch("SPY", "OPTIONS_BOOK", reason="active_contract_set", ts=1.0)
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT ended_ts FROM stream_coverage_epochs WHERE id=?", (epoch_id,)).fetchone()
    w.close()
    assert row[0] is None


def test_coverage_epoch_close_is_idempotent_never_overwrites_first_close(tmp_path):
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    epoch_id = w.open_coverage_epoch("SPY", "LEVELONE_OPTIONS", reason="x", ts=1.0)
    w.close_coverage_epoch(epoch_id, reason="first_close", ts=5.0)
    w.close_coverage_epoch(epoch_id, reason="second_close_must_not_land", ts=99.0)
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT ended_ts, reason FROM stream_coverage_epochs WHERE id=?",
        (epoch_id,)).fetchone()
    w.close()
    assert row == (5.0, "first_close")


def test_coverage_epoch_write_failure_raises_not_swallowed(tmp_path):
    """CoverageWriteError must be RAISED so a caller advancing in-memory subscription
    state can gate that advance on the durable write actually landing — a silent failure
    here would let memory claim coverage the epoch table never recorded."""
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.close()   # connection is now closed; any further write must fail
    with pytest.raises(CoverageWriteError):
        w.open_coverage_epoch("SPY", "LEVELONE_OPTIONS", reason="x")


def test_active_option_contract_signal_round_trips(tmp_path):
    p = tmp_path / "stream_active_option_contract.json"
    write_active_option_contract_signal("spy   260820c00767000", path=p)
    assert read_active_option_contract_signal(path=p) == "SPY   260820C00767000"


def test_active_option_contract_signal_absent_is_none(tmp_path):
    p = tmp_path / "does_not_exist.json"
    assert read_active_option_contract_signal(path=p) is None


def test_active_ticker_signal_round_trips(tmp_path):
    p = tmp_path / "stream_active_ticker.json"
    write_active_ticker_signal("spy", path=p)
    assert read_active_ticker_signal(path=p) == "SPY"


def test_active_ticker_signal_absent_is_none_not_a_guess(tmp_path):
    """A missing/corrupt signal must mean 'no active ticker', never a stale-cache guess
    or an exception that could crash the daemon's poll loop."""
    p = tmp_path / "does_not_exist.json"
    assert read_active_ticker_signal(path=p) is None
    p.write_text("{not json", encoding="utf-8")
    assert read_active_ticker_signal(path=p) is None


def test_active_ticker_signal_write_is_atomic_replace(tmp_path):
    """The daemon polls this file on its own schedule; a torn write must never be
    observable — write-temp-then-replace, not write-in-place."""
    p = tmp_path / "stream_active_ticker.json"
    write_active_ticker_signal("SPY", path=p)
    assert not p.with_suffix(p.suffix + ".tmp").exists()
    write_active_ticker_signal("QQQ", path=p)
    assert read_active_ticker_signal(path=p) == "QQQ"


def test_health_states_progress_running_degraded_stale():
    h = HealthRegistry()
    assert h.state("schwab_l1") == "DOWN"          # never seen != quiet market
    h.beat("schwab_l1", ts=1000.0)
    assert h.state("schwab_l1", now=1002.0) == "RUNNING"
    assert h.state("schwab_l1", now=1010.0) == "DEGRADED"
    assert h.state("schwab_l1", now=1031.0) == "STALE"
    assert h.any_stale(now=1031.0) is True         # the CR-07 suppression hook
    rep = h.report(now=1010.0)
    assert rep["schwab_l1"]["state"] == "DEGRADED" and rep["schwab_l1"]["age_sec"] == 10.0


def test_writer_drains_full_queue_on_stop(tmp_path):
    """Cursor review HIGH: stop must not vaporize buffered rows."""
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("", policy=COUNT_DROPS, maxsize=8192)
        w = CaptureWriter(tmp_path / "s.db", batch_rows=10_000, batch_sec=60.0)
        for i in range(50):
            bus.publish("print.SPY", print_msg(symbol="SPY", price=1.0, size=i, src="t"))
        stop = asyncio.Event()
        stop.set()                      # stop BEFORE the writer ever runs
        await w.run(sub, stop=stop)
        w.close()
        con = sqlite3.connect(tmp_path / "s.db")
        n = con.execute("SELECT COUNT(*) FROM stream_prints_raw").fetchone()[0]
        assert n == 50, f"drain lost rows: {n}/50"
        assert w.insert_errors == 0
    asyncio.run(go())


def test_insert_failure_is_counted_never_kills_writer(tmp_path):
    async def go():
        bus = MessageBus()
        sub = bus.subscribe("", policy=COUNT_DROPS)
        w = CaptureWriter(tmp_path / "s.db", batch_rows=10_000, batch_sec=60.0)
        bus.publish("print.SPY", object())      # not a dict -> insert raises inside
        bus.publish("print.SPY", print_msg(symbol="SPY", price=2.0, size=1, src="t"))
        stop = asyncio.Event(); stop.set()
        await w.run(sub, stop=stop)
        w.close()
        assert w.insert_errors == 1
        con = sqlite3.connect(tmp_path / "s.db")
        assert con.execute("SELECT COUNT(*) FROM stream_prints_raw").fetchone()[0] == 1
    asyncio.run(go())


def test_rc6_guard_survives_path_tricks():
    """Cursor review MEDIUM: `data/x/../ed_console.db` must not slip past the guard."""
    with pytest.raises(ValueError):
        CaptureWriter("data/nosuchdir/../ed_console.db")


def test_writer_close_is_idempotent(tmp_path):
    w = CaptureWriter(tmp_path / "s.db")
    w.close()
    w.close()  # second call must not raise
    assert w._closed is True


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
# fix: an explicit STREAM_CAPTURE_DB_PATH env override, checked before any
# checkout-relative default, so daemon and server can be pointed at the identical
# absolute file regardless of which checkout each process's code lives in.
# ─────────────────────────────────────────────────────────────────────────────

def test_db_path_a_no_override_resolves_the_existing_canonical_default(monkeypatch):
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    import stream_spine as ss
    assert ss.resolve_stream_db_path() == ss.STREAM_DB_DEFAULT.resolve()


def test_db_path_b_absolute_env_override_wins(monkeypatch, tmp_path):
    target = (tmp_path / "override.db").resolve()
    monkeypatch.setenv("STREAM_CAPTURE_DB_PATH", str(target))
    import stream_spine as ss
    assert ss.resolve_stream_db_path() == target
    # And it wins even over an explicit caller-supplied default/fallback:
    assert ss.resolve_stream_db_path(tmp_path / "not_this_one.db") == target


def test_db_path_c_relative_override_is_normalized_to_one_absolute_identity(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STREAM_CAPTURE_DB_PATH", "relative_stream.db")
    import stream_spine as ss
    resolved = ss.resolve_stream_db_path()
    assert resolved.is_absolute()
    assert resolved == (tmp_path / "relative_stream.db").resolve()


def test_db_path_d_two_different_checkout_roots_same_override_resolve_identical(monkeypatch, tmp_path):
    """Directly reproduces the RTH failure mode's fix: 'daemon' and 'server' sides
    simulated with DIFFERENT checkout-relative defaults (as if each lived under a
    different repo root), but the SAME explicit override — both must resolve to
    the identical absolute path."""
    target = (tmp_path / "shared_canonical.db").resolve()
    monkeypatch.setenv("STREAM_CAPTURE_DB_PATH", str(target))
    import stream_spine as ss
    daemon_side_default = tmp_path / "checkout_a" / "data" / "stream_capture.db"
    server_side_default = tmp_path / "checkout_b" / "data" / "stream_capture.db"
    assert ss.resolve_stream_db_path(daemon_side_default) == target
    assert ss.resolve_stream_db_path(server_side_default) == target


def test_db_path_capture_writer_default_argument_is_not_frozen_at_import_time(monkeypatch, tmp_path):
    """CaptureWriter(db_path: ... = STREAM_DB_DEFAULT) used to bind the default value
    ONCE at class-definition (import) time -- an env override set AFTER import could
    never be seen. `db_path=None` (the new default) resolves fresh on every call."""
    target = (tmp_path / "fresh_each_call.db").resolve()
    monkeypatch.setenv("STREAM_CAPTURE_DB_PATH", str(target))
    w = CaptureWriter()  # no explicit db_path -- must go through resolve_stream_db_path NOW
    try:
        assert w.db_path == target
    finally:
        w.close()


def test_db_path_e_explicit_caller_path_still_bypasses_the_resolver(tmp_path, monkeypatch):
    """An explicit db_path (tests, or the daemon's --db flag) is a deliberate escape
    hatch and must NOT be silently overridden by an unrelated env var -- only the
    "no explicit path" case goes through resolve_stream_db_path."""
    monkeypatch.setenv("STREAM_CAPTURE_DB_PATH", str((tmp_path / "should_not_be_used.db").resolve()))
    explicit = tmp_path / "explicit.db"
    w = CaptureWriter(explicit)
    try:
        assert w.db_path == explicit.resolve()
    finally:
        w.close()


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


def test_blocker2_crash_restart_orphan_epochs_reconciled_then_exactly_one_open(tmp_path):
    """REQUIRED 2C attack, end to end.

    Lifetime 1 opens A/LEVELONE_OPTIONS and A/OPTIONS_BOOK then dies HARD -- the writer
    handle is dropped WITHOUT any close_coverage_epoch call, exactly as SIGKILL would.
    Lifetime 2 runs startup reconciliation, then subscribes. Proves the prior rows are
    closed with the orphan reason and that exactly ONE epoch is open per current
    (symbol, service)."""
    db = tmp_path / "stream_capture.db"
    A = "SPY   260820C00767000"

    # ── daemon lifetime 1: open both services, then hard death (NO clean close) ──
    w1 = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w1.open_coverage_epoch(A, "LEVELONE_OPTIONS", reason="active_contract_set", ts=100.0)
    w1.open_coverage_epoch(A, "OPTIONS_BOOK", reason="active_contract_set", ts=100.0)
    w1.close()   # closes the sqlite handle only — the EPOCHS are deliberately left open
    before = _epoch_rows(db)
    assert [r[3] for r in before] == [None, None], (
        "precondition: a hard death leaves both epochs open (ended_ts NULL)")

    # ── daemon lifetime 2: startup reconciliation ──
    w2 = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        closed = w2.reconcile_orphan_coverage_epochs(ts=500.0)
        assert closed == 2, f"both prior-lifetime epochs must be reconciled, closed={closed}"
        rows = _epoch_rows(db)
        assert all(r[3] == 500.0 for r in rows), (
            "orphans close at the RECONCILIATION timestamp -- an upper bound ('known "
            "closed no later than this startup'), never a fabricated crash time")
        assert all(r[4] == CaptureWriter.COVERAGE_ORPHAN_REASON for r in rows), (
            "the reason column must mark these reconciled, not measured, closes")
        assert all(r[2] == 100.0 for r in rows), "history is closed, never deleted or rewritten"

        # ── subscribe the new contract for the SAME (symbol, service) pairs ──
        w2.open_coverage_epoch(A, "LEVELONE_OPTIONS", reason="active_contract_set", ts=501.0)
        w2.open_coverage_epoch(A, "OPTIONS_BOOK", reason="active_contract_set", ts=501.0)
        con = sqlite3.connect(db)
        try:
            per_pair = con.execute(
                "SELECT symbol, service, COUNT(*) FROM stream_coverage_epochs "
                "WHERE ended_ts IS NULL GROUP BY symbol, service ORDER BY service").fetchall()
        finally:
            con.close()
        assert per_pair == [(A, "LEVELONE_OPTIONS", 1), (A, "OPTIONS_BOOK", 1)], (
            f"exactly ONE open epoch per (symbol, service) required; got {per_pair}")
    finally:
        w2.close()


def test_blocker2_reconciliation_with_no_orphans_is_harmless_and_idempotent(tmp_path):
    """Startup with nothing open closes 0 rows, disturbs no closed history, and running
    it twice changes nothing."""
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        eid = w.open_coverage_epoch("SPY", "LEVELONE_OPTIONS", reason="x", ts=1.0)
        w.close_coverage_epoch(eid, reason="shutdown", ts=2.0)
        before = _epoch_rows(db)
        assert w.reconcile_orphan_coverage_epochs(ts=900.0) == 0
        assert w.reconcile_orphan_coverage_epochs(ts=901.0) == 0
        assert _epoch_rows(db) == before, (
            "a clean prior shutdown must be left byte-identical by reconciliation")
    finally:
        w.close()


def test_blocker2_clean_shutdown_still_closes_normally_after_the_guard(tmp_path):
    """The 2B guard must not disturb the normal open -> close -> reopen cycle."""
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        e1 = w.open_coverage_epoch("SPY", "OPTIONS_BOOK", reason="active_contract_set", ts=1.0)
        w.close_coverage_epoch(e1, reason="shutdown", ts=2.0)
        e2 = w.open_coverage_epoch("SPY", "OPTIONS_BOOK", reason="active_contract_set", ts=3.0)
        assert e2 != e1
        assert [r[3] for r in _epoch_rows(db)] == [2.0, None]
    finally:
        w.close()


def test_blocker2_forced_duplicate_open_fails_loudly_for_the_right_reason(tmp_path):
    """REQUIRED: a forced duplicate-open must fail, and fail for the CORRECT reason --
    refusing contradictory history, not dying on an incidental error."""
    db = tmp_path / "stream_capture.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        w.open_coverage_epoch("SPY", "LEVELONE_OPTIONS", reason="active_contract_set", ts=1.0)
        with pytest.raises(CoverageWriteError) as exc:
            w.open_coverage_epoch("SPY", "LEVELONE_OPTIONS", reason="active_contract_set", ts=2.0)
        msg = str(exc.value)
        assert "refusing to open a second epoch" in msg and "still open" in msg
        con = sqlite3.connect(db)
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM stream_coverage_epochs WHERE ended_ts IS NULL "
                "AND symbol='SPY' AND service='LEVELONE_OPTIONS'").fetchone()[0]
        finally:
            con.close()
        assert n == 1, "the refused open must not have written a contradictory second row"
        # A DIFFERENT service for the same symbol is a distinct pair and stays allowed.
        w.open_coverage_epoch("SPY", "OPTIONS_BOOK", reason="active_contract_set", ts=3.0)
    finally:
        w.close()

def test_default_signal_paths_sit_beside_resolved_stream_db(tmp_path, monkeypatch):
    """Signal files resolve next to the stream DB, not the checkout.

    # universal-scope-ok: path-identity test; no ticker product claim.
    """
    import stream_spine as spine

    db = tmp_path / "stream_capture.db"
    monkeypatch.setenv("STREAM_CAPTURE_DB_PATH", str(db))
    assert spine.default_active_option_contract_signal_path() == db.with_name(
        "stream_active_option_contract.json")
    assert spine.default_active_ticker_signal_path() == db.with_name(
        "stream_active_ticker.json")
    spine.write_active_option_contract_signal("SPY   260904C00772000")
    assert spine.read_active_option_contract_signal() == "SPY   260904C00772000"
    assert (tmp_path / "stream_active_option_contract.json").is_file()

