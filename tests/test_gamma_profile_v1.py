"""FIND-GAMMA-FLIP-METHOD-V1 — canonical gamma profile (hypothetical-spot recompute).

Proven 2026-07-19 on a real SPY reference chain that the cumulative-sum method does NOT
reproduce the published profile (corr 0.086, never crosses zero, 2.19e9 divergence).
Only recomputing every contract's gamma at each candidate price reproduces the published
flip. These tests run on a REAL captured Schwab chain, never a hand-built one.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import time_et
from math_levels import (
    GAMMA_FLIP_UNAVAILABLE,
    GSF_STATE_BELOW_SUPPORT,
    GSF_STATE_OK,
    GSF_STATE_UNAVAILABLE,
    compute_gamma_flip_v2,
    compute_gamma_profile,
    compute_gamma_support_levels,
    contract_inputs,
    gamma_at_price,
    gamma_flip_from_profile,
)
from option_contract import OptionContract, read_chain, read_contract
from terrain_engine import compute_terrain

#: a REAL same-day-expiry SPY chain the capture daemon captured 2026-10-07 12:32 ET, valued at its
#: own capture time (a live 0DTE, ~3.7 h to SPY's 16:15 option close)
_REAL_CHAIN = Path(__file__).parent / "fixtures" / "real_spy_0dte_chain_2026_10_07.json"
_DATA = json.loads(_REAL_CHAIN.read_text(encoding="utf-8"))
NOW = datetime.fromtimestamp(_DATA["ts_utc"], time_et.ET)


def _load_real_chain() -> tuple[list[OptionContract], float]:
    return read_chain(_DATA["chain"]), float(_DATA["spot"])


def _profile(contracts: list[OptionContract], spot: float) -> list[tuple[float, float]]:
    """The gamma profile as compute_terrain builds it for SPY: rows priced to its option close."""
    product = time_et.option_close_product("SPY")
    priced, _unpriced = contract_inputs(contracts, NOW, product=product)
    return compute_gamma_profile(priced, spot)


def _one(symbol: str) -> list[tuple[float, float]]:
    """The profile of one contract of the real chain alone, on the chain's own grid."""
    chain, spot = _load_real_chain()
    return _profile([c for c in chain if c.symbol == symbol], spot)


def _crossings(prof: list[tuple[float, float]], sign: int) -> list[tuple[float, float]]:
    """The neighbouring prices between which the profile goes from `sign` to its opposite."""
    return [(p0, p1) for (p0, v0), (p1, v1) in zip(prof, prof[1:]) if v0 * sign > 0 > v1 * sign]


def _tsla() -> tuple[list[tuple[float, float]], float]:
    """Schwab's whole TSLA chain of 2026-10-07 as its profile, with the spot it came with."""
    name = "real_tsla_complete_chain_2026_10_07.json"
    data = json.loads((_REAL_CHAIN.parent / name).read_text(encoding="utf-8"))
    at = datetime.fromtimestamp(data["ts_utc"], time_et.ET)
    product = time_et.option_close_product("TSLA")
    priced, _unpriced = contract_inputs(read_chain(data["chain"]), at, product=product)
    return compute_gamma_profile(priced, float(data["spot"])), float(data["spot"])


def test_profile_on_real_chain_is_finite_and_spans_spot() -> None:
    chain, spot = _load_real_chain()
    prof = _profile(chain, spot)
    assert len(prof) == 241
    assert all(math.isfinite(v) for _, v in prof)
    prices = [p for p, _ in prof]
    assert prices[0] < spot < prices[-1]
    assert prices == sorted(prices)


def test_profile_uses_dealer_sign_convention() -> None:
    """Calls add, puts subtract: an all-call book must be positive at every price."""
    chain, spot = _load_real_chain()
    calls = [c for c in chain if c.side == "CALL"]
    assert calls, "fixture must contain calls"
    prof = _profile(calls, spot)
    assert prof and all(v >= 0 for _, v in prof)


def test_flip_is_interpolated_within_the_profile_span() -> None:
    """RC-467: the real chain MUST yield a flip.

    The old `if flip is not None` guard let a flip-always-None regression pass silently while
    asserting nothing. MEASURED on this
    fixture at its capture time: 241 profile points, 1 sign crossing, flip = 779.02, inside
    the span. Existence is pinned; the exact value is not (it moves with vol/time inputs) -
    span containment is the invariant.
    """
    chain, spot = _load_real_chain()
    prof = _profile(chain, spot)
    flip = gamma_flip_from_profile(prof, spot)
    assert flip is not None, (
        "the real fixture chain has a zero crossing (measured flip 779.02); a None flip "
        "here means the profile or crossing detection regressed"
    )
    assert prof[0][0] <= flip <= prof[-1][0]


def test_flip_v2_fails_closed_without_inputs() -> None:
    for contracts, spot in (
        ([], 100.0),
        (None, 100.0),
        ([read_contract({"strikePrice": 100})], 0.0),
    ):
        flip, confidence, _diag = compute_gamma_flip_v2(contracts, spot, profile=[])
        assert flip is None and confidence == GAMMA_FLIP_UNAVAILABLE


def test_regime_is_defined_even_when_the_profile_never_crosses_zero() -> None:
    """RC-11: no zero-crossing means no FLIP LEVEL, never an unknown regime.

    A chain whose dealer gamma holds one sign at every price has an unambiguous regime --
    arguably more certain than one with a flip beside spot. Before this was corrected, 20
    of 51 live tickers reported UNAVAILABLE while their gamma was uniformly signed.
    """
    chain, spot = _load_real_chain()
    prof = _profile(chain, spot)
    assert prof, "real chain must produce a profile"

    at_spot = gamma_at_price(prof, spot)
    assert at_spot is not None and math.isfinite(at_spot)

    # interpolation must sit inside the bracketing profile values
    pts = sorted(prof)
    below = [v for x, v in pts if x <= spot]
    above = [v for x, v in pts if x >= spot]
    if below and above:
        lo, hi = min(below[-1], above[0]), max(below[-1], above[0])
        assert lo - 1e-6 <= at_spot <= hi + 1e-6

    # a strictly one-signed profile (the chain's calls alone) yields no flip but still reports a
    # usable value, halfway between two of its points their mean
    calls = _profile([c for c in chain if c.side == "CALL"], spot)
    (p0, v0), (p1, v1) = calls[150], calls[151]
    assert gamma_flip_from_profile(calls, spot) is None
    assert math.isclose(gamma_at_price(calls, (p0 + p1) / 2), (v0 + v1) / 2, rel_tol=1e-9)


def test_gamma_at_price_clamps_outside_the_profile() -> None:
    chain, spot = _load_real_chain()
    prof = _profile(chain, spot)
    assert gamma_at_price(prof, prof[0][0] - 50.0) == prof[0][1]  # below -> first value
    assert gamma_at_price(prof, prof[-1][0] + 50.0) == prof[-1][1]  # above -> last value
    assert gamma_at_price([], spot) is None
    assert gamma_at_price(prof, None) is None


def test_flip_detects_positive_to_negative_crossing():
    """Induced: the real chain's calls below 777 and puts above it, its in-the-money half.

    Every captured whole book crosses from negative to positive. This selection is long gamma
    below and short gamma above, a boundary the other way.
    """
    chain, spot = _load_real_chain()
    half = [c for c in chain if (c.strike < 777) == (c.side == "CALL") and c.strike != 777]
    prof = _profile(half, spot)
    ((below, above),) = _crossings(prof, 1)
    flip = gamma_flip_from_profile(prof, spot)
    assert flip is not None, "the positive-to-negative crossing was missed"
    assert below < flip < above and not _crossings(prof, -1), flip


def test_flip_still_detects_negative_to_positive():
    """The whole real chain crosses once, upward, between 778.55 and 779.52."""
    chain, spot = _load_real_chain()
    prof = _profile(chain, spot)
    ((below, above),) = _crossings(prof, -1)
    flip = gamma_flip_from_profile(prof, spot)
    assert flip is not None and 778.55 < below < flip < above < 779.53, flip


def test_flip_picks_the_crossing_nearest_spot():
    """Multi-cross profile: the boundary that governs the trade is the one beside spot.

    Induced: the real chain's puts from 774 to 779 with its calls outside them, which crosses
    down below 774 and up again below 779.
    """
    chain, spot = _load_real_chain()
    band = [c for c in chain if (774 <= c.strike <= 779) == (c.side == "PUT")]
    prof = _profile(band, spot)
    ((down_lo, down_hi),) = _crossings(prof, 1)
    ((up_lo, up_hi),) = _crossings(prof, -1)
    near_low = gamma_flip_from_profile(prof, spot=770.0)
    near_high = gamma_flip_from_profile(prof, spot=780.0)
    assert near_low is not None and down_lo < near_low < down_hi < 774, near_low
    assert near_high is not None and 774 < up_lo < near_high < up_hi, near_high
    assert near_low != near_high


def test_flip_none_when_one_signed():
    chain, spot = _load_real_chain()
    puts = _profile([c for c in chain if c.side == "PUT"], spot)
    calls = _profile([c for c in chain if c.side == "CALL"], spot)
    assert all(v < 0 for _, v in puts) and gamma_flip_from_profile(puts, spot) is None
    assert all(v > 0 for _, v in calls) and gamma_flip_from_profile(calls, spot) is None
    assert gamma_flip_from_profile([], spot) is None


def test_flip_zero_touching_profile_start_is_the_boundary():
    """A profile that starts at exactly zero has its boundary at the last zero price.

    One same-day contract alone: its gamma is exactly 0.0 far from its strike, so the profile of
    the real 777 call starts and ends with a run of zeros, and the 777 put's the same, negative.
    """
    call, put = _one("SPY   261007C00777000"), _one("SPY   261007P00777000")
    live = [p for p, v in call if v != 0.0]
    last_zero_before = max(p for p, v in call if v == 0.0 and p < live[0])
    first_zero_after = min(p for p, v in call if v == 0.0 and p > live[-1])
    assert gamma_flip_from_profile(call, call[0][0]) == last_zero_before
    assert all(v <= 0 for _, v in put) and gamma_flip_from_profile(put, put[0][0]) == (
        last_zero_before
    )
    # flat zero segments are not crossings
    zeros = [(p, v) for p, v in call if p <= last_zero_before]
    assert len(zeros) > 1 and gamma_flip_from_profile(zeros, call[0][0]) is None
    # segment ENDING at zero still interpolates to the zero point
    assert math.isclose(gamma_flip_from_profile(call, call[-1][0]), first_zero_after, rel_tol=1e-12)


def test_gsf_sits_between_flip_and_spot_and_grc_mirrors_above():
    """Schwab's whole TSLA book of 2026-10-07: positive at spot, its flip below.

    The floor is where the profile has fallen to half its value at spot, so the two profile
    points around it hold that half between them. Above spot the same holds for the ceiling.
    """
    prof, spot = _tsla()
    out = compute_gamma_support_levels(prof, spot)
    assert out["state"] == GSF_STATE_OK
    assert out["gsf"] is not None
    flip = gamma_flip_from_profile(prof, spot)
    assert flip is not None and out["gsf"] > flip  # above the flip
    assert flip < out["gsf"] < spot  # between flip and spot
    half = 0.5 * gamma_at_price(prof, spot)
    under = max((p, v) for p, v in prof if p < out["gsf"])
    over = min((p, v) for p, v in prof if p > out["gsf"])
    assert under[1] <= half < over[1]
    assert out["grc"] is not None and out["grc"] > spot


def test_grc_found_when_cushion_decays_above_spot():
    """The real TSLA profile rises to a peak above spot, then decays.

    The ceiling lands on the decaying shoulder past the peak (resistance strengthens before it
    exhausts), where the profile has fallen to half its value at spot.
    """
    prof, spot = _tsla()
    out = compute_gamma_support_levels(prof, spot)
    peak = max(prof, key=lambda point: point[1])[0]
    assert out["state"] == GSF_STATE_OK
    assert out["grc"] is not None and out["grc"] > peak > spot  # beyond the peak/wall
    half = 0.5 * gamma_at_price(prof, spot)
    under = max((p, v) for p, v in prof if p < out["grc"])
    over = min((p, v) for p, v in prof if p > out["grc"])
    assert over[1] <= half < under[1]


def test_below_support_state_never_fabricates_a_price():
    """The whole real SPY chain is negative at spot: a state, both levels None."""
    chain, spot = _load_real_chain()
    prof = _profile(chain, spot)
    assert gamma_at_price(prof, spot) < 0
    out = compute_gamma_support_levels(prof, spot)
    assert out["state"] == GSF_STATE_BELOW_SUPPORT
    assert out["gsf"] is None and out["grc"] is None


def test_unavailable_on_empty_or_bad_inputs():
    prof, spot = _tsla()
    assert compute_gamma_support_levels([], spot)["state"] == GSF_STATE_UNAVAILABLE
    assert compute_gamma_support_levels(prof, None)["state"] == GSF_STATE_UNAVAILABLE
    assert compute_gamma_support_levels(prof, -5)["state"] == GSF_STATE_UNAVAILABLE


def test_the_flip_counts_the_contracts_it_could_not_price():
    """M-10: the served flip counts the contracts it could not price, and says why.

    The profile cannot price a contract with open interest whose volatility Schwab sent as
    -999; one beyond a year runs to Schwab's own expirationDate. The served flip says how
    many were left out and why.
    Real captures of 2026-10-07: NFLX (10:32 ET; PM) -- on 2026-10-16, 100 contracts with open
    interest and a volatility; on 2027-12-17 and 2028-01-21, 585 with a volatility and 8 sent
    -999 -- and $SPX's AM-settled 2027-12-17 expiry (10:37 ET; 288 with open interest).
    """
    fx = Path(__file__).parent / "fixtures"
    nflx = json.loads(
        (fx / "real_nflx_chain_2026_10_07_three_expiries.json").read_text(encoding="utf-8")
    )
    spx = json.loads((fx / "real_spx_chain_2026_10_07_2027_12_17.json").read_text(encoding="utf-8"))
    now = datetime.fromtimestamp(nflx["ts_utc"], time_et.ET)
    nflx_chain = read_chain(nflx["chain"])
    nflx_close = time_et.option_close_product("NFLX")
    priced, unpriced = contract_inputs(nflx_chain, now, product=nflx_close)
    assert (len(priced), unpriced) == (685, {"no_volatility": 8})
    far = next(ct for ct in nflx["chain"] if ct["expirationDate"].startswith("2028-01-21"))
    assert (
        time_et.time_to_expiry_years(
            far["expirationDate"], now, settlement_type=far["settlementType"]
        )
        == (datetime.fromisoformat(far["expirationDate"]).timestamp() - now.timestamp())
        / time_et.YEAR_SECONDS
    )
    snap = compute_terrain("NFLX", nflx_chain, nflx["spot"], now=now)
    assert snap.to_dict()["flip_diag"]["unpriced"] == {"no_volatility": 8}
    at = datetime.fromtimestamp(spx["ts_utc"], time_et.ET)
    spx_close = time_et.option_close_product("$SPX")
    assert contract_inputs(read_chain(spx["chain"]), at, product=spx_close)[1] == {}
