"""Action 11.5: compute_net_charm fail-closed when no contracts contribute."""

from __future__ import annotations

from math_exposure_core import compute_net_charm


def _charm_contract(**overrides) -> dict:
    base = {
        "expirationDate": "2099-05-05",
        "putCall": "CALL",
        "strikePrice": 500.0,
        "gamma": 0.1,
        "delta": 0.5,
        "volatility": 20.0,
        "openInterest": 100.0,
        "multiplier": 100.0,
        "daysToExpiration": 1,
    }
    base.update(overrides)
    return base


def test_net_charm_unavailable_when_no_contracts_match():
    out = compute_net_charm([], 500.0, "2099-05-05")
    assert out["contracts_used"] == 0
    assert out["charm_direction"] is None
    assert out["charm_magnitude"] is None
    assert out["net_charm_daily"] is None


def test_net_charm_emits_magnitude_when_contracts_used():
    out = compute_net_charm([_charm_contract()], 500.0, "2099-05-05")
    assert out["contracts_used"] > 0
    assert out["charm_direction"] in ("buying", "selling", "neutral")
    assert out["charm_magnitude"] in ("large", "moderate", "small", "negligible")


def test_net_charm_error_distinguishes_expiry_mismatch():
    out = compute_net_charm(
        [_charm_contract(expirationDate="2099-06-06")],
        500.0,
        "2099-05-05",
    )
    assert out["contracts_used"] == 0
    assert "expirationDate matching" in out["error"]


def test_net_charm_error_reports_quality_gate_skips():
    from math_exposure_core import MISSING_GREEK_SENTINEL

    out = compute_net_charm(
        [_charm_contract(gamma=MISSING_GREEK_SENTINEL)],
        500.0,
        "2099-05-05",
    )
    assert out["contracts_used"] == 0
    assert "quality gates" in out["error"]
    assert "gamma=1" in out["error"]


def test_charm_unavailable_log_level_quality_gate_is_debug_regardless_of_skip_shape():
    """All quality-gate failures (used==0 by definition at this path) are the same
    steady-state class: complete chain unusable for charm. Whether the skip breakdown
    is uniform (40-gamma) or mixed (37-gamma + 3-oi) does not change the operator-
    actionable signal — both surface as 'chain quality blocked charm' on this tick.
    Per-tick INFO for this class was log spam; DEBUG preserves the diagnostic detail
    in the error string without flooding logs outside RTH or during feed-quality dips.
    """
    from math_exposure_core import charm_compute_unavailable_log_level
    import logging

    # SPY-shape: uniform single-category (40 gamma).
    spy_uniform = (
        "No contracts passed charm quality gates for expiry=2026-05-26 "
        "(input=40, skipped: expiry=0, oi=0, gamma=40, iv=0, mult=0, T=0, "
        "fields=0, side=0, math=0)"
    )
    assert charm_compute_unavailable_log_level(spy_uniform) == logging.DEBUG

    # IWM-shape: mixed (37 gamma + 3 oi) — the operator regression case that
    # exposed the over-narrow uniform-only rule. Same condition class, same level.
    iwm_mixed = (
        "No contracts passed charm quality gates for expiry=2026-05-26 "
        "(input=40, skipped: expiry=0, oi=3, gamma=37, iv=0, mult=0, T=0, "
        "fields=0, side=0, math=0)"
    )
    assert charm_compute_unavailable_log_level(iwm_mixed) == logging.DEBUG

    # Mixed at smaller scale.
    mixed_small = (
        "No contracts passed charm quality gates for expiry=2026-05-26 "
        "(input=4, skipped: gamma=2, oi=2)"
    )
    assert charm_compute_unavailable_log_level(mixed_small) == logging.DEBUG

    # Simplified test-fixture format (legacy single-category shape).
    simplified = (
        "No contracts passed charm quality gates for expiry=2026-05-26 "
        "(input=40, skipped: gamma=40)"
    )
    assert charm_compute_unavailable_log_level(simplified) == logging.DEBUG


def test_charm_unavailable_log_level_warning_for_expiry_and_empty():
    """Non-quality-gate errors (expiry mismatch / empty input) remain WARNING —
    different class (chain misrouted or no contracts at all); operator should act."""
    from math_exposure_core import charm_compute_unavailable_log_level
    import logging

    assert charm_compute_unavailable_log_level(
        "No contracts with expirationDate matching expiry=2026-05-26 (input=40)"
    ) == logging.WARNING
    assert charm_compute_unavailable_log_level(
        "No contracts provided for expiry=2026-05-26"
    ) == logging.WARNING
    assert charm_compute_unavailable_log_level(None) == logging.WARNING
    assert charm_compute_unavailable_log_level("") == logging.WARNING
