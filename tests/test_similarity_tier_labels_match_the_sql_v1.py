"""Every similar-setups tier label names exactly the filters that tier's SQL applies.

Audit P0 (2026-09-23): tier 5 -- every past snapshot for the ticker, no structural match --
was labelled "zone + VWAP match" on the prediction card, and tiers 1-4 named session/VIX
filters no tier applies. Labels now live beside structured_constraints_for_tier and this test
ties each one to that definition.
"""
from __future__ import annotations

from similarity_audit import TIER_MATCH_LABELS, structured_constraints_for_tier

_WORDS = {
    "zone": "zone",
    "vwap_side": "VWAP side",
    "nearest_above_dist": "distance above",
    "nearest_below_dist": "below",
}


def test_each_label_names_exactly_its_tiers_filters():
    for tier in (1, 2, 3, 4, 5):
        filters = structured_constraints_for_tier(tier, {"ticker": "X", "timeframe": "1m"})["structural_filters"]
        label = TIER_MATCH_LABELS[tier]
        for key, word in _WORDS.items():
            assert (word in label) == (key in filters), (tier, key, label)
        for never in ("session", "VIX", "exact"):
            assert never not in label, (tier, label)
    assert "no structural match" in TIER_MATCH_LABELS[5]


def test_the_prediction_engine_uses_these_labels():
    import prediction_engine
    assert prediction_engine._TIER_LABELS is TIER_MATCH_LABELS
