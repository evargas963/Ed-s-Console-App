"""AUDIT_LANE module_a_adapter — fusion provenance + finite numerics."""

from __future__ import annotations

from fusion_contract import is_ms_dict_fusion_authoritative
from signal_types import NON_TRADABLE_CANONICAL_PROVENANCE


def test_fusion_ms_authoritative_rejects_non_tradable_provenance():
    prov = next(iter(NON_TRADABLE_CANONICAL_PROVENANCE))
    ms = {"fusion_available": True, "canonical_provenance": prov}
    assert is_ms_dict_fusion_authoritative(ms) is False












