"""FIND-ISNAP-1: l1_equiv producer keys must match live_feature_adapter readers."""

from __future__ import annotations

from types import SimpleNamespace

from features.inference_snapshot import build_inference_snapshot_v1_from_signal_input
from features.live_feature_adapter import build_live_mvp_feature_row


def test_l1_equiv_spread_pts_populates_mvp_feature():
    inp = SimpleNamespace(
        ticker="SPY",
        expiry=None,
        spot=400.0,
        spread=0.02,
        zone="pin_bull",
        nearest_above_dist=1.0,
        nearest_below_dist=-1.0,
        net_gamma=0.0,
        vwap_side="above",
        vwap_dist_pts=0.5,
    )
    snap = build_inference_snapshot_v1_from_signal_input(inp, as_of_ts=1_700_000_000.0)
    assert snap["features"]["price.spread_pts"] == 0.02


def test_signal_input_l1_equiv_keys_match_live_adapter_contract():
    """Every top-level key read by build_live_mvp_feature_row must be set by from_signal_input."""
    inp = SimpleNamespace(
        ticker="SPY",
        expiry=None,
        spot=1.0,
        spread=0.01,
        zone="pin_neutral",
        nearest_above_dist=2.0,
        nearest_below_dist=3.0,
        net_gamma=4.0,
        vwap_side="above",
        vwap_dist_pts=0.25,
        refresh_ts_utc=1_700_000_100.0,
    )
    snap = build_inference_snapshot_v1_from_signal_input(inp)
    direct = build_live_mvp_feature_row(
        {
            "spot": inp.spot,
            "spread_pts": inp.spread,
            "zone": inp.zone,
            "nearest_above_dist": inp.nearest_above_dist,
            "nearest_below_dist": inp.nearest_below_dist,
            "net_gamma": inp.net_gamma,
            "vwap_side": inp.vwap_side,
            "dist_to_vwap_pts": 0.25,
        }
    )
    for key in (
        "price.spot",
        "price.spread_pts",
        "structure.zone",
        "structure.nearest_above_dist",
        "structure.nearest_below_dist",
        "structure.net_gamma",
        "anchor.vwap_side",
        "anchor.vwap_dist_pts",
    ):
        assert snap["features"][key] == direct[key]
