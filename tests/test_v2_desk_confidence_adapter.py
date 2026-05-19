"""Phase 2: v2 adapter desk confidence uses final_confidence only."""
from __future__ import annotations

from v2_decision import build_module_a_a1_decision


def _base_ms() -> dict:
    return {
        "ticker": "SPY",
        "fusion_available": True,
        "fusion_confidence": "high",
        "confidence": "low",
        "final_quality": "B",
        "dominant_dir": "up",
        "fusion_dominant_prob": 0.55,
        "is_no_trade": False,
        "execution_mode": "STANDARD",
    }


def test_confidence_uses_final_confidence_when_present() -> None:
    ms = _base_ms()
    ms["final_confidence"] = 0.7234
    dec = build_module_a_a1_decision(ms)
    assert dec["decision"]["confidence"]["value"] == 0.7234


def test_confidence_none_without_final_confidence() -> None:
    ms = _base_ms()
    dec = build_module_a_a1_decision(ms)
    assert dec["decision"]["confidence"]["value"] is None


def test_confidence_none_when_final_confidence_missing_not_zero() -> None:
    ms = _base_ms()
    ms["final_confidence"] = None
    dec = build_module_a_a1_decision(ms)
    assert dec["decision"]["confidence"]["value"] is None
