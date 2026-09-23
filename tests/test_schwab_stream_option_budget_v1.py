"""The shared Schwab socket's option budget, and what happens when the socket dies.

MEASURED 2026-09-23 (stream_capture.db): holding ~850-5,200 additional LEVELONE_OPTIONS
contracts on the ONE Schwab socket that also carries LEVELONE_EQUITIES killed the whole
socket 42 times in one session (SPY live-price gaps up to 1,341 s); on 9/15, with 10 option
subscriptions, there were 0 recycles and no SPY gap over 24 s. Each death was then
compounded: subscribe bisection kept running on the dead socket and stamped 3,223 healthy
contracts "rejected: no close frame". And the console served a 20 s REST refresh as
spot_source=streaming_plane / live. These tests lock each repair at its real seam.
"""
from __future__ import annotations

import asyncio
import sys
import time

import pytest

import app.market_data.schwab.streaming.capture as rsc
import live_market_plane as L
import stream_spine
from stream_spine import (
    OPTION_CONTRACTS_MAX_HELD,
    enforce_option_contracts_budget,
    rank_option_contracts,
)


def _sym(root: str, exp: str, cp: str, strike: float) -> str:
    return f"{root:<6}{exp}{cp}{int(round(strike * 1000)):08d}"


# ── the console ranks on canonical Schwab fields; the daemon only guards ──────────────

def _contract(root: str, exp: str, cp: str, strike: float) -> dict:
    """A chain contract as Schwab sends it: symbol, strikePrice, expirationDate."""
    yy, mm, dd = exp[:2], exp[2:4], exp[4:6]
    return {"symbol": _sym(root, exp, cp, strike), "strikePrice": float(strike),
            "expirationDate": f"20{yy}-{mm}-{dd}T20:00:00.000+00:00", "putCall": "CALL" if cp == "C" else "PUT"}


def _inputs(contracts: list, spot):
    return {c["symbol"]: {"expirationDate": c["expirationDate"], "strikePrice": c["strikePrice"],
                          "spot": spot} for c in contracts}


def test_ranking_is_nearest_expiration_then_nearest_spot():
    near = [_contract("SPY", "260924", "C", k) for k in range(700, 841)]
    far = [_contract("SPY", "261030", "P", k) for k in range(700, 941)]
    syms = [c["symbol"] for c in near + far]
    admitted, not_admitted = rank_option_contracts(syms, _inputs(near + far, 820.0), budget=150)
    assert len(admitted) == 150 and len(not_admitted) == len(syms) - 150
    assert {c["symbol"] for c in near} <= set(admitted), "the nearest expirationDate fills first"
    far_in = [c["strikePrice"] for c in far if c["symbol"] in admitted]
    assert far_in and max(abs(k - 820.0) for k in far_in) <= 5, "then nearest the SPOT"


def test_ranking_uses_canonical_fields_not_the_symbol_text():
    c = _contract("SPY", "260924", "C", 800)
    inp = {c["symbol"]: {"expirationDate": c["expirationDate"], "strikePrice": 815.0, "spot": 815.0}}
    other = _contract("SPY", "260924", "C", 810)
    inp[other["symbol"]] = {"expirationDate": other["expirationDate"], "strikePrice": 810.0,
                            "spot": 815.0}
    admitted, _ = rank_option_contracts([c["symbol"], other["symbol"]], inp, budget=1)
    assert admitted == [c["symbol"]], "strikePrice comes from the chain field, never the symbol"


def test_any_missing_canonical_input_means_not_admitted_and_says_which():
    c = _contract("SPY", "260924", "C", 800)
    for missing in ("expirationDate", "strikePrice", "spot"):
        inp = _inputs([c], 820.0)
        inp[c["symbol"]][missing] = None
        admitted, not_admitted = rank_option_contracts([c["symbol"]], inp, budget=10)
        assert admitted == [] and not_admitted[c["symbol"]] == f"not admitted: no {missing}"
    admitted, not_admitted = rank_option_contracts([c["symbol"]], {}, budget=10)
    assert admitted == [] and "not in the console's current Schwab chain" in not_admitted[c["symbol"]]


def test_ranking_is_deterministic_and_order_free():
    cs = [_contract("SPY", "260924", "C", k) for k in range(600, 900)]
    syms = [c["symbol"] for c in cs]
    a1, _ = rank_option_contracts(syms, _inputs(cs, 820.0), budget=40)
    a2, _ = rank_option_contracts(list(reversed(syms)), _inputs(cs, 820.0), budget=40)
    assert a1 == a2


def test_budget_is_below_the_load_that_still_died():
    assert OPTION_CONTRACTS_MAX_HELD < 850, (
        "~850 held contracts still killed the socket every 4-20 min on 2026-09-23")


def test_daemon_guard_never_ranks_it_holds_or_refuses():
    ok = [_sym("SPY", "260924", "C", k) for k in range(700, 710)]
    assert enforce_option_contracts_budget(ok, budget=10) == (sorted(ok), {})
    too_many = [_sym("SPY", "260924", "C", k) for k in range(700, 711)]
    admitted, refused = enforce_option_contracts_budget(too_many, budget=10)
    assert admitted == [] and set(refused) == set(too_many)
    assert all("console must rank by spot" in r for r in refused.values())


# ── the daemon applies the guard and reports refusals honestly ─────────────────────────

class _Stream:
    def __init__(self, die_after: int | None = None):
        self.calls: list[tuple[str, int]] = []
        self.held: set[str] = set()
        self._die_after = die_after

    async def _op(self, name, syms):
        self.calls.append((name, len(syms)))
        if self._die_after is not None and len(self.calls) > self._die_after:
            raise ConnectionError("no close frame received or sent")

    async def level_one_option_subs(self, syms):
        await self._op("subs", syms)
        self.held |= set(syms)

    async def level_one_option_add(self, syms):
        await self._op("add", syms)
        self.held |= set(syms)

    async def level_one_option_unsubs(self, syms):
        await self._op("unsubs", syms)
        self.held -= set(syms)

    async def options_book_subs(self, syms):
        await self._op("book_subs", syms)

    async def options_book_unsubs(self, syms):
        await self._op("book_unsubs", syms)


def _apply(stream, rejected, monkeypatch, symbols):
    monkeypatch.setattr(rsc, "read_active_option_contract_signal", lambda: None)
    monkeypatch.setattr(rsc, "read_active_option_contracts_signal", lambda: list(symbols))
    state: dict = {}
    return asyncio.run(rsc._apply_active_option_contract_subs(
        stream, state, rejected_state=rejected, rejection_backoff={}))


def test_daemon_holds_a_request_within_budget(monkeypatch):
    monkeypatch.setattr(rsc, "OPTION_CONTRACTS_MAX_HELD", 50)
    syms = [_sym("SPY", "260924", "C", k) for k in range(700, 750)]
    stream, rejected = _Stream(), {}
    _apply(stream, rejected, monkeypatch, syms)
    assert stream.held == set(syms) and not rejected


def test_daemon_refuses_an_over_budget_request_as_not_admitted(monkeypatch):
    monkeypatch.setattr(rsc, "OPTION_CONTRACTS_MAX_HELD", 50)
    syms = [_sym("SPY", "260924", "C", k) for k in range(700, 751)]
    stream, rejected = _Stream(), {}
    _apply(stream, rejected, monkeypatch, syms)
    assert stream.held == set(), "the daemon never picks contracts itself"
    assert set(rejected) == set(syms)
    assert all(r.startswith("not admitted:") for r in rejected.values()), (
        "a capacity refusal must never read as a vendor rejection")


def test_refusals_clear_when_the_request_fits_again(monkeypatch):
    monkeypatch.setattr(rsc, "OPTION_CONTRACTS_MAX_HELD", 10)
    syms = [_sym("SPY", "260924", "C", k) for k in range(700, 730)]
    rejected: dict = {}
    _apply(_Stream(), rejected, monkeypatch, syms)
    assert len(rejected) == 30
    _apply(_Stream(), rejected, monkeypatch, syms[:5])
    assert not any(v.startswith("not admitted:") for v in rejected.values())


# ── a dead socket stops the subscribe at once: no false rejections, one recycle ─────────

def test_connection_death_is_recognised():
    class ConnectionClosedError(Exception):
        pass
    assert rsc._is_connection_death(ConnectionClosedError("x"))
    assert rsc._is_connection_death(RuntimeError("received 1009 (message too big)"))
    assert rsc._is_connection_death(RuntimeError("no close frame received or sent"))
    assert not rsc._is_connection_death(RuntimeError("symbol not entitled"))


def test_socket_death_mid_subscribe_raises_once_and_rejects_nothing(monkeypatch):
    monkeypatch.setattr(rsc, "OPTION_CONTRACTS_MAX_HELD", 100_000)
    monkeypatch.setattr(rsc, "OPTION_SUBSCRIBE_MAX_BATCH_SYMBOLS", 10)
    syms = [_sym("SPY", "260924", "C", k) for k in range(700, 760)]      # 6 chunks
    stream, rejected = _Stream(die_after=2), {}
    with pytest.raises(rsc.OptionStreamConnectionLost):
        _apply(stream, rejected, monkeypatch, syms)
    assert len(stream.calls) == 3, "no further chunk and no bisection after the socket died"
    assert not rejected, "a dead socket must not stamp healthy contracts rejected"


def test_connection_lost_takes_the_existing_recycle_path():
    assert issubclass(rsc.OptionStreamConnectionLost, rsc.OptionCoverageCompensationError), (
        "the poll loop's one escalation for this class requests a stream recycle")


def test_a_genuinely_refused_symbol_is_still_bisected_and_rejected():
    refused = _sym("SPY", "260924", "C", 999)

    async def op(symbols):
        if refused in symbols:
            raise RuntimeError("vendor refused one symbol")

    good = [_sym("SPY", "260924", "C", k) for k in range(700, 707)]
    admitted: list = []
    rej = asyncio.run(rsc._batch_subscribe_with_bisection(
        op, good + [refused], on_admitted=admitted.extend))
    assert [s for s, _ in rej] == [refused] and sorted(admitted) == sorted(good)


# ── the console: honest spot identity, budgeted demand ─────────────────────────────────

def _row(ingestion, age_sec):
    return {"spot": 700.42, "server_received_ts": time.time() - age_sec,
            "exchange_quote_ts": time.time() - age_sec,
            "quote_source_detail": {"spot": "LAST_PRICE"}, "quote_ingestion": ingestion}


def _no_rest(monkeypatch, server):
    monkeypatch.setattr(server, "_spot_from_quote", lambda _tk: (None, None))


def test_a_rest_written_plane_row_is_not_spot(monkeypatch):
    """Spot is the streamed LAST_PRICE only -- a REST-written row is never spot, labelled
    or not (operator rule 2026-09-23: no fallbacks, a broken feed must look broken)."""
    import server
    tk = "ZZRESTROW"
    L._by_ticker[tk] = _row("rest_anchor_lane_refresher", 1.0)
    try:
        assert server.resolve_spot(tk) == (None, "none", None)
    finally:
        L._by_ticker.pop(tk, None)


def test_streamed_plane_row_keeps_streaming_identity(monkeypatch):
    import server
    _no_rest(monkeypatch, server)
    tk = "ZZSTREAMROW"
    L._by_ticker[tk] = _row("schwab_streaming_level_one", 1.0)
    try:
        _, source, _ = server.resolve_spot(tk)
        assert source == server.SPOT_SOURCE_PLANE
        assert server.current_spot_state(source, tk) == "live"
    finally:
        L._by_ticker.pop(tk, None)


def test_a_stale_streamed_price_is_not_spot(monkeypatch):
    """A streamed LAST_PRICE past its freshness bound is UNAVAILABLE, never served stale."""
    import server
    tk = "ZZSTALESTREAM"
    L._by_ticker[tk] = _row("schwab_streaming_level_one", L.PLANE_QUOTE_STALE_SEC + 30)
    try:
        assert server.resolve_spot(tk) == (None, "none", None)
    finally:
        L._by_ticker.pop(tk, None)


def test_no_rest_quote_is_ever_consulted_for_spot(monkeypatch):
    import server

    def _boom(*_a, **_k):
        raise AssertionError("resolve_spot must not call the REST quote")
    monkeypatch.setattr(server, "_spot_from_quote", _boom)
    monkeypatch.setattr(server, "_memoized_quote_response", _boom)
    assert server.resolve_spot("ZZNOSTREAM") == (None, "none", None)


def test_console_publishes_only_the_budget_and_reports_the_rest(monkeypatch, tmp_path):
    import app.options.order_flow.streaming as st
    import server
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **_k: (820.0, server.SPOT_SOURCE_PLANE, 1.0))
    chain = [_contract("SPY", "260924", "C", k) for k in range(700, 700 + OPTION_CONTRACTS_MAX_HELD + 37)]
    monkeypatch.setitem(server._terrain_cache, "SPY", {"_contracts_rest": chain})
    written: list = []
    monkeypatch.setattr(st, "write_active_option_contracts_signal", lambda syms: written.append(list(syms)))
    monkeypatch.setattr(st, "_active_option_contracts", [])
    syms = [c["symbol"] for c in chain]
    assert st.set_active_option_contracts(syms) is True
    assert len(written[-1]) == OPTION_CONTRACTS_MAX_HELD
    state = st.get_option_contracts_budget_state()
    assert state == {"admitted_count": OPTION_CONTRACTS_MAX_HELD, "over_budget_count": 37,
                     "budget": OPTION_CONTRACTS_MAX_HELD}


# ── the daemon's own output is recorded when it runs windowless ─────────────────────────

def test_windowless_daemon_output_goes_to_a_timestamped_log(monkeypatch, tmp_path):
    import runtime_layout
    monkeypatch.setattr(runtime_layout, "logs_dir", lambda: tmp_path)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    path = rsc._ensure_daemon_output_is_recorded()
    print("stream: socket closed (no close frame)")
    sys.stdout.flush()
    text = path.read_text(encoding="utf-8")
    assert path == tmp_path / "stream_capture.log"
    assert "socket closed" in text and text[:4].isdigit(), "each line carries its wall time"


def test_a_console_run_keeps_its_console(monkeypatch):
    assert sys.stdout is not None
    assert rsc._ensure_daemon_output_is_recorded() is None


def test_shared_budget_is_one_constant():
    assert rsc.OPTION_CONTRACTS_MAX_HELD is stream_spine.OPTION_CONTRACTS_MAX_HELD


def test_admission_summary_reports_over_budget_contracts_as_not_admitted(monkeypatch):
    import server
    import app.options.order_flow.streaming as st
    sym = _sym("SPY", "260924", "C", 900)
    monkeypatch.setattr(st, "_option_contracts_not_admitted",
                        {sym: "not admitted: outside the live-stream budget (200)"})
    out = server._option_contract_admission_summary("SPY")
    assert out["not_admitted"] == [sym], "the heatmap must be able to say why the cell has no stream"
    assert sym not in out["pending"] and sym not in out["rejected"]


# ── follow-ups from the Cursor review of #268 ──────────────────────────────────────────

def test_a_dead_pump_is_detected_but_our_own_teardown_and_placeholders_are_not():
    async def boom():
        raise ConnectionError("no close frame received or sent")

    async def run():
        dead = asyncio.ensure_future(boom())
        placeholder = asyncio.ensure_future(asyncio.sleep(0))
        cancelled = asyncio.ensure_future(asyncio.sleep(10))
        await asyncio.sleep(0.01)
        cancelled.cancel()
        await asyncio.sleep(0.01)
        return (rsc.pump_died(dead), rsc.pump_died(placeholder),
                rsc.pump_died(cancelled), rsc.pump_died(None))
    dead, placeholder, cancelled, none = asyncio.run(run())
    assert isinstance(dead, ConnectionError)
    assert placeholder is None and cancelled is None and none is None
    assert rsc.PUMP_DEATH_RECONNECT_MIN_SEC < rsc.STREAM_STALE_RECONNECT_SEC, (
        "a dead socket must recycle faster than the quiet-feed watchdog")


def test_console_ranks_on_the_chain_fields_and_streamed_spot(monkeypatch):
    import app.options.order_flow.streaming as st
    import server
    monkeypatch.setattr(st, "write_active_option_contracts_signal", lambda syms: None)
    monkeypatch.setattr(st, "_active_option_contracts", [])
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **_k: (820.0, server.SPOT_SOURCE_PLANE, 1.0))
    chain = [_contract("SPY", "260924", "C", k) for k in range(500, 1001)]
    monkeypatch.setitem(server._terrain_cache, "SPY", {"_contracts_rest": chain})
    st.set_active_option_contracts([c["symbol"] for c in chain])
    held = set(st.get_active_option_contracts())
    strikes = sorted(c["strikePrice"] for c in chain if c["symbol"] in held)
    assert abs(strikes[len(strikes) // 2] - 820) <= 1, "centred on the streamed LAST_PRICE"


def test_console_admits_nothing_without_a_streamed_spot(monkeypatch):
    import app.options.order_flow.streaming as st
    import server
    monkeypatch.setattr(st, "write_active_option_contracts_signal", lambda syms: None)
    monkeypatch.setattr(st, "_active_option_contracts", [])
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **_k: (None, "none", None))
    chain = [_contract("SPY", "260924", "C", k) for k in range(700, 720)]
    monkeypatch.setitem(server._terrain_cache, "SPY", {"_contracts_rest": chain})
    st.set_active_option_contracts([c["symbol"] for c in chain])
    assert st.get_active_option_contracts() == []
    assert set(st.get_option_contracts_not_admitted().values()) == {"not admitted: no spot"}


def test_post_returns_the_admitted_set_not_an_echo_of_the_request(monkeypatch):
    from fastapi.testclient import TestClient

    import app.options.order_flow.streaming as st
    import server
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **_k: (820.0, server.SPOT_SOURCE_PLANE, 1.0))
    monkeypatch.setattr(st, "write_active_option_contracts_signal", lambda syms: None)
    monkeypatch.setattr(st, "_active_option_contracts", [])
    chain = [_contract("SPY", "260924", "C", k) for k in range(700, 700 + OPTION_CONTRACTS_MAX_HELD + 9)]
    monkeypatch.setitem(server._terrain_cache, "SPY", {"_contracts_rest": chain})
    syms = [c["symbol"] for c in chain]
    body = TestClient(server.app).post("/api/streaming/active-option-contracts",
                                       json={"contracts": syms}).json()
    assert body["ok"] is True
    assert len(body["contracts"]) == OPTION_CONTRACTS_MAX_HELD
    assert body["requested_count"] == len(syms) and len(body["not_admitted"]) == 9


def test_watchlist_labels_a_rest_written_row_as_rest(monkeypatch):
    from fastapi.testclient import TestClient

    import server
    tk = "ZZWLREST"
    L._by_ticker[tk] = _row("rest_watchlist_batch", 1.0)
    try:
        body = TestClient(server.app).get(f"/api/watchlist-quotes?tickers={tk}").json()
        assert body["quotes"][tk]["spot_source"] == server.SPOT_SOURCE_QUOTE
    finally:
        L._by_ticker.pop(tk, None)


def test_over_budget_legs_are_stamped_not_admitted(monkeypatch):
    import app.options.order_flow.streaming as st
    import server
    c, p = _sym("SPY", "260924", "C", 900), _sym("SPY", "260924", "P", 900)
    why = "not admitted: outside the live-stream budget (200)"
    monkeypatch.setattr(st, "_option_contracts_not_admitted", {c: why, p: why})
    surface = {"cells": [{"contracts": [{"call": c, "put": p}]}]}
    server._stamp_gamma_surface_cell_stream_state(surface, {}, set(), {}, set())
    assert surface["cells"][0]["stream"][0]["state"] == "not_admitted"
    assert surface["cells"][0]["stream"][0]["call"]["not_admitted_reason"] == why
    assert server._gamma_surface_cell_state_counts(surface)["not_admitted"] == 1
