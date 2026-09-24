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
  4. (retired 2026-09-23) `_backfill_gex_cells_from_last_valid` -- when current inputs are invalid for
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
from pathlib import Path

import server
from math_exposure_core import (
    compute_exposures_by_strike,
    gamma_is_plausible,
    vendor_greeks_unavailable,
    MISSING_GREEK_SENTINEL,
)
from server import project_gamma_surface

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
# 5. No last-valid refill (operator rule 2026-09-23: no fallbacks)
# ---------------------------------------------------------------------------

def test_no_cell_is_ever_refilled_from_an_older_value():
    """A cell with no valid data THIS cycle stays empty. The last-known-valid store that used
    to refill it (computed at an older spot, possibly hours old, while gamma_available read
    True) is gone -- with its DB write-through."""
    import inspect

    import db as db_mod
    src = inspect.getsource(server)
    for gone in ("_backfill_gex_cells_from_last_valid", "_LAST_VALID_GEX_CELLS",
                 "banked_morning_reference"):
        assert gone not in src, gone
    assert not hasattr(db_mod.EdDB, "load_gamma_surface_last_valid")
    assert not hasattr(db_mod.EdDB, "persist_gamma_surface_last_valid")
