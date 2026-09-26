"""Schwab's Greeks, used as reported, with one validity rule (math_exposure_core).

A contract's gamma / delta is invalid only when it is missing, Schwab's -999 marker, or
physically impossible: negative gamma, |delta| > 1, or gamma above the contract's peak possible
gamma 1 / (sqrt(2 pi) S sigma sqrt(T)) with room for Schwab's pricing basis and its 3-decimal
rounding. MEASURED 2026-09-26 on 9,428 SPY contracts with OI: reported / peak gamma p99 1.078;
the one contract past the bound reported 5.274 (222x its peak).

Values that look odd but are Schwab's own pricing are real and used:
  * 0.000 / 0.001 gamma: Schwab rounds every Greek to 3 decimals.
  * delta exactly +-1 with gamma 0 and vega 0 on an in-the-money leg: Schwab's American-exercise
    pricing. MEASURED 2026-09-15..26 on the banked full chains: never on European $SPX (0 of
    47,382 legs), and on American contracts 31,501 in the money vs 1 out of the money.

A strike holding any contract with OI and invalid Greeks is excluded whole from every Greek
total -- never a partial strike -- and the excluded contracts are listed with the levels.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from math_exposure_core import (
    MISSING_GREEK_SENTINEL,
    bucket_metric,
    compute_exposures_by_strike,
    compute_net_vanna,
    delta_is_plausible,
    exposure_books,
    gamma_is_plausible,
    merge_exposure_books,
    vendor_greeks_unavailable,
)
from server import project_gamma_surface

_FX = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 9, 26, 14, 0, tzinfo=timezone.utc)
EXP = "2026-10-01T20:00:00.000+00:00"       # 5 days after NOW


def _ct(strike: float, side: str, oi, *, gamma=0.04, delta=0.5, vega=0.01, iv=20.0,
        exp=EXP, vol=0, symbol=None, mult=100.0):
    # institutional-synthetic-ok: each validity boundary needs one exactly-controlled field
    return {
        "strikePrice": strike, "putCall": side, "openInterest": oi, "multiplier": mult,
        "delta": delta if side == "CALL" else -abs(delta) if delta is not None else None,
        "gamma": gamma, "vega": vega, "volatility": iv, "totalVolume": vol,
        "expirationDate": exp,
        "symbol": symbol or f"TEST  261001{'C' if side == 'CALL' else 'P'}{int(strike * 1000):08d}",
    }


SPOT = 100.0


# ── 1. the validity rule ────────────────────────────────────────────────────────────────────

def test_the_minus_999_marker_invalidates_every_greek_on_the_contract():
    assert vendor_greeks_unavailable(MISSING_GREEK_SENTINEL)
    assert not gamma_is_plausible(0.04, iv=MISSING_GREEK_SENTINEL)
    assert not delta_is_plausible(0.5, iv=MISSING_GREEK_SENTINEL)
    assert not gamma_is_plausible(MISSING_GREEK_SENTINEL, iv=20.0)


def test_schwab_rounding_is_real_data():
    for g in (0.0, 0.001, 0.0005):
        assert gamma_is_plausible(g, iv=20.0, spot=740.0, t_years=5 / 365)


def test_the_american_exercise_pin_is_real_data():
    assert gamma_is_plausible(0.0, iv=61.39)
    assert delta_is_plausible(1.0, iv=61.39) and delta_is_plausible(-1.0, iv=7.83)


def test_negative_gamma_and_delta_past_one_are_impossible():
    assert not gamma_is_plausible(-91965.237, iv=35.51)
    assert not delta_is_plausible(1.2)
    assert not delta_is_plausible(float("nan"))


def test_gamma_past_the_contracts_peak_is_impossible():
    # 2026-09-26 SPY 261001C739: gamma 5.274, spot ~740, 5 days; peak ~0.03
    assert not gamma_is_plausible(5.274, iv=15.0, spot=740.0, t_years=5 / 365)
    peak = 0.0307
    assert gamma_is_plausible(peak * 1.4, iv=15.0, spot=740.0, t_years=5 / 365)


# ── 2. a strike with an invalid contract is excluded whole, and listed ─────────────────────

def test_a_strike_with_one_invalid_contract_has_no_greek_value():
    bad = _ct(100.0, "PUT", 700, gamma=5.274, delta=0.5, iv=15.0)
    good = _ct(100.0, "CALL", 500, gamma=0.04, delta=0.5, iv=20.0)
    other = _ct(105.0, "CALL", 300, gamma=0.03, delta=0.3, iv=20.0)
    exp, diag = compute_exposures_by_strike([bad, good, other], spot=SPOT, now=NOW)
    b = exp[100.0]
    assert b["has_oi"] and b["greeks_invalid"] == 1
    for key in ("call_gamma", "net_gamma", "net_gex_1pct", "net_dex_dollars", "call_vanna"):
        assert bucket_metric(b, key) is None, key          # never the call leg alone
    assert bucket_metric(b, "call_oi") == 500.0             # OI does not depend on Greeks
    assert bucket_metric(exp[105.0], "net_gamma") == 0.03 * 300 * 100
    assert diag.excluded == ((bad["symbol"], 100.0, 700.0),)


def test_net_vanna_leaves_out_an_excluded_strike():
    good = _ct(105.0, "CALL", 300, iv=20.0)
    bad = _ct(100.0, "CALL", 700, gamma=-1.0, iv=20.0)
    only_good, _ = compute_exposures_by_strike([good], spot=SPOT, now=NOW)
    with_bad, _ = compute_exposures_by_strike([good, bad], spot=SPOT, now=NOW)
    assert compute_net_vanna(with_bad, SPOT) == compute_net_vanna(only_good, SPOT)


def test_merged_books_keep_the_exclusion_and_the_list():
    bad = _ct(100.0, "PUT", 700, gamma=-1.0)
    a = compute_exposures_by_strike([bad], spot=SPOT, now=NOW)
    b = compute_exposures_by_strike([_ct(100.0, "CALL", 500)], spot=SPOT, now=NOW)
    merged, diag = merge_exposure_books([a, b])
    assert bucket_metric(merged[100.0], "net_gex_1pct") is None
    assert [e[0] for e in diag.excluded] == [bad["symbol"]]


def test_real_spy_capture_corrupt_put_is_excluded_and_pinned_calls_are_used():
    """tests/fixtures/real_spy_0dte_chain_with_poison.json: the 748 put reports gamma
    -91965.237 (excluded, strike 748 has no Greek value); the in-the-money 734-739 calls
    report delta 1.0 / gamma 0.0 (Schwab's American pricing -- used)."""
    fx = json.loads((_FX / "real_spy_0dte_chain_with_poison.json").read_text(encoding="utf-8"))
    exp, diag = compute_exposures_by_strike(fx["chain"], spot=fx["spot"], require_oi=True)
    assert bucket_metric(exp[748.0], "net_gex_1pct") is None
    assert [e[1] for e in diag.excluded] == [748.0]
    for k in (734.0, 735.0, 736.0, 737.0, 738.0, 739.0):
        assert exp[k]["has_valid_delta"] and exp[k]["has_valid_gamma"]
        assert bucket_metric(exp[k], "call_delta") > 0          # delta 1.0 x OI counted


# ── 3. a true zero stays a zero ─────────────────────────────────────────────────────────────

def test_genuine_balanced_zero_is_not_treated_as_invalid():
    call = _ct(100.0, "CALL", 500, gamma=0.04, delta=0.5, vega=0.1, iv=20.0)
    put = _ct(100.0, "PUT", 500, gamma=0.04, delta=-0.5, vega=0.1, iv=20.0)
    exposures, _diag = compute_exposures_by_strike([call, put], spot=SPOT, now=NOW)
    assert bucket_metric(exposures[100.0], "net_gex_1pct") == 0.0
    surface = project_gamma_surface([call, put], exposure_books([call, put], spot=SPOT))
    row = [r for r in surface["cells"] if r["strike"] == 100.0][0]
    assert row["gex"] == [0], "a genuine computed zero renders as 0"


# ── 4. the surface ──────────────────────────────────────────────────────────────────────────

def test_surface_cell_with_oi_but_invalid_greeks_is_none_not_zero():
    call = _ct(100.0, "CALL", 500, iv=MISSING_GREEK_SENTINEL)
    put = _ct(100.0, "PUT", 500, gamma=-3.0, iv=25.0)
    surface = project_gamma_surface([call, put], exposure_books([call, put], spot=SPOT))
    row = [r for r in surface["cells"] if r["strike"] == 100.0][0]
    assert row["gex"] == [None] and row["dex"] == [None] and row["vanna"] == [None]
    assert row["oi"] == [{"call": 500, "put": 500}]
    assert surface["gamma_available"] is False
    assert surface["cells_with_oi_but_invalid_greeks"] == 1
    assert "invalid" in surface["gamma_unavailable_reason"].lower()


def test_surface_reason_distinguishes_no_oi_from_invalid_greeks():
    no_oi_call = _ct(100.0, "CALL", 0)
    no_oi_put = _ct(100.0, "PUT", 0)
    surface = project_gamma_surface([no_oi_call, no_oi_put], exposure_books([no_oi_call, no_oi_put], spot=SPOT))
    assert surface["gamma_available"] is False
    assert surface["cells_with_oi_but_invalid_greeks"] == 0
    assert "no usable open interest" in surface["gamma_unavailable_reason"].lower()


# ── 5. no refill from an older value ────────────────────────────────────────────────────────

def test_no_cell_is_ever_refilled_from_an_older_value():
    import inspect

    import db as db_mod
    import server
    src = inspect.getsource(server)
    for gone in ("_backfill_gex_cells_from_last_valid", "_LAST_VALID_GEX_CELLS",
                 "banked_morning_reference"):
        assert gone not in src, gone
    assert not hasattr(db_mod.EdDB, "load_gamma_surface_last_valid")
    assert not hasattr(db_mod.EdDB, "persist_gamma_surface_last_valid")


def test_the_levels_payload_lists_every_excluded_contract():
    from terrain_engine import compute_terrain
    fx = json.loads((_FX / "real_spy_0dte_chain_with_poison.json").read_text(encoding="utf-8"))
    out = compute_terrain("SPY", fx["chain"], fx["spot"]).to_dict()
    assert out["greeks_excluded"] == [{"symbol": "SPY   260717P00748000", "strike": 748.0, "oi": 21605.0}]
