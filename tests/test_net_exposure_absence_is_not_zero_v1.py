"""Chain net GEX$ / net DEX$: absence is None, never 0.0 and never raw units.

Audit M-01 / M-02 (2026-09-24, operator rule: no fallbacks):
  * A bucket whose deltas (or gammas) were all invalid keeps net_delta / net_gamma = 0.0 from
    its initialiser. Summed, a book with NO valid delta read net DEX 0.0 -- and The Call's
    regime vote reads "net delta >= 0" as LONG. Absence voted.
  * aggregate_net_dex picked its units on a GAMMA test, so a spot-built book whose gammas were
    all invalid fell to raw net_delta (shares) while still being reported as DEX$.
  * "dollarized" was inferred from "some strike has non-zero dollar GEX"; it is now stamped
    by the one producer (compute_exposures_by_strike) from whether spot was provided.
"""
from __future__ import annotations

from math_exposure_core import (
    aggregate_net_dex,
    aggregate_net_gex,
    compute_exposures_by_strike,
    exposures_have_dollar_gex,
)

SPOT = 500.0


def _c(strike, typ, *, delta, gamma, oi=1000):
    # institutional-synthetic-ok: these tests MUST feed invalid greeks (NaN / None delta and
    # gamma) to prove absence stays None; a captured chain cannot be made invalid on demand.
    return {
        "strikePrice": strike, "putCall": typ, "daysToExpiration": 0, "delta": delta, "gamma": gamma,
        "openInterest": oi, "multiplier": 100,
    }


def _book(contracts, spot=SPOT):
    ex, _ = compute_exposures_by_strike(contracts, spot=spot, require_oi=True)
    return ex, sorted(ex)


def test_valid_book_sums_dollars():
    ex, ks = _book([_c(500.0, "CALL", delta=0.5, gamma=0.02),
                    _c(500.0, "PUT", delta=-0.4, gamma=0.02)])
    assert exposures_have_dollar_gex(ex)
    assert aggregate_net_dex(ex, ks) is not None
    assert aggregate_net_gex(ex, ks) is not None


def test_no_valid_delta_is_none_not_zero():
    ex, ks = _book([_c(500.0, "CALL", delta=float("nan"), gamma=0.02),
                    _c(500.0, "PUT", delta=None, gamma=0.02)])
    assert all(not b["has_valid_delta"] for b in ex.values())
    assert aggregate_net_dex(ex, ks) is None      # was 0.0 -> a LONG regime vote
    assert aggregate_net_gex(ex, ks) is None      # a strike with an invalid contract is excluded whole


def test_spot_built_book_with_no_valid_gamma_stays_dollarized():
    ex, ks = _book([_c(500.0, "CALL", delta=0.5, gamma=float("nan")),
                    _c(500.0, "PUT", delta=-0.4, gamma=None)])
    assert exposures_have_dollar_gex(ex)          # was False -> raw-unit fall-through
    assert aggregate_net_gex(ex, ks) is None      # no valid gamma -> absent, not $0
    assert aggregate_net_dex(ex, ks) is None      # the strike is excluded whole


def test_book_without_spot_has_no_dollar_aggregates():
    ex, ks = _book([_c(500.0, "CALL", delta=0.5, gamma=0.02)], spot=None)
    assert not exposures_have_dollar_gex(ex)
    assert aggregate_net_dex(ex, ks) is None
    assert aggregate_net_gex(ex, ks) is None


def test_empty_strikes_is_none():
    ex, _ = _book([_c(500.0, "CALL", delta=0.5, gamma=0.02)])
    assert aggregate_net_dex(ex, []) is None
    assert aggregate_net_gex(ex, []) is None


# ── M-03 / M-04 / M-05: unmeasured structure is None, not a label ──────────────

def test_inflection_skips_unmeasured_buckets():
    from math_levels import _pick_inflection_closest_zero
    ex, ks = _book([_c(500.0, "CALL", delta=0.5, gamma=0.02),
                    _c(500.0, "PUT", delta=-0.1, gamma=0.01),
                    _c(510.0, "CALL", delta=float("nan"), gamma=float("nan"))])
    # 510's net_delta / net_gamma are the 0.0 initialiser -> must not win "closest to zero"
    assert _pick_inflection_closest_zero(ex, ks, "net_delta") == 500.0
    assert _pick_inflection_closest_zero(ex, ks, "net_gamma") == 500.0


def test_no_measurement_gives_no_pin_bias_or_zone():
    from market_state import derive_zone
    from math_levels import _bias_from_net, _pin_strength, build_summary_rows
    ex, _ = _book([_c(500.0, "CALL", delta=float("nan"), gamma=float("nan"))])
    row = build_summary_rows(ex, SPOT, windows=[5])[0]
    assert row.pin_strength is None and row.bias_signal is None
    assert _pin_strength(ex, None, sorted(ex)) is None
    assert _bias_from_net(1.0, 1.0, None) is None
    assert _bias_from_net(None, 1.0, "High") is None
    assert derive_zone(None, 1.0) is None
    assert derive_zone("some-unknown-label", 1.0) is None
    # measured labels still map
    assert derive_zone("Chaos Zone", None) == "pin_chaos"
    assert derive_zone("Balanced", 0.0) == "pin_neutral"


def test_empty_book_summary_rows_are_unmeasured():
    from math_levels import build_summary_rows
    for r in build_summary_rows({}, SPOT, windows=[5, 10]):
        assert r.pin_strength is None and r.bias_signal is None


# ── T-01 / T-04 / M-06: per-strike bars and OI totals from the one producer ────

def test_unreported_oi_is_unknown_and_one_sided_oi_is_known():
    from math_exposure_core import book_total_oi, strike_total_oi
    ex, _ = _book([_c(500.0, "CALL", delta=0.5, gamma=0.02, oi=1000),      # one-sided: known
                   _c(510.0, "CALL", delta=0.4, gamma=0.02, oi=300),
                   _c(510.0, "PUT", delta=-0.4, gamma=0.02, oi=None)])     # OI not reported
    assert strike_total_oi(ex[500.0]) == 1000.0
    assert strike_total_oi(ex[510.0]) is None
    assert book_total_oi(ex) is None      # one unknown strike -> the book total is unknown


def test_per_strike_bars_are_dollar_gex_on_valid_gamma_only():
    from terrain_engine import _per_strike_rows
    cts = [_c(500.0, "CALL", delta=0.5, gamma=0.02),
           _c(510.0, "CALL", delta=0.5, gamma=float("nan"))]              # invalid gamma
    cts[0]["totalVolume"] = 0                                             # a REAL zero volume
    ex, _ = _book(cts)
    rows = _per_strike_rows(ex, cts)
    assert [r[0] for r in rows] == [500.0, 510.0]
    assert rows[1] == [510.0, None, None]           # excluded strike: listed, GEX null, never $0
    assert rows[0][2] == 0                          # reported zero stays zero
    ex2, _ = _book([_c(500.0, "CALL", delta=0.5, gamma=0.02)])
    assert _per_strike_rows(ex2, [_c(500.0, "CALL", delta=0.5, gamma=0.02)])[0][2] is None
    ex3, _ = _book(cts, spot=None)
    assert _per_strike_rows(ex3, cts) == []         # no spot -> no dollar bars, no raw ones


# ── max pain is PER EXPIRY (standard definition) -- the front expiry, labelled ────

def test_terrain_max_pain_uses_only_the_front_expiry():
    from math_levels import compute_max_pain
    from terrain_engine import compute_terrain

    def c(k, typ, oi, dte):
        ct = _c(k, typ, delta=0.5 if typ == "CALL" else -0.5, gamma=0.02, oi=oi)
        ct["daysToExpiration"] = dte
        return ct

    front = [c(495.0, "PUT", 1000, 0), c(500.0, "CALL", 50, 0), c(500.0, "PUT", 50, 0),
             c(505.0, "CALL", 1000, 0)]
    # a later expiry with a very different distribution that would drag a POOLED max pain
    later = [c(520.0, "CALL", 90000, 30), c(530.0, "PUT", 90000, 30)]
    snap = compute_terrain("SPY", front + later, SPOT)
    ex_front, _ = _book(front)
    assert snap.max_pain_dte == 0
    assert snap.max_pain == compute_max_pain(ex_front) == 500.0
    ex_all, _ = _book(front + later)
    assert compute_max_pain(ex_all) != snap.max_pain     # pooling would have moved it
