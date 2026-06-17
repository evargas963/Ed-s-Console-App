"""
L1 Tier B payload fingerprint — explicit MATERIAL ALLOWLIST only.

Identity hashes must not depend on exclusion lists: unknown or future diagnostic / freshness /
instrumentation fields are ignored unless added here. Structural L2 and OF key sets are
shared with planes.context_light where applicable.

Fingerprint allowlists are defined ONLY in this module (independent of
planes.l1_decision_dependencies — verified by tests).

--- Issue 49: partial-payload semantics (explicit, tested) ---

We differentiate fingerprint-relevant states:

- L1_MATERIAL_ABSENT: allowlisted *field* key is not present on the payload (or not present
  inside a dict section that *is* present). JSON-serializable string token.
- L1_MATERIAL_CONTAINER_ABSENT: allowlisted *section* key (e.g. order_flow) is not present
  on the payload at all. Distinct from section present with value None, or present as {}.
- Explicit Python None: key is present and value is None.
- Empty dict for a section (e.g. order_flow={}): section is present; each fixed sub-key is
  resolved with the same absent vs None semantics (typically all L1_MATERIAL_ABSENT).

--- Issue 50: canonical types ---

Every material value is normalized to a canonical Python type before fingerprint hashing.
- int / bool / float equivalence: bool checked before int; numeric scalars become float or int.
- Safe numeric strings (e.g. "500.0") parse to float/int per field kind.
- Values that cannot be coerced use L1_MATERIAL_INVALID (stable string), not silent wrong types.
"""

from __future__ import annotations

from typing import Any

from planes.context_light import _ORDER_FLOW_KEYS, _STRUCTURAL_KEYS

# Sentinel: allowlisted field name not present (payload or inner dict).
L1_MATERIAL_ABSENT: str = "__L1_MATERIAL_ABSENT__"
# Sentinel: allowlisted top-level section (order_flow, spot_anchors, etc.) not in payload.
L1_MATERIAL_CONTAINER_ABSENT: str = "__L1_MATERIAL_CONTAINER_ABSENT__"
# Sentinel: value present but cannot be coerced to the canonical type for that field (Issue 50).
L1_MATERIAL_INVALID: str = "__L1_MATERIAL_INVALID__"

# --- Local fingerprint allowlist (do not import from l1_decision_dependencies) ---
L1_FINGERPRINT_SCALAR_KEYS: tuple[str, ...] = (
    "plane",
    "schema_version",
    "merge_rule",
    "l1_generation",
    "l2_snapshot_version_used",
    "l2_merge_acknowledged",
    "l2_structural_scope_exact",
    "structural_context_stale",
    "l1_stale",
    "spot",
    "bid",
    "ask",
    "spot_disp",
    "bid_disp",
    "ask_disp",
    "spread",
    "spread_pts",
    "quote_ingestion",
    "ticker",
    "selected_exp",
)

SPOT_ANCHORS_KEYS: tuple[str, ...] = ("vwap", "vwap_side", "dist_to_vwap_pts")

LIQUIDITY_SUMMARY_KEYS: tuple[str, ...] = (
    "behavior_label",
    "absorption_score",
    "continuation_score",
)

READINESS_SUMMARY_KEYS: tuple[str, ...] = (
    "order_flow_readiness",
    "structural_anchor_stale",
    "has_acknowledged_l2_snapshot",
)

# Canonical type kinds: "int" | "float" | "bool" | "str"
_SCALAR_KIND: dict[str, str] = {
    "plane": "str",
    "schema_version": "int",
    "merge_rule": "str",
    "l1_generation": "int",
    "l2_snapshot_version_used": "int",
    "l2_merge_acknowledged": "bool",
    "l2_structural_scope_exact": "bool",
    "structural_context_stale": "bool",
    "l1_stale": "bool",
    "spot": "float",
    "bid": "float",
    "ask": "float",
    "spot_disp": "float",
    "bid_disp": "float",
    "ask_disp": "float",
    "spread": "float",
    "spread_pts": "float",
    "quote_ingestion": "str",
    "ticker": "str",
    "selected_exp": "str",
}

# Structural L2 fields treated as numeric in fingerprint material (tests must use numbers here).
L1_FINGERPRINT_STRUCTURAL_FLOAT_KEYS: frozenset[str] = frozenset(
    {
        "pin_strength",
        "nd_disp",
        "net_gamma",
        "nearest_above_val",
        "nearest_above_dist",
        "nearest_below_val",
        "nearest_below_dist",
        "charm_net",
    }
)

_ORDER_FLOW_STR_KEYS: frozenset[str] = frozenset(
    {
        "order_flow_regime",
        "order_flow_readiness",
        "order_flow_verdict",
        "order_flow_verdict_color",
        "order_flow_arrow",
        "order_flow_agreement",
    }
)


def _structural_kind(k: str) -> str:
    return "float" if k in L1_FINGERPRINT_STRUCTURAL_FLOAT_KEYS else "str"


def _order_flow_kind(k: str) -> str:
    return "str" if k in _ORDER_FLOW_STR_KEYS else "float"


def _spot_anchor_kind(k: str) -> str:
    return "str" if k == "vwap_side" else "float"


def _liquidity_kind(k: str) -> str:
    return "str" if k == "behavior_label" else "float"


def _readiness_kind(k: str) -> str:
    return "bool" if k in ("structural_anchor_stale", "has_acknowledged_l2_snapshot") else "str"


def _normalize_material_value(value: Any, field_path: str, kind: str) -> Any:
    """
    Enforce canonical type for fingerprint material. Sentinels and None pass through unchanged.
    Unrecoverable values become L1_MATERIAL_INVALID (documented, test-covered).
    """
    if value is None:
        return None
    if value is L1_MATERIAL_ABSENT or value is L1_MATERIAL_CONTAINER_ABSENT or value is L1_MATERIAL_INVALID:
        return value

    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value == 0:
                return False
            if value == 1:
                return True
            return L1_MATERIAL_INVALID
        if isinstance(value, str):
            s = value.strip().lower()
            if s in ("true", "1", "yes"):
                return True
            if s in ("false", "0", "no"):
                return False
            return L1_MATERIAL_INVALID
        return L1_MATERIAL_INVALID

    if kind == "int":
        if isinstance(value, bool):
            return L1_MATERIAL_INVALID
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                return L1_MATERIAL_INVALID
            if abs(value - round(value)) > 1e-9:
                return L1_MATERIAL_INVALID
            return int(round(value))
        if isinstance(value, str):
            t = value.strip()
            try:
                x = float(t)
            except (TypeError, ValueError):
                return L1_MATERIAL_INVALID
            if x != x or x in (float("inf"), float("-inf")):
                return L1_MATERIAL_INVALID
            if abs(x - round(x)) > 1e-9:
                return L1_MATERIAL_INVALID
            return int(round(x))
        return L1_MATERIAL_INVALID

    if kind == "float":
        if isinstance(value, bool):
            return L1_MATERIAL_INVALID
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            t = value.strip()
            try:
                return float(t)
            except (TypeError, ValueError):
                return L1_MATERIAL_INVALID
        return L1_MATERIAL_INVALID

    if kind == "str":
        return str(value)

    return L1_MATERIAL_INVALID


def _material_fixed_key_dict(
    raw: dict[str, Any],
    fixed_keys: tuple[str, ...],
    kind_fn: Any,
    path_prefix: str,
) -> dict[str, Any]:
    """Map fixed keys: absent sub-key → L1_MATERIAL_ABSENT; present → normalized value."""
    out: dict[str, Any] = {}
    for k in fixed_keys:
        if k not in raw:
            out[k] = L1_MATERIAL_ABSENT
        else:
            v = raw[k]
            out[k] = _normalize_material_value(v, f"{path_prefix}:{k}", kind_fn(k))
    return out


def _material_section_dict(
    payload: dict[str, Any],
    section_key: str,
    fixed_keys: tuple[str, ...],
    kind_fn: Any,
) -> Any:
    """
    Material value for a dict-shaped section (order_flow, spot_anchors, liquidity, readiness).

    - Section key not in payload → L1_MATERIAL_CONTAINER_ABSENT (string; not a dict).
    - Section explicitly None → None.
    - Section is dict (including {}) → fixed-key dict with per-key absent/None semantics.
    - Section is non-dict, non-None → None (invalid shape; isolated from container-absent).
    """
    if section_key not in payload:
        return L1_MATERIAL_CONTAINER_ABSENT
    raw = payload[section_key]
    if raw is None:
        return None
    if isinstance(raw, dict):
        return _material_fixed_key_dict(raw, fixed_keys, kind_fn, section_key)
    return None


def get_all_fingerprint_material_key_paths() -> frozenset[str]:
    """Canonical path ids for material included in the SHA fingerprint (section:key)."""
    out: set[str] = set()
    for k in L1_FINGERPRINT_SCALAR_KEYS:
        out.add(f"scalars:{k}")
    for k in _STRUCTURAL_KEYS:
        out.add(f"structural:{k}")
    for k in _ORDER_FLOW_KEYS:
        out.add(f"order_flow:{k}")
    for k in SPOT_ANCHORS_KEYS:
        out.add(f"spot_anchors:{k}")
    for k in LIQUIDITY_SUMMARY_KEYS:
        out.add(f"liquidity_summary:{k}")
    for k in READINESS_SUMMARY_KEYS:
        out.add(f"readiness_summary:{k}")
    return frozenset(out)


def get_all_fingerprint_keys() -> frozenset[str]:
    """Alias for tooling/tests (same as get_all_fingerprint_material_key_paths)."""
    return get_all_fingerprint_material_key_paths()


def build_l1_material_dict_for_fingerprint(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Construct ONLY allowlisted material fields. Does not read or strip unknown keys from a
    deep copy — everything not listed here is absent from the result.

    Partial-payload semantics are explicit (Issue 49): see module docstring for
    L1_MATERIAL_ABSENT vs L1_MATERIAL_CONTAINER_ABSENT vs None vs empty dict.

    Canonical types (Issue 50): all non-sentinel values are normalized via _normalize_material_value.
    """
    out: dict[str, Any] = {}
    for k in L1_FINGERPRINT_SCALAR_KEYS:
        if k not in payload:
            out[k] = L1_MATERIAL_ABSENT
        else:
            kind = _SCALAR_KIND[k]
            out[k] = _normalize_material_value(payload[k], f"scalars:{k}", kind)

    out["structural"] = {}
    for k in _STRUCTURAL_KEYS:
        if k not in payload:
            out["structural"][k] = L1_MATERIAL_ABSENT
        else:
            out["structural"][k] = _normalize_material_value(
                payload[k], f"structural:{k}", _structural_kind(k)
            )

    out["spot_anchors"] = _material_section_dict(
        payload, "spot_anchors", SPOT_ANCHORS_KEYS, _spot_anchor_kind
    )
    out["order_flow"] = _material_section_dict(
        payload, "order_flow", _ORDER_FLOW_KEYS, _order_flow_kind
    )
    out["liquidity_summary"] = _material_section_dict(
        payload, "liquidity_summary", LIQUIDITY_SUMMARY_KEYS, _liquidity_kind
    )
    out["readiness_summary"] = _material_section_dict(
        payload, "readiness_summary", READINESS_SUMMARY_KEYS, _readiness_kind
    )

    return out
