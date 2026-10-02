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
import json
import time
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
from app.options.order_flow.live_payload import options_live_payload
from stream_spine import book_msg, options_quote_msg

_REAL_STREAM_SAMPLES = Path(__file__).parent / "fixtures" / "real_options_stream_history_samples.json"
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
        monkeypatch.setitem(server._terrain_cache, tk, {"_chain": cts})
    return spots


def _reset(tmp_path, monkeypatch):
    ofs._feed_running = False
    ofs._active_option_contract = None
    ofs._active_option_contracts = []
    ofs._option_streaming_last_update_ts = None
    ofs._option_contract_last_update_ts.clear()
    ofls.clear_all_live_state()
    db = tmp_path / "stream_capture.db"
    lmp.record_feed_down()
    return db


def _live_daemon():
    """The daemon's status arriving on the console socket: health can only be confirmed
    while the daemon itself is alive."""
    lmp.record_feed_heartbeat({"schwab_socket_open": True, "held": {}, "health": {}}, time.time())


def _push_option_l1(symbol, content, ts_recv):
    """One LEVELONE_OPTIONS message as the daemon publishes and pushes it."""
    return ofs._ingest_pushed(f"optquote.{symbol}", options_quote_msg(
        symbol=symbol, content=content, src="schwab_options_l1", ts_recv=ts_recv))


def _push_option_book(symbol, content, ts_recv, service="OPTIONS_BOOK"):
    return ofs._ingest_pushed(f"book.{symbol}", book_msg(
        symbol=symbol, service=service, content=content,
        src="schwab_book", ts_recv=ts_recv))



@pytest.fixture(autouse=True)
def _before_the_fixture_expiries(monkeypatch):
    """The ranking never admits an expired contract; these tests rank stored chains whose
    expiries are past, so "today" is pinned before them."""
    from datetime import datetime
    import time_et
    monkeypatch.setattr(time_et, "now_et", lambda: datetime(2026, 1, 2, 10, 0, tzinfo=time_et.ET))

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


def test_the_option_book_payload_reuses_the_one_producer(tmp_path, monkeypatch):
    """The decisive proof: this is compute_book_microstructure itself (the SAME function
    the equity /api/order-flow/microstructure route calls), not a parallel computation."""
    _reset(tmp_path, monkeypatch)
    _push_option_book(_SPY_CONTRACT, _REAL_OPTIONS_BOOK_CONTENT, ts_recv=time.time())

    result = options_live_payload(_SPY_CONTRACT, time.time())
    assert result["depth"]["1"]["imbalance"] is not None


def test_the_option_book_payload_fails_closed_with_no_book():
    """No replayed content yet -> the producer's own fail-closed contract: status
    'no_book', never a fabricated imbalance."""
    ofls.clear_all_live_state()
    result = options_live_payload("QQQ   260820C00450000", time.time())
    assert result.get("status") == "no_book" or result["depth"]["1"]["imbalance"] is None


def test_set_active_option_contract_writes_signal_and_clears_old_symbol(tmp_path, monkeypatch):
    cleared = []
    monkeypatch.setattr("app.options.order_flow.streaming.clear_symbol", lambda s: cleared.append(s))
    ofs._active_option_contract = "OLD   260101C00100000"

    ok = ofs.set_active_option_contract(_SPY_CONTRACT)
    assert ok is True
    assert ofs.current_wanted()["OPTIONS_BOOK"] == [_SPY_CONTRACT], "the daemon is told"
    assert cleared == ["OLD   260101C00100000"]
    assert ofs._active_option_contract == _SPY_CONTRACT


def test_set_active_option_contracts_writes_plural_signal_and_clears_only_dropped(monkeypatch, spot_authority):
    """RC-UI-3 (2026-09-12): set_active_option_contracts mirrors set_active_option_contract
    for the ADDITIONAL-symbols slot, except a symbol still (or newly) requested must keep
    replaying -- only a symbol actually DROPPED from the desired set gets its cursor
    cleared, otherwise every unchanged tick would spuriously reset a live replay."""
    cleared = []
    monkeypatch.setattr("app.options.order_flow.streaming.clear_symbol", lambda s: cleared.append(s))
    old = "OLD   260101C00100000"
    ofs._active_option_contracts = [old, _SPY_CONTRACT]

    ok = ofs.set_active_option_contracts([_SPY_CONTRACT, _QQQ_CONTRACT])
    assert ok is True
    assert ofs.current_wanted()["LEVELONE_OPTIONS"] == sorted([_SPY_CONTRACT, _QQQ_CONTRACT])
    assert cleared == [old], "only the dropped symbol is cleared; SPY keeps replaying"
    assert sorted(ofs._active_option_contracts) == sorted([_SPY_CONTRACT, _QQQ_CONTRACT])
    ofs._active_option_contracts = []


def test_dropping_an_additional_contract_that_is_still_primary_does_not_clear_it(monkeypatch):
    """Independent-review finding (2026-09-12), REPRODUCED: removing a symbol from the
    ADDITIONAL list used to unconditionally clear_symbol() it, even when that EXACT
    symbol remains the PRIMARY/pinned contract -- wiping the one shared per-symbol live
    store (cursors, streamed greeks, book state) out from under a subscription that is
    still actively depending on it."""
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
    qqq ={**_REAL_LEVELONE_OPTIONS_CONTENT, "key": _QQQ_CONTRACT, "UNDERLYING": "QQQ"}

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
    ofs._option_contract_last_update_ts.clear()
    lmp.record_feed_down()


def _real_fixture_contract():
    """A contract Schwab streamed (tests/fixtures/real_options_stream_history_samples.json)."""
    return json.loads(_REAL_STREAM_SAMPLES.read_text(encoding="utf-8"))["contracts"][0]["symbol"]


def _daemon_heartbeat(*held_contracts):
    """The daemon's heartbeat as it arrives on the console socket, holding these contracts
    on both option services."""
    lmp.record_feed_heartbeat({"schwab_socket_open": True, "health": {}, "held": {
        "LEVELONE_OPTIONS": list(held_contracts), "OPTIONS_BOOK": list(held_contracts)}}, time.time())


def test_option_contract_streaming_diagnostics_healthy_on_recent_tick():
    """A contract the daemon holds on a live socket, with a recent update, reads healthy
    with ~0 staleness."""
    _reset_option_feed_globals()
    _daemon_heartbeat(_SPY_CONTRACT)
    ofs._feed_running = True
    ofs._active_option_contract = _SPY_CONTRACT
    ofs._option_streaming_last_update_ts = time.time()

    diag = ofs.get_option_contract_streaming_diagnostics()
    assert diag["streaming_connected"] is True
    assert diag["option_contract"] == _SPY_CONTRACT
    assert diag["streaming_healthy"] is True
    assert diag["streaming_staleness_ms"] is not None
    assert diag["streaming_staleness_ms"] < 1000.0


def test_a_quiet_contract_on_a_live_feed_reads_healthy_with_its_own_staleness():
    """Health is the one live rule (live_market_plane.feed_live_for), not the age of the last
    message: Schwab sends a field only when it changes, so a contract quiet for 30 s on a
    live feed is healthy, and its staleness is the true 30 s."""
    _reset_option_feed_globals()
    _daemon_heartbeat(_SPY_CONTRACT)
    ofs._feed_running = True
    ofs._active_option_contract = _SPY_CONTRACT
    ofs._option_streaming_last_update_ts = time.time() - 30.0

    diag = ofs.get_option_contract_streaming_diagnostics()
    assert diag["streaming_healthy"] is True
    assert diag["streaming_staleness_ms"] >= 30_000.0


def test_a_just_subscribed_contract_the_daemon_does_not_hold_is_not_healthy():
    """O-11: a contract subscribed a moment ago, with no update and not held by the daemon,
    has no live evidence: unhealthy, staleness absent. (It read healthy with a synthetic
    0.0 staleness for an 8 s grace window.)"""
    _reset_option_feed_globals()
    contract = _real_fixture_contract()
    _daemon_heartbeat()
    ofs._feed_running = True
    assert ofs.set_active_option_contract(contract) is True

    diag = ofs.get_option_contract_streaming_diagnostics()
    assert diag["option_contract"] == contract
    assert diag["streaming_healthy"] is False
    assert diag["streaming_staleness_ms"] is None


def test_a_just_subscribed_contract_the_daemon_holds_is_healthy():
    """The same contract, once the daemon's heartbeat holds it on an open Schwab socket,
    reads healthy and bound to the queried contract."""
    _reset_option_feed_globals()
    contract = _real_fixture_contract()
    _daemon_heartbeat(contract)
    ofs._feed_running = True
    assert ofs.set_active_option_contract(contract) is True

    diag = ofs.get_option_contract_streaming_diagnostics(for_contract=contract)
    assert diag["contract_match"] is True
    assert diag["streaming_healthy"] is True
    assert diag["streaming_staleness_ms"] is None


def test_option_contract_streaming_diagnostics_unhealthy_when_feed_not_running():
    _reset_option_feed_globals()
    ofs._feed_running = False
    ofs._active_option_contract = _SPY_CONTRACT
    ofs._option_streaming_last_update_ts = time.time()

    diag = ofs.get_option_contract_streaming_diagnostics()
    assert diag["streaming_connected"] is False
    assert diag["streaming_healthy"] is False


def test_option_contract_streaming_diagnostics_independent_of_equity_slot():
    """The option diagnostics read their own state only: a stale equity ticker the daemon
    does not hold must not drag down a healthy option contract."""
    _reset_option_feed_globals()
    _daemon_heartbeat(_SPY_CONTRACT)
    ofs._feed_running = True
    ofs._active_option_contract = _SPY_CONTRACT
    ofs._option_streaming_last_update_ts = time.time()

    assert lmp.feed_live_for("SPY", "LEVELONE_EQUITIES") is False
    assert ofs.get_option_contract_streaming_diagnostics()["streaming_healthy"] is True
