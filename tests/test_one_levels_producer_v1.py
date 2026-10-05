"""One producer for a ticker's levels, per-strike rows and gamma-surface grid: _publish_levels
prices the chain once (overlaid with fresher streamed greeks, at the current spot) and publishes
all three together; _on_stream_tick reprices a viewed ticker, back to back, always pricing the
last tick of a burst. Proven on a REAL
captured Schwab chain (tests/fixtures/real_crwd_complete_chain_quarter.json)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import push_changes
import server
from math_exposure_core import bucket_metric, merge_exposure_books
from stream_spine import options_quote_msg
from terrain_engine import compute_terrain

_FX = Path(__file__).resolve().parent / "fixtures"
_REAL = json.loads((_FX / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8"))
_SPOT = float(_REAL["spot"])
_CONTRACTS = [dict(ct) for ct in _REAL["chain"]]
_A = _CONTRACTS[0]["symbol"]
_B = _CONTRACTS[1]["symbol"]
TK = server.ticker_storage_key("CRWD")



@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    """The CRWD and CDE complete chains were captured 2026-09-02 (10:05 ET for CDE)."""
    return pin_clock(2026, 9, 2, 10, 5)

def _put_chain(*, fetched_ts=None, viewed=True):
    with server._terrain_cache_lock:
        server._terrain_cache[TK] = {"_chain": _CONTRACTS,
                                     "_contract_symbols": frozenset(c["symbol"] for c in _CONTRACTS),
                                     "_chain_fetched_ts": time.time() if fetched_ts is None else fetched_ts}
    push_changes._open[:] = [(t, c) for t, c in push_changes._open if t != TK]
    if viewed:
        push_changes.subscribe(TK)                  # a page open on the ticker


def _cached():
    with server._terrain_cache_lock:
        return dict(server._terrain_cache[TK])


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", 1.0))
    monkeypatch.setattr(push_changes, "_open", [])                       # no page open
    monkeypatch.setattr(push_changes, "_loop", None)                     # changes recorded, not delivered
    ofs._active_option_contract = _A
    ofs._active_option_contracts = [_B]
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)                              # this test's levels only
    with server._chains_waiting_lock:
        server._chains_delivered.discard(TK)                             # no chain delivered yet
    monkeypatch.setattr(server, "_screen_priced_last", False)           # no pricing yet
    yield
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    ofs._active_option_contract = None
    ofs._active_option_contracts = []


def _stream(values: dict, monkeypatch, held=None):
    """Streamed option values, and the daemon's heartbeat holding `held` (default: every
    streamed contract) on LEVELONE_OPTIONS -- what a live daemon streaming them reports."""
    monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", lambda sym: values.get(sym))
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "held": {
        "LEVELONE_OPTIONS": list(values if held is None else held)}})


# ── one computation behind every view ────────────────────────────────────────────────────────

def test_heatmap_per_strike_rows_and_levels_are_one_computation(monkeypatch):
    _stream({}, monkeypatch)
    _put_chain()
    snap = server._publish_levels(TK)
    c = _cached()
    assert c["_per_strike"] is snap.per_strike and c["_vanna_rows"] == server._vanna_rows(snap)
    assert c["gamma_flip"] == snap.gamma_flip and c["call_wall"] == snap.call_wall
    full, _ = merge_exposure_books(snap.books.values())
    surface = c["_gamma_surface"]
    # every strike's cells across expiries sum to the one full book the levels were picked from
    checked = 0
    for row in surface["cells"]:
        total = bucket_metric(full[row["strike"]], "net_gex_1pct")
        if total is not None:       # every listed expiry's cell known: they sum to it, unrounded
            listed = [g for g, a in zip(row["gex"], row["absent"]["gex"]) if a != server.CELL_NOT_LISTED]
            assert sum(listed) == pytest.approx(total, rel=1e-9, abs=1e-6)
            checked += 1
    assert checked


def test_the_terrain_endpoint_serves_a_published_ticker_as_json_without_internal_fields(monkeypatch):
    """2026-09-26: the payload carried the snapshot object and /api/terrain served the whole
    entry -- HTTP 500 for every published ticker, and the kept chain on every poll."""
    from fastapi.testclient import TestClient
    _stream({}, monkeypatch)
    _put_chain()
    snap = server._publish_levels(TK)
    r = TestClient(server.app).get(f"/api/terrain?ticker={TK}")
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert snap.gamma_flip is not None, "the chain must price (valued at its capture)"
    assert body["call_wall"] == snap.call_wall and body["gamma_flip"] == snap.gamma_flip
    assert not [k for k in body if k.startswith("_")]


# ── streamed greeks: fresher wins, older or stale never does, nothing compounds ──────────────

def test_a_fresh_streamed_greek_reprices_levels_heatmap_and_rows(monkeypatch):
    _put_chain(fetched_ts=time.time() - 5.0)
    _stream({_A: {"gamma": 0.9, "gamma_ts_recv": time.time()}}, monkeypatch)
    server._publish_levels(TK)
    c = _cached()
    assert c["_gamma_surface"]["stream_overlay_contracts"] == 1
    assert c["_gamma_surface"]["stream_overlay_symbols"] == [_A]
    overlaid = [dict(_CONTRACTS[0], gamma=0.9)] + _CONTRACTS[1:]
    assert c["_per_strike"] == compute_terrain(TK, overlaid, _SPOT).per_strike


def test_a_new_chain_does_not_turn_a_live_contracts_leg_stale(monkeypatch):
    """ONE-05 (measured live 2026-09-28, MU 15:46 ET): each chain download made all 200 heatmap
    legs flip between live and stale while the feed stayed live. A leg's state is the feed's
    (live while the daemon holds the contract); its value is the newest Schwab sent: the chain's,
    fetched after the contract's last streamed change (coordinator review of #433/#434,
    2026-10-01)."""
    now = time.time()
    chain = [dict(_CONTRACTS[0], quoteTimeInLong=int(now * 1000))] + _CONTRACTS[1:]   # a fresh chain
    push_changes.subscribe(TK)                                                         # a page open on it
    ofs._active_option_contract = _A                                                   # the operator's contract
    _stream({_A: {"gamma": 0.9, "gamma_ts_recv": now - 60.0}}, monkeypatch)          # last change a minute ago
    server._publish_levels(TK, chain, now)
    surface = _cached()["_gamma_surface"]
    assert surface["stream_overlay_symbols"] == []                                   # the chain is newer
    legs = [col[side] for cell in surface["cells"] for col, pair in zip(cell["stream"], cell["contracts"])
            for side in ("call", "put") if pair.get(side) == _A and col]
    assert legs and all(leg["state"] == "live" for leg in legs)


def test_a_streamed_value_applies_by_its_time(monkeypatch):
    """A streamed gamma received after the chain is the newest Schwab sent: it reprices the
    levels; one received before the chain does not. (Its feed down:
    test_a_streamed_value_whose_feed_is_down_in_session_never_reaches_the_levels.)"""
    _put_chain(fetched_ts=time.time() - 120.0)
    _stream({_A: {"gamma": 0.9, "gamma_ts_recv": time.time() - 60.0}}, monkeypatch)
    server._publish_levels(TK)
    assert _cached()["_gamma_surface"]["stream_overlay_symbols"] == [_A]
    _stream({_A: {"gamma": 0.9, "gamma_ts_recv": time.time() - 600.0}}, monkeypatch)
    server._publish_levels(TK)
    assert _cached()["_gamma_surface"]["stream_overlay_contracts"] == 0


def test_every_desired_contract_is_overlaid_not_only_the_one_that_ticked(monkeypatch):
    _put_chain(fetched_ts=time.time() - 5.0)
    now = time.time()
    _stream({_A: {"gamma": 0.9, "gamma_ts_recv": now}, _B: {"gamma": 0.8, "gamma_ts_recv": now}},
            monkeypatch)
    server._publish_levels(TK)
    assert sorted(_cached()["_gamma_surface"]["stream_overlay_symbols"]) == sorted([_A, _B])


def test_repeated_reprices_start_from_the_raw_chain_never_a_prior_overlay(monkeypatch):
    _put_chain(fetched_ts=time.time() - 5.0)
    _stream({_A: {"gamma": 0.9, "gamma_ts_recv": time.time()}}, monkeypatch)
    server._publish_levels(TK)
    _stream({}, monkeypatch)                    # the stream for A ended
    server._publish_levels(TK)
    c = _cached()
    assert c["_chain"] is _CONTRACTS and _CONTRACTS[0].get("gamma") != 0.9
    assert c["_gamma_surface"]["stream_overlay_contracts"] == 0
    assert c["_per_strike"] == compute_terrain(TK, _CONTRACTS, _SPOT).per_strike


def test_a_volume_only_tick_reaches_the_per_strike_volume_column(monkeypatch):
    _put_chain(fetched_ts=time.time() - 5.0)
    _stream({_A: {"total_volume": 999999.0, "total_volume_ts_recv": time.time()}}, monkeypatch)
    server._publish_levels(TK)
    strike = round(_CONTRACTS[0]["strikePrice"], 2)
    row = next(r for r in _cached()["_per_strike"]["all"] if r[0] == strike)
    assert row[2] >= 999999


def test_a_streamed_value_whose_feed_is_down_in_session_never_reaches_the_levels(monkeypatch):
    """docs/DATA_FLOW.md §2 D5: the contract's LEVELONE_OPTIONS feed down (the daemon holds
    none), at 11:00 ET on 2026-09-30 its streamed volume is not current and the chain's stands;
    at 22:00 ET (Closed) the streamed value as of the close reaches the per-strike column."""
    strike = round(_CONTRACTS[0]["strikePrice"], 2)
    for now, reaches in ((1790780400.0, False), (1790820000.0, True)):
        monkeypatch.setattr(time, "time", lambda now=now: now)
        _put_chain(fetched_ts=now - 5.0)
        _stream({_A: {"total_volume": 999999.0, "total_volume_ts_recv": now}}, monkeypatch, held=[])
        server._publish_levels(TK)
        row = next(r for r in _cached()["_per_strike"]["all"] if r[0] == strike)
        assert (row[2] >= 999999) is reaches


def test_a_foreign_tickers_contract_never_overlays_this_chain(monkeypatch):
    foreign = "SPY   260911C00583000"
    ofs._active_option_contract = None
    ofs._active_option_contracts = [ofs.ticker_storage_key(foreign)]
    _put_chain(fetched_ts=time.time() - 5.0)
    _stream({foreign: {"gamma": 0.99, "gamma_ts_recv": time.time()}}, monkeypatch)
    assert server._desired_stream_greeks_for_ticker(_cached()["_contract_symbols"]) == {}
    server._publish_levels(TK)
    assert _cached()["_gamma_surface"]["stream_overlay_contracts"] == 0


# ── spot ─────────────────────────────────────────────────────────────────────────────────────

def test_a_moved_spot_reprices_every_view_at_the_new_spot(monkeypatch):
    _stream({}, monkeypatch)
    _put_chain()
    server._publish_levels(TK)
    before = _cached()["_gamma_surface"]
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT * 1.02, "stub", 2.0))
    server._publish_levels(TK)
    after = _cached()
    assert after["_gamma_surface"]["spot"] == _SPOT * 1.02 and after["spot"] == _SPOT * 1.02
    assert after["_gamma_surface"]["cells"] != before["cells"]          # GEX scales with spot
    assert after["_gamma_surface"]["surface_seq"] == before["surface_seq"] + 1


# ── what is kept, and for whom ───────────────────────────────────────────────────────────────

def test_every_ticker_keeps_its_chain_and_heatmap_so_a_switch_shows_at_once(monkeypatch):
    """2026-10-01, operator: "when i switch tickers the heatmap doesnt render right away". Only a
    viewed ticker kept its chain and got a heatmap, so a ticker put on screen showed none until
    its chain was fetched again. Every ticker's publication keeps its chain and its heatmap."""
    _stream({}, monkeypatch)
    server._publish_levels(TK, _CONTRACTS, time.time())                 # published while not viewed
    c = _cached()
    assert c["_chain"] and c["_gamma_surface"] is not None
    assert c["_gamma_surface"]["cells"]
    assert server._publish_levels(TK) is not None                        # repriced from its kept chain


def test_a_stored_capture_and_a_live_chain_publish_the_same_fields(monkeypatch):
    """2026-09-28 audit: ATR was set only after a live download (then the console's fetch), so every
    publication from a stored capture (startup, a closed market) served it absent for every
    ticker, and the chain basis carried two labels for the same full chain ("full" live, the
    capture's own label stored). The one producer sets them all."""
    from terrain_atr import AtrPair
    _stream({}, monkeypatch)
    monkeypatch.setattr(server, "_atr_pair", lambda tk: AtrPair(4.2, 0.7))
    now = time.time()
    server._publish_levels(TK, _CONTRACTS, now)
    live = _cached()
    capture = {"contracts": _CONTRACTS, "ts_utc": now, "spot": _SPOT, "et_date": "2026-09-02",
               "basis": server.CAPTURE_BASIS}
    server._publish_levels(TK, captures=[capture])
    stored = _cached()
    public = {k for k in live if not k.startswith("_")}
    assert public == {k for k in stored if not k.startswith("_")}
    for c in (live, stored):
        assert (c["atr_daily"], c["atr_15m"]) == (4.2, 0.7)
        assert c["chain_basis"] == server.CAPTURE_BASIS


def test_vanna_and_charm_by_strike_read_the_published_snapshot(monkeypatch):
    import time_et
    from datetime import datetime
    from zoneinfo import ZoneInfo
    # the fixture chain's own session: its 2026-09-18 expiry still has time value (charm needs T)
    monkeypatch.setattr(time_et, "now_et",
                        lambda *a, **k: datetime(2026, 9, 11, 12, 0, tzinfo=ZoneInfo("America/New_York")))
    _stream({}, monkeypatch)
    _put_chain()
    snap = server._publish_levels(TK)
    charm = json.loads(server.get_charm_by_strike(TK, scope="all").body)
    assert charm["available"] and charm["spot"] == snap.spot
    assert len(charm["rows"]) == sum(1 for b in snap.charm_by_strike.values() if b.get("net_charm") is not None)
    vanna = json.loads(server.get_vanna_by_strike(TK, scope="all").body)
    assert vanna["available"] and vanna["rows"]


# ── one at a time ────────────────────────────────────────────────────────────────────────────

def _drain():
    """Wait until the pricing thread has priced everything waiting, ticks it queued included."""
    while True:
        server._chain_pricing.submit(lambda: None).result(timeout=60)
        with server._chains_waiting_lock:
            if not server._chains_waiting:
                return


def test_publications_never_overlap(monkeypatch):
    """Ticks and delivered chains, from the event loop and any thread, are priced one at a time."""
    _stream({}, monkeypatch)
    _put_chain()
    push_changes.subscribe(TK)
    active, peak = [0], [0]
    real = server.compute_terrain

    def slow(*a, **k):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        time.sleep(0.02)
        try:
            return real(*a, **k)
        finally:
            active[0] -= 1
    monkeypatch.setattr(server, "compute_terrain", slow)
    ts = [threading.Thread(target=server._on_stream_tick, args=(TK,)) for _ in range(4)]
    ts.append(threading.Thread(target=server._on_chain, args=(TK, _CONTRACTS, time.time())))
    for t in ts:
        t.start()
    for t in ts:
        t.join(10)
    _drain()
    assert peak[0] == 1


# ── the tick dispatcher ──────────────────────────────────────────────────────────────────────

def _count_publishes(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_publish_levels",
                        lambda tk, *a: calls.append((tk, time.monotonic())) or True)   # published
    return calls


def test_a_ticker_put_on_screen_reprices_from_its_kept_chain(monkeypatch):
    """Switching tickers: the ticker's chain is already held (every publication keeps it), so its
    first tick reprices it at once. The console fetches nothing: the chain comes from the daemon."""
    _stream({}, monkeypatch)
    server._publish_levels(TK, _CONTRACTS, time.time())                 # published while not viewed
    push_changes.subscribe(TK)                                           # the operator switches to it
    server._on_stream_tick(TK)
    _drain()
    assert _cached()["_gamma_surface"] is not None


def test_a_tick_on_an_unviewed_ticker_reprices_nothing(monkeypatch):
    calls = _count_publishes(monkeypatch)
    server._on_stream_tick("ZZUNVIEWED")
    time.sleep(0.05)
    assert calls == []


def test_a_burst_of_ticks_reprices_back_to_back_and_prices_the_last(monkeypatch):
    """No wait between reprices: the ticks that arrive while one reprice runs are all in the
    next, which is already waiting when it ends (the pricing thread takes it at once)."""
    calls = []

    def slow_publish(tk, *a):
        n = sum(1 for c in calls if c[0] == "start")
        calls.append(("start", n))
        if n < 3:                                        # quotes arrive while it reprices
            for _ in range(10):
                server._on_stream_tick("ZZBURST")
        with server._chains_waiting_lock:
            calls.append(("end", tk in server._chains_waiting))
        return True
    monkeypatch.setattr(server, "_publish_levels", slow_publish)
    push_changes.subscribe("ZZBURST")
    server._on_stream_tick("ZZBURST")
    _drain()
    assert calls == [("start", 0), ("end", True), ("start", 1), ("end", True),
                     ("start", 2), ("end", True), ("start", 3), ("end", False)], \
        "each reprice's ten ticks are one next reprice, already waiting when it ends"


def test_an_option_tick_reprices_its_underlying(monkeypatch):
    calls = _count_publishes(monkeypatch)
    _put_chain()
    push_changes.subscribe(TK)
    server._on_stream_tick(_A)
    _drain()
    assert calls and calls[0][0] == TK


# ── the feed calls the one callback for exactly the ticks that move the math ────────────────

_SPY_OPT = "SPY   260820C00767000"
_GREEKS = {"key": _SPY_OPT, "BID_PRICE": 1.26, "ASK_PRICE": 1.28, "LAST_PRICE": 1.27,
           "TOTAL_VOLUME": 44994, "OPEN_INTEREST": 2097, "DELTA": 0.456}
_BID_ASK = {"key": _SPY_OPT, "BID_PRICE": 1.30, "ASK_PRICE": 1.32, "LAST_PRICE": 1.31}


def _optquote(content):
    ofs._ingest_pushed(f"optquote.{_SPY_OPT}", options_quote_msg(
        symbol=_SPY_OPT, content=content, src="schwab_options_l1", ts_recv=1700000000.0))


@pytest.mark.parametrize("content,called", [(_GREEKS, True), (_BID_ASK, False),
                                            ({**_BID_ASK, "TOTAL_VOLUME": 5}, True)])
def test_an_option_quote_reaches_the_callback_only_when_it_moves_the_math(monkeypatch, content, called):
    hits = []
    monkeypatch.setattr(ofs, "_on_tick_callback", hits.append)
    ofls.clear_all_live_state()
    _optquote(content)
    assert hits == ([_SPY_OPT] if called else [])


def test_an_option_quote_lands_in_state_with_no_callback(monkeypatch):
    monkeypatch.setattr(ofs, "_on_tick_callback", None)
    ofls.clear_all_live_state()
    _optquote(_GREEKS)
    assert any(i.get("LAST_PRICE") == 1.27 for i in ofls.get_content_for_symbol(_SPY_OPT))



def test_a_reprice_on_a_kept_chain_keeps_the_chains_time(monkeypatch):
    """Levels are as of the chain they come from: repricing a kept chain on a tick must not make
    them newer, or a chain that stops arriving would never show as stale."""
    fetched = time.time() - 600.0
    _put_chain(fetched_ts=fetched)
    server._publish_levels(TK)
    assert _cached()["computed_ts_utc"] == fetched


def test_the_route_serves_the_publication_and_no_live_price_publishes_no_levels(monkeypatch):
    """/api/terrain serves the levels exactly as the producer published them -- every at-spot
    value from the publication, none recomputed per request. Their spot is the price they were
    computed at, labelled by its source and time and never called live (it can be a minute old
    while the ticker's feed is live). The next publication with no live price has no levels,
    with its reason."""
    from app.options.order_flow import streaming as ofs_mod
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, server.SPOT_SOURCE_PLANE, 1.0))
    server._publish_levels(TK, _CONTRACTS, time.time())
    published = _cached()
    monkeypatch.setattr(ofs_mod, "_price_rows", {})              # the price is no longer live
    out = server.get_terrain(ticker=TK)
    for k in ("spot", "regime", "net_gex_at_spot", "call_wall", "call_wall_state", "call_wall_lean",
              "dist_to_call_wall", "flip_relation", "headline"):
        assert out[k] == published[k], k
    assert "spot_state" not in out and out["spot_as_of_ts_utc"] == 1.0
    assert out["spot_source"] == server.SPOT_SOURCE_PLANE
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (None, "none", None))
    server._publish_levels(TK, _CONTRACTS, time.time())          # the next chain: no live price
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


# ── the chains the daemon delivers ─────────────────────────────────────────────────────────────

def _board_is(board):
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "board": list(board)})


@pytest.mark.parametrize("delivered_first", [True, False])
def test_a_stored_capture_never_replaces_a_delivered_chain(monkeypatch, tmp_path, _at_capture, delivered_first):
    """The startup load queues the stored capture on the one pricing thread, and only for a
    ticker the daemon has delivered no chain for: delivered first, the capture is not queued;
    queued first and still waiting, the delivered chain replaces it. Either way the delivered
    chain is what is held, and no live chain waits behind the whole stored load."""
    from calibration.complete_chain_capture import CAPTURE_BASIS, persist_complete_chain_capture
    from db import EdDB
    db, taken = tmp_path / "ed_console.db", _at_capture.timestamp()
    by_expiry: dict = {}
    for ct in _CONTRACTS:
        by_expiry.setdefault(ct["expirationDate"][:10], []).append(ct)
    for expiry, cts in by_expiry.items():
        persist_complete_chain_capture(db, ticker=TK, expiry=expiry, contracts=cts, spot=_SPOT,
                                       completeness_basis=CAPTURE_BASIS, ts_utc=taken - 86400)
    edb = EdDB(db)
    monkeypatch.setattr(server, "get_db", lambda: edb)
    live = taken
    gate = threading.Event()
    server._chain_pricing.submit(gate.wait, 10)                 # the pricing thread is busy
    if delivered_first:
        server._on_chain(TK, _CONTRACTS, live)
        assert server._load_stored_levels([TK]) == 0
    else:
        assert server._load_stored_levels([TK]) == 1
        server._on_chain(TK, _CONTRACTS, live)                  # arrives while the capture waits
    gate.set()
    server._chain_pricing.submit(lambda: None).result(timeout=60)
    held = _cached()
    assert held["_chain_fetched_ts"] == held["computed_ts_utc"] == live


def test_chains_waiting_to_be_priced_keep_only_the_newest_of_each_ticker(monkeypatch):
    """2026-10-01 audit: the pricing queue had no bound -- a sweep faster than pricing grew it
    without end. One chain per ticker waits; a newer one replaces it."""
    _board_is([TK])
    priced: list = []
    real = server._publish_levels
    monkeypatch.setattr(server, "_publish_levels", lambda tk, c=None, ts=None, **k: priced.append(ts) or real(tk, c, ts, **k))
    gate = threading.Event()
    server._chain_pricing.submit(gate.wait, 10)                 # the pricing thread is busy
    now = time.time()
    for i in range(3):
        server._on_chain(TK, _CONTRACTS, now + i)
    gate.set()
    server._chain_pricing.submit(lambda: None).result(timeout=60)
    assert priced == [now + 2]


def test_the_ticker_on_screens_chain_takes_the_next_turn(monkeypatch):
    """The ticker on screen, the same ticker the daemon fetches first, takes the next turn when it
    did not take the last: its chain is priced ahead of chains that arrived before it, a page open
    on another ticker included."""
    priced: list = []
    monkeypatch.setattr(server, "_price_chain", lambda tk, what, c, ts: priced.append(tk))
    push_changes.subscribe("ZZA")                                # an older page on ZZA
    push_changes.subscribe(TK)                                   # the newest page: CRWD on screen
    gate = threading.Event()
    server._chain_pricing.submit(gate.wait, 10)                 # the pricing thread is busy
    now = time.time()
    for tk in ("ZZA", "ZZB", TK):
        server._on_chain(tk, _CONTRACTS, now)
    gate.set()
    server._chain_pricing.submit(lambda: None).result(timeout=60)
    assert priced == [TK, "ZZA", "ZZB"]


def test_a_ticker_repriced_on_every_tick_takes_every_other_turn(monkeypatch):
    """In market hours the ticker on screen is ticked faster than it can be repriced (every
    equity quote moves it). The chains the daemon delivers for the others are priced between its
    reprices, never behind them: before, its reprices held the console's one core and every
    other ticker's levels fell minutes behind."""
    priced: list = []

    def price(tk, what, c, ts):
        priced.append((tk, what))
        if tk == TK and len(priced) < 12:
            server._on_stream_tick(TK)                           # the next quote, mid-reprice
    monkeypatch.setattr(server, "_price_chain", price)
    push_changes.subscribe(TK)                                   # CRWD on screen
    gate = threading.Event()
    server._chain_pricing.submit(gate.wait, 10)                 # the pricing thread is busy
    server._on_stream_tick(TK)
    for tk in ("ZZA", "ZZB", "ZZC"):
        server._on_chain(tk, _CONTRACTS, time.time())
    gate.set()
    _drain()
    R, D = server.REPRICE, server.DELIVERED
    assert priced[:6] == [(TK, R), ("ZZA", D), (TK, R), ("ZZB", D), (TK, R), ("ZZC", D)]


def test_a_failed_reprice_keeps_the_chains_own_reason(monkeypatch):
    """A reprice of the held chain that fails is logged; the ticker's reason stays the one its
    chain gave (here: the daemon's fetch failed), never replaced by the reprice's."""
    def boom(tk, *a, **k):
        raise RuntimeError("reprice boom")
    monkeypatch.setattr(server, "_publish_levels", boom)
    monkeypatch.setitem(server._terrain_refresh_last_error, TK, "chain fetch failed (HTTP 429)")
    server._price_chain(TK, server.REPRICE, None, None)
    assert server._terrain_refresh_last_error[TK] == "chain fetch failed (HTTP 429)"


def test_a_delivered_chain_is_priced_before_the_stored_ones_waiting(monkeypatch):
    """The startup load queues every board ticker's stored captures at once; a chain the daemon
    delivers meanwhile, for a ticker off screen, is priced ahead of them, not behind the load."""
    priced: list = []
    monkeypatch.setattr(server, "_price_chain", lambda tk, what, c, ts: priced.append((tk, what == server.DELIVERED)))
    for tk in ("ZZC", "ZZD"):
        server._chains_delivered.discard(tk)
    gate = threading.Event()
    server._chain_pricing.submit(gate.wait, 10)                 # the pricing thread is busy
    assert server._load_stored_levels(["ZZC", "ZZD"]) == 2
    server._on_chain(TK, _CONTRACTS, time.time())               # CRWD is not on screen
    gate.set()
    server._chain_pricing.submit(lambda: None).result(timeout=60)
    assert priced == [(TK, True), ("ZZC", False), ("ZZD", False)]


def test_the_ticker_on_screen_is_the_newest_open_page(monkeypatch):
    """One rule: the ticker on screen is the newest page still open, and the books, the chain
    fetched first and the option contract all follow it, in the order the pages open and close."""
    import asyncio
    followed: list = []
    monkeypatch.setattr(server, "_follow_screen_contract", lambda: followed.append(push_changes.on_screen()))

    async def open_page(tk):
        stream = (await server.get_changes(ticker=tk)).body_iterator
        await stream.__anext__()                            # the page's connection is streaming
        return stream

    async def go():
        a = await open_page("AAA")                          # a page opens on AAA ...
        b = await open_page("BBB")                          # ... a second page on BBB
        assert ofs.current_wanted()["active"] == "BBB" and ofs.current_wanted()["NYSE_BOOK"] == ["BBB"]
        await b.aclose()                                    # the BBB page closes
        assert ofs.current_wanted()["active"] == "AAA"
        await a.aclose()                                    # the last page closes
    monkeypatch.setattr(push_changes, "_open", [])
    asyncio.run(go())
    assert followed == ["AAA", "BBB", "AAA", None], "the option contract follows in the same order"
    assert ofs.current_wanted()["active"] is None and ofs.current_wanted()["NYSE_BOOK"] == []


def test_a_page_whose_open_fails_is_closed(monkeypatch):
    """A listener of the open failing still closes the page: it is not left the ticker on screen
    with no client."""
    import asyncio
    monkeypatch.setattr(push_changes, "_open", [])

    def broken():
        raise RuntimeError("listener failed")
    monkeypatch.setattr(server, "_follow_screen_contract", broken)

    async def go():
        stream = (await server.get_changes(ticker="AAA")).body_iterator
        with pytest.raises(RuntimeError):
            await stream.__anext__()
    asyncio.run(go())
    assert push_changes.on_screen() is None


def test_a_listener_registered_again_replaces_its_own(monkeypatch):
    """A module that registers its listener again (a second import of server) replaces it: every
    change of the ticker on screen runs it once."""
    monkeypatch.setattr(push_changes, "_open", [])
    monkeypatch.setattr(push_changes, "_screen_listeners", {})
    heard: list = []

    def listener(old, new):
        heard.append(new)
    push_changes.on_screen_change(listener)
    push_changes.on_screen_change(listener)
    push_changes.subscribe("AAA")
    assert heard == ["AAA"]


def test_a_manual_contract_admitted_before_a_ticker_switch_is_superseded(monkeypatch):
    """2026-10-01 audit: the operator's contract POST for one ticker, landing after the screen
    moved to another, installed the old ticker's contract under the new one."""
    _stream({}, monkeypatch)
    server._publish_levels(TK, _CONTRACTS, time.time())         # TK's chain: its default contract
    ofs._active_option_contract = None
    manual = ofs.begin_option_contract_command()                # a POST admitted for another ticker
    push_changes.subscribe(TK)                                  # then the screen moves to TK
    chosen = ofs.get_active_option_contract()
    assert server._contract_is_for(chosen, TK)
    with pytest.raises(ofs.StaleOptionCommandError):
        ofs.set_active_option_contract("SPY   261120C00875000", command_generation=manual)
    assert ofs.get_active_option_contract() == chosen


def test_a_ticker_opened_before_its_chain_gets_its_contract_when_the_chain_comes(monkeypatch):
    """2026-10-01 audit: a ticker opened before its chain was held got no option contract, and
    none was chosen when the chain arrived, until the page reopened."""
    _stream({}, monkeypatch)
    ofs._active_option_contract = None
    push_changes.subscribe(TK)                                  # the page is open; no chain yet
    assert ofs.get_active_option_contract() is None
    server._publish_levels(TK, _CONTRACTS, time.time())         # the daemon's chain is priced
    push_changes._mark(TK, push_changes.CHAIN)                  # (on the event loop)
    assert server._contract_is_for(ofs.get_active_option_contract(), TK)


def test_an_unknown_board_is_said_so():
    """2026-10-01 audit: with the daemon's heartbeat late, the board is unknown, never empty."""
    lmp.record_feed_down()
    assert "BOARD UNKNOWN" in server._status_line()
