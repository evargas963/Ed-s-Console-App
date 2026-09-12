"""set_streamed_greeks_hook / _replay_option_contract_rows (app/options/order_flow/streaming.py):
the hook that lets a consumer (server.py's gamma-surface cache) learn the instant a streamed
option L1 tick carries new GAMMA/DELTA/OPEN_INTEREST, instead of only via the slow poll of
OrderFlowState. Same shape/precedent as the existing `_on_tick_callback`. Proven against the
REAL replay path (_replay_option_contract_rows reading real stream_capture.db rows written by
CaptureWriter), not a reimplementation of its dispatch logic."""
from __future__ import annotations

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
from stream_spine import CaptureWriter, options_quote_msg

_SPY_CONTRACT = "SPY   260820C00767000"

#: Real content shape (reports/of_capability_probe/options_20260820T1354Z/), same fixture the
#: existing options order-flow semantics tests use.
_REAL_LEVELONE_OPTIONS_CONTENT = {
    "key": _SPY_CONTRACT, "assetMainType": "OPTION", "BID_PRICE": 1.26, "ASK_PRICE": 1.28,
    "LAST_PRICE": 1.27, "LAST_SIZE": 2, "BID_SIZE": 458, "ASK_SIZE": 209,
    "TOTAL_VOLUME": 44994, "TRADE_TIME_MILLIS": 1787234092319, "OPEN_INTEREST": 2097,
    "DELTA": 0.45644607, "CONTRACT_TYPE": "C", "UNDERLYING": "SPY",
}
_BID_ASK_ONLY_CONTENT = {
    "key": _SPY_CONTRACT, "assetMainType": "OPTION", "BID_PRICE": 1.30, "ASK_PRICE": 1.32,
    "LAST_PRICE": 1.31, "LAST_SIZE": 1, "TRADE_TIME_MILLIS": 1787234093000,
}


def _reset(tmp_path, monkeypatch):
    ofs._feed_running = False
    ofs._active_option_contract = None
    ofs._option_l1_cursor = {}
    ofs._option_book_cursor = {}
    ofs._streamed_greeks_hook = None
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


def test_set_streamed_greeks_hook_registers_and_clears():
    calls = []
    ofs.set_streamed_greeks_hook(lambda sym, ts: calls.append((sym, ts)))
    assert ofs._streamed_greeks_hook is not None
    ofs.set_streamed_greeks_hook(None)
    assert ofs._streamed_greeks_hook is None


def test_hook_fires_on_a_tick_carrying_greeks_or_open_interest(tmp_path, monkeypatch):
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, ts_recv=1700000000.0)
    calls = []
    ofs.set_streamed_greeks_hook(lambda sym, ts: calls.append((sym, ts)))
    try:
        con = ofs._open_capture_db_readonly(db)
        ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
        con.close()
    finally:
        ofs.set_streamed_greeks_hook(None)
    assert calls == [(_SPY_CONTRACT, 1700000000.0)]


def test_hook_does_not_fire_on_a_bid_ask_only_tick(tmp_path, monkeypatch):
    """A tick with no GAMMA/DELTA/OPEN_INTEREST at all is not worth an eager recompute --
    nothing changed that the exposure formula reads."""
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _BID_ASK_ONLY_CONTENT, ts_recv=1700000000.0)
    calls = []
    ofs.set_streamed_greeks_hook(lambda sym, ts: calls.append((sym, ts)))
    try:
        con = ofs._open_capture_db_readonly(db)
        ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
        con.close()
    finally:
        ofs.set_streamed_greeks_hook(None)
    assert calls == []


def test_hook_fires_on_a_volume_only_tick_with_no_greeks_present(tmp_path, monkeypatch):
    """Independent-review finding (2026-09-12): 'the current hook is triggered by
    GAMMA/DELTA/OPEN_INTEREST; that does not complete volume-only update delivery.' A tick
    that carries ONLY TOTAL_VOLUME (no Greeks/OI at all) must still fire the hook, since
    _per_strike's volume column and compute_exposures_by_strike's own volume aggregation both
    read a contract's totalVolume directly."""
    db = _reset(tmp_path, monkeypatch)
    volume_only = dict(_BID_ASK_ONLY_CONTENT, TOTAL_VOLUME=54321)
    _write_option_l1_row(db, _SPY_CONTRACT, volume_only, ts_recv=1700000000.0)
    calls = []
    ofs.set_streamed_greeks_hook(lambda sym, ts: calls.append((sym, ts)))
    try:
        con = ofs._open_capture_db_readonly(db)
        ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
        con.close()
    finally:
        ofs.set_streamed_greeks_hook(None)
    assert calls == [(_SPY_CONTRACT, 1700000000.0)]


def test_no_hook_registered_does_not_break_the_replay(tmp_path, monkeypatch):
    """The default (unregistered) state -- must not raise or skip the ordinary push_level_one."""
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, ts_recv=1700000000.0)
    assert ofs._streamed_greeks_hook is None
    con = ofs._open_capture_db_readonly(db)
    ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()
    items = ofls.get_content_for_symbol(_SPY_CONTRACT)
    assert any(i.get("LAST_PRICE") == 1.27 for i in items)


def test_a_hook_that_raises_does_not_break_the_replay(tmp_path, monkeypatch):
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, ts_recv=1700000000.0)

    def _boom(sym, ts):
        raise RuntimeError("simulated hook failure")

    ofs.set_streamed_greeks_hook(_boom)
    try:
        con = ofs._open_capture_db_readonly(db)
        ofs._replay_option_contract_rows(con, _SPY_CONTRACT)  # must not raise
        con.close()
    finally:
        ofs.set_streamed_greeks_hook(None)
    items = ofls.get_content_for_symbol(_SPY_CONTRACT)
    assert any(i.get("LAST_PRICE") == 1.27 for i in items), (
        "a failing hook must not prevent the real observation from being applied"
    )


def test_a_burst_of_rows_in_one_poll_batch_fires_the_hook_exactly_once(tmp_path, monkeypatch):
    """Independent-review finding (2026-09-12), REPRODUCED then fixed: calling the hook once
    PER ROW meant a burst of N rows landing in one poll batch triggered N sequential expensive
    recomputes on the consumer side (MEASURED: ~3.1s each on a full SPXW-scale book -- three
    sequential calls, 9.3s total, zero suppressed). Three rows are written here BEFORE the
    daemon ever replays them (simulating a burst that accumulated between poll ticks, a real
    shape: CaptureWriter and the replay poll are independent), so ONE _replay_option_contract_rows
    call sees all three in a single query -- proving the hook fires exactly once for the whole
    batch, not three times, while EVERY row still lands in OrderFlowState (nothing is dropped
    from the state itself, only the expensive recompute is coalesced)."""
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_REAL_LEVELONE_OPTIONS_CONTENT, GAMMA=0.01), ts_recv=1700000000.0)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_REAL_LEVELONE_OPTIONS_CONTENT, GAMMA=0.02), ts_recv=1700000001.0)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_REAL_LEVELONE_OPTIONS_CONTENT, GAMMA=0.03), ts_recv=1700000002.0)

    calls = []
    ofs.set_streamed_greeks_hook(lambda sym, ts: calls.append((sym, ts)))
    try:
        con = ofs._open_capture_db_readonly(db)
        ofs._replay_option_contract_rows(con, _SPY_CONTRACT)  # ONE call sees all three rows
        con.close()
    finally:
        ofs.set_streamed_greeks_hook(None)

    assert calls == [(_SPY_CONTRACT, 1700000002.0)], (
        "exactly one hook call for the whole batch, stamped with the FRESHEST row's ts_recv"
    )
    # every row still reached OrderFlowState -- push_level_one ran for all three, the LATEST
    # (gamma=0.03) is what a consumer reading state now sees, nothing from the batch was lost
    assert ofls.get_stream_greeks(_SPY_CONTRACT)["gamma"] == 0.03


def test_a_batch_with_no_qualifying_rows_never_fires_the_hook(tmp_path, monkeypatch):
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _BID_ASK_ONLY_CONTENT, ts_recv=1700000000.0)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_BID_ASK_ONLY_CONTENT, LAST_PRICE=1.35), ts_recv=1700000001.0)

    calls = []
    ofs.set_streamed_greeks_hook(lambda sym, ts: calls.append((sym, ts)))
    try:
        con = ofs._open_capture_db_readonly(db)
        ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
        con.close()
    finally:
        ofs.set_streamed_greeks_hook(None)
    assert calls == []


def test_a_batch_with_one_qualifying_row_among_several_fires_once_with_that_rows_ts(tmp_path, monkeypatch):
    """A qualifying row in the MIDDLE of a batch (not the last row overall) must still be the
    one whose ts_recv is used -- 'freshest QUALIFYING row', not 'last row in the batch'."""
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _BID_ASK_ONLY_CONTENT, ts_recv=1700000000.0)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_REAL_LEVELONE_OPTIONS_CONTENT, GAMMA=0.05), ts_recv=1700000001.0)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_BID_ASK_ONLY_CONTENT, LAST_PRICE=1.40), ts_recv=1700000002.0)

    calls = []
    ofs.set_streamed_greeks_hook(lambda sym, ts: calls.append((sym, ts)))
    try:
        con = ofs._open_capture_db_readonly(db)
        ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
        con.close()
    finally:
        ofs.set_streamed_greeks_hook(None)
    assert calls == [(_SPY_CONTRACT, 1700000001.0)]
