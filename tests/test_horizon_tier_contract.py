"""Hard contract: primary vs secondary governed horizons (authoritative vs diagnostics-only)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_partition_and_constants():
    from ml_horizon import (
        ALL_GOVERNED_HORIZONS,
        ML_HORIZON_SLUGS,
        PRIMARY_DECISION_HORIZONS,
        SECONDARY_SUPPORT_HORIZONS,
    )

    assert ALL_GOVERNED_HORIZONS == ML_HORIZON_SLUGS
    assert ALL_GOVERNED_HORIZONS == PRIMARY_DECISION_HORIZONS
    assert PRIMARY_DECISION_HORIZONS == ("1c", "5c", "15c", "60c")
    assert SECONDARY_SUPPORT_HORIZONS == ()
    assert set(ALL_GOVERNED_HORIZONS) == set(PRIMARY_DECISION_HORIZONS) | set(
        SECONDARY_SUPPORT_HORIZONS
    )
    assert not (set(PRIMARY_DECISION_HORIZONS) & set(SECONDARY_SUPPORT_HORIZONS))


def test_product_horizons_alias_matches_primary():
    from ml_horizon import PRIMARY_DECISION_HORIZONS
    from multi_horizon_decision import PRODUCT_HORIZONS

    assert PRODUCT_HORIZONS == PRIMARY_DECISION_HORIZONS


def test_mh_bundle_only_primary_keys():
    from ml_horizon import PRIMARY_DECISION_HORIZONS
    from multi_horizon_ml_bundle import build_multi_horizon_ml_fusion_bundle

    # Deliberately poison with secondary keys — must be ignored for authority rows.
    fusion_by_hz = {
        "1c": None,
        "3c": None,
        "5c": None,
        "8c": None,
        "13c": None,
        "15c": None,
        "60c": None,
    }
    b = build_multi_horizon_ml_fusion_bundle(fusion_by_hz, live_canonical_horizon_slug="1c")
    assert set(b.by_horizon.keys()) == set(PRIMARY_DECISION_HORIZONS)
    for hz in PRIMARY_DECISION_HORIZONS:
        assert b.snapshot(hz) is not None
        assert b.snapshot(hz).horizon_tier == "primary_decision"
    assert b.snapshot("3c") is None


def test_secondary_not_in_multi_horizon_decision_loop():
    from ml_horizon import PRIMARY_DECISION_HORIZONS, SECONDARY_SUPPORT_HORIZONS
    from multi_horizon_decision import compute_multi_horizon_synthesis

    class _Pred:
        mh_prob_source_by_horizon = {hz: "empirical_histogram" for hz in PRIMARY_DECISION_HORIZONS}
        up_prob_1c = down_prob_1c = flat_prob_1c = 0.34
        up_prob_5c = down_prob_5c = flat_prob_5c = 0.34
        up_prob_15c = down_prob_15c = flat_prob_15c = 0.34
        up_prob_60c = down_prob_60c = flat_prob_60c = 0.34
        avg_3c_pts = None

    class _Inp:
        mins_to_close = 200.0

    class _Canon:
        probability_up = probability_down = probability_flat = 1.0 / 3.0

    s = compute_multi_horizon_synthesis(_Inp(), _Pred(), _Canon(), mh_ml_bundle=None)
    assert set(s.hmap.keys()) == set(PRIMARY_DECISION_HORIZONS)
    for sec in SECONDARY_SUPPORT_HORIZONS:
        assert sec not in s.hmap


def test_live_stack_skips_missing_secondary_active_bundles(monkeypatch):
    import ml_horizon
    import signals
    import ml_predict

    governed = ("1c", "3c", "5c", "8c")
    primary = ("1c", "5c")
    secondary = ("3c", "8c")
    monkeypatch.setattr(ml_horizon, "ALL_GOVERNED_HORIZONS", governed)
    monkeypatch.setattr(ml_horizon, "ML_HORIZON_SLUGS", governed)
    monkeypatch.setattr(ml_horizon, "PRIMARY_DECISION_HORIZONS", primary)
    monkeypatch.setattr(ml_horizon, "SECONDARY_SUPPORT_HORIZONS", secondary)
    monkeypatch.setattr(signals, "ALL_GOVERNED_HORIZONS", governed)
    monkeypatch.setattr(signals, "PRIMARY_DECISION_HORIZONS", primary)
    monkeypatch.setattr(signals, "SECONDARY_SUPPORT_HORIZONS", secondary)

    def _fake_model_dir_for_ticker(_ticker: str):
        hz = ml_predict.get_ml_infer_horizon_slug()
        if hz in ("3c", "8c"):
            raise FileNotFoundError(f"no active {hz} bundle")
        return ROOT

    monkeypatch.setattr(ml_predict, "_model_dir_for_ticker", _fake_model_dir_for_ticker)

    horizons, skipped = signals._live_model_stack_horizons("SPY")

    assert horizons == ("1c", "5c")
    assert set(skipped) == {"3c", "8c"}
    assert skipped["3c"]["provenance"] == "skipped_missing_active_bundle"
    assert skipped["3c"]["non_authoritative"] is True


def test_trader_payload_strips_legacy_horizon_prob_bar_keys():
    from server import _apply_trader_horizon_contract

    ms = {
        "horizon_prob_bars": {
            "1m": {"up": 0.4, "down": 0.3, "flat": 0.3},
            "8c": {"up": 0.5, "down": 0.25, "flat": 0.25},
            "13c": {"up": 0.5, "down": 0.25, "flat": 0.25},
        },
        "up_prob_8c": 0.5,
    }
    _apply_trader_horizon_contract(ms)
    assert set(ms["horizon_prob_bars"].keys()) == {"1m"}
    assert "up_prob_8c" not in ms
