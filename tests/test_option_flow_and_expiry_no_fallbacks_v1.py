"""Option-flow scores and expiry selection: measured or absent, never substituted.

2026-09-24, fallback register S-06, S-07, N-11 (operator rule: no fallbacks). Measured on the
real captured chains (568 contracts): bidSize / askSize / totalVolume are reported on every
contract, 0 often -- so an absent side is a known zero and an unreported one is UNKNOWN.
"""
from __future__ import annotations

import inspect

from math_exposure_core import compute_exposures_by_strike
from math_probabilities import (
    compute_option_flow_imbalance,
    compute_smart_money_signal,
    option_flow_book_imbalance,
)

SPOT = 100.0


def _c(k, typ, *, bid_size=10, ask_size=5, vol=100, oi=1000):
    # institutional-synthetic-ok: these tests MUST feed unreported sizes / zero books, which
    # no captured chain provides on demand.
    ct = {"strikePrice": k, "putCall": typ, "daysToExpiration": 0, "delta": 0.5 if typ == "CALL" else -0.5,
          "gamma": 0.02, "openInterest": oi, "multiplier": 100}
    if bid_size is not None:
        ct["bidSize"] = bid_size
    if ask_size is not None:
        ct["askSize"] = ask_size
    if vol is not None:
        ct["totalVolume"] = vol
    return ct


def _book(cts):
    ex, _ = compute_exposures_by_strike(cts, spot=SPOT, require_oi=True)
    return ex


def test_book_imbalance_has_no_volume_stand_in():
    ex = _book([_c(100.0, "CALL", bid_size=0, ask_size=0, vol=500),
                _c(100.0, "PUT", bid_size=0, ask_size=0, vol=10)])
    # zero displayed size: the imbalance is undefined -- it used to switch to the volume ratio
    assert option_flow_book_imbalance(ex, SPOT) == (None, "none")
    ex2 = _book([_c(100.0, "CALL", bid_size=30, ask_size=10), _c(100.0, "PUT", bid_size=10, ask_size=10)])
    norm, src = option_flow_book_imbalance(ex2, SPOT)
    assert src == "book" and norm == round((20 - 0) / 60, 3)


def test_unreported_size_in_the_window_makes_flow_unknown():
    ex = _book([_c(100.0, "CALL"), _c(101.0, "PUT", bid_size=None)])
    assert compute_option_flow_imbalance(ex, SPOT)["normalized"] is None
    assert compute_option_flow_imbalance({}, SPOT)["label"] is None      # no data: no label


def test_smart_money_needs_every_component():
    full = _book([_c(100.0, "CALL"), _c(100.0, "PUT", bid_size=5, ask_size=10)])
    assert compute_smart_money_signal(full, SPOT)["score"] is not None
    no_vol = _book([_c(100.0, "CALL", vol=0), _c(100.0, "PUT", vol=0)])
    assert compute_smart_money_signal(no_vol, SPOT)["score"] is None     # vol/OI base undefined
    unreported = _book([_c(100.0, "CALL"), _c(100.0, "PUT", vol=None)])
    assert compute_smart_money_signal(unreported, SPOT)["score"] is None


def test_requested_past_expiry_is_refused_not_replaced():
    import server
    src = inspect.getsource(server._fetch_state)
    assert "— using default" not in src          # the old log line of the substitution
    assert "selected_exp = expiry or _default_expiry" not in src
    assert "requested_expiry_unavailable" in src
