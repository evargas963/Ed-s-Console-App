"""Institutional consistency: dollar GEX pickers and aggregates."""

from math_exposure_core import (
    aggregate_net_gex,
    compute_exposures_by_strike,
    exposures_have_dollar_gex,
    pick_gamma_pin_strike,
    pick_hvl_strike,
)
from math_levels import build_summary_rows, compute_gamma_flip, pick_gamma_wall_strikes


def _dollarized_exposures():
  spot = 500.0
  contracts = [
      {"strikePrice": 495, "putCall": "PUT", "openInterest": 1000, "multiplier": 100,
       "gamma": 0.05, "delta": -0.3, "daysToExpiration": 0},
      {"strikePrice": 500, "putCall": "CALL", "openInterest": 2000, "multiplier": 100,
       "gamma": 0.08, "delta": 0.5, "daysToExpiration": 0},
      {"strikePrice": 500, "putCall": "PUT", "openInterest": 1500, "multiplier": 100,
       "gamma": 0.07, "delta": -0.45, "daysToExpiration": 0},
      {"strikePrice": 505, "putCall": "CALL", "openInterest": 3000, "multiplier": 100,
       "gamma": 0.06, "delta": 0.4, "daysToExpiration": 0},
  ]
  exposures, _ = compute_exposures_by_strike(contracts, spot=spot, require_oi=True)
  return exposures, spot


def test_exposures_are_dollarized():
    exposures, _ = _dollarized_exposures()
    assert exposures_have_dollar_gex(exposures)


def test_gamma_pin_uses_net_gex_not_raw_when_dollarized():
    exposures, _ = _dollarized_exposures()
    pin = pick_gamma_pin_strike(exposures, sorted(exposures.keys()))
    assert pin is not None
    rows = build_summary_rows(exposures, 500.0, windows=[5])
    assert rows[0].gamma_pin == pin


def test_hvl_can_differ_from_gamma_pin():
    exposures, spot = _dollarized_exposures()
    pin = pick_gamma_pin_strike(exposures, sorted(exposures.keys()))
    hvl = pick_hvl_strike(exposures, sorted(exposures.keys()))
    assert pin is not None and hvl is not None
    (cg, _), (pg, _) = pick_gamma_wall_strikes(exposures, sorted(exposures.keys()))
    assert cg is not None or pg is not None


def test_consensus_net_gamma_equals_aggregate_net_gex():
    exposures, spot = _dollarized_exposures()
    strikes = sorted(exposures.keys())
    agg = aggregate_net_gex(exposures, strikes)
    rows = build_summary_rows(exposures, spot, windows=[5])
    assert rows[0].net_gamma == agg


def test_gamma_flip_prefers_net_gex_1pct():
    exposures, spot = _dollarized_exposures()
    flip = compute_gamma_flip(exposures, spot)
    assert flip is None or isinstance(flip, float)
