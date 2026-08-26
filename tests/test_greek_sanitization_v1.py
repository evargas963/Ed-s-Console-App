"""FIND-GREEK-SANITIZATION-V1 — reject physically-impossible Schwab gamma."""

from __future__ import annotations

from math_exposure_core import (
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
    assert gamma_is_plausible(0.04, 0.50) is True
    assert gamma_is_plausible(-91965.237, -0.979) is False
    assert gamma_is_plausible(3.647, 0.99) is False
    assert gamma_is_plausible(0.04, -0.99) is False  # deep |delta|>=0.98 + non-zero gamma
    # Fixture |delta|=0.979 is just under the deep threshold; negative gamma still rejects it.
    assert gamma_is_plausible(-91965.237, -0.979) is False


def test_corrupt_spy_748p_excluded_from_gamma_sums_oi_kept() -> None:
    normal_call = _ct(strikePrice=740.0, putCall="CALL", gamma=0.04, delta=0.50, openInterest=500)
    normal_put = _ct(strikePrice=735.0, putCall="PUT", gamma=0.03, delta=-0.45, openInterest=400)
    atm = _ct(strikePrice=742.0, putCall="CALL", gamma=0.05, delta=0.48, openInterest=300)

    with_bad = [normal_call, normal_put, atm, SPY_748P_CORRUPT]
    clean = [normal_call, normal_put, atm]

    exp_bad, diag_bad = compute_exposures_by_strike(with_bad, spot=742.0)
    exp_clean, _diag_clean = compute_exposures_by_strike(clean, spot=742.0)

    # (a) corrupt contract excluded from gamma sums
    bad_bucket = exp_bad.get(748.0, {})
    # RC-274 repair 2026-08-26: this asserted `== 0.0`, which pinned the MECHANISM (an
    # untouched 0.0 accumulator) rather than this test's stated intent — that the corrupt
    # contract contributes NOTHING. A 0.0 could not express that: it read identically to a
    # strike measured at flat gamma, which is how a rejected strike reached the terrain panel
    # as a real-looking bar at zero. Absence is now None, so the intent is asserted directly
    # AND the stronger property holds: excluded is distinguishable from measured-flat.
    assert bad_bucket.get("put_gamma") is None, "a rejected gamma left a fabricated number"
    assert bad_bucket.get("net_gex_1pct") is None, "rejected greeks produced a measured net"
    # OI-only metrics still record the contract
    assert bad_bucket.get("put_oi") == 21605.0

    # (b) net_gamma / pin match the clean set
    def total_net_gamma(exp: dict) -> float:
        return sum(float(b.get("net_gamma") or 0.0) for b in exp.values())

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
    assert gamma_is_plausible(0.04, 0.50) is True


def test_gex_r1_screen_skips_corrupt_gamma() -> None:
    from research.gex_r1_screen_v1.signal import gex_0dte_from_chain

    import json
    import math
    from pathlib import Path

    # Real captured SPY 0DTE chain that actually contains the -91965 poison PUT.
    fx = json.loads(
        (Path(__file__).parent / "fixtures" / "real_spy_0dte_chain_with_poison.json").read_text(encoding="utf-8")
    )
    chain, spot = fx["chain"], float(fx["spot"])
    poison = [c for c in chain if c.get("gamma") is not None and abs(float(c["gamma"])) > 1.0]
    assert poison, "fixture must contain a real poisoned-gamma contract"
    p = poison[0]
    poison_raw = abs(float(p["gamma"]) * float(p["openInterest"]) * 100.0 * spot * spot * 0.01)

    gex, n_c, n_p = gex_0dte_from_chain(chain, spot)
    assert math.isfinite(gex)
    # sanitizer excluded the poison: |gex| is orders of magnitude below its raw contribution
    assert abs(gex) < poison_raw * 0.01
