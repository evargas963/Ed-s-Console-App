"""
Issue 48: value-level propagation from L1 payload into build_l1_material_dict_for_fingerprint.

Proves decision-relevant mutations reach the canonical material dict paths (not only the hash).
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planes.context_light import (  # noqa: E402
    MERGE_RULE_L1,
    PLANE_L1,
    _ORDER_FLOW_KEYS,
    _STRUCTURAL_KEYS,
)
from planes.l1_decision_dependencies import (  # noqa: E402
    L1_DECISION_DEPENDENCY_KEYS,
    get_all_decision_dependency_keys,
)
from planes.l1_fingerprint_material import (  # noqa: E402
    L1_FINGERPRINT_STRUCTURAL_FLOAT_KEYS,
    build_l1_material_dict_for_fingerprint,
)


def _full_l1_payload() -> dict:
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
        "range_imbalance_label": "retired_absent",
        "range_imbalance_stall_score": 11,
        "range_imbalance_push_score": 22,
    }
    p["readiness_summary"] = {
        "order_flow_readiness": "ready",
        "structural_anchor_stale": False,
        "has_acknowledged_l2_snapshot": True,
    }
    return p


def _material_get(mat: dict, path: str):
    section, key = path.split(":", 1)
    if section == "scalars":
        return mat[key]
    if section == "structural":
        return mat["structural"][key]
    if section == "order_flow":
        return mat["order_flow"][key]
    if section == "spot_anchors":
        return mat["spot_anchors"][key]
    if section == "liquidity_summary":
        return mat["liquidity_summary"][key]
    if section == "readiness_summary":
        return mat["readiness_summary"][key]
    raise AssertionError(f"unknown section {section}")


def _bump(v):
    if isinstance(v, bool):
        return not v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) + 1_000_000.0
    if isinstance(v, str):
        return v + "__mut"
    if v is None:
        return "was_none"
    return str(v) + "_m"


def _mutate_path(payload: dict, path: str) -> dict:
    out = copy.deepcopy(payload)
    section, key = path.split(":", 1)
    if section == "scalars":
        out[key] = _bump(out.get(key))
    elif section == "structural":
        out[key] = _bump(out.get(key))
    elif section == "spot_anchors":
        sa = dict(out.get("spot_anchors") or {})
        sa[key] = _bump(sa.get(key))
        out["spot_anchors"] = sa
    elif section == "order_flow":
        od = dict(out.get("order_flow") or {})
        od[key] = _bump(od.get(key))
        out["order_flow"] = od
    elif section == "liquidity_summary":
        lq = dict(out.get("liquidity_summary") or {})
        lq[key] = _bump(lq.get(key))
        out["liquidity_summary"] = lq
    elif section == "readiness_summary":
        rs = dict(out.get("readiness_summary") or {})
        rs[key] = _bump(rs.get(key))
        out["readiness_summary"] = rs
    else:
        raise AssertionError(section)
    return out


@pytest.mark.parametrize("path", sorted(get_all_decision_dependency_keys()))
def test_each_decision_path_propagates_to_material_dict(path: str):
    """Mutating the canonical payload source changes material dict at that path (not hash-only)."""
    base = _full_l1_payload()
    base_mat = build_l1_material_dict_for_fingerprint(base)
    alt = _mutate_path(base, path)
    alt_mat = build_l1_material_dict_for_fingerprint(alt)
    assert _material_get(base_mat, path) != _material_get(alt_mat, path), (
        f"Mutation did not propagate into material dict for {path}"
    )


def test_full_payload_has_no_absent_sentinels_at_decision_paths():
    """Regression: full Tier B payload must populate every material path (no silent ABSENT collapse)."""
    from planes.l1_fingerprint_material import L1_MATERIAL_ABSENT, L1_MATERIAL_CONTAINER_ABSENT

    p = _full_l1_payload()
    mat = build_l1_material_dict_for_fingerprint(p)
    for sec in ("order_flow", "spot_anchors", "liquidity_summary", "readiness_summary"):
        assert mat[sec] is not L1_MATERIAL_CONTAINER_ABSENT
        assert mat[sec] is not None
    for path in get_all_decision_dependency_keys():
        assert _material_get(mat, path) is not L1_MATERIAL_ABSENT, path


def test_top_level_vwap_alias_does_not_override_spot_anchors_canonical():
    """
    Canonical VWAP for fingerprint is spot_anchors.* only (planes/l1_fingerprint_material.py).
    Top-level vwap / vwap_side / dist_to_vwap_pts are duplicate UI fields — must not shadow material.
    """
    p = _full_l1_payload()
    p["vwap"] = 99999.0
    p["vwap_side"] = "alias_side"
    p["dist_to_vwap_pts"] = 99.0
    mat = build_l1_material_dict_for_fingerprint(p)
    assert mat["spot_anchors"]["vwap"] == 550.0
    assert mat["spot_anchors"]["vwap_side"] == "below"
    # Mutate alias only — material spot_anchors unchanged
    p2 = copy.deepcopy(p)
    p2["vwap"] = 1.0
    m2 = build_l1_material_dict_for_fingerprint(p2)
    assert m2["spot_anchors"] == mat["spot_anchors"]


def test_tier_b_structural_dict_does_not_feed_structural_block():
    """
    Material structural{} uses top-level keys only (payload.get(k) per _STRUCTURAL_KEYS).
    tier_b_structural subdict is not read by fingerprint material — shadow if out of sync.
    """
    p = _full_l1_payload()
    p["tier_b_structural"] = {k: f"SHADOW_{k}" for k in _STRUCTURAL_KEYS}
    mat = build_l1_material_dict_for_fingerprint(p)
    for k in _STRUCTURAL_KEYS:
        assert mat["structural"][k] == p[k], k
        assert mat["structural"][k] != p["tier_b_structural"][k]


def test_mutating_tier_b_structural_only_does_not_change_material_structural():
    p = _full_l1_payload()
    base_mat = build_l1_material_dict_for_fingerprint(p)
    p2 = copy.deepcopy(p)
    p2["tier_b_structural"] = {"zone": "ONLY_SHADOW_CHANGED"}
    mat2 = build_l1_material_dict_for_fingerprint(p2)
    assert mat2["structural"] == base_mat["structural"]


def test_liquidity_behavior_summary_duplicate_does_not_replace_liquidity_summary():
    """liquidity_behavior_summary may duplicate liquidity_summary — material uses liquidity_summary only."""
    p = _full_l1_payload()
    base_mat = build_l1_material_dict_for_fingerprint(p)
    p2 = copy.deepcopy(p)
    p2["liquidity_behavior_summary"] = {
        "behavior_label": "SHADOW",
        "range_imbalance_stall_score": 99,
        "range_imbalance_push_score": 99,
    }
    assert build_l1_material_dict_for_fingerprint(p2)["liquidity_summary"] == base_mat["liquidity_summary"]


def test_diagnostic_like_key_at_top_level_does_not_affect_material():
    """Unknown top-level keys must not appear in material dict (allowlist-only)."""
    p = _full_l1_payload()
    p["l1_instrumentation"] = {"spoof_zone": "bad"}
    p["zone_like_diagnostic"] = "noise"
    mat = build_l1_material_dict_for_fingerprint(p)
    assert "l1_instrumentation" not in mat
    assert "zone_like_diagnostic" not in mat
    assert mat["structural"]["zone"] == p["zone"]
