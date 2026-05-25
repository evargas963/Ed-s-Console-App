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


def test_charm_unavailable_log_level_uniform_skip_is_debug():
    """Uniform single-category skip (all 40 contracts failed gamma gate) is a
    steady-state chain-feed condition, not per-tick INFO. The operator complaint
    was log spam from SPY outside RTH when every contract has gamma=-999."""
    from math_exposure_core import charm_compute_unavailable_log_level
    import logging

    # Full production format (server.py:3486-3492 actual log) — all skips in one category.
    full_uniform = (
        "No contracts passed charm quality gates for expiry=2026-05-26 "
        "(input=40, skipped: expiry=0, oi=0, gamma=40, iv=0, mult=0, T=0, "
        "fields=0, side=0, math=0)"
    )
    assert charm_compute_unavailable_log_level(full_uniform) == logging.DEBUG

    # Simplified test-fixture format (legacy paired-fix shape) — same uniform property.
    simplified_uniform = (
        "No contracts passed charm quality gates for expiry=2026-05-26 "
        "(input=40, skipped: gamma=40)"
    )
    assert charm_compute_unavailable_log_level(simplified_uniform) == logging.DEBUG


def test_charm_unavailable_log_level_mixed_skips_stays_info():
    """Mixed skip distribution indicates transient partial-quality (some gamma,
    some OI gaps) — operator may want to see this; keep at INFO."""
    from math_exposure_core import charm_compute_unavailable_log_level
    import logging

    mixed = (
        "No contracts passed charm quality gates for expiry=2026-05-26 "
        "(input=40, skipped: expiry=0, oi=10, gamma=20, iv=10, mult=0, T=0, "
        "fields=0, side=0, math=0)"
    )
    assert charm_compute_unavailable_log_level(mixed) == logging.INFO

    # Edge: two-category mixed at smaller scale.
    mixed_small = (
        "No contracts passed charm quality gates for expiry=2026-05-26 "
        "(input=4, skipped: gamma=2, oi=2)"
    )
    assert charm_compute_unavailable_log_level(mixed_small) == logging.INFO


def test_charm_unavailable_log_level_warning_for_expiry_and_empty():
    """Non-quality-gate errors (expiry mismatch / empty input) remain WARNING —
    these are not steady-state and warrant operator attention."""
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


def test_charm_skip_uniform_helper_edge_cases():
    """_charm_skip_is_uniform_steady_state edge cases: parse robustness."""
    from math_exposure_core import _charm_skip_is_uniform_steady_state

    # No input= → False (can't determine uniformity)
    assert _charm_skip_is_uniform_steady_state("No contracts passed charm quality gates") is False
    # input=0 → False (no contracts to skip uniformly from)
    assert _charm_skip_is_uniform_steady_state("input=0, skipped: gamma=0") is False
    # Partial sum (skips < input) → False (shouldn't happen but be safe)
    assert _charm_skip_is_uniform_steady_state("input=40, skipped: gamma=30)") is False
    # Single category equals input → True
    assert _charm_skip_is_uniform_steady_state("input=40, skipped: gamma=40)") is True
    # All zeros → False (zero non-zero categories)
    assert _charm_skip_is_uniform_steady_state(
        "input=40, skipped: expiry=0, oi=0, gamma=0, iv=0)"
    ) is False
