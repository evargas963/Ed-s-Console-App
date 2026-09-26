"""Stack integrity / degradation surfacing (no silent MH overlay or shared-overlay drops)."""

from __future__ import annotations

from types import SimpleNamespace


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
    assert any(e.get("fallback_used") is True for e in events)
    # Fail-closed fusion contract: a broken ML bundle WITHHOLDS product triplets — it never
    # fabricates an empirical_histogram fallback (empirical is signal-rail context only, blend
    # opt-in via ED_MH_EMPIRICAL_SUPPORT). Every horizon resolves to fusion_unavailable + withheld.
    assert all(src[hz] == "fusion_unavailable" for hz in PRIMARY_DECISION_HORIZONS)
    assert all(out[hz] == (None, None, None) for hz in PRIMARY_DECISION_HORIZONS)


def test_mh_overlay_records_non_dict_by_horizon():
    bundle = SimpleNamespace(by_horizon=["not", "a", "dict"])
    out, src, events = _overlay_multi_horizon_ml_on_product_triplets(_uniform_empirical(), bundle)
    assert any("by_horizon_not_a_dict" in (e.get("reason") or "") for e in events)
    assert events




