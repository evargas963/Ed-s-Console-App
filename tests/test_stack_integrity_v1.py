"""Stack integrity / degradation surfacing (no silent MH overlay or shared-overlay drops)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from features.stack_integrity_v1 import finalize_stack_integrity_v1, record_stack_degradation
from prediction_engine import _overlay_multi_horizon_ml_on_product_triplets
from ml_horizon import PRIMARY_DECISION_HORIZONS


def _uniform_empirical():
    u = 1.0 / 3.0
    return {hz: (u, u, u) for hz in PRIMARY_DECISION_HORIZONS}


def test_mh_overlay_records_when_by_horizon_property_raises():
    class BadBundle:
        @property
        def by_horizon(self):
            raise RuntimeError("simulated descriptor failure")

    out, src, events = _overlay_multi_horizon_ml_on_product_triplets(_uniform_empirical(), BadBundle())
    assert any(e.get("component") == "mh_ml_product_overlay" for e in events)
    assert any(e.get("authority_intact") is False for e in events)
    assert all(src[hz] == "empirical_histogram" for hz in PRIMARY_DECISION_HORIZONS)
    assert out["1c"] == out["5c"]  # empirical-only fallback


def test_mh_overlay_records_non_dict_by_horizon():
    bundle = SimpleNamespace(by_horizon=["not", "a", "dict"])
    out, src, events = _overlay_multi_horizon_ml_on_product_triplets(_uniform_empirical(), bundle)
    assert any("by_horizon_not_a_dict" in (e.get("reason") or "") for e in events)
    assert events


def test_finalize_strips_dedupe_keys():
    ev: list = []
    record_stack_degradation(
        ev,
        component="run_base_models_once",
        severity="warning",
        reason="x",
        dedupe_key="k1",
    )
    fin = finalize_stack_integrity_v1(ev)
    assert "dedupe_key" not in fin["events"][0]


def test_compute_fusion_policy_flat_for_replay_returns_integrity_dict():
    from tests.test_call_prediction_vote import _inp
    from signals import compute_fusion_policy_flat_for_replay

    with patch(
        "prediction_engine.build_fusion_model_overlay_for_stack",
        side_effect=RuntimeError("overlay down"),
    ):
        flat, errs, integrity = compute_fusion_policy_flat_for_replay(_inp(), MagicMock())
    assert isinstance(integrity, dict)
    assert integrity.get("version") == 1
    assert integrity.get("degraded") is True
    assert any(
        e.get("component") == "fusion_model_overlay" for e in (integrity.get("events") or [])
    )
    assert isinstance(flat, dict)
    assert isinstance(errs, list)
