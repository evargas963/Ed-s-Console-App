"""
Issue 49: missing vs None vs empty dict — explicit material semantics (no silent collapse).
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planes.context_light import MERGE_RULE_L1, PLANE_L1, _ORDER_FLOW_KEYS, _STRUCTURAL_KEYS  # noqa: E402
from planes.l1_decision_dependencies import L1_DECISION_DEPENDENCY_KEYS  # noqa: E402
from planes.l1_fingerprint_material import (  # noqa: E402
    L1_FINGERPRINT_STRUCTURAL_FLOAT_KEYS,
    L1_MATERIAL_ABSENT,
    L1_MATERIAL_CONTAINER_ABSENT,
    build_l1_material_dict_for_fingerprint,
)


def _full_payload() -> dict:
    """Minimal complete material payload (all sections present as dicts)."""
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
        "absorption_score": 11,
        "continuation_score": 22,
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


def test_missing_vs_none_order_flow_fingerprint_differs():
    base = _full_payload()
    missing_payload = copy.deepcopy(base)
    del missing_payload["order_flow"]

    none_payload = copy.deepcopy(base)
    none_payload["order_flow"] = None

    assert build_l1_material_dict_for_fingerprint(missing_payload)["order_flow"] == L1_MATERIAL_CONTAINER_ABSENT
    assert build_l1_material_dict_for_fingerprint(none_payload)["order_flow"] is None

    assert _fp(missing_payload) != _fp(none_payload)


def test_missing_vs_empty_liquidity_summary_fingerprint_differs():
    base = _full_payload()
    missing_payload = copy.deepcopy(base)
    del missing_payload["liquidity_summary"]

    empty_payload = copy.deepcopy(base)
    empty_payload["liquidity_summary"] = {}

    m_missing = build_l1_material_dict_for_fingerprint(missing_payload)["liquidity_summary"]
    m_empty = build_l1_material_dict_for_fingerprint(empty_payload)["liquidity_summary"]

    assert m_missing == L1_MATERIAL_CONTAINER_ABSENT
    assert isinstance(m_empty, dict)
    assert all(m_empty[k] == L1_MATERIAL_ABSENT for k in m_empty)

    assert _fp(missing_payload) != _fp(empty_payload)


def test_scalar_missing_vs_none_differs():
    base = _full_payload()
    m1 = copy.deepcopy(base)
    del m1["spot"]

    m2 = copy.deepcopy(base)
    m2["spot"] = None

    assert build_l1_material_dict_for_fingerprint(m1)["spot"] == L1_MATERIAL_ABSENT
    assert build_l1_material_dict_for_fingerprint(m2)["spot"] is None
    assert _fp(m1) != _fp(m2)


def test_spot_anchors_missing_vs_none_vs_empty():
    base = _full_payload()

    miss = copy.deepcopy(base)
    del miss["spot_anchors"]

    none_p = copy.deepcopy(base)
    none_p["spot_anchors"] = None

    empty_p = copy.deepcopy(base)
    empty_p["spot_anchors"] = {}

    a = build_l1_material_dict_for_fingerprint(miss)["spot_anchors"]
    b = build_l1_material_dict_for_fingerprint(none_p)["spot_anchors"]
    c = build_l1_material_dict_for_fingerprint(empty_p)["spot_anchors"]

    assert a == L1_MATERIAL_CONTAINER_ABSENT
    assert b is None
    assert isinstance(c, dict) and c["vwap"] == L1_MATERIAL_ABSENT

    assert len({_fp(miss), _fp(none_p), _fp(empty_p)}) == 3


def test_structural_field_missing_vs_none_on_payload():
    from planes.context_light import _STRUCTURAL_KEYS

    base = _full_payload()
    k0 = _STRUCTURAL_KEYS[0]

    miss = copy.deepcopy(base)
    del miss[k0]

    none_p = copy.deepcopy(base)
    none_p[k0] = None

    assert build_l1_material_dict_for_fingerprint(miss)["structural"][k0] == L1_MATERIAL_ABSENT
    assert build_l1_material_dict_for_fingerprint(none_p)["structural"][k0] is None
    assert _fp(miss) != _fp(none_p)


def test_order_flow_inner_key_missing_vs_explicit_none():
    base = _full_payload()
    key = "order_flow_regime"

    a = copy.deepcopy(base)
    del a["order_flow"][key]

    b = copy.deepcopy(base)
    b["order_flow"][key] = None

    ma = build_l1_material_dict_for_fingerprint(a)["order_flow"][key]
    mb = build_l1_material_dict_for_fingerprint(b)["order_flow"][key]
    assert ma == L1_MATERIAL_ABSENT
    assert mb is None
    assert _fp(a) != _fp(b)


def test_regression_documented_sentinels_are_stable_strings():
    assert isinstance(L1_MATERIAL_ABSENT, str) and isinstance(L1_MATERIAL_CONTAINER_ABSENT, str)
    assert L1_MATERIAL_ABSENT != L1_MATERIAL_CONTAINER_ABSENT
