from __future__ import annotations

import inspect
from typing import get_type_hints

import v2_decision.module_a_adapter as module_a_adapter
from v2_decision.a1_raw_probability import dominant_probability


def test_module_a_adapter_delegates_to_public_dominant_probability(monkeypatch):
    calls = []

    def fake_dominant_probability(ms_dict):
        calls.append(ms_dict)
        return 0.4321

    monkeypatch.setattr(module_a_adapter, "dominant_probability", fake_dominant_probability, raising=False)

    decision = module_a_adapter._decision_block({"dominant_dir": "up", "dominant_prob": 0.91})

    assert calls == [{"dominant_dir": "up", "dominant_prob": 0.91}]
    assert decision["probability"]["value"] == 0.4321
    assert decision["P_entry_success"]["value"] == 0.4321


def test_dominant_probability_byte_equivalent_to_legacy_for_representative_inputs():
    # WIRE-4 / FIND-FP1-3 tightened the fusion authority gate to require BOTH
    # fusion_available AND canonical_provenance in TRADABLE_CANONICAL_PROVENANCE
    # (= {"bayesian_fusion"}). Cases that exercise the fusion path now include
    # canonical_provenance explicitly.
    cases = [
        # Fusion authoritative + valid fusion_dominant_prob -> use it (rounded to 4 decimals)
        ({"fusion_available": True, "canonical_provenance": "bayesian_fusion", "fusion_dominant_prob": "0.87654", "dominant_prob": 0.1}, 0.8765),
        # fusion_available=False -> not authoritative -> fall through to dominant_prob
        ({"fusion_available": False, "fusion_dominant_prob": 0.9, "dominant_prob": "0.23456"}, 0.2346),
        # Fusion authoritative but fusion_dominant_prob INVALID -> fall through to dominant_prob
        ({"fusion_available": True, "canonical_provenance": "bayesian_fusion", "fusion_dominant_prob": "bad", "dominant_prob": 0.34567}, 0.3457),
        # No valid dominant_prob -> None (final_confidence is intentionally NOT a fallback)
        ({"dominant_prob": None, "final_confidence": "0.45678"}, None),
        ({"dominant_prob": object(), "final_confidence": 0.56789}, None),
    ]

    for ms_dict, expected in cases:
        assert dominant_probability(ms_dict) == expected, f"failed for {ms_dict}"


def test_dominant_probability_returns_none_for_empty_ms_dict():
    assert dominant_probability({}) is None


def test_module_a_adapter_no_longer_defines_private_dominant_probability():
    assert not hasattr(module_a_adapter, "_dominant_probability")


def test_dominant_probability_signature_takes_dict_returns_float_or_none():
    signature = inspect.signature(dominant_probability)
    hints = get_type_hints(dominant_probability)

    assert list(signature.parameters) == ["ms_dict"]
    assert hints["return"] == float | None
