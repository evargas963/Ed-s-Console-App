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
import time

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
from stream_spine import book_msg, options_quote_msg

_SPY_CONTRACT = "SPY   260820C00767000"
_QQQ_CONTRACT = "QQQ   260820C00450000"

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


@pytest.fixture
def spot_authority(monkeypatch):
    """The live path ranks additional contracts by their underlying's SPOT from
    resolve_spot (no spot, not admitted). These tests serve a real-looking spot per
    underlying through that one authority instead of bypassing the ranking."""
    import server
    spots = {"SPY": 767.0, "QQQ": 450.0}
    monkeypatch.setattr(server, "resolve_spot",
                        lambda tk, **_k: (spots.get(tk), server.SPOT_SOURCE_PLANE, 1.0)
                        if tk in spots else (None, "none", None))
    # the ranking reads each contract's own Schwab fields from the chain the console holds
    chains = {"SPY": [{"symbol": _SPY_CONTRACT, "strikePrice": 767.0,
                       "expirationDate": "2026-08-20T20:00:00.000+00:00"}],
              "QQQ": [{"symbol": _QQQ_CONTRACT, "strikePrice": 450.0,
                       "expirationDate": "2026-08-20T20:00:00.000+00:00"}]}
    for tk, cts in chains.items():
        monkeypatch.setitem(server._terrain_cache, tk, {"_contracts_rest": cts})
    return spots


def _reset(tmp_path, monkeypatch):
    ofs._feed_running = False
    ofs._active_option_contract = None
    ofs._active_option_contracts = []
    ofs._option_streaming_last_update_ts = None
    ofs._option_contract_last_update_ts.clear()
    ofls.clear_all_live_state()
    db = tmp_path / "stream_capture.db"
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    monkeypatch.setattr(
        "app.options.contracts.default.default_option_contract",
        lambda *a, **k: None,
    )
    return db


def _push_option_l1(symbol, content, ts_recv):
    """One LEVELONE_OPTIONS message as the daemon publishes and pushes it."""
    return ofs._ingest_pushed(f"optquote.{symbol}", options_quote_msg(
        symbol=symbol, content=content, src="schwab_options_l1", ts_recv=ts_recv))


def _push_option_book(symbol, content, ts_recv, service="OPTIONS_BOOK"):
    return ofs._ingest_pushed(f"book.{symbol}", book_msg(
        symbol=symbol, service=service, content=content,
        src="schwab_book", ts_recv=ts_recv))


def test_option_contract_l1_lands_in_order_flow_state(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    _push_option_l1(_SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, ts_recv=time.time())

    items = ofls.get_content_for_symbol(_SPY_CONTRACT)
    assert any(i.get("LAST_PRICE") == 1.27 for i in items)


def test_option_contract_book_lands_verbatim(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    _push_option_book(_SPY_CONTRACT, _REAL_OPTIONS_BOOK_CONTENT, ts_recv=time.time())

    items = ofls.get_content_for_symbol(_SPY_CONTRACT)
    assert any(i.get("BIDS") == _REAL_OPTIONS_BOOK_CONTENT["BIDS"] for i in items)


def test_only_an_options_book_advances_the_contracts_freshness_clock(tmp_path, monkeypatch):
    """A NASDAQ_BOOK/NYSE_BOOK message is an equity book: it must never count as an option
    contract's OPTIONS_BOOK activity, even under the same symbol string."""
    _reset(tmp_path, monkeypatch)
    _push_option_book(_SPY_CONTRACT, {"key": _SPY_CONTRACT, "BIDS": [], "ASKS": []},
                      ts_recv=time.time(), service="NASDAQ_BOOK")
    assert _SPY_CONTRACT not in ofs._option_contract_last_update_ts
    assert ofs._option_streaming_last_update_ts is None

    ts = time.time()
    _push_option_book(_SPY_CONTRACT, _REAL_OPTIONS_BOOK_CONTENT, ts_recv=ts)
    assert ofs._option_contract_last_update_ts[_SPY_CONTRACT] == ts


def test_get_option_contract_book_microstructure_reuses_the_one_producer(tmp_path, monkeypatch):
    """The decisive proof: this is compute_book_microstructure itself (the SAME function
    the equity /api/order-flow/microstructure route calls), not a parallel computation."""
    _reset(tmp_path, monkeypatch)
    _push_option_book(_SPY_CONTRACT, _REAL_OPTIONS_BOOK_CONTENT, ts_recv=time.time())

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


def test_set_active_option_contracts_writes_plural_signal_and_clears_only_dropped(monkeypatch, spot_authority):
    """RC-UI-3 (2026-09-12): set_active_option_contracts mirrors set_active_option_contract
    for the ADDITIONAL-symbols slot, except a symbol still (or newly) requested must keep
    replaying -- only a symbol actually DROPPED from the desired set gets its cursor
    cleared, otherwise every unchanged tick would spuriously reset a live replay."""
    calls = []
    monkeypatch.setattr("app.options.order_flow.streaming.write_active_option_contracts_signal",
                        lambda s: calls.append(list(s)))
    cleared = []
    monkeypatch.setattr("app.options.order_flow.streaming.clear_symbol", lambda s: cleared.append(s))
    old = "OLD   260101C00100000"
    ofs._active_option_contracts = [old, _SPY_CONTRACT]

    ok = ofs.set_active_option_contracts([_SPY_CONTRACT, _QQQ_CONTRACT])
    assert ok is True
    assert calls == [sorted([_SPY_CONTRACT, _QQQ_CONTRACT])]
    assert cleared == [old], "only the dropped symbol is cleared; SPY keeps replaying"
    assert sorted(ofs._active_option_contracts) == sorted([_SPY_CONTRACT, _QQQ_CONTRACT])
    ofs._active_option_contracts = []


def test_dropping_an_additional_contract_that_is_still_primary_does_not_clear_it(monkeypatch):
    """Independent-review finding (2026-09-12), REPRODUCED: removing a symbol from the
    ADDITIONAL list used to unconditionally clear_symbol() it, even when that EXACT
    symbol remains the PRIMARY/pinned contract -- wiping the one shared per-symbol live
    store (cursors, streamed greeks, book state) out from under a subscription that is
    still actively depending on it."""
    monkeypatch.setattr("app.options.order_flow.streaming.write_active_option_contracts_signal",
                        lambda *_a, **_k: None)
    cleared = []
    monkeypatch.setattr("app.options.order_flow.streaming.clear_symbol", lambda s: cleared.append(s))
    try:
        ofs._active_option_contract = _SPY_CONTRACT     # SPY is (and stays) the primary
        ofs._active_option_contracts = [_SPY_CONTRACT]  # SPY is ALSO currently additional

        ok = ofs.set_active_option_contracts([])         # drop SPY from the additional set
        assert ok is True
        assert cleared == [], (
            f"SPY must not be cleared while it remains the primary contract: {cleared}")
        assert ofs._active_option_contract == _SPY_CONTRACT, (
            "the primary slot must be entirely unaffected by the additional set's change")
    finally:
        ofs._active_option_contract = None
        ofs._active_option_contracts = []


def test_switching_the_primary_away_does_not_clear_a_symbol_still_additional(monkeypatch):
    """The mirror case: the primary switches from SPY to QQQ while SPY remains desired in
    the ADDITIONAL set -- SPY must not be cleared either, for the same reason (its shared
    live store is still needed by the additional-contracts subscription)."""
    monkeypatch.setattr("app.options.order_flow.streaming.write_active_option_contract_signal",
                        lambda *_a, **_k: None)
    cleared = []
    monkeypatch.setattr("app.options.order_flow.streaming.clear_symbol", lambda s: cleared.append(s))
    try:
        ofs._active_option_contract = _SPY_CONTRACT
        ofs._active_option_contracts = [_SPY_CONTRACT]  # SPY is ALSO desired as additional

        ok = ofs.set_active_option_contract(_QQQ_CONTRACT)   # primary switches SPY -> QQQ
        assert ok is True
        assert cleared == [], (
            f"SPY must not be cleared while it remains desired in the additional set: {cleared}")
        assert ofs._active_option_contract == _QQQ_CONTRACT
        assert ofs._active_option_contracts == [_SPY_CONTRACT], (
            "the additional set is entirely unaffected by the primary's switch")
    finally:
        ofs._active_option_contract = None
        ofs._active_option_contracts = []


def test_dropping_an_additional_contract_not_also_primary_still_clears_it(monkeypatch):
    """Negative control on the two tests above: a symbol dropped from the additional set
    that is genuinely NOT the primary must still be cleared -- the guard must be scoped
    to the actual cross-slot overlap, not disable clearing altogether."""
    monkeypatch.setattr("app.options.order_flow.streaming.write_active_option_contracts_signal",
                        lambda *_a, **_k: None)
    cleared = []
    monkeypatch.setattr("app.options.order_flow.streaming.clear_symbol", lambda s: cleared.append(s))
    try:
        ofs._active_option_contract = _SPY_CONTRACT       # primary is SPY, unrelated to QQQ
        ofs._active_option_contracts = [_QQQ_CONTRACT]

        ok = ofs.set_active_option_contracts([])
        assert ok is True
        assert cleared == [_QQQ_CONTRACT], (
            "QQQ genuinely stops being desired anywhere and must still be cleared")
    finally:
        ofs._active_option_contract = None
        ofs._active_option_contracts = []


def test_feed_loop_applies_the_ticker_and_every_option_contract_from_one_push(tmp_path, monkeypatch):
    """The equity ticker, a primary contract and an additional contract all arrive on the
    daemon's ONE push connection and each lands in its own state -- nothing is filtered by
    which slot asked for it (the daemon only streams what was requested)."""
    import socket

    from app.market_data.schwab.streaming import live_push
    from stream_spine import MessageBus, quote_msg

    _reset(tmp_path, monkeypatch)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setattr(ofs, "LIVE_PUSH_URL", f"ws://127.0.0.1:{port}")
    ofs._active_ticker = "SPY"
    qqq = {**_REAL_LEVELONE_OPTIONS_CONTENT, "key": _QQQ_CONTRACT, "UNDERLYING": "QQQ"}

    def _landed():
        return (any(i.get("LAST_PRICE") == 450.0 for i in ofls.get_content_for_symbol("SPY"))
                and any(i.get("LAST_PRICE") == 1.27 for i in ofls.get_content_for_symbol(_SPY_CONTRACT))
                and any(i.get("LAST_PRICE") == 1.27 for i in ofls.get_content_for_symbol(_QQQ_CONTRACT)))

    async def go():
        bus = MessageBus()
        stop = asyncio.Event()
        stats: dict = {}
        server = asyncio.create_task(live_push.serve_live_push(bus, stop, port=port, stats=stats))
        ofs._feed_running = True
        task = asyncio.create_task(ofs._feed_loop())
        try:
            deadline = time.monotonic() + 10.0
            while stats.get("clients") != 1 and time.monotonic() < deadline:
                await asyncio.sleep(0.02)
            now = time.time()
            bus.publish("quote.SPY", quote_msg(symbol="SPY", last=450.0, src="schwab_l1",
                                               ts_recv=now, native={"key": "SPY", "LAST_PRICE": 450.0}))
            bus.publish(f"optquote.{_SPY_CONTRACT}", options_quote_msg(
                symbol=_SPY_CONTRACT, content=_REAL_LEVELONE_OPTIONS_CONTENT,
                src="schwab_options_l1", ts_recv=now))
            bus.publish(f"optquote.{_QQQ_CONTRACT}", options_quote_msg(
                symbol=_QQQ_CONTRACT, content=qqq, src="schwab_options_l1", ts_recv=now))
            while not _landed() and time.monotonic() < deadline:
                await asyncio.sleep(0.02)
        finally:
            ofs._feed_running = False
            task.cancel()
            stop.set()
            await asyncio.gather(task, server, return_exceptions=True)
    asyncio.run(go())
    assert _landed()


def _reset_option_feed_globals():
    ofs._feed_running = False
    ofs._active_option_contract = None
    ofs._active_option_contracts = []
    ofs._option_streaming_last_update_ts = None
    ofs._option_last_subscribe_completed_ts = None


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
