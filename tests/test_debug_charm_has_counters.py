"""`/api/debug/charm` honest greek/IV presence counters.

The counter pattern in `server.debug_charm` must classify a contract as having
``has_gamma`` only when the gamma value is a usable wire read (not None,
not Schwab's ``-999.0`` missing-greek sentinel (`MISSING_GREEK_SENTINEL`), not NaN/Inf). The same applies
to ``has_delta``, ``has_theta``, ``has_vega``, and ``has_iv``.

These tests pin the inline counter expression that the route uses on raw
Schwab chain dicts. Each comprehension below is the literal inline expression
the route uses for a single field — duplicated per field on purpose so the
sentinel rules are visible at every read site.
"""

from __future__ import annotations

import math

from math_exposure import MISSING_GREEK_SENTINEL


def _row(**overrides):
    # institutional-synthetic-ok: greek-presence counter tests inject sentinel/None/NaN
    # greeks to prove has_gamma/has_delta/... classification; controlled input required.
    base = {
        "putCall": "CALL",
        "strikePrice": 500.0,
        "delta": 0.5,
        "gamma": 0.05,
        "theta": -0.1,
        "vega": 0.02,
        "rho": 0.01,
        "volatility": 0.22,
        "openInterest": 100,
    }
    base.update(overrides)
    return base


def _gamma_count(contracts):
    n = 0
    for ct in contracts:
        v = ct.get("gamma")
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != MISSING_GREEK_SENTINEL and math.isfinite(f):
            n += 1
    return n


def _delta_count(contracts):
    n = 0
    for ct in contracts:
        v = ct.get("delta")
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != MISSING_GREEK_SENTINEL and math.isfinite(f):
            n += 1
    return n


def _theta_count(contracts):
    n = 0
    for ct in contracts:
        v = ct.get("theta")
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != MISSING_GREEK_SENTINEL and math.isfinite(f):
            n += 1
    return n


def _vega_count(contracts):
    n = 0
    for ct in contracts:
        v = ct.get("vega")
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != MISSING_GREEK_SENTINEL and math.isfinite(f):
            n += 1
    return n


def _iv_count(contracts):
    n = 0
    for ct in contracts:
        v = ct.get("volatility")
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0 and f != MISSING_GREEK_SENTINEL and math.isfinite(f):
            n += 1
    return n


def _gamma_sentinel_count(contracts):
    return sum(1 for ct in contracts if ct.get("gamma") == MISSING_GREEK_SENTINEL)


def test_gamma_excludes_minus_999_sentinel():
    contracts = [
        _row(gamma=0.05),
        _row(gamma=MISSING_GREEK_SENTINEL),
        _row(gamma=None),
        _row(gamma=0.0),
    ]
    assert _gamma_count(contracts) == 2  # 0.05 and 0.0 are usable; -999 and None are not
    assert _gamma_sentinel_count(contracts) == 1


def test_iv_reads_volatility_only_no_theoretical_fallback():
    """``debug_charm`` reads ``volatility`` directly; no fallback to
    ``theoreticalVolatility`` (helper-era ladder is gone).
    """
    contracts = [
        _row(volatility=0.22),
        _row(volatility=MISSING_GREEK_SENTINEL, theoreticalVolatility=18.5),
        _row(volatility=MISSING_GREEK_SENTINEL, theoreticalVolatility=MISSING_GREEK_SENTINEL),
        _row(volatility=None, theoreticalVolatility=None),
    ]
    assert _iv_count(contracts) == 1


def test_counters_reject_nan_and_inf():
    """Each row spoils exactly one greek; the targeted counter drops by 1."""
    contracts = [
        _row(delta=float("nan")),
        _row(theta=float("inf")),
        _row(vega=float("-inf")),
        _row(),
    ]
    assert _delta_count(contracts) == 3
    assert _theta_count(contracts) == 3
    assert _vega_count(contracts) == 3
    assert _gamma_count(contracts) == 4
    assert _iv_count(contracts) == 4


def test_counters_match_total_when_all_clean():
    contracts = [_row() for _ in range(5)]
    assert _gamma_count(contracts) == 5
    assert _delta_count(contracts) == 5
    assert _theta_count(contracts) == 5
    assert _vega_count(contracts) == 5
    assert _iv_count(contracts) == 5
    assert _gamma_sentinel_count(contracts) == 0


def test_counters_zero_when_all_sentinels_or_missing():
    # institutional-synthetic-ok: missing-greek-key test needs a bare contract with no
    # greek fields to prove has_X counters report 0.
    contracts = [
        _row(
            delta=MISSING_GREEK_SENTINEL,
            gamma=MISSING_GREEK_SENTINEL,
            theta=MISSING_GREEK_SENTINEL,
            vega=MISSING_GREEK_SENTINEL,
            volatility=MISSING_GREEK_SENTINEL,
            theoreticalVolatility=None,
        ),
        {"putCall": "CALL", "strikePrice": 500.0},  # bare row, no greek keys
    ]
    assert _gamma_count(contracts) == 0
    assert _delta_count(contracts) == 0
    assert _theta_count(contracts) == 0
    assert _vega_count(contracts) == 0
    assert _iv_count(contracts) == 0
    assert _gamma_sentinel_count(contracts) == 1
