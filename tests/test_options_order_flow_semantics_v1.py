"""OPTIONS_ORDER_FLOW_V1 — order-flow/options semantic products.

app.options.order_flow.state.push_level_one/push_book are symbol-generic and read Schwab's
native field names, not an equity-specific schema — proven here by feeding them the REAL
captured LEVELONE_OPTIONS/OPTIONS_BOOK shapes (reports/of_capability_probe/
options_20260820T1354Z/) and reading the result back through the SAME producer equities
use (order_flow_engine.compute_book_microstructure), never a second book-imbalance
computation for options.
"""

from __future__ import annotations

import asyncio
import threading
import time

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
from stream_spine import CaptureWriter, book_msg, options_quote_msg

_SPY_CONTRACT = "SPY   260820C00767000"

#: Real content shapes from the live-proven probe — not invented.
_REAL_LEVELONE_OPTIONS_CONTENT = {
    "key": _SPY_CONTRACT, "assetMainType": "OPTION", "BID_PRICE": 1.26, "ASK_PRICE": 1.28,
    "LAST_PRICE": 1.27, "LAST_SIZE": 2, "BID_SIZE": 458, "ASK_SIZE": 209,
    "TOTAL_VOLUME": 44994, "TRADE_TIME_MILLIS": 1787234092319, "OPEN_INTEREST": 2097,
    "DELTA": 0.45644607, "CONTRACT_TYPE": "C", "UNDERLYING": "SPY",
}
_REAL_OPTIONS_BOOK_CONTENT = {
    "key": _SPY_CONTRACT, "BOOK_TIME": 1787234093764,
    "BIDS": [{"BID_PRICE": 1.28, "TOTAL_VOLUME": 1746, "NUM_BIDS": 1,
             "BIDS": [{"EXCHANGE": "NYSE", "BID_VOLUME": 262, "SEQUENCE": 1}]}],
    "ASKS": [{"ASK_PRICE": 1.3, "TOTAL_VOLUME": 1533, "NUM_ASKS": 1,
             "ASKS": [{"EXCHANGE": "EDGX", "ASK_VOLUME": 346, "SEQUENCE": 2}]}],
}


def _reset(tmp_path, monkeypatch):
    ofs._feed_running = False
    ofs._active_option_contract = None
    ofs._option_l1_cursor = {}
    ofs._option_book_cursor = {}
    ofls.clear_all_live_state()
    db = tmp_path / "stream_capture.db"
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    monkeypatch.setattr(
        "app.options.contracts.default.default_option_contract",
        lambda *a, **k: None,
    )
    return db


def _write_option_l1_row(db, symbol, content, ts_recv):
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert(f"optquote.{symbol}", options_quote_msg(
        symbol=symbol, content=content, src="schwab_options_l1", ts_recv=ts_recv))
    w.commit()
    w.close()


def _write_option_book_row(db, symbol, content, ts_recv):
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert(f"book.{symbol}", book_msg(
        symbol=symbol, service="OPTIONS_BOOK", content=content,
        src="schwab_options_book", ts_recv=ts_recv))
    w.commit()
    w.close()


def test_option_contract_l1_replays_into_order_flow_state(tmp_path, monkeypatch):
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, ts_recv=1.0)

    con = ofs._open_capture_db_readonly(db)
    ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()

    items = ofls.get_content_for_symbol(_SPY_CONTRACT)
    assert any(i.get("LAST_PRICE") == 1.27 for i in items)


def test_option_contract_book_replays_verbatim(tmp_path, monkeypatch):
    db = _reset(tmp_path, monkeypatch)
    _write_option_book_row(db, _SPY_CONTRACT, _REAL_OPTIONS_BOOK_CONTENT, ts_recv=1.0)

    con = ofs._open_capture_db_readonly(db)
    ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()

    items = ofls.get_content_for_symbol(_SPY_CONTRACT)
    assert any(i.get("BIDS") == _REAL_OPTIONS_BOOK_CONTENT["BIDS"] for i in items)


def test_option_contract_replay_reads_only_options_book_service(tmp_path, monkeypatch):
    """A NASDAQ_BOOK/NYSE_BOOK row for the SAME symbol string (should never happen for an
    OSI contract symbol, but the query must not accidentally cross services) must not
    leak into the option contract's replayed content."""
    db = _reset(tmp_path, monkeypatch)
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert(f"book.{_SPY_CONTRACT}", book_msg(
        symbol=_SPY_CONTRACT, service="NASDAQ_BOOK",
        content={"key": _SPY_CONTRACT, "BIDS": [{"WRONG_SERVICE": True}], "ASKS": []},
        src="t", ts_recv=1.0))
    w.commit()
    w.close()

    con = ofs._open_capture_db_readonly(db)
    ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()

    items = ofls.get_content_for_symbol(_SPY_CONTRACT)
    assert not any(i.get("BIDS") == [{"WRONG_SERVICE": True}] for i in items)


def test_get_option_contract_book_microstructure_reuses_the_one_producer(tmp_path, monkeypatch):
    """The decisive proof: this is compute_book_microstructure itself (the SAME function
    the equity /api/order-flow/microstructure route calls), not a parallel computation."""
    db = _reset(tmp_path, monkeypatch)
    _write_option_book_row(db, _SPY_CONTRACT, _REAL_OPTIONS_BOOK_CONTENT, ts_recv=1.0)
    con = ofs._open_capture_db_readonly(db)
    ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()

    result = ofs.get_option_contract_book_microstructure(_SPY_CONTRACT)
    assert result["depth"]["1"]["imbalance"] is not None


def test_get_option_contract_book_microstructure_fails_closed_with_no_book():
    """No replayed content yet -> the producer's own fail-closed contract: status
    'no_book', never a fabricated imbalance."""
    ofls.clear_all_live_state()
    result = ofs.get_option_contract_book_microstructure("QQQ   260820C00450000")
    assert result.get("status") == "no_book" or result["depth"]["1"]["imbalance"] is None


def test_set_active_option_contract_writes_signal_and_clears_old_symbol(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("app.options.order_flow.streaming.write_active_option_contract_signal",
                        lambda s: calls.append(s))
    cleared = []
    monkeypatch.setattr("app.options.order_flow.streaming.clear_symbol", lambda s: cleared.append(s))
    ofs._active_option_contract = "OLD   260101C00100000"

    ok = ofs.set_active_option_contract(_SPY_CONTRACT)
    assert ok is True
    assert calls == [_SPY_CONTRACT]
    assert cleared == ["OLD   260101C00100000"]
    assert ofs._active_option_contract == _SPY_CONTRACT


def test_feed_loop_replays_both_ticker_and_option_contract_independently(tmp_path, monkeypatch):
    """The equity active ticker and the option contract are independent slots — both must
    hydrate in the SAME poll tick without interfering with each other."""
    db = _reset(tmp_path, monkeypatch)
    ofs._active_ticker = None
    ofs._l1_cursor = {}
    ofs._book_cursor = {}
    monkeypatch.setattr("app.options.order_flow.streaming.write_active_ticker_signal", lambda *_a, **_k: None)
    monkeypatch.setattr("app.options.order_flow.streaming.write_active_option_contract_signal", lambda *_a, **_k: None)

    from stream_spine import quote_msg
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert("quote.SPY", quote_msg(symbol="SPY", bid=450.0, src="schwab_l1", ts_recv=1.0,
                                    native={"key": "SPY", "LAST_PRICE": 450.0}))
    w.commit()
    w.close()
    _write_option_l1_row(db, _SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, ts_recv=1.0)

    async def go():
        ofs._feed_running = True
        ofs.set_streaming_active_ticker("SPY")
        ofs.set_active_option_contract(_SPY_CONTRACT)
        task = asyncio.get_event_loop().create_task(ofs._feed_loop())
        # TEST_SYSTEM_REHAB_V2: was a flat `await asyncio.sleep(0.3)`. _feed_loop's
        # first tick needs three SEQUENTIAL executor round-trips (open db, replay
        # ticker, replay contract) before either slot is populated; under real system
        # load those round-trips can individually exceed 300ms, so this failed
        # (assert False on the option-contract slot) under measured 100% CPU
        # contention while passing 3/3 in isolation -- a load-sensitive fixed sleep,
        # not a production defect. Poll for the actual condition instead: exits in
        # ~one tick under normal load, tolerates real contention up to 10s, and still
        # fails for real if the production code genuinely never populates a slot.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if (any(i.get("LAST_PRICE") == 450.0 for i in ofls.get_content_for_symbol("SPY"))
                    and any(i.get("LAST_PRICE") == 1.27
                            for i in ofls.get_content_for_symbol(_SPY_CONTRACT))):
                break
            await asyncio.sleep(0.05)
        ofs._feed_running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    asyncio.run(go())

    assert any(i.get("LAST_PRICE") == 450.0 for i in ofls.get_content_for_symbol("SPY"))
    assert any(i.get("LAST_PRICE") == 1.27 for i in ofls.get_content_for_symbol(_SPY_CONTRACT))


def test_feed_loop_confines_every_db_touch_to_one_thread(tmp_path, monkeypatch):
    """ROOT-CAUSE regression: sqlite3.Connection is thread-affine (check_same_thread=True).
    _feed_loop used to route open+replay through the DEFAULT asyncio.to_thread executor,
    which has multiple workers and no affinity guarantee between calls — reproduced as
    "SQLite objects created in a thread can only be used in that same thread" under real
    cross-call thread reuse (not synthetic). Proves the fix directly: every DB-touching
    call across several poll ticks reports the SAME thread ident, not merely that no
    exception happened to surface this run."""
    db = _reset(tmp_path, monkeypatch)
    ofs._active_ticker = None
    ofs._l1_cursor = {}
    ofs._book_cursor = {}
    monkeypatch.setattr("app.options.order_flow.streaming.write_active_ticker_signal", lambda *_a, **_k: None)
    monkeypatch.setattr("app.options.order_flow.streaming.write_active_option_contract_signal", lambda *_a, **_k: None)
    _write_option_l1_row(db, _SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, ts_recv=1.0)

    seen_idents: set[int] = set()
    real_open = ofs._open_capture_db_readonly
    real_replay = ofs._replay_option_contract_rows

    def spy_open(*a, **k):
        seen_idents.add(threading.get_ident())
        return real_open(*a, **k)

    def spy_replay(*a, **k):
        seen_idents.add(threading.get_ident())
        return real_replay(*a, **k)

    monkeypatch.setattr(ofs, "_open_capture_db_readonly", spy_open)
    monkeypatch.setattr(ofs, "_replay_option_contract_rows", spy_replay)

    async def go():
        ofs._feed_running = True
        ofs.set_active_option_contract(_SPY_CONTRACT)
        task = asyncio.get_event_loop().create_task(ofs._feed_loop())
        await asyncio.sleep(1.5)   # several POLL_INTERVAL_SEC=0.5 ticks -> several to_thread calls
        ofs._feed_running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    asyncio.run(go())

    assert len(seen_idents) == 1, (
        f"DB touches spanned {len(seen_idents)} threads — a shared sqlite3.Connection "
        f"crossing threads is exactly the defect this test exists to catch")


def _reset_option_feed_globals():
    ofs._feed_running = False
    ofs._active_option_contract = None
    ofs._option_streaming_last_update_ts = None
    ofs._option_last_subscribe_completed_ts = None
    ofs._option_l1_cursor = {}
    ofs._option_book_cursor = {}


def test_option_contract_streaming_diagnostics_healthy_on_recent_tick():
    """Mirrors get_streaming_diagnostics()'s own equity-side contract exactly, for the
    independent option-contract slot: a recent update ts reads healthy with ~0 staleness."""
    _reset_option_feed_globals()
    ofs._feed_running = True
    ofs._active_option_contract = _SPY_CONTRACT
    ofs._option_streaming_last_update_ts = time.time()
    # Gap 2 (PR214 final remediation): streaming_healthy now also requires a producer
    # identity that is either confirmed (a fresh DB heartbeat) or still within the
    # startup grace window — this test has no real daemon/DB behind it, so it must
    # establish that grace explicitly, same as test_..._grace_window_before_first_tick.
    ofs._option_last_subscribe_completed_ts = time.time()

    diag = ofs.get_option_contract_streaming_diagnostics()
    assert diag["streaming_connected"] is True
    assert diag["option_contract"] == _SPY_CONTRACT
    assert diag["streaming_healthy"] is True
    assert diag["streaming_staleness_ms"] is not None
    assert diag["streaming_staleness_ms"] < 1000.0


def test_option_contract_streaming_diagnostics_stale_past_threshold():
    """Past STREAMING_STALE_MS (25s) with no fresher tick, the contract must read
    unhealthy — the same staleness gate the equity slot enforces."""
    _reset_option_feed_globals()
    ofs._feed_running = True
    ofs._active_option_contract = _SPY_CONTRACT
    ofs._option_streaming_last_update_ts = time.time() - 30.0

    diag = ofs.get_option_contract_streaming_diagnostics()
    assert diag["streaming_healthy"] is False
    assert diag["streaming_staleness_ms"] >= 30_000.0


def test_option_contract_streaming_diagnostics_grace_window_before_first_tick():
    """Immediately after subscribing (no data yet), the grace window
    (GRACE_AFTER_SUBSCRIBE_SEC=8s) must read healthy with a fabricated-zero staleness —
    not unhealthy just because no tick has landed yet."""
    _reset_option_feed_globals()
    ofs._feed_running = True
    ofs._active_option_contract = _SPY_CONTRACT
    ofs._option_last_subscribe_completed_ts = time.time()

    diag = ofs.get_option_contract_streaming_diagnostics()
    assert diag["streaming_healthy"] is True
    assert diag["streaming_staleness_ms"] == 0.0


def test_option_contract_streaming_diagnostics_unhealthy_when_feed_not_running():
    _reset_option_feed_globals()
    ofs._feed_running = False
    ofs._active_option_contract = _SPY_CONTRACT
    ofs._option_streaming_last_update_ts = time.time()

    diag = ofs.get_option_contract_streaming_diagnostics()
    assert diag["streaming_connected"] is False
    assert diag["streaming_healthy"] is False


def test_option_contract_streaming_diagnostics_independent_of_equity_slot():
    """The two diagnostics functions must read their own module-level state only — a
    stale/dead equity ticker must not drag down a healthy option contract, and vice
    versa, since the mission requires both to be watchable independently at once."""
    _reset_option_feed_globals()
    ofs._active_ticker = "SPY"
    ofs._streaming_last_update_ts = time.time() - 60.0
    ofs._last_subscribe_completed_ts = None
    ofs._feed_running = True
    ofs._active_option_contract = _SPY_CONTRACT
    ofs._option_streaming_last_update_ts = time.time()
    # Gap 2: see test_option_contract_streaming_diagnostics_healthy_on_recent_tick — no
    # real daemon/DB behind this test, so the option slot's healthy=True needs explicit
    # startup grace. The equity slot deliberately has none (it must read unhealthy).
    ofs._option_last_subscribe_completed_ts = time.time()

    assert ofs._streaming_healthy() is False
    assert ofs._option_streaming_healthy() is True
    assert ofs.get_streaming_diagnostics()["streaming_healthy"] is False
    assert ofs.get_option_contract_streaming_diagnostics()["streaming_healthy"] is True


def test_reused_readonly_feed_sees_later_option_commits(tmp_path, monkeypatch):
    """The live plane reuses one readonly connection. A deferred SQLite snapshot
    would hide later OPTIONS_BOOK commits (history hydrates; live stays no_book).
    # universal-scope-ok: vendor OSI fixture, not a SPY-only product claim.
    """
    db = _reset(tmp_path, monkeypatch)
    ofs._option_streaming_last_update_ts = None
    CaptureWriter(db, batch_rows=1, batch_sec=10.0).close()
    con = ofs._open_capture_db_readonly(db)
    assert con is not None
    assert con.isolation_level is None
    ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    assert ofs._option_streaming_last_update_ts is None
    assert not any(i.get("BIDS") for i in ofls.get_content_for_symbol(_SPY_CONTRACT))

    _write_option_l1_row(db, _SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, ts_recv=2.0)
    _write_option_book_row(db, _SPY_CONTRACT, _REAL_OPTIONS_BOOK_CONTENT, ts_recv=2.0)

    ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()
    assert ofs._option_streaming_last_update_ts is not None
    items = ofls.get_content_for_symbol(_SPY_CONTRACT)
    assert any(i.get("LAST_PRICE") == 1.27 for i in items)
    assert any(i.get("BIDS") == _REAL_OPTIONS_BOOK_CONTENT["BIDS"] for i in items)


def test_first_tick_option_replay_is_snapshot_tail_not_lifetime(tmp_path, monkeypatch):
    """A long-lived OPTIONS_BOOK history must not be fully replayed on bind.
    # universal-scope-ok: vendor OSI fixture, not a SPY-only product claim.
    """
    db = _reset(tmp_path, monkeypatch)
    old = dict(_REAL_OPTIONS_BOOK_CONTENT)
    old = {**old, "BIDS": [{"BID_PRICE": 9.99, "TOTAL_VOLUME": 1}]}
    latest = _REAL_OPTIONS_BOOK_CONTENT
    _write_option_book_row(db, _SPY_CONTRACT, old, ts_recv=1.0)
    _write_option_book_row(db, _SPY_CONTRACT, latest, ts_recv=2.0)
    con = ofs._open_capture_db_readonly(db)
    ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()
    items = ofls.get_content_for_symbol(_SPY_CONTRACT)
    bids = [i.get("BIDS") for i in items if i.get("BIDS")]
    assert latest["BIDS"] in bids
    assert old["BIDS"] not in bids


def test_ensure_default_adopts_matching_signal_file(tmp_path, monkeypatch):
    """Process start with empty in-memory slot must bind the daemon's existing signal.
    # universal-scope-ok: vendor OSI fixture, not a SPY-only product claim.
    """
    _reset(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ofs, "read_active_option_contract_signal", lambda: _SPY_CONTRACT)
    written = []
    monkeypatch.setattr(ofs, "write_active_option_contract_signal", lambda s: written.append(s))
    monkeypatch.setattr(ofs, "_contract_matches_underlying", lambda c, t, **k: c == _SPY_CONTRACT)
    ofs._active_option_contract = None
    ofs._ensure_default_option_contract_for_ticker("SPY")
    assert ofs._active_option_contract == _SPY_CONTRACT
    assert written == [_SPY_CONTRACT]
