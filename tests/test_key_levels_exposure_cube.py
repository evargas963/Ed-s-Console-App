"""KEY LEVELS faucet: charm on the exposure cube, one stamp, honest nets."""

from __future__ import annotations

from math_exposure_core import (
    MISSING_GREEK_SENTINEL,
    aggregate_net_vanna,
    charm_result_from_exposures,
    compute_exposures_by_strike,
    compute_net_charm,
)
from math_levels import WallsRow, stamp_key_levels_from_cube


def _empty_wall(**kwargs) -> WallsRow:
    return WallsRow(
        "CONSENSUS",
        None,
        kwargs.get("call_gamma_wall"),
        kwargs.get("call_gamma_strength"),
        None,
        None,
        "CALL",
        None,
        None,
        None,
        None,
        None,
        None,
        "PUT",
        None,
        None,
        None,
        None,
        None,
        None,
        "CALL",
        None,
        None,
        None,
        None,
    )


def _contract(**overrides) -> dict:
    base = {
        "expirationDate": "2099-05-05",
        "putCall": "CALL",
        "strikePrice": 500.0,
        "gamma": 0.1,
        "delta": 0.5,
        "vega": 0.12,
        "volatility": 20.0,
        "openInterest": 100.0,
        "multiplier": 100.0,
        "daysToExpiration": 1,
    }
    base.update(overrides)
    return base


def test_cube_vanna_none_when_vega_missing():
    exposures, diag = compute_exposures_by_strike(
        [_contract(vega=None)], spot=500.0, require_oi=True
    )
    b = exposures[500.0]
    assert b["call_vanna"] is None
    assert b["net_vanna"] is None
    assert aggregate_net_vanna(exposures) is None
    assert diag.contracts_used == 1


def test_cube_vanna_present_when_vega_and_iv():
    exposures, _ = compute_exposures_by_strike([_contract()], spot=500.0)
    b = exposures[500.0]
    assert b["call_vanna"] is not None
    assert b["call_vanna"] != 0.0
    assert aggregate_net_vanna(exposures) == b["call_vanna"]


def test_cube_charm_none_when_gamma_sentinel():
    exposures, diag = compute_exposures_by_strike(
        [_contract(gamma=MISSING_GREEK_SENTINEL)], spot=500.0
    )
    b = exposures[500.0]
    assert b["call_charm"] is None
    assert b["net_charm"] is None
    assert diag.charm_contracts_used == 0
    assert "quality gates" in diag.charm_error
    out = charm_result_from_exposures(
        exposures,
        contracts_used=diag.charm_contracts_used,
        error=diag.charm_error,
    )
    assert out["net_charm_daily"] is None
    assert out["contracts_used"] == 0


def test_cube_charm_matches_compute_net_charm():
    cts = [
        _contract(),
        _contract(putCall="PUT", delta=-0.45, strikePrice=500.0),
    ]
    exposures, diag = compute_exposures_by_strike(cts, spot=500.0)
    from_cube = charm_result_from_exposures(
        exposures,
        drift_toward_strike=500.0,
        contracts_used=diag.charm_contracts_used,
        error=diag.charm_error,
    )
    walked = compute_net_charm(cts, 500.0, "2099-05-05", drift_toward_strike=500.0)
    assert diag.charm_contracts_used == walked["contracts_used"] == 2
    assert from_cube["net_charm_daily"] == walked["net_charm_daily"]
    assert from_cube["charm_direction"] == walked["charm_direction"]
    assert exposures[500.0]["call_charm"] is not None
    assert exposures[500.0]["put_charm"] is not None


def test_stamp_omits_fabricated_gex_and_missing_vanna():
    wall = _empty_wall()
    target: dict = {}
    stamp_key_levels_from_cube(
        target,
        walls=[wall],
        consensus=None,
        exposures={500.0: {"call_vanna": None, "put_vanna": None}},
        charm={"net_charm_daily": None, "charm_direction": None},
        gamma_flip=None,
        gamma_voids=[],
        hvl=None,
        max_pain=None,
    )
    assert target["kl_net_gex"] is None
    assert "kl_net_gex_mag" not in target
    assert "kl_net_gex_regime" not in target
    assert "kl_net_vanna" not in target
    assert target["charm_direction_display"] is None
    assert target["kl_call_gamma_wall"] is None


def test_stamp_writes_vanna_and_charm_when_cube_contributed():
    from math_exposure_core import ExposureRow

    cts = [_contract()]
    exposures, diag = compute_exposures_by_strike(cts, spot=500.0)
    charm = charm_result_from_exposures(
        exposures,
        drift_toward_strike=500.0,
        contracts_used=diag.charm_contracts_used,
        error=diag.charm_error,
    )
    wall = _empty_wall(call_gamma_wall=510.0, call_gamma_strength=1e6)
    cs = ExposureRow("CONSENSUS", None, 1.2e9, 0.0, 500.0, None, None, None, "Low", "Neutral")
    target: dict = {}
    stamp_key_levels_from_cube(
        target,
        walls=[wall],
        consensus=cs,
        exposures=exposures,
        charm=charm,
        gamma_flip=501.0,
        gamma_voids=[],
        hvl=500.0,
        max_pain=499.0,
        diag=diag,
        expiry_source="selected",
    )
    assert target["kl_call_gamma_wall"] == 510.0
    assert target["kl_call_gamma_str"] == "$1.0M/pt"
    assert target["kl_net_gex"] == 1.2e9
    assert target["kl_net_gex_mag"] != "negligible" or target["kl_net_gex"] == 0
    assert "kl_net_vanna" in target
    assert target["charm_net"] == charm["net_charm_daily"]
    assert target["charm_direction"] in ("buying", "selling", "neutral")
    assert target["kl_expiry_source"] == "selected"
