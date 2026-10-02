"""Always-live heatmap mandate (2026-09-15): every gamma-surface cell must carry per-leg
(call/put) evidence of whether it is CURRENTLY backed by a confirmed-fresh Schwab stream tick --
'live' (fresh streamed), 'stale' (desired/subscribed but not fresh right now), or 'unavailable'
(never desired -- covers unsubscribed, missing, and mismatched-identity contracts alike), rolled
up into a cell-level 'live' / 'partial' / 'stale' / 'unavailable' aggregate.

Proven directly against `_stamp_gamma_surface_cell_stream_state` (it never touches a cell's
computed exposure value, only annotates it), against the real end-to-end `_publish_levels` path
with a REAL captured chain fixture, and through `/api/options/gamma-surface`'s served view (the
header's count of the window's cells)."""
from __future__ import annotations

import pytest

import json
import time
from pathlib import Path

import live_market_plane as lmp
import server
from server import (
    _stamp_gamma_surface_cell_stream_state,
    get_options_gamma_surface,
    _publish_levels,
    ticker_storage_key,
)

_FX = Path(__file__).resolve().parent / "fixtures"
_REAL = json.loads((_FX / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8"))
_SPOT = float(_REAL["spot"])
_CONTRACTS = [dict(ct) for ct in _REAL["chain"]]
_CONTRACT_SYMBOL = _CONTRACTS[0]["symbol"]
TK = ticker_storage_key("CRWD")


# ---------------------------------------------------------------------------
# Unit-level: _stamp_gamma_surface_cell_stream_state / _stream_coverage
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    """Valued at the stored chain's capture (2026-09-02), so its expiries passing never change
    what this test measures."""
    return pin_clock(2026, 9, 2, 10, 5)

def _surface(*rows):
    return {"expirations": [{"expiry": "2026-09-11"}],
            "cells": [{"strike": float(i), "contracts": [row]} for i, row in enumerate(rows)]}


def _states(cov):
    return {k: cov[k] for k in ("live", "partial", "stale", "pending", "daemon_unavailable",
                                "rejected", "unavailable")}


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
    # never-streamed, or (since _desired_stream_greeks_for_ticker keeps only contracts Schwab
    # listed in the ticker's chain) another ticker's contract.
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
    surf["strikes"] = [c["strike"] for c in surf["cells"]]
    surf["cells"].sort(key=lambda c: c["strike"])
    surf["strikes"].sort()
    tk = ticker_storage_key("ZZZTALLY")
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 10.0}
    try:
        counts = _states(_call(tk))
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
    # cell0: live (both legs live). cell1: stale (CCC desired, not overlaid). cell2: unavailable (DDD never desired).
    assert counts == {"live": 1, "partial": 0, "stale": 1, "pending": 0,
                       "daemon_unavailable": 0, "rejected": 0, "unavailable": 1}


# ---------------------------------------------------------------------------
# End-to-end: _publish_levels stamps a REAL fixture-derived surface
# ---------------------------------------------------------------------------

def _clear_cache():
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)


def _put_chain(view, *, fetched_ts=None):
    """A viewed ticker (a page open on it) whose chain the terrain loop fetched at `fetched_ts`."""
    with server._terrain_cache_lock:
        server._terrain_cache[TK] = {
            "_chain": _CONTRACTS,
            "_contract_symbols": frozenset(c["symbol"] for c in _CONTRACTS),
            "_chain_fetched_ts": time.time() if fetched_ts is None else fetched_ts,
        }
    view(TK)
    server._gamma_surface_seq.pop(TK, None)


def _published_surface():
    with server._terrain_cache_lock:
        return server._terrain_cache[TK]["_gamma_surface"]


def setup_function(_fn):
    _clear_cache()
    import app.options.order_flow.streaming as _ofs
    _ofs._active_option_contract = _CONTRACT_SYMBOL
    _ofs._active_option_contracts = []


def teardown_function(_fn):
    _clear_cache()
    import app.options.order_flow.streaming as _ofs
    _ofs._active_option_contract = None
    _ofs._active_option_contracts = []


def _daemon_holds(*symbols):
    """The daemon's heartbeat: Schwab socket open, these contracts held on LEVELONE_OPTIONS."""
    lmp.record_feed_heartbeat({"schwab_socket_open": True,
                               "held": {"LEVELONE_OPTIONS": list(symbols)}}, time.time())


def test_a_fresh_tick_marks_the_ticking_contracts_own_cell_live(monkeypatch, view):
    _put_chain(view, fetched_ts=time.time() - 10.0)
    now = time.time()
    _daemon_holds(_CONTRACT_SYMBOL)
    live = {_CONTRACT_SYMBOL: {"gamma": 0.05, "gamma_ts_recv": now}}
    monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", lambda sym: live.get(sym))
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))

    assert _publish_levels(TK) is not None
    cells = _published_surface()["cells"]

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


def test_a_desired_contract_the_daemon_no_longer_holds_is_stale_never_live(monkeypatch, view):
    # The contract is desired (primary slot, set in setup_function) and ticked a second ago, but
    # the daemon no longer holds it: its leg reads stale (the feed is not delivering it), and its
    # streamed gamma, newer than the chain, is still the value Schwab last sent.
    _put_chain(view, fetched_ts=time.time() - 10.0)
    _daemon_holds()
    live = {_CONTRACT_SYMBOL: {"gamma": 0.05, "gamma_ts_recv": time.time()}}
    monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", lambda sym: live.get(sym))
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))

    _publish_levels(TK)
    surface = _published_surface()
    assert surface["stream_overlay_contracts"] == 1   # the newest value Schwab sent
    counts = _call(TK)
    assert counts["live"] == 0
    assert counts["stale"] > 0


def test_dropped_contract_becomes_unavailable_not_lingering_stale(monkeypatch, view):
    import app.options.order_flow.streaming as _ofs
    _put_chain(view)
    _ofs._active_option_contract = None   # coverage genuinely ended -- no longer desired at all
    monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", lambda sym: None)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))

    _publish_levels(TK)
    counts = _call(TK)
    assert counts["live"] == 0 and counts["stale"] == 0
    assert counts["unavailable"] > 0


# ---------------------------------------------------------------------------
# Endpoint: /api/options/gamma-surface's view.coverage (the heatmap header's chip)
# ---------------------------------------------------------------------------

def _call(tk, expiry=None):
    """The coverage of every strike drawn (scope All) in every column, or the one `expiry`."""
    body = json.loads(get_options_gamma_surface(tk, scope="all", centre=None, shift=0, cols=None,
                                                expiry=expiry).body)
    return body["view"]["coverage"]


def test_endpoint_reads_all_streaming_when_every_cell_on_screen_is_live():
    """2026-09-16 audit finding #6: ALL STREAMING requires 100% of cells WITH a contract
    identity to be live -- a single-cell surface where that one cell is live is the trivial
    case where the bar and the old (wrong) >=1 threshold coincide."""
    tk = ticker_storage_key("ZZZTEST1")
    surf = {"expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [10.0],
            "cells": [{"strike": 10.0, "gex": [1.0], "contracts": [{"call": "X", "put": None}]}],
            "contracts_total": 1, "contracts_used": 1, "contracts_excluded_malformed_expiry": 0}
    _stamp_gamma_surface_cell_stream_state(surf, {"X": {"gamma_ts_recv": time.time()}}, {"X"})
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 10.0,
                                      "spot_source": "last", "spot_as_of_ts_utc": time.time(), "chain_basis": "full"}
    try:
        d = _call(tk)
        assert d["state"] == server.COVERAGE_LIVE and d["live_pct"] == 100 and d["live"] == 1
        assert d["label"] == "ALL STREAMING" and d["title"] == "all 1 cells streaming"
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def test_endpoint_reads_zero_streaming_when_no_cell_is_live():
    tk = ticker_storage_key("ZZZTEST2")
    surf = {"expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [10.0],
            "cells": [{"strike": 10.0, "gex": [1.0], "contracts": [{"call": "X", "put": None}]}],
            "contracts_total": 1, "contracts_used": 1, "contracts_excluded_malformed_expiry": 0}
    _stamp_gamma_surface_cell_stream_state(surf, {}, set())   # never desired
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 10.0,
                                      "spot_source": "last", "spot_as_of_ts_utc": time.time(), "chain_basis": "full"}
    try:
        d = _call(tk)
        assert d["state"] == server.COVERAGE_PARTIAL and d["live_pct"] == 0
        assert d["unavailable"] == 1 and d["label"] == "0% STREAMING"
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def test_endpoint_reads_partial_when_only_some_cells_are_live():
    """The core of audit finding #6: MORE than zero live cells, but not ALL of them, is never
    ALL STREAMING -- the exact case the old >=1-cell threshold got wrong."""
    tk = ticker_storage_key("ZZZTEST_PARTIAL")
    surf = {"expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [10.0, 11.0],
            "cells": [
                {"strike": 10.0, "gex": [1.0], "contracts": [{"call": "X", "put": None}]},
                {"strike": 11.0, "gex": [1.0], "contracts": [{"call": "Y", "put": None}]},
            ],
            "contracts_total": 2, "contracts_used": 2, "contracts_excluded_malformed_expiry": 0}
    # X is live-streaming; Y is desired but has never been confirmed fresh -- one of two
    # visible cells is live, the other merely 'stale'.
    _stamp_gamma_surface_cell_stream_state(
        surf, {"X": {"gamma_ts_recv": time.time()}, "Y": {"gamma_ts_recv": time.time() - 999}}, {"X"})
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 10.0,
                                      "spot_source": "last", "spot_as_of_ts_utc": time.time(), "chain_basis": "full"}
    try:
        cov = _call(tk)
        assert cov["cells"] == 2
        assert cov["live"] == 1 and cov["stale"] == 1
        assert cov["live_pct"] == 50 and cov["state"] == server.COVERAGE_PARTIAL
        assert cov["label"] == "50% STREAMING" and cov["title"] == "1 of 2 cells streaming · 1 stale"
        assert _call(tk, expiry="2026-09-11")["live_pct"] == 50
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


@pytest.mark.parametrize("live, words", [(299, "99% STREAMING"), (1, "<1% STREAMING")])
def test_the_chip_never_claims_more_or_less_than_streams(live, words):
    """2026-10-01 review: rounded, 299 of 300 live cells read "100% STREAMING" (as if all were)
    and 1 of 300 read "0%" (as if none were)."""
    tk = ticker_storage_key("ZZZTEST_SHARE")
    syms = [f"S{i}" for i in range(300)]
    surf = {"expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [float(i) for i in range(300)],
            "cells": [{"strike": float(i), "gex": [1.0], "contracts": [{"call": s, "put": None}]}
                      for i, s in enumerate(syms)]}
    _stamp_gamma_surface_cell_stream_state(surf, {s: {"gamma_ts_recv": time.time()} for s in syms}, set(syms[:live]))
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 10.0}
    try:
        cov = _call(tk)
        assert (cov["live"], cov["cells"], cov["label"]) == (live, 300, words)
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def test_endpoint_reports_pending_coverage_distinctly_and_excludes_it_from_live():
    """Operator follow-up mandate (2026-09-16): coverage disclosure must count live/
    partial/stale/PENDING/rejected/unavailable cells distinctly -- a pending contract
    (requested, no tick yet) never counts as streaming, and is never silently folded into
    the unavailable bucket."""
    tk = ticker_storage_key("ZZZTEST_PENDING")
    surf = {"expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [10.0, 11.0],
            "cells": [
                {"strike": 10.0, "gex": [1.0], "contracts": [{"call": "X", "put": None}]},
                {"strike": 11.0, "gex": [1.0], "contracts": [{"call": "Y", "put": None}]},
            ],
            "contracts_total": 2, "contracts_used": 2, "contracts_excluded_malformed_expiry": 0}
    # X is live-streaming; Y has been requested (desired) but never ticked.
    _stamp_gamma_surface_cell_stream_state(
        surf, {"X": {"gamma_ts_recv": time.time()}}, {"X"}, None, {"X", "Y"})
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 10.0,
                                      "spot_source": "last", "spot_as_of_ts_utc": time.time(), "chain_basis": "full"}
    try:
        cov = _call(tk)
        assert cov["cells"] == 2
        assert cov["live"] == 1 and cov["pending"] == 1
        assert cov["unavailable"] == 0, "the pending leg must not also be counted as unavailable"
        assert cov["state"] == server.COVERAGE_PARTIAL
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def test_endpoint_reports_daemon_unavailable_coverage_distinctly_from_pending():
    """Independent-review finding (2026-09-16, follow-up mandate): a desired-but-untouched
    contract while the capture daemon itself is unreachable counts in its OWN bucket,
    distinct from 'pending' (daemon alive, outcome merely not yet known) -- neither streams,
    but conflating them hides an operator-actionable fact (restart the daemon)."""
    tk = ticker_storage_key("ZZZTEST_DAEMON_DOWN")
    surf = {"expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [10.0, 11.0],
            "cells": [
                {"strike": 10.0, "gex": [1.0], "contracts": [{"call": "X", "put": None}]},
                {"strike": 11.0, "gex": [1.0], "contracts": [{"call": "Y", "put": None}]},
            ],
            "contracts_total": 2, "contracts_used": 2, "contracts_excluded_malformed_expiry": 0}
    # X is live-streaming; Y is desired but the daemon itself is confirmed unreachable.
    _stamp_gamma_surface_cell_stream_state(
        surf, {"X": {"gamma_ts_recv": time.time()}}, {"X"}, None, {"X", "Y"}, daemon_available=False)
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 10.0,
                                      "spot_source": "last", "spot_as_of_ts_utc": time.time(), "chain_basis": "full"}
    try:
        cov = _call(tk)
        assert cov["live"] == 1 and cov["daemon_unavailable"] == 1
        assert cov["pending"] == 0, "a daemon-down symbol must not also count as pending"
        assert cov["unavailable"] == 0, "a daemon-down symbol must not also count as unavailable"
        assert cov["state"] == server.COVERAGE_PARTIAL
        assert cov["title"] == "1 of 2 cells streaming · 1 daemon unavailable"
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def test_rejected_contract_reports_a_distinct_state_not_generic_unavailable():
    """2026-09-16 audit finding #6/#1: a vendor-rejected contract must be visibly
    distinguishable from a merely never-requested one -- 'fail the affected cells
    visibly', not silently lump it into 'unavailable' forever."""
    tk = ticker_storage_key("ZZZTEST_REJECTED")
    surf = {"expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [10.0],
            "cells": [{"strike": 10.0, "gex": [None], "contracts": [{"call": "BADSYM", "put": None}]}],
            "contracts_total": 1, "contracts_used": 1, "contracts_excluded_malformed_expiry": 0}
    _stamp_gamma_surface_cell_stream_state(surf, {}, set(), {"BADSYM": "RuntimeError: refused"})
    assert surf["cells"][0]["stream"][0]["state"] == "rejected"
    assert surf["cells"][0]["stream"][0]["call"]["rejected_reason"] == "RuntimeError: refused"
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 10.0,
                                      "spot_source": "last", "spot_as_of_ts_utc": time.time(), "chain_basis": "full"}
    try:
        d = _call(tk)
        assert d["rejected"] == 1 and d["state"] == server.COVERAGE_PARTIAL
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


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


