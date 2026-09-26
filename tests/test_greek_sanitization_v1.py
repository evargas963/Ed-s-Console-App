"""FIND-GREEK-SANITIZATION-V1 — reject physically-impossible Schwab gamma."""

from __future__ import annotations

from math_exposure_core import (
    bucket_metric,
    compute_exposures_by_strike,
    gamma_is_plausible,
    pick_net_gex_peak_strike,
)


def _ct(**kw):
    # institutional-synthetic-ok: sanitizer/exclusion fail-closed test needs controlled
    # inputs (a clean set vs the same set + one known-corrupt contract) to prove EXACT
    # exclusion; that comparison cannot be done on found real data.
    base = {
        "strikePrice": 740.0,
        "putCall": "CALL",
        "openInterest": 100,
        "totalVolume": 1,
        "bidSize": 1,
        "askSize": 1,
        "delta": 0.50,
        "gamma": 0.04,
        "vega": 0.02,
        "volatility": 20.0,
        "multiplier": 100,
    }
    base.update(kw)
    return base


# Real contaminated fixture from reports/gex_gamma_flip_audit.md Finding 0
SPY_748P_CORRUPT = _ct(
    strikePrice=748.0,
    putCall="PUT",
    gamma=-91965.237,
    delta=-0.979,
    openInterest=21605,
)


def test_gamma_is_plausible_rejects_negative_and_keeps_atm() -> None:
    assert gamma_is_plausible(0.04, iv=20.0) is True
    assert gamma_is_plausible(-91965.237, iv=35.51) is False
    # 3.647 on a 742 underlying at 20% vol, 30 days: peak gamma ~0.009 -- impossible
    assert gamma_is_plausible(3.647, iv=20.0, spot=742.0, t_years=30 / 365) is False


def test_corrupt_spy_748p_excluded_from_gamma_sums_oi_kept() -> None:
    normal_call = _ct(strikePrice=740.0, putCall="CALL", gamma=0.04, delta=0.50, openInterest=500)
    normal_put = _ct(strikePrice=735.0, putCall="PUT", gamma=0.03, delta=-0.45, openInterest=400)
    atm = _ct(strikePrice=742.0, putCall="CALL", gamma=0.05, delta=0.48, openInterest=300)

    with_bad = [normal_call, normal_put, atm, SPY_748P_CORRUPT]
    clean = [normal_call, normal_put, atm]

    exp_bad, diag_bad = compute_exposures_by_strike(with_bad, spot=742.0)
    exp_clean, _diag_clean = compute_exposures_by_strike(clean, spot=742.0)

    # (a) corrupt contract excluded from gamma sums
    bad_bucket = exp_bad[748.0]
    assert bucket_metric(bad_bucket, "put_gamma") is None
    # OI-only metrics still record the contract
    assert bad_bucket.get("put_oi") == 21605.0

    # (b) net_gamma / pin match the clean set
    def total_net_gamma(exp: dict) -> float:
        return sum(g for b in exp.values() if (g := bucket_metric(b, "net_gamma")) is not None)

    assert abs(total_net_gamma(exp_bad) - total_net_gamma(exp_clean)) < 1e-9
    strikes_bad = sorted(exp_bad)
    strikes_clean = sorted(exp_clean)
    # pin from gamma-bearing strikes only — both should agree on ATM/normal set
    peak_bad = pick_net_gex_peak_strike(exp_bad, strikes_bad)
    peak_clean = pick_net_gex_peak_strike(exp_clean, strikes_clean)
    assert peak_bad == peak_clean

    # Sign of aggregate net gamma matches
    assert (total_net_gamma(exp_bad) > 0) == (total_net_gamma(exp_clean) > 0)

    # Without sanitization the bad put would dominate; with it, diag still counts used
    assert diag_bad.contracts_used >= 3
    # corrupt row still "used" for OI path but gamma marked missing
    assert diag_bad.greeks_missing >= 1


def test_normal_atm_gamma_retained() -> None:
    atm = _ct(strikePrice=742.0, putCall="CALL", gamma=0.04, delta=0.50, openInterest=200)
    exp, diag = compute_exposures_by_strike([atm], spot=742.0)
    assert diag.contracts_used == 1
    assert exp[742.0]["call_gamma"] == 0.04 * 200 * 100
    assert gamma_is_plausible(0.04, iv=20.0) is True


