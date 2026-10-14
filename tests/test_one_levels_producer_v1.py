"""One producer for a ticker's levels, per-strike rows and gamma-surface grid: _publish_levels
prices the ticker's contract records once (the daemon's ledger, option_ledger: each opened from
Schwab's REST answer and posted to by every message, at the current spot) and publishes all three
together, so no second producer can show a different number (question 2: the screen shows it
correctly and promptly; question 3: each value is the one computation's).

Through the real code: the daemon's status (live_market_plane.record_feed_heartbeat), the ledger's
records on the daemon's bus pushed to the console (streaming._ingest_pushed), the price as the
console holds it (its live_market_plane record), the console's pages (push_changes), the pricing
thread, the chain captures in the console's database. Real data: CRWD's 2026-10-16 chain captured
2026-10-07 10:38:40 ET (tests/real_chains.py), valued at its capture.
STAND-INS (named): each streamed value of a CRWD contract (no CRWD contract was streamed in a
capture), each with its Schwab time a second after the capture, and the daemon's status holding them.
"""
from __future__ import annotations

import json
import threading
from collections import Counter
import time
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import option_ledger
import app.options.order_flow.streaming as ofs
import push_changes
import server
from calibration.complete_chain_capture import CAPTURE_BASIS, persist_complete_chain_capture
from math_exposure_core import bucket_metric, merge_exposure_books
from stream_spine import MessageBus
from terrain_engine import compute_terrain
from tests.feed_live_helper import (daemon_holds, forget_price, ledger_open, no_daemon, price_sent,
                                    through_the_daemons_bus)
from tests.real_chains import CRWD
from time_et import ET

_FX = Path(__file__).resolve().parent / "fixtures"
_SPOT = CRWD.spot
_CONTRACTS = [dict(ct) for ct in CRWD.chain]
_A = _CONTRACTS[0]["symbol"]
_B = _CONTRACTS[1]["symbol"]
TK = server.ticker_storage_key("CRWD")
#: CRWD's chain was captured 2026-10-07 at 10:38:40 ET: everything is valued there
_AT = CRWD.now
_T = _AT.timestamp()
_MIX = json.loads((_FX / "real_stream_mix_2026_10_05_1400ct.json").read_text(encoding="utf-8"))["messages"]


@pytest.fixture(autouse=True)
def _clean():
    """This test's state only: no page of its own open, no daemon status, no streamed value, no
    price row, no levels of TK; the console's push delivers to no event loop."""
    pages: list = []
    push_changes.bind(None)
    _LEDGER.clear()
    ofls.clear_all_live_state()
    no_daemon()
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    with server._chains_waiting_lock:
        server._chains_delivered.discard(TK)
    yield pages
    for tk, page in pages:
        push_changes.unsubscribe(tk, page)
    ofls.clear_all_live_state()
    no_daemon()
    forget_price(TK)
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)


def _view(pages: list, tk: str = TK) -> None:
    """A page opens on `tk` (its /api/live connection)."""
    pages.append((tk, push_changes.subscribe(tk)))


def _daemon(held=(), *, socket_open=True, price: "float | None" = _SPOT, at: float = _T) -> None:
    """The daemon's status at `at` (the chain's publication time unless given): Schwab's socket
    open, TK held on LEVELONE_EQUITIES and `held` on LEVELONE_OPTIONS; and TK's last trade as
    Schwab sends it (None: no price)."""
    daemon_holds(at, {"LEVELONE_EQUITIES": [TK], "LEVELONE_OPTIONS": list(held)}, socket_open=socket_open)
    if price is None:
        forget_price(TK)
    else:
        price_sent(TK, price, _T)


#: this test's ledger: the daemon's bus, holding each contract's one record
_LEDGER: list = []


def _bus() -> MessageBus:
    if not _LEDGER:
        _LEDGER.append(MessageBus())
    return _LEDGER[0]


def _streamed(sym: str, content: dict, ts: float) -> None:
    """One LEVELONE_OPTIONS message for `sym`, Schwab's time `ts`, posted to its record and pushed
    as the daemon pushes it."""
    through_the_daemons_bus(_bus(), sym, [content], [ts])


def _publish(chain=None, fetched_ts=None, **kw):
    """A round of TK (its contracts' records opened from `chain`, Schwab's answer) priced, or with
    no chain the records repriced as they are."""
    if chain is not None:
        ledger_open(TK, chain, fetched_ts, _bus())
    return server._publish_levels(TK, fetched_ts, now=_AT, **kw)


def _put_chain(fetched_ts=_T):
    """TK's round as the console holds it after the daemon delivered it."""
    return _publish(_CONTRACTS, fetched_ts)


def _cached():
    with server._terrain_cache_lock:
        return dict(server._terrain_cache[TK])


def _drain():
    """Wait until the pricing thread has priced everything waiting."""
    while True:
        server._chain_pricing.submit(lambda: None).result(timeout=60)
        with server._chains_waiting_lock:
            if not server._chains_waiting:
                return


def _busy():
    """Hold the pricing thread until the returned event is set."""
    gate = threading.Event()
    server._chain_pricing.submit(gate.wait, 10)
    return gate


# ── one computation behind every view ────────────────────────────────────────────────────────

def test_heatmap_per_strike_rows_and_levels_are_one_computation():
    _daemon()
    snap = _put_chain()
    c = _cached()
    assert c["_per_strike"] is snap.per_strike and c["_vanna_rows"] == server._vanna_rows(snap)
    assert c["gamma_flip"] == snap.gamma_flip and c["call_wall"] == snap.call_wall
    full, _ = merge_exposure_books(snap.books.values())
    checked = 0
    for row in c["_gamma_surface"]["cells"]:        # every strike's cells sum to the levels' book
        total = bucket_metric(full[row["strike"]], "net_gex_1pct")
        if total is not None:
            valued = [g for g in row["gex"] if g is not None]
            assert sum(valued) == pytest.approx(total, rel=1e-9, abs=1e-6)
            checked += 1
    assert checked


def test_published_levels_equal_compute_terrain_on_the_same_inputs():
    _daemon()
    _put_chain()
    expected = compute_terrain(TK, _CONTRACTS, _SPOT, now=_AT).to_dict()
    got = _cached()
    assert expected["gamma_flip"] is not None, "the chain must price (valued at its capture)"
    for k in ("gamma_flip", "call_wall", "put_wall", "absolute_gamma_strike", "max_pain",
              "net_gex_peak", "contracts_used"):
        assert got[k] == expected[k], k


def test_the_terrain_endpoint_serves_a_published_ticker_as_json_without_internal_fields():
    """2026-09-26: the payload carried the snapshot object and /api/terrain served the whole
    entry -- HTTP 500 for every published ticker, and the kept chain on every poll."""
    from fastapi.testclient import TestClient
    _daemon()
    snap = _put_chain()
    r = TestClient(server.app).get(f"/api/terrain?ticker={TK}")
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert snap.gamma_flip is not None
    assert body["call_wall"] == snap.call_wall and body["gamma_flip"] == snap.gamma_flip
    assert not [k for k in body if k.startswith("_")]


# ── a held contract's one record: the REST answer, each field the stream sends in its place ────

def _strike_rows(priced: "list | None" = None) -> list:
    """Every strike's row as /api/terrain/strikes serves it now; with `priced`, as it serves those
    contracts in a fresh ledger with nothing streamed (the expected answer)."""
    if priced is not None:
        _LEDGER.clear()
        ofls.clear_all_live_state()
        _daemon(held=[])
        _publish(priced, _T - 30.0)
    return json.loads(server.get_terrain_strikes(ticker=TK, scope="all").body)["today"]["all"]


def _served() -> "dict[str, dict]":
    """TK's contracts as /api/chain serves them (CRWD's chain has one expiration), by symbol,
    each with its fields' Schwab times."""
    body = json.loads(server.get_chain(ticker=TK, expiry=None).body)
    return {ct["symbol"]: ct for ct in body["contracts"]}


def _as_sent(ct: dict) -> dict:
    """A served contract's Schwab fields: without its record's ticker, stream time and field times."""
    return {k: v for k, v in ct.items() if k not in ("ticker", "streamTime", "fieldTimes")}


def test_a_held_contract_starts_from_the_rest_answer_and_takes_each_field_the_stream_sends():
    """Operator 2026-10-13: each held contract's record starts from Schwab's REST answer and each
    field is replaced when the stream sends it, with the stream's time for it; its delta, never
    streamed, is the REST answer's as sent, with its time."""
    _daemon(held=[_A])
    _put_chain(fetched_ts=_T - 30.0)
    _streamed(_A, {"GAMMA": 0.9}, _T + 1)
    _publish()
    served = _served()
    assert _as_sent(served[_A]) == {**_CONTRACTS[0], "gamma": 0.9}
    assert served[_A]["fieldTimes"]["gamma"] == int((_T + 1) * 1000)
    assert served[_A]["fieldTimes"]["delta"] == _CONTRACTS[0]["quoteTimeInLong"]
    rows = _strike_rows()
    assert rows and rows == _strike_rows([_as_sent(served[_A])] + _CONTRACTS[1:])


def test_a_held_contract_with_no_message_yet_is_its_rest_answer():
    _daemon(held=[_A])
    _put_chain()
    assert _as_sent(_served()[_A]) == _CONTRACTS[0]


def test_a_stream_message_older_than_the_rest_answer_never_replaces_it():
    """Each field is the newest Schwab sent, by Schwab's own time: a stream message a minute older
    than the contract's REST answer changes nothing."""
    _daemon(held=[_A])
    _put_chain()
    _streamed(_A, {"GAMMA": 0.9}, _CONTRACTS[0]["quoteTimeInLong"] / 1000 - 60)
    _publish()
    assert _served()[_A]["gamma"] == _CONTRACTS[0]["gamma"]


def test_a_streamed_minus_999_greek_is_absent_never_the_old_value():
    """CARRIED-PRS (#424), rule 2: Schwab's -999 replaces the value it held, as sent, and every
    reader takes it as no number: the contract's gamma leaves the book."""
    _daemon(held=[_A])
    _put_chain(fetched_ts=_T - 10.0)
    _streamed(_A, {"GAMMA": 0.9}, _T + 1)
    _streamed(_A, {"GAMMA": -999}, _T + 2)
    _publish()
    assert _served()[_A]["gamma"] == -999
    rows = _strike_rows()
    assert rows == _strike_rows([dict(_CONTRACTS[0], gamma=-999)] + _CONTRACTS[1:])
    assert rows != _strike_rows([dict(_CONTRACTS[0], gamma=0.9)] + _CONTRACTS[1:])


def test_a_new_round_does_not_turn_a_live_contracts_leg_stale():
    """ONE-05 (measured live 2026-09-28, MU 15:46 ET): each chain download made all 200 heatmap
    legs flip between live and stale while the feed stayed live. A leg's state is the feed's
    (live while the daemon holds the contract and the stream delivers it), whatever round came in."""
    _daemon(held=[_A])
    _put_chain(fetched_ts=_T - 60.0)
    _streamed(_A, {"GAMMA": 0.9}, _T + 1)
    _put_chain(fetched_ts=_T)                                        # the next round
    surface = _cached()["_gamma_surface"]
    legs = [col[side] for cell in surface["cells"] for col, pair in zip(cell["stream"], cell["contracts"])
            for side in ("call", "put") if pair.get(side) == _A and col]
    assert legs and all(leg["state"] == "live" for leg in legs)


def test_every_streamed_contract_is_priced_not_only_the_one_that_ticked():
    _daemon(held=[_A, _B])
    _put_chain(fetched_ts=_T - 5.0)
    _streamed(_A, {"GAMMA": 0.9}, _T + 1)
    _streamed(_B, {"GAMMA": 0.8}, _T + 1)
    _publish()
    served = _served()
    assert (served[_A]["gamma"], served[_B]["gamma"]) == (0.9, 0.8)


def test_a_released_contract_takes_its_next_rest_answer():
    """A contract the daemon stops streaming keeps its record; the sweep asks for it again, and
    Schwab's newer answer replaces what the stream had sent."""
    _daemon(held=[_A])
    _put_chain(fetched_ts=_T - 5.0)
    _streamed(_A, {"GAMMA": 0.9}, _T + 1)
    _daemon(held=[])                                   # the daemon no longer streams A
    requoted = dict(_CONTRACTS[0], quoteTimeInLong=int((_T + 2) * 1000))     # its next answer
    _publish([requoted], _T + 2)
    assert _as_sent(_served()[_A]) == requoted
    assert _cached()["_per_strike"] == compute_terrain(TK, [requoted] + _CONTRACTS[1:], _SPOT, now=_AT).per_strike


def test_a_volume_only_tick_reaches_the_per_strike_volume_column():
    _daemon(held=[_A])
    _put_chain(fetched_ts=_T - 5.0)
    _streamed(_A, {"TOTAL_VOLUME": 999999}, _T + 1)
    _publish()
    strike = round(_CONTRACTS[0]["strikePrice"], 2)
    row = next(r for r in _cached()["_per_strike"]["all"] if r[0] == strike)
    assert row[2] >= 999999


def test_a_streamed_value_whose_feed_is_down_in_session_stands_in_the_levels_marked_not_live():
    """docs/DATA_FLOW.md §2 D5, Schwab's socket closed (the daemon still reporting, holding TK and
    the contract): at 11:00 ET on 2026-10-07 (RTH by Schwab's /markets) and at 22:00 ET (Closed)
    the levels are priced at the last spot Schwab sent, the streamed volume in the per-strike
    column (operator 2026-10-14: "the last values stand, marked not live ... on every derived
    value"); in RTH the one judgment marks them not live, while Closed it does not. Before, the
    levels were not published in RTH."""
    import live_market_plane as lmp
    strike = round(_CONTRACTS[0]["strikePrice"], 2)
    out = {}
    for at in (datetime(2026, 10, 7, 11, 0, tzinfo=ET), datetime(2026, 10, 7, 22, 0, tzinfo=ET)):
        _LEDGER.clear()
        ofls.clear_all_live_state()
        _daemon(held=[_A], socket_open=False, at=at.timestamp())
        ledger_open(TK, _CONTRACTS, at.timestamp() - 120.0, _bus())
        _streamed(_A, {"TOTAL_VOLUME": 999999}, at.timestamp() - 60.0)
        server._publish_levels(TK, at.timestamp() - 120.0, now=at)
        out[at.hour] = (_cached(), lmp.outage(TK, "LEVELONE_EQUITIES", at.timestamp()))
    for hour, outage in ((11, "Schwab LEVELONE_EQUITIES feed down during RTH"), (22, None)):
        levels, judged = out[hour]
        row = next(r for r in levels["_per_strike"]["all"] if r[0] == strike)
        assert levels["spot"] == _SPOT and levels["_gamma_surface"] is not None and row[2] >= 999999
        assert judged == outage


def test_a_foreign_tickers_contract_never_prices_this_chain():
    foreign = "SPY   260911C00583000"
    _daemon(held=[foreign])
    _put_chain(fetched_ts=_T - 5.0)
    _streamed(foreign, {"GAMMA": 0.99}, _T + 1)
    _publish()
    assert [_as_sent(c) for c in _served().values()] == _CONTRACTS


# ── spot ─────────────────────────────────────────────────────────────────────────────────────

def test_a_moved_spot_reprices_every_view_at_the_new_spot():
    _daemon()
    _put_chain()
    before = _cached()["_gamma_surface"]
    _daemon(price=_SPOT * 1.02)
    _publish()
    after = _cached()
    assert after["_gamma_surface"]["spot"] == _SPOT * 1.02 and after["spot"] == _SPOT * 1.02
    assert after["_gamma_surface"]["cells"] != before["cells"]          # GEX scales with spot
    assert after["_gamma_surface"]["surface_seq"] == before["surface_seq"] + 1


# ── what is kept, and for whom ───────────────────────────────────────────────────────────────

def test_every_ticker_keeps_its_chain_and_heatmap_so_a_switch_shows_at_once():
    """2026-10-01, operator: "when i switch tickers the heatmap doesnt render right away". Every
    ticker's publication keeps its heatmap, viewed or not, and its records stay to reprice."""
    _daemon()
    _put_chain()                                                        # published while not viewed
    assert _cached()["_gamma_surface"]["cells"]
    assert _publish() is not None                                       # repriced from its records


def test_a_stored_capture_and_a_live_chain_publish_the_same_fields():
    """2026-09-28 audit: a publication from a stored capture (startup, a closed market) and one
    from a live chain served different fields and two labels for the same full chain."""
    _daemon()
    _put_chain()
    live = _cached()
    _publish(captures=[{"contracts": _CONTRACTS, "ts_utc": _T, "spot": _SPOT, "et_date": "2026-10-07",
                        "spot_trade_ts": int(_T * 1000) / 1000,      # the live spot's trade time
                        "basis": server.CAPTURE_BASIS}])
    stored = _cached()
    assert {k for k in live if not k.startswith("_")} == {k for k in stored if not k.startswith("_")}
    assert live["chain_basis"] == stored["chain_basis"] == server.CAPTURE_BASIS


def test_vanna_and_charm_by_strike_read_the_published_snapshot():
    """Valued in the chain's own session (2026-10-07 12:00 ET): its 2026-10-16 expiry still has
    time value, which charm needs."""
    valued = datetime(2026, 10, 7, 12, 0, tzinfo=ET)
    _daemon(at=valued.timestamp())                       # live when the chain is published
    ledger_open(TK, _CONTRACTS, _T, _bus())
    snap = server._publish_levels(TK, _T, now=valued)
    _daemon(at=time.time())                              # live now, as the routes read it
    charm = json.loads(server.get_charm_by_strike(TK, scope="all").body)
    assert charm["available"] and charm["spot"] == snap.spot
    assert len(charm["rows"]) == sum(1 for b in snap.charm_by_strike.values() if b.get("net_charm") is not None)
    vanna = json.loads(server.get_vanna_by_strike(TK, scope="all").body)
    assert vanna["available"] and vanna["rows"]


def test_a_reprice_on_a_kept_chain_keeps_the_chains_time():
    """Levels are as of the chain they come from: repricing a kept chain on a tick must not make
    them newer, or a chain that stops arriving would never show as stale."""
    _daemon()
    _put_chain(fetched_ts=_T - 600.0)
    _publish()
    assert _cached()["computed_ts_utc"] == _T - 600.0


def test_the_route_serves_the_publication_and_no_live_price_publishes_no_levels():
    """/api/terrain serves the levels exactly as the producer published them, none recomputed per
    request, their spot labelled by its source and time. The next publication with no live price
    has no levels, with its reason."""
    _daemon()
    _put_chain()
    published = _cached()
    _daemon(price=None)                                         # the price is no longer live
    out = server.get_terrain(ticker=TK)
    for k in ("spot", "regime", "net_gex_at_spot", "call_wall", "call_wall_state", "call_wall_lean",
              "dist_to_call_wall", "flip_relation", "headline"):
        assert out[k] == published[k], k
    assert "spot_state" not in out and out["spot_as_of_ts_utc"] == int(_T * 1000) / 1000   # Schwab's TRADE_TIME, in ms
    assert out["spot_source"] == server.SPOT_SOURCE_PLANE
    _put_chain()                                                # the next chain: no live price
    out = server.get_terrain(ticker=TK)
    assert out["regime"] == "UNAVAILABLE" and out["call_wall"] is None and out["error"] == "no spot price"


def test_an_unknown_gamma_at_spot_never_reads_as_short_gamma():
    """Measured 2026-09-26: with gamma at spot unknown, the regime read UNAVAILABLE while the
    headline said "Short gamma -- trend regime. Follow breaks" -- advice from nothing."""
    from terrain_read import GAMMA_FLIP_TRUSTED, build_terrain_read
    r = build_terrain_read(spot=100.0, flip=99.0, flip_confidence=GAMMA_FLIP_TRUSTED,
                           gamma_at_spot=None)
    assert r.regime == "UNAVAILABLE" and "gamma" not in r.headline.lower().split("—")[0]
    assert "Short gamma" not in r.headline and "Long gamma" not in r.headline


# ── the ticks and chains that reach the one pricing thread ───────────────────────────────────

def test_a_ticker_on_screen_reprices_on_its_ticks_its_options_included_and_a_burst_is_one_reprice(_clean):
    """A streamed tick on a viewed ticker, an equity quote or one of its options, queues one
    reprice of its kept chain; every tick that arrives while it waits is in that one reprice."""
    _daemon()
    _put_chain()
    _view(_clean)
    gate = _busy()
    try:
        server._on_stream_tick(_A)                              # an option of TK
        for _ in range(10):
            server._on_stream_tick(TK)
        with server._chains_waiting_lock:
            waiting = dict(server._chains_waiting)
    finally:
        gate.set()
        _drain()
    assert waiting == {TK: (server.REPRICE, None)}


def test_rounds_waiting_to_be_priced_keep_only_the_newest_of_each_ticker():
    """2026-10-01 audit: the pricing queue had no bound -- a sweep faster than pricing grew it
    without end. One round per ticker waits; a newer one replaces it."""
    ledger_open(TK, _CONTRACTS, _T, _bus())
    gate = _busy()
    try:
        for i in range(3):
            server._on_chain(TK, _T + i)
        with server._chains_waiting_lock:
            waiting = server._chains_waiting[TK]
    finally:
        gate.set()
        _drain()
    assert waiting == (server.DELIVERED, _T + 2)
    assert _cached()["computed_ts_utc"] == _T + 2


# ── the stored captures: the last session's levels stand, saved and labeled ─────────────────────

def _store(tk: str, ts: float, spot: float = _SPOT) -> None:
    """TK's chain as a full capture of `tk` in the console's database, one row per expiry."""
    by_expiry: dict = {}
    for ct in _CONTRACTS:
        by_expiry.setdefault(ct["expirationDate"][:10], []).append(ct)
    for expiry, cts in by_expiry.items():
        persist_complete_chain_capture(server.get_db().db_path, ticker=tk, expiry=expiry, contracts=cts,
                                       spot=spot, completeness_basis=CAPTURE_BASIS, ts_utc=ts)


def _forget(*tickers):
    with server._terrain_cache_lock:
        for tk in tickers:
            server._terrain_cache.pop(tk, None)


def test_startup_prices_the_newest_capture_with_its_own_price_and_time():
    """DATA_FLOW decision 7: after a restart, a weekend or the close, each watchlist ticker's
    newest full chain capture is priced once with Schwab's underlying price from that capture,
    valued and dated at the capture's time. A row that is not a full chain is never loaded."""
    tk = "ZZCAPSTART"
    _store(tk, _T)
    persist_complete_chain_capture(server.get_db().db_path, ticker=tk, expiry=_CONTRACTS[0]["expirationDate"][:10],
                                   contracts=_CONTRACTS[:2], spot=1.0, completeness_basis="strike_range=ALL",
                                   ts_utc=_T + 60)
    try:
        assert server._load_stored_levels([tk]) == 1
        _drain()
        with server._terrain_cache_lock:
            loaded = dict(server._terrain_cache[tk])
    finally:
        _forget(tk)
    assert loaded["computed_ts_utc"] == _T
    assert loaded["spot"] == _SPOT and loaded["spot_source"] == server.SPOT_SOURCE_CAPTURE
    expected = compute_terrain(tk, _CONTRACTS, _SPOT, now=_AT)
    assert expected.gamma_flip is not None, "the capture must price (valued at its own time)"
    for k in ("gamma_flip", "call_wall", "put_wall", "max_pain"):
        assert loaded[k] == getattr(expected, k), k


@pytest.mark.parametrize("delivered_first", [True, False])
def test_a_stored_capture_never_replaces_a_delivered_chain(delivered_first):
    """The startup load queues a ticker's stored capture only when the daemon has delivered no
    chain for it: delivered first, the capture is not queued; queued first and still waiting, the
    delivered chain replaces it. Either way the delivered chain is what is held."""
    tk = f"ZZCAPDELIV{int(delivered_first)}"
    _store(tk, _T - 86400)
    ledger_open(tk, _CONTRACTS, _T, _bus())
    gate = _busy()
    try:
        if delivered_first:
            server._on_chain(tk, _T)
            queued = server._load_stored_levels([tk])
        else:
            queued = server._load_stored_levels([tk])
            server._on_chain(tk, _T)                             # arrives while the capture waits
    finally:
        gate.set()
        _drain()
    try:
        with server._terrain_cache_lock:
            held = dict(server._terrain_cache[tk])
    finally:
        _forget(tk)
        with server._chains_waiting_lock:
            server._chains_delivered.discard(tk)
    assert queued == (0 if delivered_first else 1)
    assert held["_round_ts"] == held["computed_ts_utc"] == _T


def test_a_delivered_chain_is_priced_before_the_stored_ones_waiting():
    """The startup load queues every watchlist ticker's stored captures at once; a chain the
    daemon delivers meanwhile is priced ahead of them, not behind the load."""
    stored = ("ZZCAPWAITA", "ZZCAPWAITB")
    for tk in stored:
        _store(tk, _T)
    _forget(TK, *stored)
    ledger_open(TK, _CONTRACTS, _T, _bus())
    gate = _busy()
    try:
        assert server._load_stored_levels(list(stored)) == 2
        server._on_chain(TK, _T)
    finally:
        gate.set()
        _drain()
    try:
        with server._terrain_cache_lock:
            order = [tk for tk in server._terrain_cache if tk in (TK, *stored)]
    finally:
        _forget(*stored)
    assert order == [TK, *stored]


# ── the feed calls the one callback for exactly the ticks that move the math ────────────────

def test_every_option_message_recalculates_and_the_levels_price_the_daemons_record():
    """Real LEVELONE_OPTIONS messages (2026-10-05 14:00 CT) of one contract through the daemon's
    bus: Schwab sends a Change message only when a field changed (Streamer API §1.1), so each
    reaches the callback once, and the console holds the contract's one record (every field
    Schwab has sent, the last of each, named once: option_ledger.STREAM_FIELDS)."""
    options = [m for m in _MIX if m["service"] == "LEVELONE_OPTIONS"]
    sym = Counter(m["item"]["key"] for m in options).most_common(1)[0][0]
    mine = [m for m in options if m["item"]["key"] == sym]
    bus = MessageBus()
    hits: list = []
    ofs._on_tick_callback = hits.append                        # the console's callback, as start_order_flow_stream sets it
    try:
        through_the_daemons_bus(bus, sym, [m["item"] for m in mine], [m["ts_recv"] for m in mine])
    finally:
        ofs._on_tick_callback = None
    assert len(mine) > 1 and hits == [sym] * len(mine)
    merged: dict = {}
    for m in mine:
        merged.update(m["item"])
    assert ofls.contract(sym).fields == option_ledger.from_stream(merged, int(mine[-1]["ts_recv"] * 1000))
