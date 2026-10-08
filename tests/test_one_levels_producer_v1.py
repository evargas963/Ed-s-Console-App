"""One producer for a ticker's levels, per-strike rows and gamma-surface grid: _publish_levels
prices the chain once (overlaid with the streamed values Schwab sent after it, at the current spot)
and publishes all three together, so no second producer can show a different number (question 2:
the screen shows it correctly and promptly; question 3: each value is the one computation's).

Through the real code: the daemon's status (live_market_plane.record_feed_heartbeat), its pushed
option messages applied by the console (streaming._ingest_pushed), its price row as the console
holds it (streaming._price_rows), the console's pages (push_changes), the pricing thread, the
chain captures in the console's database. Real data: CRWD's 2026-10-16 chain captured 2026-10-07
10:38:40 ET (tests/real_chains.py), valued at its capture.
STAND-INS (named): each streamed value of a CRWD contract (no CRWD contract was streamed in a
capture), and the daemon's status holding them.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import push_changes
import server
from calibration.complete_chain_capture import CAPTURE_BASIS, persist_complete_chain_capture
from math_exposure_core import bucket_metric, merge_exposure_books
from stream_spine import options_quote_msg
from terrain_engine import compute_terrain
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
    ofls.clear_all_live_state()
    lmp.record_feed_down()
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    with server._chains_waiting_lock:
        server._chains_delivered.discard(TK)
    yield pages
    for tk, page in pages:
        push_changes.unsubscribe(tk, page)
    ofls.clear_all_live_state()
    lmp.record_feed_down()
    ofs._price_rows.pop(TK, None)
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)


def _view(pages: list, tk: str = TK) -> None:
    """A page opens on `tk` (its /api/changes connection)."""
    pages.append((tk, push_changes.subscribe(tk)))


def _daemon(held=(), *, socket_open=True, price: "float | None" = _SPOT) -> None:
    """The daemon's status: Schwab's socket open, TK held on LEVELONE_EQUITIES and `held` on
    LEVELONE_OPTIONS; and TK's price row as the daemon pushes it (None: no price)."""
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": socket_open,
                               "held": {"LEVELONE_EQUITIES": [TK], "LEVELONE_OPTIONS": list(held)}})
    if price is None:
        ofs._price_rows.pop(TK, None)
    else:
        ofs._price_rows[TK] = {"ticker": TK, "spot": price, "trade_ts": _T}


def _streamed(sym: str, content: dict, ts: float) -> None:
    """One LEVELONE_OPTIONS message for `sym`, as the daemon pushes it."""
    ofs._ingest_pushed(f"optquote.{sym}", options_quote_msg(
        symbol=sym, content={"key": sym, **content}, src="schwab_options_l1", ts_recv=ts))


def _publish(chain=None, fetched_ts=None, **kw):
    return server._publish_levels(TK, chain, fetched_ts, now=_AT, **kw)


def _put_chain(fetched_ts=_T):
    """TK's chain as the console holds it after the daemon delivered it."""
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
            listed = [g for g, a in zip(row["gex"], row["absent"]["gex"]) if a != server.CELL_NOT_LISTED]
            assert sum(listed) == pytest.approx(total, rel=1e-9, abs=1e-6)
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


# ── streamed values: the newest Schwab sent wins, an older or a stopped one never does ──────────

def test_a_fresh_streamed_greek_reprices_levels_heatmap_and_rows():
    _daemon(held=[_A])
    _streamed(_A, {"GAMMA": 0.9}, _T)
    _put_chain(fetched_ts=_T - 5.0)
    c = _cached()
    assert c["_gamma_surface"]["stream_overlay_contracts"] == 1
    assert c["_gamma_surface"]["stream_overlay_symbols"] == [_A]
    overlaid = [dict(_CONTRACTS[0], gamma=0.9)] + _CONTRACTS[1:]
    assert c["_per_strike"] == compute_terrain(TK, overlaid, _SPOT, now=_AT).per_strike


def test_a_new_chain_does_not_turn_a_live_contracts_leg_stale():
    """ONE-05 (measured live 2026-09-28, MU 15:46 ET): each chain download made all 200 heatmap
    legs flip between live and stale while the feed stayed live. A leg's state is the feed's
    (live while the daemon holds the contract); its value is the newest Schwab sent: the chain's,
    fetched after the contract's last streamed change."""
    chain = [dict(_CONTRACTS[0], quoteTimeInLong=int(_T * 1000))] + _CONTRACTS[1:]   # a fresh chain
    _daemon(held=[_A])
    _streamed(_A, {"GAMMA": 0.9}, _T - 60.0)                                       # a minute ago
    _publish(chain, _T)
    surface = _cached()["_gamma_surface"]
    assert surface["stream_overlay_symbols"] == []                                   # the chain is newer
    legs = [col[side] for cell in surface["cells"] for col, pair in zip(cell["stream"], cell["contracts"])
            for side in ("call", "put") if pair.get(side) == _A and col]
    assert legs and all(leg["state"] == "live" for leg in legs)


def test_a_streamed_value_applies_by_its_time():
    """A streamed gamma received after the chain is the newest Schwab sent: it reprices the
    levels; one received before the chain does not."""
    _daemon(held=[_A])
    _streamed(_A, {"GAMMA": 0.9}, _T - 60.0)
    _put_chain(fetched_ts=_T - 120.0)
    assert _cached()["_gamma_surface"]["stream_overlay_symbols"] == [_A]
    _put_chain(fetched_ts=_T - 30.0)
    assert _cached()["_gamma_surface"]["stream_overlay_contracts"] == 0


def test_every_streamed_contract_is_overlaid_not_only_the_one_that_ticked():
    _daemon(held=[_A, _B])
    _streamed(_A, {"GAMMA": 0.9}, _T)
    _streamed(_B, {"GAMMA": 0.8}, _T)
    _put_chain(fetched_ts=_T - 5.0)
    assert sorted(_cached()["_gamma_surface"]["stream_overlay_symbols"]) == sorted([_A, _B])


def test_repeated_reprices_start_from_the_raw_chain_never_a_prior_overlay():
    _daemon(held=[_A])
    _streamed(_A, {"GAMMA": 0.9}, _T)
    _put_chain(fetched_ts=_T - 5.0)
    _daemon(held=[])                                   # the daemon no longer streams A
    _publish()
    c = _cached()
    assert c["_chain"] is _CONTRACTS and _CONTRACTS[0].get("gamma") != 0.9
    assert c["_gamma_surface"]["stream_overlay_contracts"] == 0
    assert c["_per_strike"] == compute_terrain(TK, _CONTRACTS, _SPOT, now=_AT).per_strike


def test_a_volume_only_tick_reaches_the_per_strike_volume_column():
    _daemon(held=[_A])
    _streamed(_A, {"TOTAL_VOLUME": 999999}, _T)
    _put_chain(fetched_ts=_T - 5.0)
    strike = round(_CONTRACTS[0]["strikePrice"], 2)
    row = next(r for r in _cached()["_per_strike"]["all"] if r[0] == strike)
    assert row[2] >= 999999


def test_a_streamed_value_whose_feed_is_down_in_session_never_reaches_the_levels():
    """docs/DATA_FLOW.md §2 D5, Schwab's socket closed (the daemon still reporting, holding TK and
    the contract): at 11:00 ET on 2026-10-07 (RTH by Schwab's /markets) nothing streamed is
    current -- the spot is absent with its reason, and no level is published from a value from
    elsewhere; at 22:00 ET (Closed) the values as of the close stand, the streamed volume in the
    per-strike column."""
    strike = round(_CONTRACTS[0]["strikePrice"], 2)
    out = {}
    for at in (datetime(2026, 10, 7, 11, 0, tzinfo=ET), datetime(2026, 10, 7, 22, 0, tzinfo=ET)):
        ofls.clear_all_live_state()
        _daemon(held=[_A], socket_open=False)
        _streamed(_A, {"TOTAL_VOLUME": 999999}, at.timestamp() - 60.0)
        server._publish_levels(TK, _CONTRACTS, at.timestamp() - 120.0, now=at)
        out[at.hour] = _cached()
    rth, closed = out[11], out[22]
    assert rth["spot"] is None and rth["spot_source"] == "Schwab LEVELONE_EQUITIES feed down during RTH"
    assert rth["_gamma_surface"] is None and rth["gamma_flip"] is None
    row = next(r for r in closed["_per_strike"]["all"] if r[0] == strike)
    assert closed["spot"] == _SPOT and row[2] >= 999999


def test_a_foreign_tickers_contract_never_overlays_this_chain():
    foreign = "SPY   260911C00583000"
    _daemon(held=[foreign])
    _streamed(foreign, {"GAMMA": 0.99}, _T)
    _put_chain(fetched_ts=_T - 5.0)
    assert server._streamed_greeks_for_ticker(_cached()["_contract_symbols"]) == {}
    assert _cached()["_gamma_surface"]["stream_overlay_contracts"] == 0


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
    ticker's publication keeps its chain and its heatmap, viewed or not."""
    _daemon()
    _put_chain()                                                        # published while not viewed
    c = _cached()
    assert c["_chain"] and c["_gamma_surface"]["cells"]
    assert _publish() is not None                                       # repriced from its kept chain


def test_a_stored_capture_and_a_live_chain_publish_the_same_fields():
    """2026-09-28 audit: a publication from a stored capture (startup, a closed market) and one
    from a live chain served different fields and two labels for the same full chain."""
    _daemon()
    _put_chain()
    live = _cached()
    _publish(captures=[{"contracts": _CONTRACTS, "ts_utc": _T, "spot": _SPOT, "et_date": "2026-10-07",
                        "basis": server.CAPTURE_BASIS}])
    stored = _cached()
    assert {k for k in live if not k.startswith("_")} == {k for k in stored if not k.startswith("_")}
    assert live["chain_basis"] == stored["chain_basis"] == server.CAPTURE_BASIS


def test_vanna_and_charm_by_strike_read_the_published_snapshot():
    """Valued in the chain's own session (2026-10-07 12:00 ET): its 2026-10-16 expiry still has
    time value, which charm needs."""
    _daemon()
    snap = server._publish_levels(TK, _CONTRACTS, _T, now=datetime(2026, 10, 7, 12, 0, tzinfo=ET))
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
    assert "spot_state" not in out and out["spot_as_of_ts_utc"] == _T
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
    assert waiting == {TK: (server.REPRICE, None, None)}


def test_chains_waiting_to_be_priced_keep_only_the_newest_of_each_ticker():
    """2026-10-01 audit: the pricing queue had no bound -- a sweep faster than pricing grew it
    without end. One chain per ticker waits; a newer one replaces it."""
    gate = _busy()
    try:
        for i in range(3):
            server._on_chain(TK, _CONTRACTS, _T + i)
        with server._chains_waiting_lock:
            waiting = server._chains_waiting[TK]
    finally:
        gate.set()
        _drain()
    assert waiting[0] == server.DELIVERED and waiting[2] == _T + 2
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
    gate = _busy()
    try:
        if delivered_first:
            server._on_chain(tk, _CONTRACTS, _T)
            queued = server._load_stored_levels([tk])
        else:
            queued = server._load_stored_levels([tk])
            server._on_chain(tk, _CONTRACTS, _T)                 # arrives while the capture waits
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
    assert held["_chain_fetched_ts"] == held["computed_ts_utc"] == _T


def test_a_delivered_chain_is_priced_before_the_stored_ones_waiting():
    """The startup load queues every watchlist ticker's stored captures at once; a chain the
    daemon delivers meanwhile is priced ahead of them, not behind the load."""
    stored = ("ZZCAPWAITA", "ZZCAPWAITB")
    for tk in stored:
        _store(tk, _T)
    _forget(TK, *stored)
    gate = _busy()
    try:
        assert server._load_stored_levels(list(stored)) == 2
        server._on_chain(TK, _CONTRACTS, _T)
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

def _real_option(with_greek: bool) -> dict:
    """A real LEVELONE_OPTIONS message (2026-10-05 14:00 CT) carrying a value the levels use
    (GAMMA, DELTA, OPEN_INTEREST, TOTAL_VOLUME, VOLUME), or none of them."""
    used = {"GAMMA", "DELTA", "OPEN_INTEREST", "TOTAL_VOLUME", "VOLUME"}
    return next(m for m in _MIX if m["service"] == "LEVELONE_OPTIONS"
                and bool(used & set(m["item"])) is with_greek and "BID_PRICE" in m["item"])


@pytest.mark.parametrize("with_greek", [True, False])
def test_an_option_quote_reaches_the_callback_only_when_it_moves_the_math(with_greek):
    m = _real_option(with_greek)
    hits: list = []
    ofs._on_tick_callback = hits.append                        # the console's callback, as start_order_flow_stream sets it
    try:
        ofs._ingest_pushed(f"optquote.{m['item']['key']}", options_quote_msg(
            symbol=m["item"]["key"], content=m["item"], src="schwab_options_l1", ts_recv=m["ts_recv"]))
    finally:
        ofs._on_tick_callback = None
    assert hits == ([m["item"]["key"]] if with_greek else [])
