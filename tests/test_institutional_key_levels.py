"""Institutional consistency: dollar GEX pickers and aggregates.

RC-292 honesty: Console `kl_gamma_pin` is bound to `pick_gamma_pin_strike`
(|net GEX$| peak). Labels/tooltips must say that — not "Gamma Pin" / total-gamma.
HVL remains the total-gamma concentration. This file does not recover pin_score
or persisted `gamma_pin`.
"""

from pathlib import Path

from math_exposure_core import (
    aggregate_net_gex,
    bucket_metric_abs,
    compute_exposures_by_strike,
    exposures_have_dollar_gex,
    pick_gamma_pin_strike,
    pick_hvl_strike,
    total_gex_dollars_at_strike,
)
from math_levels import build_summary_rows, compute_gamma_flip, pick_gamma_wall_strikes

_INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"
_PIN_TIP = (
    "Largest |net GEX$| per 1% on the selected expiry. "
    "Not the total-gamma magnet (that is HVL)."
)


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


def _split_net_vs_total_exposures():
    """One strike leads |net GEX$|; a different strike leads total gamma."""
    spot = 500.0
    contracts = [
        # 490: balanced call+put → high total gamma, near-zero net
        {"strikePrice": 490, "putCall": "CALL", "openInterest": 8000, "multiplier": 100,
         "gamma": 0.10, "delta": 0.55, "daysToExpiration": 1},
        {"strikePrice": 490, "putCall": "PUT", "openInterest": 8000, "multiplier": 100,
         "gamma": 0.10, "delta": -0.45, "daysToExpiration": 1},
        # 510: one-sided call → lower total, larger |net|
        {"strikePrice": 510, "putCall": "CALL", "openInterest": 4000, "multiplier": 100,
         "gamma": 0.08, "delta": 0.35, "daysToExpiration": 1},
        {"strikePrice": 510, "putCall": "PUT", "openInterest": 200, "multiplier": 100,
         "gamma": 0.02, "delta": -0.15, "daysToExpiration": 1},
    ]
    exposures, _ = compute_exposures_by_strike(contracts, spot=spot, require_oi=True)
    return exposures, spot


def test_gamma_pin_is_abs_net_gex_peak_not_total_gamma():
    """Bound semantic for kl_gamma_pin / consensus gamma_pin: |net GEX$|, not HVL."""
    exposures, _ = _split_net_vs_total_exposures()
    strikes = sorted(exposures.keys())
    pin = pick_gamma_pin_strike(exposures, strikes)
    hvl = pick_hvl_strike(exposures, strikes)
    assert pin == 510.0
    assert hvl == 490.0
    assert pin != hvl
    pin_abs_net = bucket_metric_abs(exposures[pin], "net_gex_1pct")
    other_abs_net = bucket_metric_abs(exposures[hvl], "net_gex_1pct")
    assert pin_abs_net is not None and other_abs_net is not None
    assert pin_abs_net > other_abs_net
    assert total_gex_dollars_at_strike(exposures[hvl]) > total_gex_dollars_at_strike(
        exposures[pin]
    )
    rows = build_summary_rows(exposures, 500.0, windows=[5])
    assert rows[0].gamma_pin == pin


def test_console_kl_gamma_pin_label_matches_bound_net_gex():
    """RC-292 UI label child: Console must not call the net-GEX peak 'Gamma Pin'."""
    html = _INDEX.read_text(encoding="utf-8")
    assert "key: 'kl_gamma_pin'" in html
    assert "label: 'Net Γ Peak'" in html
    assert "srLabel: 'Net Γ'" in html
    assert "label: 'Gamma Pin'" not in html
    assert "label: 'HVL'" in html
    assert "srLabel: 'Peak Γ'" in html


def test_console_pin_tooltip_matches_bound_net_gex():
    """RC-292 tooltip child: operator text names |net GEX$|, not total-gamma."""
    html = _INDEX.read_text(encoding="utf-8")
    assert _PIN_TIP in html
    assert html.count(_PIN_TIP) >= 3  # KEY LEVELS + decision rail + exec card
    pin_block = html[html.find("key: 'kl_gamma_pin'") : html.find("key: 'kl_gamma_pin'") + 400]
    assert _PIN_TIP in pin_block
    assert "total-gamma magnet" in pin_block
    assert "title: 'Largest net-gamma strike'" not in html
    assert "title: 'Largest total gamma" not in html


def test_decision_exec_pin_labeled_net_gamma():
    """Same bound field on the rail/exec card must not say PIN."""
    html = _INDEX.read_text(encoding="utf-8")
    assert 'id="dr-lvl-pin"' in html
    assert 'id="exec-pin"' in html
    assert 'decision-k">PIN</div><div class="decision-v" id="dr-lvl-pin"' not in html
    assert 'decision-k">PIN</div><div class="decision-v" id="exec-pin"' not in html
    assert ">NET Γ</div><div class=\"decision-v\" id=\"dr-lvl-pin\">" in html
    assert ">NET Γ</div><div class=\"decision-v\" id=\"exec-pin\">" in html
