"""One producer for a ticker's levels, per-strike rows and gamma-surface grid: _publish_levels
prices the chain once (overlaid with fresher streamed greeks, at the current spot) and publishes
all three together; _on_stream_tick reprices a viewed ticker, at most once per
LEVELS_REPRICE_MIN_INTERVAL_SEC, always pricing the last tick of a burst. Proven on a REAL
captured Schwab chain (tests/fixtures/real_crwd_complete_chain_quarter.json)."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import server
from math_exposure_core import merge_exposure_books
from stream_spine import options_quote_msg
from terrain_engine import compute_terrain

_FX = Path(__file__).resolve().parent / "fixtures"
_REAL = json.loads((_FX / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8"))
_SPOT = float(_REAL["spot"])
_CONTRACTS = [dict(ct) for ct in _REAL["chain"]]
_A = _CONTRACTS[0]["symbol"]
_B = _CONTRACTS[1]["symbol"]
TK = server.ticker_storage_key("CRWD")


def _put_chain(*, fetched_ts=None, viewed=True):
    with server._terrain_cache_lock:
        server._terrain_cache[TK] = {"_chain": _CONTRACTS,
                                     "_chain_fetched_ts": time.time() if fetched_ts is None else fetched_ts}
    if viewed:
        server._note_gamma_surface_demand(TK)
    else:
        server._gamma_surface_demand.pop(TK, None)


def _cached():
    with server._terrain_cache_lock:
        return dict(server._terrain_cache[TK])


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", 1.0))
    monkeypatch.setattr(server, "_is_loggable_session", lambda: True)   # the open market, unless a test closes it
    ofs._active_option_contract = _A
    ofs._active_option_contracts = [_B]
    yield
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    server._gamma_surface_demand.pop(TK, None)
    while not server._l1_sse_thread_queue.empty():
        server._l1_sse_thread_queue.get_nowait()
    ofs._active_option_contract = None
    ofs._active_option_contracts = []


def _stream(values: dict, monkeypatch):
    monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", lambda sym: values.get(sym))


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
    for row in surface["cells"]:
        cells = [g for g in row["gex"] if g is not None]
        if cells and full[row["strike"]].get("has_valid_gamma"):
            assert abs(sum(cells) - full[row["strike"]]["net_gex_1pct"]) <= len(cells)   # per-cell rounding


def test_published_levels_equal_compute_terrain_on_the_same_inputs(monkeypatch):
    _stream({}, monkeypatch)
    _put_chain()
    server._publish_levels(TK)
    expected = compute_terrain(TK, _CONTRACTS, _SPOT).to_dict()
    got = _cached()
    for k in ("gamma_flip", "call_wall", "put_wall", "absolute_gamma_strike", "max_pain",
              "net_gex_peak", "contracts_used"):
        assert got[k] == expected[k], k


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


def test_a_streamed_value_older_than_the_chains_own_quote_is_not_applied(monkeypatch):
    """The baseline is each contract's own vendor quote time (quoteTimeInLong)."""
    now = time.time()
    chain = [dict(_CONTRACTS[0], quoteTimeInLong=int(now * 1000))] + _CONTRACTS[1:]
    server._note_gamma_surface_demand(TK)
    _stream({_A: {"gamma": 0.9, "gamma_ts_recv": now - 1.0}}, monkeypatch)
    server._publish_levels(TK, chain, now)
    assert _cached()["_gamma_surface"]["stream_overlay_contracts"] == 0
    _stream({_A: {"gamma": 0.9, "gamma_ts_recv": now + 0.5}}, monkeypatch)
    server._publish_levels(TK, chain, now)
    assert _cached()["_gamma_surface"]["stream_overlay_contracts"] == 1


def test_a_stale_streamed_value_is_not_applied(monkeypatch):
    _put_chain(fetched_ts=time.time() - 60.0)
    _stream({_A: {"gamma": 0.9,
                  "gamma_ts_recv": time.time() - server.GAMMA_SURFACE_STREAM_STALENESS_SEC - 5}},
            monkeypatch)
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


def test_a_foreign_tickers_contract_never_overlays_this_chain(monkeypatch):
    foreign = "SPY   260911C00583000"
    ofs._active_option_contract = None
    ofs._active_option_contracts = [ofs.ticker_storage_key(foreign)]
    _put_chain(fetched_ts=time.time() - 5.0)
    _stream({foreign: {"gamma": 0.99, "gamma_ts_recv": time.time()}}, monkeypatch)
    assert server._desired_stream_greeks_for_ticker(TK) == {}
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

def test_an_unviewed_ticker_keeps_no_chain_and_gets_no_heatmap(monkeypatch):
    _stream({}, monkeypatch)
    server._gamma_surface_demand.pop(TK, None)
    server._publish_levels(TK, _CONTRACTS, time.time())
    c = _cached()
    assert c["_chain"] is None and c["_gamma_surface"] is None
    assert c["gamma_flip"] is not None or c["call_wall"] is not None     # levels still published
    assert server._publish_levels(TK) is None                            # nothing to reprice


def test_fields_the_terrain_loop_adds_survive_a_tick_reprice(monkeypatch):
    _stream({}, monkeypatch)
    _put_chain()
    server._publish_levels(TK)
    with server._terrain_cache_lock:
        server._terrain_cache[TK]["atr_daily"] = 4.2
        server._terrain_cache[TK]["delta_oi_walls"] = {"x": 1}
    server._publish_levels(TK)
    assert _cached()["atr_daily"] == 4.2 and _cached()["delta_oi_walls"] == {"x": 1}


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
    monkeypatch.setattr(server, "_touch_tracked_ticker_view", lambda tk: None)
    charm = json.loads(server.get_charm_by_strike(TK).body)
    assert charm["available"] and charm["spot"] == snap.spot
    assert len(charm["rows"]) == sum(1 for b in snap.charm_by_strike.values() if b.get("net_charm") is not None)
    vanna = json.loads(server.get_vanna_by_strike(TK).body)
    assert vanna["available"] and vanna["rows"]


# ── one at a time per ticker ─────────────────────────────────────────────────────────────────

def test_publications_for_one_ticker_never_overlap(monkeypatch):
    _stream({}, monkeypatch)
    _put_chain()
    active, peak = [0], [0]
    real = server.compute_terrain

    def slow(*a, **k):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        try:
            return real(*a, **k)
        finally:
            active[0] -= 1
    monkeypatch.setattr(server, "compute_terrain", slow)
    ts = [threading.Thread(target=server._publish_levels, args=(TK,)) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(10)
    assert peak[0] == 1


# ── the tick dispatcher ──────────────────────────────────────────────────────────────────────

def _count_publishes(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_publish_levels", lambda tk, *a: calls.append((tk, time.monotonic())))
    return calls


def _wait_idle(tk, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        with server._reprice_guard:
            if tk not in server._reprice_running:
                return
        time.sleep(0.01)
    raise AssertionError("reprice worker did not finish")


def test_a_tick_on_an_unviewed_ticker_reprices_nothing(monkeypatch):
    calls = _count_publishes(monkeypatch)
    server._gamma_surface_demand.pop("ZZUNVIEWED", None)
    server._on_stream_tick("ZZUNVIEWED")
    time.sleep(0.05)
    assert calls == []


def test_a_burst_of_ticks_reprices_at_most_once_per_interval_and_prices_the_last(monkeypatch):
    monkeypatch.setattr(server, "LEVELS_REPRICE_MIN_INTERVAL_SEC", 0.2)
    calls = _count_publishes(monkeypatch)
    server._note_gamma_surface_demand("ZZBURST")
    try:
        for _ in range(50):
            server._on_stream_tick("ZZBURST")
            time.sleep(0.002)
        _wait_idle("ZZBURST")
    finally:
        server._gamma_surface_demand.pop("ZZBURST", None)
    assert len(calls) == 2          # the first tick at once, the rest of the burst once, after
    assert calls[1][1] - calls[0][1] >= 0.2 - 0.01


def test_an_option_tick_reprices_its_underlying(monkeypatch):
    monkeypatch.setattr(server, "LEVELS_REPRICE_MIN_INTERVAL_SEC", 0.05)
    calls = _count_publishes(monkeypatch)
    _put_chain()
    server._on_stream_tick(_A)
    _wait_idle(TK)
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


# ── the closed market: the last session's levels stand, saved and labeled ─────────────────────

def test_a_publication_is_saved_and_a_restart_restores_it(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "SESSION_LEVELS_DIR", tmp_path)
    _stream({_A: {"gamma": 0.9, "gamma_ts_recv": time.time()}}, monkeypatch)
    _put_chain(fetched_ts=time.time() - 5.0)
    server._publish_levels(TK)
    published = _cached()
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK)
    assert server._load_session_levels() == 1
    restored = _cached()
    assert "_chain" not in restored, "the raw chain is not saved"
    for k in ("gamma_flip", "call_wall", "put_wall", "computed_ts_utc", "_per_strike",
              "_vanna_rows", "_charm_rows"):
        assert restored[k] == json.loads(json.dumps(published[k])), k
    # nothing has streamed a saved heatmap since it was saved
    states = {leg["state"] for cell in restored["_gamma_surface"]["cells"]
              for pair in cell["stream"] if pair for leg in pair.values() if isinstance(leg, dict)}
    assert "live" not in states


def test_while_closed_the_levels_are_the_last_sessions_labeled_with_their_time(monkeypatch):
    monkeypatch.setattr(server, "_is_loggable_session", lambda: False)
    fri_close = datetime(2026, 9, 25, 16, 29, tzinfo=ZoneInfo("America/New_York")).timestamp()
    st = server.terrain_staleness(fri_close, TK)
    assert st["levels_market_closed"] is True and st["levels_stale"] is False
    assert st["levels_as_of"] == "Fri 09/25 03:29 PM CT"
    assert st["levels_refresh_active"] is False and st["levels_failing"] is False


def test_a_tick_while_closed_reprices_nothing(monkeypatch):
    monkeypatch.setattr(server, "_is_loggable_session", lambda: False)
    calls = _count_publishes(monkeypatch)
    _put_chain()
    server._on_stream_tick("CRWD")
    time.sleep(0.05)
    assert calls == []
