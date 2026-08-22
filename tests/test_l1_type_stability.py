"""
Issue 50: canonical types for fingerprint material — int/float equivalence, strings, invalid.
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planes.context_light import MERGE_RULE_L1, PLANE_L1, _ORDER_FLOW_KEYS, _STRUCTURAL_KEYS  # noqa: E402
from planes.l1_decision_dependencies import L1_DECISION_DEPENDENCY_KEYS  # noqa: E402
from planes.l1_fingerprint_material import (  # noqa: E402
    L1_FINGERPRINT_STRUCTURAL_FLOAT_KEYS,
    L1_MATERIAL_INVALID,
    build_l1_material_dict_for_fingerprint,
)


def _full_payload() -> dict:
    p: dict = {}
    for k in L1_DECISION_DEPENDENCY_KEYS["scalars"]:
        if k in ("l2_merge_acknowledged", "l2_structural_scope_exact", "structural_context_stale", "l1_stale"):
            p[k] = False
        elif k == "l2_snapshot_version_used":
            p[k] = 7
        elif k == "plane":
            p[k] = PLANE_L1
        elif k == "schema_version":
            p[k] = 1
        elif k == "merge_rule":
            p[k] = MERGE_RULE_L1
        elif k == "l1_generation":
            p[k] = 3
        elif k == "spot":
            p[k] = 555.125
        elif k == "ticker":
            p[k] = "SPY"
        elif k == "selected_exp":
            p[k] = "2026-06-01"
        else:
            p[k] = 12.34
    for k in _STRUCTURAL_KEYS:
        if k in L1_FINGERPRINT_STRUCTURAL_FLOAT_KEYS:
            p[k] = float(hash(k) % 10_000) / 100.0
        else:
            p[k] = f"sval_{k}"
    p["spot_anchors"] = {
        "vwap": 550.0,
        "vwap_side": "below",
        "dist_to_vwap_pts": 0.5,
    }
    p["order_flow"] = {k: float(i + 1) for i, k in enumerate(_ORDER_FLOW_KEYS)}
    p["liquidity_summary"] = {
        "behavior_label": "lb",
        "range_imbalance_stall_score": 11,
        "range_imbalance_push_score": 22,
    }
    p["readiness_summary"] = {
        "order_flow_readiness": "ready",
        "structural_anchor_stale": False,
        "has_acknowledged_l2_snapshot": True,
    }
    return p


def _fp(payload: dict) -> str:
    import server as srv

    return srv._l1_payload_fingerprint(payload)


def test_int_and_float_spot_produce_same_fingerprint():
    p1 = _full_payload()
    p2 = _full_payload()
    p1["spot"] = 500
    p2["spot"] = 500.0
    assert _fp(p1) == _fp(p2)
    assert build_l1_material_dict_for_fingerprint(p1)["spot"] == build_l1_material_dict_for_fingerprint(p2)["spot"]


def test_string_numeric_spot_normalizes_to_float_equivalence():
    p1 = _full_payload()
    p2 = _full_payload()
    p1["spot"] = "500.0"
    p2["spot"] = 500.0
    assert _fp(p1) == _fp(p2)


def test_invalid_numeric_string_becomes_invalid_sentinel():
    p = _full_payload()
    p["spot"] = "INVALID"
    mat = build_l1_material_dict_for_fingerprint(p)
    assert mat["spot"] is L1_MATERIAL_INVALID
    assert _fp(p) != _fp(_full_payload())


def test_order_flow_score_int_vs_float_equivalent():
    p1 = _full_payload()
    p2 = _full_payload()
    p1["order_flow"]["order_flow_score"] = 10
    p2["order_flow"]["order_flow_score"] = 10.0
    assert _fp(p1) == _fp(p2)


def test_schema_version_int_and_float_integral_equivalent():
    p1 = _full_payload()
    p2 = _full_payload()
    p1["schema_version"] = 1
    p2["schema_version"] = 1.0
    assert _fp(p1) == _fp(p2)
    assert build_l1_material_dict_for_fingerprint(p1)["schema_version"] == 1


def test_schema_version_non_integral_float_is_invalid():
    p = _full_payload()
    p["schema_version"] = 1.5
    assert build_l1_material_dict_for_fingerprint(p)["schema_version"] is L1_MATERIAL_INVALID


def test_regression_material_dict_normalizes_spot_float_not_int() -> None:
    """Fails if someone removes normalization and spot stays Python int (JSON fingerprint differs)."""
    p = _full_payload()
    p["spot"] = 500
    v = build_l1_material_dict_for_fingerprint(p)["spot"]
    assert v == 500.0
    assert isinstance(v, float)


def test_bool_like_int_for_flags_normalized():
    p1 = _full_payload()
    p2 = _full_payload()
    p1["l1_stale"] = 0
    p2["l1_stale"] = False
    assert _fp(p1) == _fp(p2)
