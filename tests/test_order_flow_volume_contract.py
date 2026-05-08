from __future__ import annotations

from order_flow_engine import _compute_options_flow


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

    score, direction, ratio, delta_weighted = _compute_options_flow(data)

    assert score == -0.5
    assert direction == "put"
    assert ratio == 10 / (30 + 1e-9)
    assert delta_weighted == 17.0


def test_options_flow_fails_closed_when_schwab_total_volume_missing():
    data = {
        "callExpDateMap": {"2099-05-05:0": {"500.0": _contract(last_size=999, delta=0.5)}},
        "putExpDateMap": {"2099-05-05:0": {"500.0": _contract(last_size=999, delta=-0.4)}},
    }

    assert _compute_options_flow(data) == (None, None, None, None)


def test_options_flow_does_not_default_missing_delta_weight_to_zero():
    data = {
        "callExpDateMap": {"2099-05-05:0": {"500.0": _contract(total_volume=10, delta=None)}},
        "putExpDateMap": {},
    }

    score, direction, ratio, delta_weighted = _compute_options_flow(data)

    assert score == 1.0
    assert direction == "call"
    assert ratio is not None
    assert delta_weighted is None
