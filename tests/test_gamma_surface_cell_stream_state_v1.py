"""Always-live heatmap mandate (2026-09-15): every gamma-surface cell must carry per-leg
(call/put) evidence of whether it is CURRENTLY backed by a confirmed-fresh Schwab stream tick --
'live' (fresh streamed), 'stale' (desired/subscribed but not fresh right now), or 'unavailable'
(never desired -- covers unsubscribed, missing, and mismatched-identity contracts alike), rolled
up into a cell-level 'live' / 'partial' / 'stale' / 'unavailable' aggregate.

Proven directly against `_stamp_gamma_surface_cell_stream_state` /
`_gamma_surface_cell_state_counts` (the pure, in-place annotation functions — RC-80: they never
touch a cell's already-computed exposure value, only annotate it), against the real end-to-end
`refresh_gamma_surface_from_stream` path with a REAL captured chain fixture (matching this
repo's existing gamma-surface test convention, not invented contracts), and against
`/api/options/gamma-surface`'s own served JSON for both the live and banked-morning-reference
branches."""
from __future__ import annotations

import json
import time
from pathlib import Path

import server
from server import (
    _stamp_gamma_surface_cell_stream_state,
    _gamma_surface_cell_state_counts,
    get_options_gamma_surface,
    refresh_gamma_surface_from_stream,
    project_gamma_surface,
    ticker_storage_key,
)

_FX = Path(__file__).resolve().parent / "fixtures"
_REAL = json.loads((_FX / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8"))
_SPOT = float(_REAL["spot"])
_CONTRACTS = [dict(ct) for ct in _REAL["chain"]]
_CONTRACT_SYMBOL = _CONTRACTS[0]["symbol"]
_CONTRACT_SYMBOL_B = _CONTRACTS[1]["symbol"]
TK = ticker_storage_key("CRWD")


# ---------------------------------------------------------------------------
# Unit-level: _stamp_gamma_surface_cell_stream_state / _gamma_surface_cell_state_counts
# ---------------------------------------------------------------------------

def _surface(*rows):
    return {"cells": [{"strike": float(i), "contracts": [row]} for i, row in enumerate(rows)]}


def test_live_leg_requires_membership_in_overlay_symbols_this_cycle():
    surf = _surface({"call": "AAA", "put": "BBB"})
    streamed = {"AAA": {"gamma_ts_recv": time.time()}, "BBB": {"gamma_ts_recv": time.time()}}
    _stamp_gamma_surface_cell_stream_state(surf, streamed, {"AAA", "BBB"})
    col = surf["cells"][0]["stream"][0]
    assert col["call"]["state"] == "live" and col["put"]["state"] == "live"
    assert col["state"] == "live"
    assert col["call"]["ts_recv"] is not None and col["call"]["age_sec"] is not None


def test_desired_but_not_overlaid_this_cycle_is_stale_not_live():
    surf = _surface({"call": "AAA", "put": "BBB"})
    streamed = {"AAA": {"gamma_ts_recv": time.time() - 30.0}, "BBB": {"gamma_ts_recv": time.time() - 30.0}}
    _stamp_gamma_surface_cell_stream_state(surf, streamed, set())  # nothing passed this cycle's check
    col = surf["cells"][0]["stream"][0]
    assert col["call"]["state"] == "stale" and col["put"]["state"] == "stale"
    assert col["state"] == "stale"


def test_never_desired_is_unavailable_covers_unsubscribed_missing_mismatched():
    # "AAA"/"BBB" never appear in `streamed` at all -- exactly the shape of an unsubscribed,
    # never-streamed, or (since _desired_stream_greeks_for_ticker already filters by
    # contract_matches_underlying) mismatched-identity contract.
    surf = _surface({"call": "AAA", "put": "BBB"})
    _stamp_gamma_surface_cell_stream_state(surf, {}, set())
    col = surf["cells"][0]["stream"][0]
    assert col["call"]["state"] == "unavailable" and col["put"]["state"] == "unavailable"
    assert col["state"] == "unavailable"
    assert col["call"]["ts_recv"] is None and col["call"]["age_sec"] is None


def test_missing_contract_leg_is_absent_not_a_crash():
    # A strike/expiry with a call but genuinely no put in the chain.
    surf = _surface({"call": "AAA", "put": None})
    _stamp_gamma_surface_cell_stream_state(surf, {"AAA": {"gamma_ts_recv": time.time()}}, {"AAA"})
    col = surf["cells"][0]["stream"][0]
    assert col["call"]["state"] == "live"
    assert "put" not in col
    assert col["state"] == "live"   # the only leg that EXISTS is live


def test_mixed_call_live_put_unavailable_is_partial_not_live():
    surf = _surface({"call": "AAA", "put": "BBB"})
    _stamp_gamma_surface_cell_stream_state(surf, {"AAA": {"gamma_ts_recv": time.time()}}, {"AAA"})
    col = surf["cells"][0]["stream"][0]
    assert col["call"]["state"] == "live" and col["put"]["state"] == "unavailable"
    assert col["state"] == "partial"


def test_mixed_call_live_put_stale_is_partial():
    surf = _surface({"call": "AAA", "put": "BBB"})
    streamed = {"AAA": {"gamma_ts_recv": time.time()}, "BBB": {"gamma_ts_recv": time.time() - 60}}
    _stamp_gamma_surface_cell_stream_state(surf, streamed, {"AAA"})
    col = surf["cells"][0]["stream"][0]
    assert col["state"] == "partial"


def test_no_legs_at_all_is_unavailable():
    surf = _surface({"call": None, "put": None})
    _stamp_gamma_surface_cell_stream_state(surf, {}, set())
    col = surf["cells"][0]["stream"][0]
    assert col["state"] == "unavailable"


def test_cell_state_counts_tallies_across_cells_and_columns():
    surf = _surface({"call": "AAA", "put": "BBB"}, {"call": "CCC", "put": None})
    surf["cells"].append({"strike": 9.0, "contracts": [{"call": None, "put": "DDD"}]})
    streamed = {"AAA": {"gamma_ts_recv": time.time()}, "BBB": {"gamma_ts_recv": time.time()},
                "CCC": {"gamma_ts_recv": time.time() - 99}}
    _stamp_gamma_surface_cell_stream_state(surf, streamed, {"AAA", "BBB"})
    counts = _gamma_surface_cell_state_counts(surf)
    # cell0: live (both legs live). cell1: stale (CCC desired, not overlaid). cell2: unavailable (DDD never desired).
    assert counts == {"live": 1, "partial": 0, "stale": 1, "unavailable": 1}


# ---------------------------------------------------------------------------
# End-to-end: refresh_gamma_surface_from_stream stamps a REAL fixture-derived surface
# ---------------------------------------------------------------------------

def _clear_cache():
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)


def _put_rest_baseline(*, computed_ts_utc=None):
    ts = time.time() if computed_ts_utc is None else computed_ts_utc
    with server._terrain_cache_lock:
        server._terrain_cache[TK] = {
            "_contracts_rest": _CONTRACTS, "_contracts_rest_spot": _SPOT,
            "_contracts_rest_computed_ts": ts,
            "_gamma_surface": project_gamma_surface(_CONTRACTS, _SPOT),
            "computed_ts_utc": ts,
        }
    server._gamma_surface_seq.pop(TK, None)


def _drain_l1_sse_thread_queue():
    while not server._l1_sse_thread_queue.empty():
        try:
            server._l1_sse_thread_queue.get_nowait()
        except Exception:
            break


def setup_function(_fn):
    _clear_cache()
    _drain_l1_sse_thread_queue()
    import app.options.order_flow.streaming as _ofs
    _ofs._active_option_contract = _CONTRACT_SYMBOL
    _ofs._active_option_contracts = []


def teardown_function(_fn):
    _clear_cache()
    _drain_l1_sse_thread_queue()
    import app.options.order_flow.streaming as _ofs
    _ofs._active_option_contract = None
    _ofs._active_option_contracts = []


def test_eager_refresh_marks_the_ticking_contracts_own_cell_live(monkeypatch):
    _put_rest_baseline(computed_ts_utc=time.time() - 10.0)
    now = time.time()
    live = {_CONTRACT_SYMBOL: {"gamma": 0.05, "gamma_ts_recv": now}}
    monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", lambda sym: live.get(sym))

    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now) == "ok"
    with server._terrain_cache_lock:
        cells = server._terrain_cache[TK]["_gamma_surface"]["cells"]

    found_live = False
    for cell in cells:
        for col_idx, pair in enumerate(cell["contracts"]):
            if pair.get("call") == _CONTRACT_SYMBOL or pair.get("put") == _CONTRACT_SYMBOL:
                col = cell["stream"][col_idx]
                side = "call" if pair.get("call") == _CONTRACT_SYMBOL else "put"
                assert col[side]["state"] == "live"
                assert col[side]["age_sec"] is not None and col[side]["age_sec"] < 5.0
                found_live = True
    assert found_live, "fixture must contain the streamed symbol on at least one cell"


def test_rest_only_cycle_marks_desired_contract_stale_never_live(monkeypatch):
    # The contract is currently desired (primary slot, set in setup_function) but its own
    # streamed record is old enough to fail the staleness gate this cycle -- REST alone must
    # never present it as 'live'.
    _put_rest_baseline(computed_ts_utc=time.time())
    stale_ts = time.time() - 999.0
    live = {_CONTRACT_SYMBOL: {"gamma": 0.05, "gamma_ts_recv": stale_ts}}
    monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", lambda sym: live.get(sym))

    # Drive it through the same code path _terrain_refresh_one uses for stamping, without a
    # live vendor fetch: call the overlay + stamp directly, matching server.py's own sequence.
    from server import _gamma_surface_contracts_with_stream_overlay, _desired_stream_greeks_for_ticker
    overlaid, n, overlay_syms = _gamma_surface_contracts_with_stream_overlay(TK, _CONTRACTS, newer_than_ts=time.time())
    assert n == 0   # too stale to overlay at all
    surface = project_gamma_surface(overlaid, _SPOT)
    _stamp_gamma_surface_cell_stream_state(surface, _desired_stream_greeks_for_ticker(TK), set(overlay_syms))
    counts = _gamma_surface_cell_state_counts(surface)
    assert counts["live"] == 0
    assert counts["stale"] > 0   # the desired contract's own cell(s) show up as stale, not live


def test_dropped_contract_becomes_unavailable_not_lingering_stale(monkeypatch):
    import app.options.order_flow.streaming as _ofs
    from server import _gamma_surface_contracts_with_stream_overlay, _desired_stream_greeks_for_ticker
    _put_rest_baseline(computed_ts_utc=time.time())
    _ofs._active_option_contract = None   # coverage genuinely ended -- no longer desired at all
    monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", lambda sym: None)
    overlaid, n, overlay_syms = _gamma_surface_contracts_with_stream_overlay(TK, _CONTRACTS, newer_than_ts=time.time())
    surface = project_gamma_surface(overlaid, _SPOT)
    _stamp_gamma_surface_cell_stream_state(surface, _desired_stream_greeks_for_ticker(TK), set(overlay_syms))
    counts = _gamma_surface_cell_state_counts(surface)
    assert counts["live"] == 0 and counts["stale"] == 0
    assert counts["unavailable"] > 0


# ---------------------------------------------------------------------------
# Endpoint: /api/options/gamma-surface exposes cell_stream_state_counts / stream_confirmed_live
# ---------------------------------------------------------------------------

def _call(tk):
    return json.loads(get_options_gamma_surface(tk).body)


def test_endpoint_live_branch_reports_stream_confirmed_live_true_when_a_cell_is_live():
    tk = ticker_storage_key("ZZZTEST1")
    surf = {"expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [10.0],
            "cells": [{"strike": 10.0, "gex": [1.0], "contracts": [{"call": "X", "put": None}]}],
            "contracts_total": 1, "contracts_used": 1, "contracts_excluded_malformed_expiry": 0,
            "gamma_available": True}
    _stamp_gamma_surface_cell_stream_state(surf, {"X": {"gamma_ts_recv": time.time()}}, {"X"})
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 10.0,
                                      "spot_source": "last", "spot_as_of_ts_utc": time.time(), "chain_basis": "full"}
    try:
        d = _call(tk)
        assert d["stream_confirmed_live"] is True
        assert d["cell_stream_state_counts"]["live"] == 1
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        server._GAMMA_SURFACE_CACHE.pop(tk, None)


def test_endpoint_live_branch_reports_stream_confirmed_live_false_when_no_cell_is_live():
    tk = ticker_storage_key("ZZZTEST2")
    surf = {"expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [10.0],
            "cells": [{"strike": 10.0, "gex": [1.0], "contracts": [{"call": "X", "put": None}]}],
            "contracts_total": 1, "contracts_used": 1, "contracts_excluded_malformed_expiry": 0,
            "gamma_available": True}
    _stamp_gamma_surface_cell_stream_state(surf, {}, set())   # never desired
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 10.0,
                                      "spot_source": "last", "spot_as_of_ts_utc": time.time(), "chain_basis": "full"}
    try:
        d = _call(tk)
        assert d["stream_confirmed_live"] is False
        assert d["cell_stream_state_counts"]["unavailable"] == 1
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        server._GAMMA_SURFACE_CACHE.pop(tk, None)


class _FakeDB:
    def __init__(self, path):
        self.db_path = str(path)


def _seed_morning_full(path, ticker: str, et_date: str, ts_utc: float, spot: float, chain_json: str):
    import sqlite3
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE IF NOT EXISTS option_chain_morning_full ("
        "ticker TEXT, et_date TEXT, ts_utc REAL, spot REAL, n_contracts INT, "
        "n_expiries INT, max_dte REAL, chain_json TEXT, source TEXT)"
    )
    con.execute(
        "INSERT INTO option_chain_morning_full "
        "(ticker, et_date, ts_utc, spot, n_contracts, n_expiries, max_dte, chain_json, source) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (ticker, et_date, ts_utc, spot, 0, 0, None, chain_json, "test"),
    )
    con.commit()
    con.close()


def test_banked_morning_reference_never_reports_stream_confirmed_live(tmp_path, monkeypatch):
    # REST-only reference path (RC-UI-1 fallback) must never claim confirmed-live coverage --
    # "REST may bootstrap or recover the surface, but it cannot satisfy the LIVE state." Uses the
    # same real-tmp-sqlite-db pattern as tests/test_gamma_exposure_honest_absence_v1.py.
    from time_et import now_et
    tk = ticker_storage_key("ZZZTEST3")
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    server._GAMMA_SURFACE_CACHE.pop(tk, None)

    db = tmp_path / "morning.db"
    today_et = now_et().strftime("%Y-%m-%d")
    _seed_morning_full(db, "ZZZTEST3", today_et, time.time() - 1800.0, _SPOT, json.dumps(_CONTRACTS))
    monkeypatch.setattr(server, "get_db", lambda: _FakeDB(db))
    try:
        d = _call(tk)
        assert d["source"] == "banked_morning_reference"
        assert d["stream_confirmed_live"] is False
        assert d["cell_stream_state_counts"]["live"] == 0
        assert d["cell_stream_state_counts"]["unavailable"] > 0
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        server._GAMMA_SURFACE_CACHE.pop(tk, None)
