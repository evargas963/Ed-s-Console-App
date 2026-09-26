"""Layer 5 signals L91-102: canonical_forecast_from_fusion + non-tradable provenance gate."""

from __future__ import annotations


from signal_types import NON_TRADABLE_CANONICAL_PROVENANCE


def test_non_tradable_provenance_includes_directional_missing_and_invalid():
    assert "fusion_directional_missing" in NON_TRADABLE_CANONICAL_PROVENANCE
    assert "fusion_directional_invalid" in NON_TRADABLE_CANONICAL_PROVENANCE
    assert "fusion_directional_unauthorized" in NON_TRADABLE_CANONICAL_PROVENANCE
    assert "fusion_unavailable" in NON_TRADABLE_CANONICAL_PROVENANCE










