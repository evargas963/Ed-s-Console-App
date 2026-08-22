"""
Issue 47: fingerprint scope integrity — decision deps vs fingerprint vs drift warnings.
"""
from __future__ import annotations

import copy
import logging
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
    L1_ALLOWED_FINGERPRINT_EXTRA_KEYS,
    L1_DECISION_DEPENDENCY_KEYS,
    L1_KNOWN_NON_MATERIAL_TOP_LEVEL_KEYS,
    get_all_decision_dependency_keys,
    warn_l1_payload_key_drift,
)
from planes.l1_fingerprint_material import (  # noqa: E402
    L1_FINGERPRINT_STRUCTURAL_FLOAT_KEYS,
    build_l1_material_dict_for_fingerprint,
    get_all_fingerprint_keys,
)


def _full_l1_payload() -> dict:
    """Populate every decision path with a distinct, mutable value."""
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


def test_coverage_fingerprint_superset_of_decision_paths():
    decision_keys = get_all_decision_dependency_keys()
    fingerprint_keys = get_all_fingerprint_keys()
    missing = decision_keys - fingerprint_keys
    assert not missing, f"Fingerprint missing decision-critical keys: {sorted(missing)}"


def test_fingerprint_does_not_include_unclassified_fields():
    fingerprint_keys = get_all_fingerprint_keys()
    decision_keys = get_all_decision_dependency_keys()

    extra = set(fingerprint_keys - decision_keys)

    allowed = L1_ALLOWED_FINGERPRINT_EXTRA_KEYS
    unexpected = extra - allowed

    assert not unexpected, (
        f"Fingerprint includes non-decision, non-approved fields: {sorted(unexpected)}"
    )


def test_coverage_material_dict_exposes_every_decision_path():
    base = _full_l1_payload()
    mat = build_l1_material_dict_for_fingerprint(base)
    missing: list[str] = []
    for path in sorted(get_all_decision_dependency_keys()):
        try:
            _material_get(mat, path)
        except Exception:
            missing.append(path)
    assert not missing, f"missing paths in material dict: {missing}"


@pytest.mark.parametrize("path", sorted(get_all_decision_dependency_keys()))
def test_sensitivity_mutating_decision_field_changes_fingerprint(path: str):
    import server as srv

    base = _full_l1_payload()
    alt = _mutate_path(base, path)
    assert srv._l1_payload_fingerprint(base) != srv._l1_payload_fingerprint(alt)


def test_negative_diagnostic_and_unknown_do_not_change_fingerprint():
    import server as srv

    base = _full_l1_payload()
    alt = {
        **base,
        "l1_instrumentation": {"n": 1},
        "l1_projection": {"cache_age_sec": 5.0},
        "as_of_ts": 999999.0,
        "brand_new_unknown_top_level": {"x": 1},
    }
    assert srv._l1_payload_fingerprint(base) == srv._l1_payload_fingerprint(alt)


def test_runtime_drift_warns_on_unclassified_top_level():
    payload = {
        "plane": PLANE_L1,
        "spot": 1.0,
        "zone": "z",
        "mystery_unclassified_field": 123,
    }
    drift = warn_l1_payload_key_drift(payload, logger=logging.getLogger("test_drift"))
    assert drift == ["mystery_unclassified_field"]


def test_runtime_drift_silent_for_union_of_material_and_known_non_material():
    p = _full_l1_payload()
    for k in L1_KNOWN_NON_MATERIAL_TOP_LEVEL_KEYS:
        if k not in p:
            p[k] = None
    drift = warn_l1_payload_key_drift(p, logger=logging.getLogger("test_drift"))
    assert drift == []


def test_runtime_drift_silent_for_live_quote_overlay_provenance_keys():
    """S009 overlay stamps spread_pts (material) + mid/spread provenance (non-material)."""
    p = {
        **_full_l1_payload(),
        "spread_pts": 0.05,
        "quote_mid": 500.25,
        "mid_source": "derived_bid_ask_mid",
        "spread_source": "schwab_quote",
        "spread_pts_source": "schwab_quote",
    }
    drift = warn_l1_payload_key_drift(p, logger=logging.getLogger("test_drift"))
    assert drift == []
