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


def test_desired_not_yet_ticked_is_pending_not_unavailable():
    """Operator follow-up mandate (2026-09-16): a contract the daemon has genuinely
    REQUESTED from the vendor, but which has not produced its first tick (and was not
    rejected), is a materially different fact from "nobody asked for this contract at
    all" -- it must report 'pending', never fall into the same 'unavailable' bucket."""
    surf = _surface({"call": "AAA", "put": "BBB"})
    # Neither symbol has ever streamed (absent from `streamed`); both are desired.
    _stamp_gamma_surface_cell_stream_state(surf, {}, set(), None, {"AAA", "BBB"})
    col = surf["cells"][0]["stream"][0]
    assert col["call"]["state"] == "pending" and col["put"]["state"] == "pending"
    assert col["state"] == "pending"


def test_desired_symbol_reads_daemon_unavailable_not_pending_when_daemon_is_down():
    """Independent-review finding (2026-09-16, follow-up mandate): 'pending' used to mean
    only "the client desires this symbol" -- indistinguishable from a daemon that has
    silently died and will never admit anything. A DEAD daemon must read a materially
    different, more actionable state than 'still queued behind a live one'."""
    surf = _surface({"call": "AAA", "put": "BBB"})
    _stamp_gamma_surface_cell_stream_state(
        surf, {}, set(), None, {"AAA", "BBB"}, daemon_available=False)
    col = surf["cells"][0]["stream"][0]
    assert col["call"]["state"] == "daemon_unavailable"
    assert col["put"]["state"] == "daemon_unavailable"
    assert col["state"] == "daemon_unavailable"


def test_daemon_unavailable_never_reported_for_a_symbol_nobody_desired():
    # daemon_available=False must not turn EVERY never-desired symbol into
    # daemon_unavailable too -- it only applies to symbols actually desired.
    surf = _surface({"call": "AAA", "put": "BBB"})
    _stamp_gamma_surface_cell_stream_state(surf, {}, set(), None, set(), daemon_available=False)
    col = surf["cells"][0]["stream"][0]
    assert col["call"]["state"] == "unavailable" and col["put"]["state"] == "unavailable"


def test_pending_takes_priority_over_unavailable_but_not_over_stale_or_live():
    # One leg desired-but-never-ticked (pending), the other never desired (unavailable):
    # the cell aggregate must read 'pending', not 'unavailable'.
    surf = _surface({"call": "AAA", "put": "BBB"})
    _stamp_gamma_surface_cell_stream_state(surf, {}, set(), None, {"AAA"})
    col = surf["cells"][0]["stream"][0]
    assert col["call"]["state"] == "pending" and col["put"]["state"] == "unavailable"
    assert col["state"] == "pending"
    # A stale leg (has ticked before, just not fresh this cycle) still outranks pending.
    surf2 = _surface({"call": "AAA", "put": "BBB"})
    _stamp_gamma_surface_cell_stream_state(
        surf2, {"AAA": {"gamma_ts_recv": time.time() - 60}}, set(), None, {"AAA", "BBB"})
    col2 = surf2["cells"][0]["stream"][0]
    assert col2["call"]["state"] == "stale" and col2["put"]["state"] == "pending"
    assert col2["state"] == "stale"


def test_rejected_desired_symbol_reports_rejected_not_pending():
    # A symbol both desired AND vendor-rejected must read 'rejected' -- the vendor's own
    # explicit refusal is more informative than the generic "awaiting an outcome" pending
    # state, and rejected is checked before desired-but-absent in the leg classification.
    surf = _surface({"call": "AAA", "put": None})
    _stamp_gamma_surface_cell_stream_state(
        surf, {}, set(), {"AAA": "RuntimeError: refused"}, {"AAA"})
    col = surf["cells"][0]["stream"][0]
    assert col["call"]["state"] == "rejected"


def test_cell_state_counts_tallies_across_cells_and_columns():
    surf = _surface({"call": "AAA", "put": "BBB"}, {"call": "CCC", "put": None})
    surf["cells"].append({"strike": 9.0, "contracts": [{"call": None, "put": "DDD"}]})
    streamed = {"AAA": {"gamma_ts_recv": time.time()}, "BBB": {"gamma_ts_recv": time.time()},
                "CCC": {"gamma_ts_recv": time.time() - 99}}
    _stamp_gamma_surface_cell_stream_state(surf, streamed, {"AAA", "BBB"})
    counts = _gamma_surface_cell_state_counts(surf)
    # cell0: live (both legs live). cell1: stale (CCC desired, not overlaid). cell2: unavailable (DDD never desired).
    assert counts == {"live": 1, "partial": 0, "stale": 1, "pending": 0,
                       "daemon_unavailable": 0, "rejected": 0, "unavailable": 1}


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
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))

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
# Endpoint: /api/options/gamma-surface exposes cell_stream_state_counts / stream_coverage
# ---------------------------------------------------------------------------

def _call(tk):
    return json.loads(get_options_gamma_surface(tk).body)


def test_endpoint_reports_meets_live_requirement_true_when_every_visible_cell_is_live():
    """2026-09-16 audit finding #6: LIVE requires 100% of cells WITH a contract identity to
    be live -- a single-cell, single-contract surface where that one cell is live is the
    trivial case where the bar and the old (wrong) >=1 threshold happen to coincide."""
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
        assert "stream_confirmed_live" not in d, (
            "the dead, misleadingly-named field must be removed, not merely superseded")
        assert d["stream_coverage"]["meets_live_requirement"] is True
        assert d["stream_coverage"]["live_pct"] == 100.0
        assert d["cell_stream_state_counts"]["live"] == 1
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        server._GAMMA_SURFACE_CACHE.pop(tk, None)


def test_endpoint_reports_meets_live_requirement_false_when_no_cell_is_live():
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
        assert d["stream_coverage"]["meets_live_requirement"] is False
        assert d["stream_coverage"]["live_pct"] == 0.0
        assert d["cell_stream_state_counts"]["unavailable"] == 1
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        server._GAMMA_SURFACE_CACHE.pop(tk, None)


def test_endpoint_reports_meets_live_requirement_false_when_only_partial_coverage():
    """The core of audit finding #6: MORE than zero live cells, but not ALL of them, must
    still report meets_live_requirement=False -- the exact case the old >=1-cell threshold
    got wrong (it would have reported confirmed-live here)."""
    tk = ticker_storage_key("ZZZTEST_PARTIAL")
    surf = {"expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [10.0, 11.0],
            "cells": [
                {"strike": 10.0, "gex": [1.0], "contracts": [{"call": "X", "put": None}]},
                {"strike": 11.0, "gex": [1.0], "contracts": [{"call": "Y", "put": None}]},
            ],
            "contracts_total": 2, "contracts_used": 2, "contracts_excluded_malformed_expiry": 0,
            "gamma_available": True}
    # X is live-streaming; Y is desired but has never been confirmed fresh -- one of two
    # visible cells is live, the other merely 'stale'.
    _stamp_gamma_surface_cell_stream_state(
        surf, {"X": {"gamma_ts_recv": time.time()}, "Y": {"gamma_ts_recv": time.time() - 999}}, {"X"})
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 10.0,
                                      "spot_source": "last", "spot_as_of_ts_utc": time.time(), "chain_basis": "full"}
    try:
        d = _call(tk)
        cov = d["stream_coverage"]
        assert cov["total_visible_cells"] == 2
        assert cov["live"] == 1 and cov["stale"] == 1
        assert cov["live_pct"] == 50.0
        assert cov["meets_live_requirement"] is False, (
            "one live cell out of two must NOT satisfy the LIVE requirement"
        )
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        server._GAMMA_SURFACE_CACHE.pop(tk, None)


def test_endpoint_reports_pending_coverage_distinctly_and_excludes_it_from_live():
    """Operator follow-up mandate (2026-09-16): coverage disclosure must count live/
    partial/stale/PENDING/rejected/unavailable cells distinctly -- a pending contract
    (requested, no tick yet) must never count toward meets_live_requirement, and must
    never be silently folded into the unavailable bucket the client cannot act on."""
    tk = ticker_storage_key("ZZZTEST_PENDING")
    surf = {"expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [10.0, 11.0],
            "cells": [
                {"strike": 10.0, "gex": [1.0], "contracts": [{"call": "X", "put": None}]},
                {"strike": 11.0, "gex": [1.0], "contracts": [{"call": "Y", "put": None}]},
            ],
            "contracts_total": 2, "contracts_used": 2, "contracts_excluded_malformed_expiry": 0,
            "gamma_available": True}
    # X is live-streaming; Y has been requested (desired) but never ticked.
    _stamp_gamma_surface_cell_stream_state(
        surf, {"X": {"gamma_ts_recv": time.time()}}, {"X"}, None, {"X", "Y"})
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 10.0,
                                      "spot_source": "last", "spot_as_of_ts_utc": time.time(), "chain_basis": "full"}
    try:
        d = _call(tk)
        cov = d["stream_coverage"]
        assert cov["total_visible_cells"] == 2
        assert cov["live"] == 1 and cov["pending"] == 1
        assert cov["unavailable"] == 0, "the pending leg must not also be counted as unavailable"
        assert cov["meets_live_requirement"] is False, (
            "a pending (not-yet-confirmed) cell must NOT satisfy the LIVE requirement")
        assert d["cell_stream_state_counts"]["pending"] == 1
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        server._GAMMA_SURFACE_CACHE.pop(tk, None)


def test_endpoint_reports_daemon_unavailable_coverage_distinctly_from_pending():
    """Independent-review finding (2026-09-16, follow-up mandate): a desired-but-untouched
    contract while the capture daemon itself is unreachable must count in its OWN bucket,
    distinct from 'pending' (daemon alive, outcome merely not yet known) -- both must be
    excluded from meets_live_requirement, but conflating them hides an operator-actionable
    fact (restart the daemon) behind one that implies nothing is wrong (just wait)."""
    tk = ticker_storage_key("ZZZTEST_DAEMON_DOWN")
    surf = {"expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [10.0, 11.0],
            "cells": [
                {"strike": 10.0, "gex": [1.0], "contracts": [{"call": "X", "put": None}]},
                {"strike": 11.0, "gex": [1.0], "contracts": [{"call": "Y", "put": None}]},
            ],
            "contracts_total": 2, "contracts_used": 2, "contracts_excluded_malformed_expiry": 0,
            "gamma_available": True}
    # X is live-streaming; Y is desired but the daemon itself is confirmed unreachable.
    _stamp_gamma_surface_cell_stream_state(
        surf, {"X": {"gamma_ts_recv": time.time()}}, {"X"}, None, {"X", "Y"}, daemon_available=False)
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 10.0,
                                      "spot_source": "last", "spot_as_of_ts_utc": time.time(), "chain_basis": "full"}
    try:
        d = _call(tk)
        cov = d["stream_coverage"]
        assert cov["live"] == 1 and cov["daemon_unavailable"] == 1
        assert cov["pending"] == 0, "a daemon-down symbol must not also count as pending"
        assert cov["unavailable"] == 0, "a daemon-down symbol must not also count as unavailable"
        assert cov["meets_live_requirement"] is False
        assert d["cell_stream_state_counts"]["daemon_unavailable"] == 1
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        server._GAMMA_SURFACE_CACHE.pop(tk, None)


def test_rejected_contract_reports_a_distinct_state_not_generic_unavailable():
    """2026-09-16 audit finding #6/#1: a vendor-rejected contract must be visibly
    distinguishable from a merely never-requested one -- 'fail the affected cells
    visibly', not silently lump it into 'unavailable' forever."""
    tk = ticker_storage_key("ZZZTEST_REJECTED")
    surf = {"expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [10.0],
            "cells": [{"strike": 10.0, "gex": [None], "contracts": [{"call": "BADSYM", "put": None}]}],
            "contracts_total": 1, "contracts_used": 1, "contracts_excluded_malformed_expiry": 0,
            "gamma_available": False}
    _stamp_gamma_surface_cell_stream_state(surf, {}, set(), {"BADSYM": "RuntimeError: refused"})
    assert surf["cells"][0]["stream"][0]["state"] == "rejected"
    assert surf["cells"][0]["stream"][0]["call"]["rejected_reason"] == "RuntimeError: refused"
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 10.0,
                                      "spot_source": "last", "spot_as_of_ts_utc": time.time(), "chain_basis": "full"}
    try:
        d = _call(tk)
        assert d["cell_stream_state_counts"]["rejected"] == 1
        assert d["stream_coverage"]["rejected"] == 1
        assert d["stream_coverage"]["meets_live_requirement"] is False
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


def test_banked_morning_reference_never_reports_meets_live_requirement(tmp_path, monkeypatch):
    # REST-only reference path (RC-UI-1 fallback) must never claim confirmed-live coverage --
    # "REST may bootstrap or recover the surface, but it cannot satisfy the LIVE state." Uses the
    # same real-tmp-sqlite-db pattern as tests/test_gamma_exposure_honest_absence_v1.py.
    #
    # RC-REHAB-2 (2026-09-19): today_et used to come from the real wall clock, making this a
    # time bomb whenever real "today" landed on a weekend/holiday -- is_trading_day_et correctly
    # refuses a non-trading date as a morning reference, so the endpoint fell through to
    # available=False before this test's own assertions about stream-state counts ever ran
    # (MEASURED: real date is 2026-09-19, a Saturday). Freeze now_et to the same known trading
    # weekday already used by test_gamma_exposure_honest_absence_v1.py for this identical fix.
    from datetime import datetime as _dt

    from time_et import ET
    _FROZEN = _dt(2026, 7, 17, 10, 0, tzinfo=ET)
    monkeypatch.setattr(server, "now_et", lambda: _FROZEN)
    tk = ticker_storage_key("ZZZTEST3")
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    server._GAMMA_SURFACE_CACHE.pop(tk, None)

    db = tmp_path / "morning.db"
    today_et = _FROZEN.strftime("%Y-%m-%d")
    _seed_morning_full(db, "ZZZTEST3", today_et, time.time() - 1800.0, _SPOT, json.dumps(_CONTRACTS))
    monkeypatch.setattr(server, "get_db", lambda: _FakeDB(db))
    try:
        d = _call(tk)
        assert d["source"] == "banked_morning_reference"
        assert d["stream_coverage"]["meets_live_requirement"] is False
        assert d["cell_stream_state_counts"]["live"] == 0
        assert d["cell_stream_state_counts"]["unavailable"] > 0
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        server._GAMMA_SURFACE_CACHE.pop(tk, None)
