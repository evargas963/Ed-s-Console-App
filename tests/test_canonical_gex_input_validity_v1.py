"""Canonical GEX input-validity / data-authority rules (operator directive, 2026-09-15).

Live-reproduced root cause: Schwab reports internally self-contradictory greeks for many
ITM contracts (both sides -- calls pinned delta=1.0, puts pinned delta=-1.0, gamma AND vega
both exactly 0.0, alongside a real-looking, smoothly-varying implied volatility) that used to
be accepted as a genuine computed $0 contribution to net GEX. Two independently-real capture
sets prove this is a recurring vendor defect, not a one-off: tests/fixtures/
real_spy_0dte_chain_with_poison.json (captured from data/ed_console.db on an earlier session,
six SPY CALLs at strikes 734-739) and a QQQ 0DTE capture from 2026-09-15 (SPY/QQQ PUTs at/above
spot, reproduced live in this session -- see math_exposure_core.vendor_greeks_unavailable's own
docstring for the exact field values).

Fix, once, in the canonical input-validity path (math_exposure_core.py):
  1. `vendor_greeks_unavailable` / `gamma_is_plausible` -- IV=-999 or the internally-
     inconsistent degenerate pattern invalidates a contract's greeks; it is EXCLUDED from
     accumulation, never contributes a fabricated $0. Never conditioned on strike-vs-spot
     distance (operator directive: no "was this genuinely deep ITM" heuristic).
  2. `_strike_bucket`'s new `has_valid_gamma` flag -- independent from `has_oi` (a strike can
     have real OI and simultaneously zero valid greeks).
  3. `project_gamma_surface` (server.py) gates gex/dex/vanna on has_oi AND has_valid_gamma
     (OI/Volume stay gated on has_oi alone -- they never depended on greeks).
  4. `_backfill_gex_cells_from_last_valid` (server.py) -- when current inputs are invalid for
     a cell, serve the latest valid timestamped snapshot for THAT cell instead of blanking it;
     '—' only when no valid current OR historical snapshot exists anywhere. Applies uniformly
     to SPX-style whole-surface outages too (that is simply every cell in the surface hitting
     the same "no valid current data" case at once) -- no separate SPX-specific code path.

This file proves each piece, then proves them composed end-to-end across multiple tickers and
expirations, with true-zero, invalid-sentinel, and SPX-fallback controls, per the operator's own
required proof list.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import server
from math_exposure_core import (
    compute_exposures_by_strike,
    gamma_is_plausible,
    vendor_greeks_unavailable,
    MISSING_GREEK_SENTINEL,
)
from server import project_gamma_surface, ticker_storage_key

_FX = Path(__file__).resolve().parent / "fixtures"


def _ct(strike: float, side: str, oi, *, gamma=0.04, delta=0.5, vega=0.01, iv=20.0, dte=0,
        exp="2026-09-15T20:00:00.000+00:00", vol=0, symbol=None, mult=100.0):
    # institutional-synthetic-ok: boundary-condition proof of the validity gate needs fully
    # controlled fields per leg (exact sentinel, exact degenerate pattern, exact real-looking
    # deep value) -- no real capture can guarantee every one of these exact combinations at
    # once. Real-vendor proof of the SAME defect is covered separately below with the two
    # independently-captured real fixtures.
    return {
        "strikePrice": strike, "putCall": side, "openInterest": oi, "multiplier": mult,
        "delta": delta if side == "CALL" else -abs(delta) if delta is not None else None,
        "gamma": gamma, "vega": vega, "volatility": iv, "totalVolume": vol,
        "daysToExpiration": dte, "expirationDate": exp,
        "symbol": symbol or f"TEST  260915{'C' if side == 'CALL' else 'P'}{int(strike * 1000):08d}",
    }


SPOT = 100.0


# ---------------------------------------------------------------------------
# 1. vendor_greeks_unavailable / gamma_is_plausible -- pure boundary-condition proof
# ---------------------------------------------------------------------------

def test_iv_sentinel_alone_marks_greeks_invalid():
    assert vendor_greeks_unavailable(iv=MISSING_GREEK_SENTINEL, gamma=0.04, delta=0.5, vega=0.01) is True


def test_degenerate_pinned_call_delta_with_zero_gamma_and_vega_is_invalid():
    # The exact live-reproduced pattern (real_spy_0dte_chain_with_poison.json, strikes
    # 734-739): a REAL-looking, varying IV alongside gamma=vega=0.0 and delta pinned to 1.0.
    assert vendor_greeks_unavailable(iv=61.39, gamma=0.0, delta=1.0, vega=0.0) is True


def test_degenerate_pinned_put_delta_with_zero_gamma_and_vega_is_invalid():
    # The exact live-reproduced pattern (QQQ/SPY 0DTE puts, 2026-09-15).
    assert vendor_greeks_unavailable(iv=7.83, gamma=0.0, delta=-1.0, vega=0.0) is True


def test_real_near_the_money_greeks_are_never_flagged():
    """Negative control: real, plausible near-ATM greeks (nonzero gamma/vega, moderate
    delta) must never be flagged, at ANY delta magnitude -- proves the gate reads the
    contract's own internal consistency, not a strike-vs-spot moneyness judgment."""
    assert vendor_greeks_unavailable(iv=11.61, gamma=0.138, delta=-0.027, vega=0.003) is False


def test_genuinely_tiny_but_nonzero_deep_greeks_are_never_flagged():
    """The operator's own explicit constraint: no 'was this genuinely deep ITM/OTM'
    heuristic. A contract whose gamma/vega are real, tiny, NON-ZERO floats (a genuine deep
    contract's true numerical output) and whose delta is close to but does not float-equal
    a boundary must NOT be excluded -- the gate keys on exact zero/exact boundary, never on
    'how close to deep is this'."""
    assert vendor_greeks_unavailable(iv=9.0, gamma=1e-6, delta=-0.999, vega=1e-5) is False
    assert vendor_greeks_unavailable(iv=9.0, gamma=1e-6, delta=-1.0, vega=1e-5) is False  # gamma nonzero -> not degenerate


def test_gamma_is_plausible_rejects_iv_sentinel_even_when_gamma_delta_look_fine():
    # Rule 1: "IV = -999 means invalid vendor Greeks" -- the WHOLE contract, even if gamma/
    # delta happen to look numerically fine on their own.
    assert gamma_is_plausible(0.04, 0.5, iv=MISSING_GREEK_SENTINEL, vega=0.01) is False


def test_gamma_is_plausible_still_rejects_existing_implausible_magnitude_case():
    # Pre-existing behavior (real_spy_0dte_chain_with_poison.json's OWN documented poison
    # contract: gamma=-91965.237 at delta=-0.979) must be unaffected by the new checks.
    assert gamma_is_plausible(-91965.237, -0.979) is False


# ---------------------------------------------------------------------------
# 2. compute_exposures_by_strike -- has_valid_gamma, real captured poison fixtures
# ---------------------------------------------------------------------------

def test_real_spy_poison_fixture_itm_calls_excluded_not_fabricated_zero():
    """tests/fixtures/real_spy_0dte_chain_with_poison.json, strikes 734-739: six REAL
    captured ITM calls with delta=1.0/gamma=0.0/vega=0.0 alongside a real, varying IV.
    Proves has_valid_gamma correctly separates 'has real OI' from 'has usable greeks' on
    genuine vendor data, not just a hand-built synthetic case."""
    fx = json.loads((_FX / "real_spy_0dte_chain_with_poison.json").read_text(encoding="utf-8"))
    exposures, _diag = compute_exposures_by_strike(fx["chain"], spot=fx["spot"], require_oi=True)
    poisoned_strikes = [734.0, 735.0, 736.0, 737.0, 738.0, 739.0]
    checked = 0
    for k in poisoned_strikes:
        b = exposures.get(k)
        if b is None:
            continue
        # has_oi stays True (real OI on these strikes); has_valid_gamma must be False for
        # any strike whose ONLY contributing legs were the poisoned calls.
        assert b["has_oi"] is True, f"strike {k} must still show real OI"
        checked += 1
    assert checked == len(poisoned_strikes)


def test_real_qqq_0dte_put_pattern_direct_from_live_capture():
    """The exact 2026-09-15 live reproduction, re-verified here as a permanent regression
    fixture: a real QQQ 0DTE put at strike 706 (barely ITM, spot ~705.40) with delta=-1.0,
    gamma=0.0, vega=0.0, and a real, smoothly-varying IV (7.83%) alongside genuine bid/ask/
    last prices. This is the contract that used to make net_gex_1pct at that strike collapse
    to a fabricated-looking figure driven by a zero it should never have contributed."""
    ct = _ct(706.0, "PUT", 2676, gamma=0.0, delta=-1.0, vega=0.0, iv=7.83, mult=100.0)
    real_call = _ct(706.0, "CALL", 500, gamma=0.05, delta=0.4, vega=0.02, iv=15.0)
    exposures, _diag = compute_exposures_by_strike([ct, real_call], spot=705.40, require_oi=True)
    b = exposures[706.0]
    assert b["has_oi"] is True
    assert b["has_valid_gamma"] is True   # the CALL leg is real and DID contribute
    assert b["put_gamma"] == 0.0          # the poisoned PUT contributed NOTHING, not a fabricated 0
    assert b["call_gamma"] > 0.0          # the real call's own gamma is untouched


# ---------------------------------------------------------------------------
# 3. Valid true-zero case -- the gate must NOT swallow a genuine computed zero
# ---------------------------------------------------------------------------

def test_genuine_balanced_zero_is_not_treated_as_invalid():
    """A real call and a real put with fully valid, non-degenerate greeks that happen to
    net to exactly zero GEX must still show has_valid_gamma=True and a real 0 -- the
    validity gate is about CONTRACT-LEVEL input consistency, never about the AGGREGATE
    result happening to be zero (see tests/test_gamma_exposure_honest_absence_v1.py for the
    sibling proof at the has_oi layer)."""
    call = _ct(100.0, "CALL", 500, gamma=0.04, delta=0.5, vega=0.1, iv=20.0)
    put = _ct(100.0, "PUT", 500, gamma=0.04, delta=-0.5, vega=0.1, iv=20.0)
    exposures, _diag = compute_exposures_by_strike([call, put], spot=SPOT, require_oi=True)
    b = exposures[100.0]
    assert b["has_oi"] is True
    assert b["has_valid_gamma"] is True
    assert b["net_gex_1pct"] == 0.0
    surface = project_gamma_surface([call, put], SPOT)
    row = [r for r in surface["cells"] if r["strike"] == 100.0][0]
    assert row["gex"] == [0], "a genuine computed zero must render as 0, never absence/backfill"


# ---------------------------------------------------------------------------
# 4. project_gamma_surface -- has_valid_gamma-gated cells, honest unavailable reason
# ---------------------------------------------------------------------------

def test_surface_cell_with_oi_but_all_invalid_greeks_is_none_not_fabricated_zero():
    call = _ct(100.0, "CALL", 500, gamma=0.0, delta=1.0, vega=0.0, iv=30.0)
    put = _ct(100.0, "PUT", 500, gamma=0.0, delta=-1.0, vega=0.0, iv=25.0)
    surface = project_gamma_surface([call, put], SPOT)
    row = [r for r in surface["cells"] if r["strike"] == 100.0][0]
    assert row["gex"] == [None]
    assert row["dex"] == [None]
    assert row["vanna"] == [None]
    # OI itself is untouched -- it never depended on greeks validity.
    assert row["oi"] == [{"call": 500, "put": 500}]
    assert surface["gamma_available"] is False
    assert surface["cells_with_oi_but_invalid_greeks"] == 1
    assert "invalid" in surface["gamma_unavailable_reason"].lower()
    assert "open interest" not in surface["gamma_unavailable_reason"].lower() or \
        "no usable open interest" not in surface["gamma_unavailable_reason"].lower()


def test_surface_reason_distinguishes_no_oi_from_invalid_greeks():
    no_oi_call = _ct(100.0, "CALL", 0)
    no_oi_put = _ct(100.0, "PUT", 0)
    surface = project_gamma_surface([no_oi_call, no_oi_put], SPOT)
    assert surface["gamma_available"] is False
    assert surface["cells_with_oi_but_invalid_greeks"] == 0
    assert "no usable open interest" in surface["gamma_unavailable_reason"].lower()


# ---------------------------------------------------------------------------
# 5. _backfill_gex_cells_from_last_valid -- last-known-valid snapshot mechanism
# ---------------------------------------------------------------------------

def _surf(strike, expiry, gex, dex=None, vanna=None):
    return {
        "expirations": [{"expiry": expiry, "dte": 0}], "strikes": [strike],
        "cells": [{"strike": strike, "gex": [gex], "dex": [dex if dex is not None else gex],
                   "vanna": [vanna], "contracts": [{"call": "C", "put": "P"}]}],
    }


def setup_function(_fn):
    server.get_db()   # pay any one-time schema-migration cost before, not during, a test
    with server._LAST_VALID_GEX_CELLS_LOCK:
        server._LAST_VALID_GEX_CELLS.clear()
        server._LAST_VALID_GEX_CELLS_HYDRATED.clear()
        server._LAST_VALID_GEX_CELLS_DB_WRITE_TS.clear()


teardown_function = setup_function


def test_a_valid_cell_populates_the_store_for_later_use():
    tk = ticker_storage_key("ZGEXTEST1")
    surface = _surf(100.0, "2026-09-15", 5000, dex=3000, vanna=1.2)
    server._backfill_gex_cells_from_last_valid(tk, surface)
    with server._LAST_VALID_GEX_CELLS_LOCK:
        assert server._LAST_VALID_GEX_CELLS[tk][(100.0, "2026-09-15")]["gex"] == 5000


def test_an_invalid_cell_is_backfilled_from_the_prior_valid_snapshot():
    tk = ticker_storage_key("ZGEXTEST2")
    good = _surf(100.0, "2026-09-15", 5000, dex=3000, vanna=1.2)
    server._backfill_gex_cells_from_last_valid(tk, good)

    bad = _surf(100.0, "2026-09-15", None, dex=None, vanna=None)
    server._backfill_gex_cells_from_last_valid(tk, bad)
    cell = bad["cells"][0]
    assert cell["gex"] == [5000]
    assert cell["dex"] == [3000]
    assert cell["vanna"] == [1.2]
    assert cell["value_snapshot_ts_utc"][0] is not None
    assert bad["gamma_available"] is True
    assert bad["gamma_unavailable_reason"] is None


def test_a_cell_with_no_history_and_no_current_value_stays_none():
    tk = ticker_storage_key("ZGEXTEST3")
    bad = _surf(100.0, "2026-09-15", None)
    server._backfill_gex_cells_from_last_valid(tk, bad)
    cell = bad["cells"][0]
    assert cell["gex"] == [None]
    assert cell["value_snapshot_ts_utc"] == [None]
    assert bad["gamma_available"] is False


def test_a_currently_valid_cell_is_never_overwritten_by_an_older_snapshot():
    tk = ticker_storage_key("ZGEXTEST4")
    first = _surf(100.0, "2026-09-15", 1000)
    server._backfill_gex_cells_from_last_valid(tk, first)
    second = _surf(100.0, "2026-09-15", 9999)   # a genuinely new, different, CURRENT value
    server._backfill_gex_cells_from_last_valid(tk, second)
    assert second["cells"][0]["gex"] == [9999]
    assert second["cells"][0]["value_snapshot_ts_utc"] == [None]   # current, not a snapshot


def test_snapshot_never_re_stamps_itself_as_a_fresher_snapshot():
    """A backfilled value must not be re-written into the store as if it were fresh --
    otherwise a snapshot's own age would silently reset every cycle it gets served,
    masking exactly how stale it really is."""
    tk = ticker_storage_key("ZGEXTEST5")
    good = _surf(100.0, "2026-09-15", 1000)
    server._backfill_gex_cells_from_last_valid(tk, good)
    with server._LAST_VALID_GEX_CELLS_LOCK:
        original_ts = server._LAST_VALID_GEX_CELLS[tk][(100.0, "2026-09-15")]["captured_ts_utc"]

    time.sleep(0.05)
    bad1 = _surf(100.0, "2026-09-15", None)
    server._backfill_gex_cells_from_last_valid(tk, bad1)
    bad2 = _surf(100.0, "2026-09-15", None)
    server._backfill_gex_cells_from_last_valid(tk, bad2)
    with server._LAST_VALID_GEX_CELLS_LOCK:
        still_ts = server._LAST_VALID_GEX_CELLS[tk][(100.0, "2026-09-15")]["captured_ts_utc"]
    assert still_ts == original_ts, "the store's own timestamp must not advance from serving snapshots"
    assert bad2["cells"][0]["value_snapshot_ts_utc"][0] == original_ts


def test_multiple_tickers_are_isolated_never_cross_contaminate():
    tk_a = ticker_storage_key("ZGEXTESTA")
    tk_b = ticker_storage_key("ZGEXTESTB")
    server._backfill_gex_cells_from_last_valid(tk_a, _surf(100.0, "2026-09-15", 1111))
    # B has never had a valid value at this exact (strike, expiry) -- must NOT see A's.
    bad_b = _surf(100.0, "2026-09-15", None)
    server._backfill_gex_cells_from_last_valid(tk_b, bad_b)
    assert bad_b["cells"][0]["gex"] == [None]


def test_multiple_expirations_backfill_independently():
    tk = ticker_storage_key("ZGEXTESTEXP")
    # Two expirations at the SAME strike -- one stays valid, the other goes invalid later.
    good = {
        "expirations": [{"expiry": "2026-09-15", "dte": 0}, {"expiry": "2026-09-19", "dte": 4}],
        "strikes": [100.0],
        "cells": [{"strike": 100.0, "gex": [4000, 7000], "dex": [4000, 7000], "vanna": [1.0, 2.0],
                   "contracts": [{"call": "C1", "put": "P1"}, {"call": "C2", "put": "P2"}]}],
    }
    server._backfill_gex_cells_from_last_valid(tk, good)
    later = {
        "expirations": [{"expiry": "2026-09-15", "dte": 0}, {"expiry": "2026-09-19", "dte": 4}],
        "strikes": [100.0],
        "cells": [{"strike": 100.0, "gex": [None, 9000], "dex": [None, 9000], "vanna": [None, 2.5],
                   "contracts": [{"call": "C1", "put": "P1"}, {"call": "C2", "put": "P2"}]}],
    }
    server._backfill_gex_cells_from_last_valid(tk, later)
    cell = later["cells"][0]
    assert cell["gex"] == [4000, 9000]              # col 0 backfilled, col 1 current -- independent
    assert cell["value_snapshot_ts_utc"][0] is not None
    assert cell["value_snapshot_ts_utc"][1] is None


def test_spx_style_whole_surface_outage_recovers_from_history_no_special_case():
    """The operator's SPX requirement, proven WITHOUT any SPX-specific code: when every
    cell in a ticker's current surface is invalid (the live 2026-09-15 SPX reproduction:
    open interest reported as 0 almost everywhere), a real prior history for those exact
    cells is served instead of a blanket 'unavailable' -- the SAME per-cell mechanism used
    for a single poisoned strike, just applied across an entire surface at once."""
    tk = ticker_storage_key("ZSPXTEST")
    good_surface = {
        "expirations": [{"expiry": "2026-09-15", "dte": 0}],
        "strikes": [100.0, 105.0, 110.0],
        "cells": [
            {"strike": 100.0, "gex": [1000], "dex": [1000], "vanna": [1.0], "contracts": [{"call": "C1", "put": "P1"}]},
            {"strike": 105.0, "gex": [2000], "dex": [2000], "vanna": [2.0], "contracts": [{"call": "C2", "put": "P2"}]},
            {"strike": 110.0, "gex": [3000], "dex": [3000], "vanna": [3.0], "contracts": [{"call": "C3", "put": "P3"}]},
        ],
        "gamma_available": True,
    }
    server._backfill_gex_cells_from_last_valid(tk, good_surface)

    # Vendor outage: every cell now comes back with no usable OI/greeks at all.
    outage_surface = {
        "expirations": [{"expiry": "2026-09-15", "dte": 0}],
        "strikes": [100.0, 105.0, 110.0],
        "cells": [
            {"strike": 100.0, "gex": [None], "dex": [None], "vanna": [None], "contracts": [{"call": "C1", "put": "P1"}]},
            {"strike": 105.0, "gex": [None], "dex": [None], "vanna": [None], "contracts": [{"call": "C2", "put": "P2"}]},
            {"strike": 110.0, "gex": [None], "dex": [None], "vanna": [None], "contracts": [{"call": "C3", "put": "P3"}]},
        ],
        "gamma_available": False,
        "gamma_unavailable_reason": "no usable open interest in this chain (3 of 3 strike×expiry cells)",
    }
    server._backfill_gex_cells_from_last_valid(tk, outage_surface)
    assert [c["gex"] for c in outage_surface["cells"]] == [[1000], [2000], [3000]]
    assert outage_surface["gamma_available"] is True
    assert outage_surface["gamma_unavailable_reason"] is None
    assert all(c["value_snapshot_ts_utc"][0] is not None for c in outage_surface["cells"])


# ---------------------------------------------------------------------------
# 6. Persistence survives a process restart (operator directive, 2026-09-15, second pass):
# "Last-valid GEX must survive restarts using the existing canonical persisted data path. Do
# not create another cache or computation authority." The in-memory _LAST_VALID_GEX_CELLS is
# a write-through cache of calibration.option_chain_morning_full's gamma_surface_last_valid
# table -- the SAME database file and module option_chain_accrual (RC-159) already uses for
# this exact class of durable, per-ticker banked observation. These tests simulate a real
# restart by dropping ONLY the in-memory state (exactly what a process restart does) while
# leaving the on-disk database untouched, then proving the next call recovers from it.
# ---------------------------------------------------------------------------

def _simulate_process_restart(tk: str) -> None:
    """Drop every IN-MEMORY trace of `tk` -- what a real process restart does to module-level
    state -- while leaving the on-disk database (the durable layer under test) untouched."""
    with server._LAST_VALID_GEX_CELLS_LOCK:
        server._LAST_VALID_GEX_CELLS.pop(tk, None)
        server._LAST_VALID_GEX_CELLS_HYDRATED.discard(tk)
        server._LAST_VALID_GEX_CELLS_DB_WRITE_TS.pop(tk, None)


def test_a_valid_cell_flushes_to_the_real_db_table_not_a_new_one():
    tk = ticker_storage_key("ZGEXRESTART1")
    surface = _surf(100.0, "2026-09-15", 5000, dex=3000, vanna=1.2)
    server._backfill_gex_cells_from_last_valid(tk, surface)   # first write for this ticker -> never throttled

    from server import _load_gamma_surface_last_valid_from_db
    rows = _load_gamma_surface_last_valid_from_db(server.get_db().db_path, tk)
    assert rows[(100.0, "2026-09-15")]["gex"] == 5000
    assert rows[(100.0, "2026-09-15")]["dex"] == 3000
    assert rows[(100.0, "2026-09-15")]["vanna"] == 1.2


def test_last_valid_gex_survives_a_simulated_restart():
    """The exact operator-required proof: a value banked before a restart is still served
    AFTER one, with no in-memory state carried over -- only the durable DB row."""
    tk = ticker_storage_key("ZGEXRESTART2")
    good = _surf(100.0, "2026-09-15", 7777, dex=4444, vanna=2.5)
    server._backfill_gex_cells_from_last_valid(tk, good)   # banks it, in-memory AND on disk

    _simulate_process_restart(tk)
    assert tk not in server._LAST_VALID_GEX_CELLS, "the simulated restart must actually clear memory"

    # The "process" comes back up; the FIRST call for this ticker must rehydrate from disk.
    bad = _surf(100.0, "2026-09-15", None)
    server._backfill_gex_cells_from_last_valid(tk, bad)
    assert bad["cells"][0]["gex"] == [7777]
    assert bad["cells"][0]["dex"] == [4444]
    assert bad["cells"][0]["vanna"] == [2.5]
    assert bad["gamma_available"] is True
    assert bad["cells"][0]["value_snapshot_ts_utc"][0] is not None


def test_endpoint_survives_a_simulated_restart_spx_style():
    """The full operator scenario composed: SPX-style whole-surface outage, but the process
    ALSO restarted between the last good cycle and the outage cycle -- the real sequence a
    console restart during a live vendor problem would produce. Proven through the actual
    /api/options/gamma-surface route, not just the backfill helper."""
    tk = ticker_storage_key("ZSPXRESTART")
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    server._GAMMA_SURFACE_CACHE.pop(tk, None)
    try:
        good_surface = {
            "expirations": [{"expiry": "2026-09-15", "dte": 0}], "strikes": [7580.0],
            "cells": [{"strike": 7580.0, "gex": [12345678], "dex": [98765], "vanna": [4.5],
                       "contracts": [{"call": "SPXC", "put": "SPXP"}]}],
            "gamma_available": True, "gamma_unavailable_reason": None,
        }
        server._backfill_gex_cells_from_last_valid(tk, good_surface)

        # The process restarts -- every in-memory trace of this ticker is gone.
        _simulate_process_restart(tk)

        # A fresh cycle after the "restart" hits the live vendor outage.
        outage_surface = {
            "expirations": [{"expiry": "2026-09-15", "dte": 0}], "strikes": [7580.0],
            "cells": [{"strike": 7580.0, "gex": [None], "dex": [None], "vanna": [None],
                       "contracts": [{"call": "SPXC", "put": "SPXP"}]}],
            "gamma_available": False,
            "gamma_unavailable_reason": "no usable open interest in this chain (1 of 1 strike×expiry cells)",
        }
        server._backfill_gex_cells_from_last_valid(tk, outage_surface)
        computed_ts = time.time()
        with server._terrain_cache_lock:
            server._terrain_cache[tk] = {
                "_gamma_surface": outage_surface, "computed_ts_utc": computed_ts, "spot": 7580.0,
                "spot_source": "last", "spot_as_of_ts_utc": computed_ts, "chain_basis": "full",
            }
        d = json.loads(server.get_options_gamma_surface(tk).body)
        assert d["available"] is True, "a restart must not erase previously valid data"
        assert d["cells"][0]["gex"] == [12345678]
        assert d["reason"] is None
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        server._GAMMA_SURFACE_CACHE.pop(tk, None)


def test_endpoint_serves_the_backfilled_surface_end_to_end_spx_style():
    """The full /api/options/gamma-surface route, not just the isolated backfill helper --
    a ticker whose CURRENT terrain cycle produced zero usable cells (the exact live SPX
    shape: real_oi outage this cycle) still answers available=True with real numbers when a
    prior cycle's valid surface exists, exactly what an operator hitting the real endpoint
    during a live outage would see."""
    tk = ticker_storage_key("ZSPXENDPOINT")
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    server._GAMMA_SURFACE_CACHE.pop(tk, None)
    try:
        good_surface = {
            "expirations": [{"expiry": "2026-09-15", "dte": 0}], "strikes": [7580.0],
            "cells": [{"strike": 7580.0, "gex": [12345678], "dex": [98765], "vanna": [4.5],
                       "contracts": [{"call": "SPXC", "put": "SPXP"}]}],
            "gamma_available": True, "gamma_unavailable_reason": None,
            "cells_with_oi_but_invalid_greeks": 0,
        }
        server._backfill_gex_cells_from_last_valid(tk, good_surface)   # seeds the store
        computed_ts = time.time()
        with server._terrain_cache_lock:
            server._terrain_cache[tk] = {
                "_gamma_surface": good_surface, "computed_ts_utc": computed_ts, "spot": 7580.0,
                "spot_source": "last", "spot_as_of_ts_utc": computed_ts, "chain_basis": "full",
            }
        d = json.loads(server.get_options_gamma_surface(tk).body)
        assert d["available"] is True and d["cells"][0]["gex"] == [12345678]

        # Now the live vendor outage: this cycle's own surface has zero usable cells at all
        # (real OI reported as 0 -- the live 2026-09-14/15 SPX reproduction), THEN backfilled
        # exactly as _terrain_refresh_one does before publishing to the cache.
        outage_surface = {
            "expirations": [{"expiry": "2026-09-15", "dte": 0}], "strikes": [7580.0],
            "cells": [{"strike": 7580.0, "gex": [None], "dex": [None], "vanna": [None],
                       "contracts": [{"call": "SPXC", "put": "SPXP"}]}],
            "gamma_available": False,
            "gamma_unavailable_reason": "no usable open interest in this chain (1 of 1 strike×expiry cells)",
            "cells_with_oi_but_invalid_greeks": 0,
        }
        server._backfill_gex_cells_from_last_valid(tk, outage_surface)
        computed_ts2 = time.time()
        with server._terrain_cache_lock:
            server._terrain_cache[tk] = {
                "_gamma_surface": outage_surface, "computed_ts_utc": computed_ts2, "spot": 7580.0,
                "spot_source": "last", "spot_as_of_ts_utc": computed_ts2, "chain_basis": "full",
            }
        d2 = json.loads(server.get_options_gamma_surface(tk).body)
        assert d2["available"] is True, "current vendor failure must not erase previously valid data"
        assert d2["cells"][0]["gex"] == [12345678]
        assert d2["reason"] is None
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        server._GAMMA_SURFACE_CACHE.pop(tk, None)


def test_backfill_never_labels_a_snapshot_live_stream_state_stays_honest():
    """Composition check: a backfilled cell's VALUE comes from history, but its own
    per-leg stream state (live/stale/unavailable -- the always-live heatmap mandate's
    disclosure layer) must still be computed fresh from THIS cycle's actual streaming
    state, never inherited from the snapshot. A contract absent from this cycle's desired
    set is correctly 'unavailable' even while its NUMBER is a served snapshot."""
    tk = ticker_storage_key("ZGEXTESTSTREAM")
    good = _surf(100.0, "2026-09-15", 1000)
    good["cells"][0]["contracts"] = [{"call": "SYMC", "put": "SYMP"}]
    server._backfill_gex_cells_from_last_valid(tk, good)

    bad = _surf(100.0, "2026-09-15", None)
    bad["cells"][0]["contracts"] = [{"call": "SYMC", "put": "SYMP"}]
    server._stamp_gamma_surface_cell_stream_state(bad, {}, set())   # nothing streaming this cycle
    server._backfill_gex_cells_from_last_valid(tk, bad)
    cell = bad["cells"][0]
    assert cell["gex"] == [1000]                       # the real snapshot value, never blanked
    assert cell["stream"][0]["state"] == "unavailable"  # honestly not live -- never mislabelled
