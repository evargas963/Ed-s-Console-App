"""order_flow_engine._compute_options_flow must not treat a missing total_volume as
zero flow -- the same missing-vs-zero contract as the live-state and tape-print
seams, proved here at the options-flow computation itself."""
from __future__ import annotations

from app.options.order_flow.engine import _compute_options_flow


def _contract(total_volume=None, last_size=25, delta=0.5) -> dict:
    out = {
        "strikePrice": 500.0,
        "lastSize": last_size,
        "delta": delta,
    }
    if total_volume is not None:
        out["totalVolume"] = total_volume
    return out


def test_options_flow_uses_schwab_total_volume_not_last_size_fallback():
    data = {
        "callExpDateMap": {"2099-05-05:0": {"500.0": _contract(total_volume=10, last_size=999, delta=0.5)}},
        "putExpDateMap": {"2099-05-05:0": {"500.0": _contract(total_volume=30, last_size=999, delta=-0.4)}},
    }

    score, direction, ratio, delta_weighted, vol_src = _compute_options_flow(data)

    assert score == -0.5
    assert vol_src == "schwab_chain_totalVolume"
    assert direction == "put"
    assert ratio == 10 / 30          # no epsilon in the denominator (2026-09-24)
    assert delta_weighted == 17.0


def test_options_flow_fails_closed_when_schwab_total_volume_missing():
    data = {
        "callExpDateMap": {"2099-05-05:0": {"500.0": _contract(last_size=999, delta=0.5)}},
        "putExpDateMap": {"2099-05-05:0": {"500.0": _contract(last_size=999, delta=-0.4)}},
    }

    assert _compute_options_flow(data) == (None, None, None, None, None)


def test_options_flow_does_not_default_missing_delta_weight_to_zero():
    data = {
        "callExpDateMap": {"2099-05-05:0": {"500.0": _contract(total_volume=10, delta=None)}},
        "putExpDateMap": {},
    }

    score, direction, ratio, delta_weighted, _ = _compute_options_flow(data)

    assert score == 1.0
    assert direction == "call"
    assert ratio is None             # no put volume: the ratio is undefined, not ~1e10
    assert delta_weighted is None


def test_options_flow_treats_minus_999_delta_sentinel_as_missing():
    """Schwab uses -999.0 to flag 'missing greek'. delta_weighted must not include it."""
    data = {
        "callExpDateMap": {
            "2099-05-05:0": {"500.0": _contract(total_volume=10, delta=-999.0)}
        },
        "putExpDateMap": {
            "2099-05-05:0": {"500.0": _contract(total_volume=30, delta=-999.0)}
        },
    }

    score, direction, ratio, delta_weighted, vol_src = _compute_options_flow(data)

    assert score == -0.5
    assert vol_src == "schwab_chain_totalVolume"
    assert direction == "put"
    assert ratio == 10 / 30
    assert delta_weighted is None


def test_options_flow_one_missing_delta_makes_delta_weighted_unknown():
    """2026-09-24: a traded contract with no valid delta makes delta-weighted flow UNKNOWN --
    it used to be skipped, reporting the calls' side alone as the whole book."""
    data = {
        "callExpDateMap": {
            "2099-05-05:0": {"500.0": _contract(total_volume=10, delta=0.5)}
        },
        "putExpDateMap": {
            "2099-05-05:0": {"500.0": _contract(total_volume=30, delta=-999.0)}
        },
    }

    score, direction, ratio, delta_weighted, vol_src = _compute_options_flow(data)

    assert score == -0.5
    assert vol_src == "schwab_chain_totalVolume"
    assert direction == "put"
    assert delta_weighted is None


def test_options_flow_counts_every_contract_at_a_strike():
    """Schwab maps a strike to a LIST of contracts; every one counts (was: first only)."""
    data = {
        "callExpDateMap": {"2099-05-05:0": {"500.0": [_contract(total_volume=10, delta=0.5),
                                                      _contract(total_volume=20, delta=0.5)]}},
        "putExpDateMap": {"2099-05-05:0": {"500.0": [_contract(total_volume=30, delta=-0.4)]}},
    }
    score, _, ratio, delta_weighted, _ = _compute_options_flow(data)
    assert ratio == 1.0 and score == 0.0
    assert delta_weighted == 0.5 * 30 + 0.4 * 30


def test_options_flow_one_contract_without_volume_makes_the_flow_unknown():
    data = {
        "callExpDateMap": {"2099-05-05:0": {"500.0": [_contract(total_volume=10, delta=0.5),
                                                      _contract(delta=0.5)]}},
        "putExpDateMap": {"2099-05-05:0": {"500.0": _contract(total_volume=30, delta=-0.4)}},
    }
    assert _compute_options_flow(data) == (None, None, None, None, None)
