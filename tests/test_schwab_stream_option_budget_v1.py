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
import time


import app.market_data.schwab.streaming.capture as rsc
import live_market_plane as L
from stream_spine import (
    OPTION_CONTRACTS_MAX_HELD,
    rank_option_contracts,
)


def _sym(root: str, exp: str, cp: str, strike: float) -> str:
    return f"{root:<6}{exp}{cp}{int(round(strike * 1000)):08d}"


# ── the console ranks on canonical Schwab fields; the daemon only guards ──────────────

def _contract(root: str, exp: str, cp: str, strike: float) -> dict:
    """A chain contract as Schwab sends it: symbol, strikePrice, expirationDate.

    # institutional-synthetic-ok: the ranking is pure geometry (expiration order, then
    # |strike - spot|), and these tests need exact strike grids spanning MORE than the
    # budget across TWO expirations to pin which contracts are admitted; no committed real
    # chain has that shape (the real single-expiry TSLA chain is exercised separately in
    # test_ranking_on_a_real_schwab_chain)."""
    yy, mm, dd = exp[:2], exp[2:4], exp[4:6]
    return {"symbol": _sym(root, exp, cp, strike), "strikePrice": float(strike),
            "expirationDate": f"20{yy}-{mm}-{dd}T20:00:00.000+00:00", "putCall": "CALL" if cp == "C" else "PUT"}


def _inputs(contracts: list, spot):
    return {c["symbol"]: {"expirationDate": c["expirationDate"], "strikePrice": c["strikePrice"],
                          "spot": spot} for c in contracts}


def test_ranking_on_a_real_schwab_chain():
    """The real, complete TSLA chain Schwab returned (236 contracts, one expiry, fractional
    strikes included) ranked against a streamed spot: exactly the budget's worth nearest the
    spot are admitted, every other contract is refused with the budget reason."""
    import json
    from pathlib import Path

    chain = json.loads((Path(__file__).parent / "fixtures" /
                        "real_tsla_complete_chain_strike_range_all.json").read_text())["chain"]
    assert len(chain) > OPTION_CONTRACTS_MAX_HELD
    spot = 342.5
    inputs = {c["symbol"]: {"expirationDate": c["expirationDate"],
                            "strikePrice": c["strikePrice"], "spot": spot} for c in chain}
    admitted, not_admitted = rank_option_contracts(list(inputs), inputs)
    expected = [c["symbol"] for c in sorted(
        chain, key=lambda c: (abs(c["strikePrice"] - spot), c["symbol"]))][:OPTION_CONTRACTS_MAX_HELD]
    assert sorted(admitted) == sorted(expected)
    assert set(not_admitted) == set(inputs) - set(expected)
    assert all("outside the live-stream budget" in r for r in not_admitted.values())


def test_a_non_finite_strike_or_spot_is_not_admitted():
    admitted, not_admitted = rank_option_contracts(
        ["A", "B"], {"A": {"expirationDate": "2026-09-24", "strikePrice": float("nan"), "spot": 1.0},
                     "B": {"expirationDate": "2026-09-24", "strikePrice": 1.0, "spot": "x"}})
    assert admitted == []
    assert not_admitted == {"A": "not admitted: no strikePrice",
                            "B": "not admitted: no spot"}


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


# ── a dead socket stops the subscribe at once: no false rejections, one recycle ─────────


# ── the console: honest spot identity, budgeted demand ─────────────────────────────────

def _row(ingestion, age_sec):
    return {"spot": 700.42, "server_received_ts": time.time() - age_sec, "spot_received_ts": time.time() - age_sec,
            "exchange_quote_ts": time.time() - age_sec,
            "quote_source_detail": {"spot": "LAST_PRICE"}, "quote_ingestion": ingestion}


def _no_rest(monkeypatch, server):
    """Every REST quote read in server.py raises: a spot answer cannot have come from REST.
    (The REST spot leg `_spot_from_quote` was deleted; the memo and its raw fetch are the
    only remaining vendor quote reads, test_spot_authority_v1::
    test_every_vendor_quote_read_goes_through_the_memo.)"""
    def _boom(*_a, **_k):
        raise AssertionError("resolve_spot must not call the REST quote")
    assert not hasattr(server, "_spot_from_quote"), "the REST spot leg is back"
    monkeypatch.setattr(server, "_memoized_quote_response", _boom)
    monkeypatch.setattr(server, "_safe_get_quote_with_retry", _boom)
    monkeypatch.setattr(server, "safe_get_quote", _boom)


def test_a_rest_written_plane_row_is_not_spot(monkeypatch):
    """Spot is the streamed LAST_PRICE only -- a REST-written row is never spot, labelled
    or not (operator rule 2026-09-23: no fallbacks, a broken feed must look broken)."""
    import server
    tk = "ZZRESTROW"
    L._by_ticker[tk] = dict(_row("rest_anchor_lane_refresher", 1.0), ticker=tk)
    try:
        assert server.resolve_spot(tk) == (None, "none", None)
    finally:
        L._by_ticker.pop(tk, None)


def test_streamed_plane_row_keeps_streaming_identity(monkeypatch):
    from tests.feed_live_helper import mark_feed_live
    mark_feed_live('ZZSTREAMROW')   # the daemon holds it on a live feed
    import server
    _no_rest(monkeypatch, server)
    tk = "ZZSTREAMROW"
    L._by_ticker[tk] = dict(_row("schwab_streaming_level_one", 1.0), ticker=tk)
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
    L._by_ticker[tk] = dict(_row("schwab_streaming_level_one", L.PLANE_QUOTE_STALE_SEC + 30), ticker=tk)
    try:
        assert server.resolve_spot(tk) == (None, "none", None)
    finally:
        L._by_ticker.pop(tk, None)


def test_no_rest_quote_is_ever_consulted_for_spot(monkeypatch):
    import server

    _no_rest(monkeypatch, server)
    L._by_ticker.pop("ZZNOSTREAM", None)
    # no streamed row: UNAVAILABLE, and no REST read was attempted to fill the gap
    assert server.resolve_spot("ZZNOSTREAM") == (None, "none", None)
    # a fresh streamed row: served, still without touching REST
    from tests.feed_live_helper import mark_feed_live
    tk = "ZZNORESTLIVE"
    mark_feed_live(tk)
    L._by_ticker[tk] = dict(_row("schwab_streaming_level_one", 1.0), ticker=tk)
    try:
        spot, source, _ = server.resolve_spot(tk)
        assert spot == float(L._by_ticker[tk]["spot"]) and source == server.SPOT_SOURCE_PLANE
    finally:
        L._by_ticker.pop(tk, None)


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


def test_watchlist_never_serves_a_rest_written_row(monkeypatch):
    """Stream only: a fresh-looking REST-written plane row is not a watchlist quote."""
    from fastapi.testclient import TestClient

    import server
    tk = "ZZWLREST"
    L._by_ticker[tk] = dict(_row("rest_watchlist_batch", 1.0), ticker=tk)
    try:
        body = TestClient(server.app).get(f"/api/watchlist-quotes?tickers={tk}").json()
        assert tk not in body["quotes"]
        assert body == {"ok": False, "error": "stream_unavailable", "quotes": {}}
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
