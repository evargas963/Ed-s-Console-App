"""PR214_RTH_DEFECT_REMEDIATION_FINAL_GAPS — Gap 2: the REAL failure-shape proof.

Operator's explicit requirement: reproduce the ACTUAL RTH two-checkout geometry
(daemon running from one repo checkout, server running from a DIFFERENT checkout) —
NOT two processes monkeypatched onto one shared fake status file. Every scenario below
uses two genuinely separate directory trees (`checkout_a/`, `checkout_b/`), each with
its OWN `data/stream_capture.db` file, exercised through the REAL production code paths
on both sides:

  - "daemon" side: stream_spine.CaptureWriter (the exact class tools/run_stream_capture.py
    constructs) writing real quote rows and a real write_heartbeat() call into its own
    resolved db_path.
  - "server" side: order_flow_streaming's REAL _open_capture_db_readonly /
    _stream_db_identity_status / get_streaming_diagnostics, resolving STREAM_DB_DEFAULT
    to whichever checkout's file this scenario says the server is pointed at.

The only "communication channel" between the two sides in every case is the literal
stream_capture.db file each one independently opens — there is no shared monkeypatched
intermediary standing in for a second process.
"""

from __future__ import annotations

import time as _time

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
from stream_spine import CaptureWriter, quote_msg


def _reset():
    ofs._feed_running = False
    ofs._active_ticker = None
    ofs._streaming_last_update_ts = None
    ofs._last_subscribe_completed_ts = None
    ofs._l1_cursor = {}
    ofs._book_cursor = {}
    ofls.clear_all_live_state()


def _checkout_db(tmp_path, name: str):
    """A genuinely separate directory tree, mirroring `Path(__file__).resolve().parent /
    'data' / 'stream_capture.db'` under a DIFFERENT root — the real shape of
    stream_spine.STREAM_DB_DEFAULT computed from two different repo checkouts."""
    root = tmp_path / name
    (root / "data").mkdir(parents=True, exist_ok=True)
    return root / "data" / "stream_capture.db"


def _daemon_write_quote_and_heartbeat(db, *, heartbeat_ts=None, write_heartbeat: bool = True):
    """The REAL daemon-side write path: one CaptureWriter, real quote_msg row, real
    write_heartbeat -- exactly what tools/run_stream_capture.py's write_status() now
    calls on its periodic cadence."""
    native = {"key": "SPY", "BID_PRICE": 449.98, "ASK_PRICE": 450.02, "LAST_PRICE": 450.0,
             "LAST_SIZE": 100, "TRADE_TIME_MILLIS": 1000, "TOTAL_VOLUME": 5000}
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert("quote.SPY", quote_msg(symbol="SPY", bid=449.98, ask=450.02, last=450.0,
                                    src="schwab_l1", ts_recv=_time.time(), native=native))
    w.commit()
    if write_heartbeat:
        w.write_heartbeat(ts=heartbeat_ts)
    w.close()


def _server_replay_and_diagnose(db):
    """The REAL server-side path: replay through the resolved DB, then read the real
    diagnostics dict — the same call path server.py/order_flow_streaming use in
    production."""
    con = ofs._open_capture_db_readonly(db)
    if con is not None:
        ofs._replay_new_rows(con, "SPY")
        con.close()
    return ofs.get_streaming_diagnostics()


def test_case1_same_explicit_canonical_db_identity_passes_and_healthy_allowed(tmp_path, monkeypatch):
    """Both 'processes' resolve to the SAME physical file (the STREAM_CAPTURE_DB_PATH
    cross-checkout override, or a coincidentally-identical resolution) — the daemon's
    heartbeat is visible to the server through that one shared file, and fresh replayed
    data is allowed to read healthy."""
    _reset()
    shared_db = _checkout_db(tmp_path, "checkout_shared")
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", shared_db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)

    _daemon_write_quote_and_heartbeat(shared_db)
    ofs._feed_running = True
    ofs._active_ticker = "SPY"
    try:
        diag = _server_replay_and_diagnose(shared_db)
        assert diag["stream_db_identity"]["identity_match"] is True
        assert diag["streaming_healthy"] is True, "same physical DB, fresh heartbeat + fresh replay must read healthy"
    finally:
        ofs._feed_running = False
        ofs._active_ticker = None
        ofs._streaming_last_update_ts = None


def test_case2_different_checkout_dbs_server_must_not_report_healthy(tmp_path, monkeypatch):
    """THE actual RTH failure geometry: the daemon (checkout A) writes real quote rows
    and a real heartbeat into checkout A's db. The server (checkout B) independently
    resolves a DIFFERENT physical file — its own checkout-relative default — and reads
    ONLY that file. It must never see checkout A's heartbeat (there is no shared
    channel), so it must not report healthy, no matter how fresh checkout A's data is."""
    _reset()
    checkout_a_db = _checkout_db(tmp_path, "checkout_a")
    checkout_b_db = _checkout_db(tmp_path, "checkout_b")
    assert checkout_a_db != checkout_b_db, "sanity: the two checkouts really are different files"

    # Daemon (checkout A): fully healthy, real quote row + real fresh heartbeat.
    _daemon_write_quote_and_heartbeat(checkout_a_db)

    # Server (checkout B): resolves its OWN default, distinct from the daemon's file.
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", checkout_b_db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    ofs._feed_running = True
    ofs._active_ticker = "SPY"
    ofs._last_subscribe_completed_ts = None  # no startup grace — this must fail closed unconditionally
    try:
        diag = _server_replay_and_diagnose(checkout_b_db)
        assert diag["stream_db_identity"]["server_resolved_path"] == str(checkout_b_db.resolve())
        assert diag["stream_db_identity"]["identity_match"] is not True, (
            "the server's own resolved file has never seen checkout A's heartbeat")
        assert diag["streaming_healthy"] is False, (
            "two different checkout DBs: the server must never report a connected stream plane")
    finally:
        ofs._feed_running = False
        ofs._active_ticker = None
        ofs._streaming_last_update_ts = None


def test_case3_local_fresh_rows_but_no_producer_heartbeat_must_not_report_healthy(tmp_path, monkeypatch):
    """Server resolves the SAME file the (older/incompatible) daemon writes quote rows
    to -- local replay genuinely looks fresh -- but that daemon has never written a
    producer heartbeat into it (pre-heartbeat daemon, or a non-canonical writer). Past
    the startup grace window this must not report healthy."""
    _reset()
    db = _checkout_db(tmp_path, "checkout_no_heartbeat")
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)

    _daemon_write_quote_and_heartbeat(db, write_heartbeat=False)  # rows only, no heartbeat

    ofs._feed_running = True
    ofs._active_ticker = "SPY"
    ofs._last_subscribe_completed_ts = None  # past grace
    try:
        diag = _server_replay_and_diagnose(db)
        assert diag["stream_db_identity"]["identity_match"] is None
        assert diag["streaming_healthy"] is False, (
            "fresh local rows with no producer heartbeat at all, past grace, must not report healthy")
    finally:
        ofs._feed_running = False
        ofs._active_ticker = None
        ofs._streaming_last_update_ts = None


def test_case4_stale_producer_heartbeat_must_not_report_healthy(tmp_path, monkeypatch):
    """Server resolves the SAME file as the daemon (no cross-checkout ambiguity), and a
    heartbeat row IS present — but it is old: the producer that wrote it is no longer
    demonstrably alive. Must not report healthy even with fresh local replay."""
    _reset()
    db = _checkout_db(tmp_path, "checkout_stale_heartbeat")
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)

    stale_ts = _time.time() - (ofs.STREAM_PRODUCER_HEARTBEAT_STALE_SEC + 10.0)
    _daemon_write_quote_and_heartbeat(db, heartbeat_ts=stale_ts)

    ofs._feed_running = True
    ofs._active_ticker = "SPY"
    try:
        diag = _server_replay_and_diagnose(db)
        assert diag["stream_db_identity"]["identity_match"] is False
        assert diag["streaming_healthy"] is False, (
            "a stale producer heartbeat must fail closed regardless of local replay freshness")
    finally:
        ofs._feed_running = False
        ofs._active_ticker = None
        ofs._streaming_last_update_ts = None


def test_case5_normal_single_checkout_default_remains_backward_compatible(tmp_path, monkeypatch):
    """No cross-checkout split at all -- daemon and server both resolve the ONE default
    path (the ordinary single-machine, single-checkout deployment). This must keep
    working exactly as it did before Gap 2's remediation: fresh heartbeat + fresh
    replay reads healthy."""
    _reset()
    single_db = _checkout_db(tmp_path, "checkout_normal")
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", single_db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)

    _daemon_write_quote_and_heartbeat(single_db)
    ofs._feed_running = True
    ofs._active_ticker = "SPY"
    try:
        diag = _server_replay_and_diagnose(single_db)
        assert diag["stream_db_identity"]["identity_match"] is True
        assert diag["streaming_healthy"] is True
        top = ofls.get_content_for_symbol("SPY")
        assert any(item.get("BID_PRICE") == 449.98 for item in top), (
            "sanity: this is still the real replay path, not a stub")
    finally:
        ofs._feed_running = False
        ofs._active_ticker = None
        ofs._streaming_last_update_ts = None
