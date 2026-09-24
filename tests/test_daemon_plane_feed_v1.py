"""SINGLE-STREAM-AUTHORITY root fix — the live plane is fed by the canonical capture daemon,
with zero Schwab connection of its own.

This is the seam that used to be a second `schwab.streaming.StreamClient`. Since 2026-09-23
the daemon PUSHES each message (live_push); these tests drive the REAL message constructors
the daemon publishes with (stream_spine.quote_msg / book_msg) through the REAL ingest
(order_flow_streaming._ingest_pushed). The socket end to end is
tests/test_live_push_channel_v1.py.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import time

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
from stream_spine import CaptureWriter, book_msg, quote_msg


@pytest.fixture(autouse=True)
def _isolate_stream_capture_env(monkeypatch):
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)


def _reset(tmp_path):
    ofs._feed_running = False
    ofs._active_ticker = None
    ofs._streaming_last_update_ts = None
    ofs._last_subscribe_completed_ts = None
    ofls.clear_all_live_state()
    return tmp_path / "stream_capture.db"


def _write_l1_row(db, symbol, native, ts_recv):
    """A capture DB with one row -- for the producer-identity checks below, which read the
    daemon's heartbeat from stream_capture.db (health, not a live value)."""
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert(f"quote.{symbol}", quote_msg(symbol=symbol, bid=native.get("BID_PRICE"),
                                          src="schwab_l1", ts_recv=ts_recv, native=native))
    w.commit()
    w.close()


def _push_l1(symbol, native, ts_recv):
    ofs._ingest_pushed(f"quote.{symbol}", quote_msg(
        symbol=symbol, bid=native.get("BID_PRICE"), src="schwab_l1", ts_recv=ts_recv,
        native=native))


def _push_book(symbol, content, ts_recv):
    ofs._ingest_pushed(f"book.{symbol}", book_msg(
        symbol=symbol, service="NASDAQ_BOOK", content=content, src="schwab_book",
        ts_recv=ts_recv))


def test_no_schwab_import_anywhere_in_this_module():
    """THE root fix, structurally: this module must not be ABLE to open a Schwab
    session — not merely choose not to. An `import schwab` statement here (not prose
    mentioning the word — the docstring explains the repair using it) is the violation."""
    tree = ast.parse(inspect.getsource(ofs))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] == "schwab" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "schwab"


def test_l1_message_lands_in_both_planes(tmp_path, monkeypatch):
    _reset(tmp_path)
    monkeypatch.setattr(lmp, "_by_ticker", {})
    native = {"key": "SPY", "BID_PRICE": 449.98, "ASK_PRICE": 450.02, "LAST_PRICE": 450.0,
              "LAST_SIZE": 100, "TRADE_TIME_MILLIS": 1000, "TOTAL_VOLUME": 5000}
    _push_l1("SPY", native, ts_recv=time.time())

    top = ofls.get_content_for_symbol("SPY")
    assert any(item.get("LAST_PRICE") == 450.0 for item in top)
    assert lmp.get_quote("SPY")["spot"] == 450.0


def test_book_message_lands_verbatim(tmp_path):
    _reset(tmp_path)
    content = {"key": "SPY", "BIDS": [{"BID_PRICE": 449.9, "BID_SIZE": 100}],
               "ASKS": [{"ASK_PRICE": 450.1, "ASK_SIZE": 200}], "BOOK_TIME": 555}
    _push_book("SPY", content, ts_recv=time.time())

    items = ofls.get_content_for_symbol("SPY")
    assert any(i.get("BIDS") == content["BIDS"] for i in items)


def test_each_symbol_lands_in_its_own_state_only(tmp_path, monkeypatch):
    """Every roster symbol is applied (the watchlist reads each one's streamed LAST_PRICE),
    each into its OWN state: a QQQ tick must never appear in SPY's."""
    _reset(tmp_path)
    monkeypatch.setattr(lmp, "_by_ticker", {})
    ofs._active_ticker = "SPY"
    _push_l1("QQQ", {"key": "QQQ", "LAST_PRICE": 380.0}, ts_recv=time.time())

    assert not any(i.get("LAST_PRICE") == 380.0 for i in ofls.get_content_for_symbol("SPY"))
    assert any(i.get("LAST_PRICE") == 380.0 for i in ofls.get_content_for_symbol("QQQ"))
    assert lmp.get_quote("QQQ")["spot"] == 380.0
    assert lmp.get_quote("SPY") is None
    # the ACTIVE ticker's feed-health clock is not advanced by another symbol's tick
    assert ofs._streaming_last_update_ts is None


def test_missing_capture_db_is_handled_not_fatal(tmp_path, monkeypatch):
    """Cold start: the daemon has not created stream_capture.db yet. The feed must
    tolerate this (retry next tick), never crash the server's lifespan startup."""
    db = tmp_path / "does_not_exist.db"
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    assert ofs._open_capture_db_readonly(db) is None


def test_authority_is_streaming_after_a_pushed_tick_for_the_active_ticker(tmp_path, monkeypatch):
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.setattr("stream_spine.write_active_ticker_signal", lambda *_a, **_k: None)
    ofs._feed_running = True
    ofs.set_streaming_active_ticker("SPY")
    _push_l1("SPY", {"key": "SPY", "LAST_PRICE": 450.0}, ts_recv=time.time())

    assert ofs.get_plane_authority_for_ticker("SPY") == "streaming"
    assert ofs.get_plane_authority_for_ticker("QQQ") == "not_active_ticker"


def test_set_active_ticker_writes_the_daemon_signal(tmp_path, monkeypatch):
    """This is the ONLY channel by which this module influences the daemon's
    subscriptions — proves the write actually happens, not just that no error is raised."""
    calls = []
    monkeypatch.setattr("app.options.order_flow.streaming.write_active_ticker_signal",
                        lambda t: calls.append(t))
    ofs._active_ticker = None
    ofs.set_streaming_active_ticker("spy")
    assert calls == ["SPY"]


def test_feed_loop_starts_and_stops_cleanly(tmp_path, monkeypatch):
    """start_order_flow_stream/stop_order_flow_stream must work with NO Schwab client
    (None) — the whole point of the repair is that this feed needs no account/session."""
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.setattr("stream_spine.write_active_ticker_signal", lambda *_a, **_k: None)

    async def go():
        ok = ofs.start_order_flow_stream(None, None, "SPY")
        assert ok is True
        assert ofs.is_order_flow_stream_running() is True
        await asyncio.sleep(0.05)
        ofs.stop_order_flow_stream(join_timeout=1.0)
        assert ofs.is_order_flow_stream_running() is False
    asyncio.run(go())


# ─────────────────────────────────────────────────────────────────────────────
# PR214_RTH_DEFECT_REMEDIATION_FINAL_GAPS — Gap 2: producer identity now lives INSIDE
# stream_capture.db itself (stream_producer_heartbeat), not a second checkout-relative
# status file. These tests drive the REAL CaptureWriter.write_heartbeat and the REAL
# _stream_db_identity_status/_open_capture_db_readonly path — same-process, single-DB
# scenarios (matched, stale, absent heartbeat). The MANDATORY real two-checkout-root
# proof (two genuinely different physical DB files, one server resolving each) lives in
# tests/test_stream_producer_identity_two_checkout_v1.py — this file's cases below
# would NOT catch the actual RTH failure geometry on their own, by design; that is the
# other file's job.
# ─────────────────────────────────────────────────────────────────────────────

def test_producer_identity_a_matched_heartbeat_in_same_db_allows_healthy(tmp_path, monkeypatch):
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.write_heartbeat()
    w.close()
    ofs._feed_running = True
    ofs._active_ticker = "SPY"
    ofs._streaming_last_update_ts = __import__("time").time()
    try:
        diag = ofs.get_streaming_diagnostics()
        assert diag["stream_db_identity"]["identity_match"] is True
        assert diag["stream_db_identity"]["server_resolved_path"] == str(db.resolve())
        assert diag["streaming_healthy"] is True
    finally:
        ofs._feed_running = False
        ofs._active_ticker = None
        ofs._streaming_last_update_ts = None


def test_producer_identity_b_stale_heartbeat_fails_closed(tmp_path, monkeypatch):
    """A heartbeat row EXISTS in the exact file the server reads (same DB — no
    cross-checkout ambiguity at all) but is old: a producer once wrote here and has
    since gone dark. Must surface identity_match=False and force
    streaming_healthy=False even though local replay looks perfectly fresh."""
    import time as _time
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.write_heartbeat(ts=_time.time() - (ofs.STREAM_PRODUCER_HEARTBEAT_STALE_SEC + 5.0))
    w.close()
    ofs._feed_running = True
    ofs._active_ticker = "SPY"
    ofs._streaming_last_update_ts = _time.time()
    try:
        diag = ofs.get_streaming_diagnostics()
        assert diag["stream_db_identity"]["identity_match"] is False
        assert diag["streaming_healthy"] is False, (
            "a confirmed-stale producer heartbeat must fail closed regardless of local replay freshness")
    finally:
        ofs._feed_running = False
        ofs._active_ticker = None
        ofs._streaming_last_update_ts = None


def test_producer_identity_c_no_heartbeat_row_is_unknown_and_tolerated_within_grace(tmp_path, monkeypatch):
    """A DB exists (even with real quote rows already in it, from a pre-heartbeat
    daemon or a first-tick race) but NO heartbeat row has ever been written. This is
    the EXISTING 'unknown' case, not a confirmed mismatch — during the startup grace
    window it must not itself force streaming_healthy=False."""
    import time as _time
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    _write_l1_row(db, "SPY", {"key": "SPY", "LAST_PRICE": 450.0}, ts_recv=1.0)  # no write_heartbeat call
    ofs._feed_running = True
    ofs._active_ticker = "SPY"
    ofs._streaming_last_update_ts = _time.time()
    ofs._last_subscribe_completed_ts = _time.time()  # within GRACE_AFTER_SUBSCRIBE_SEC
    try:
        diag = ofs.get_streaming_diagnostics()
        assert diag["stream_db_identity"]["identity_match"] is None
        assert diag["streaming_healthy"] is True, "brief cold-start unknown must not itself fail closed"
    finally:
        ofs._feed_running = False
        ofs._active_ticker = None
        ofs._streaming_last_update_ts = None
        ofs._last_subscribe_completed_ts = None


def test_producer_identity_d_no_heartbeat_row_past_grace_fails_closed(tmp_path, monkeypatch):
    """Gap 2, Case 3 (operator requirement, verbatim): 'server sees local fresh-looking
    rows but no current canonical producer heartbeat -> MUST NOT report healthy.' Once
    the startup grace window has elapsed, an indefinite 'no heartbeat' can no longer
    coexist with a positive healthy claim, even though local replay is fresh."""
    import time as _time
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    _write_l1_row(db, "SPY", {"key": "SPY", "LAST_PRICE": 450.0}, ts_recv=1.0)  # no write_heartbeat call
    ofs._feed_running = True
    ofs._active_ticker = "SPY"
    ofs._streaming_last_update_ts = _time.time()
    ofs._last_subscribe_completed_ts = None  # no grace in effect
    try:
        diag = ofs.get_streaming_diagnostics()
        assert diag["stream_db_identity"]["identity_match"] is None
        assert diag["streaming_healthy"] is False, (
            "no producer heartbeat past the startup grace window must fail closed even with fresh local rows")
    finally:
        ofs._feed_running = False
        ofs._active_ticker = None
        ofs._streaming_last_update_ts = None


def test_producer_identity_e_missing_db_is_unknown_not_a_false_mismatch(tmp_path, monkeypatch):
    """Cold start: the daemon has not created stream_capture.db yet at all. Must be the
    EXISTING 'unknown' case, distinct from a confirmed mismatch."""
    db = tmp_path / "does_not_exist.db"
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    diag = ofs.get_streaming_diagnostics()
    assert diag["stream_db_identity"]["identity_match"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 2026-09-16, audit finding #6 (bounded-vendor-call reconciliation): the producer's
# rejected-contract map rides the SAME heartbeat row as claimed_coverage_json. These
# prove the REAL CaptureWriter.write_heartbeat / read_producer_rejected_option_contracts
# round trip: sticky-unless-explicit (a frequent claimed_coverage-only publish must not
# wipe a standing rejection) and the same staleness fail-closed rule as coverage.
# ─────────────────────────────────────────────────────────────────────────────

def test_rejected_contracts_round_trip_through_the_real_heartbeat_row(tmp_path, monkeypatch):
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.write_heartbeat(rejected_contracts={"QQQ   260820C00450000": "RuntimeError: refused"})
    w.close()
    got = ofs.read_producer_rejected_option_contracts()
    assert got == {"QQQ   260820C00450000": "RuntimeError: refused"}


def test_rejected_contracts_are_sticky_across_a_claimed_coverage_only_publish(tmp_path, monkeypatch):
    """A coverage-claim publish (open/close/retry) fires far more often than the
    reconciler's own rejection update and never passes rejected_contracts — it must NOT
    wipe a standing rejection back to {} in between (see CaptureWriter's own
    _last_rejected_contracts docstring)."""
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.write_heartbeat(rejected_contracts={"BAD": "vendor refused"})
    w.write_heartbeat(claimed_coverage={"LEVELONE_OPTIONS": [1]})   # no rejected_contracts kwarg
    w.close()
    assert ofs.read_producer_rejected_option_contracts() == {"BAD": "vendor refused"}


def test_rejected_contracts_explicit_empty_dict_clears_it(tmp_path, monkeypatch):
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.write_heartbeat(rejected_contracts={"BAD": "vendor refused"})
    w.write_heartbeat(rejected_contracts={})   # explicit clear
    w.close()
    assert ofs.read_producer_rejected_option_contracts() == {}


def test_rejected_contracts_go_unknown_past_the_staleness_window(tmp_path, monkeypatch):
    import time as _time
    db = _reset(tmp_path)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.write_heartbeat(ts=_time.time() - (ofs.STREAM_PRODUCER_HEARTBEAT_STALE_SEC + 5.0),
                      rejected_contracts={"BAD": "vendor refused"})
    w.close()
    assert ofs.read_producer_rejected_option_contracts() == {}, (
        "a stale producer heartbeat must report unknown (empty), never a standing rejection")
