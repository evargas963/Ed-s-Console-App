"""
Strict source → canonical coercion for MVP features.

Distinguishes:
- **missing**: source key absent, or source value is JSON/SQL NULL → canonical ``None``
- **invalid**: source key present with a value that cannot be coerced to a legal canonical value →
  raises `MvpFeatureSourceError` (never laundered into ``None``).

Invalid includes: unparseable numerics, bool for numeric fields, dict/list for numerics,
non-finite floats, empty strings for categoricals, vocabulary violations, wrong types for
`liquidity_summary` container.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from features.canonical_contract import ALLOWED_VWAP_SIDE_VALUES, ALLOWED_ZONE_VALUES


class MvpFeatureSourceError(ValueError):
    """Source payload cannot be coerced to MVP canonical features without data loss or ambiguity."""


def _contains_key(m: Mapping[str, Any], key: str) -> bool:
    try:
        return key in m
    except TypeError:
        return False


def _require_mapping(parent: Any, canonical_field: str) -> Mapping[str, Any]:
    if not isinstance(parent, Mapping):
        raise MvpFeatureSourceError(
            f"{canonical_field}: parent must be a Mapping, got {type(parent).__name__!r}"
        )
    return parent


def strict_float_from_raw(raw: Any, canonical_field: str) -> float:
    """Parse a required numeric; raises MvpFeatureSourceError if value is not a legal finite float."""
    if isinstance(raw, bool):
        raise MvpFeatureSourceError(f"{canonical_field}: bool is not a valid numeric source")
    if isinstance(raw, (dict, list, tuple, set)):
        raise MvpFeatureSourceError(
            f"{canonical_field}: invalid type {type(raw).__name__!r} for numeric field (expected scalar)"
        )
    try:
        v = float(raw)
    except (TypeError, ValueError) as e:
        raise MvpFeatureSourceError(
            f"{canonical_field}: unparseable numeric value {raw!r}"
        ) from e
    if not math.isfinite(v):
        raise MvpFeatureSourceError(f"{canonical_field}: non-finite value {v!r}")
    return v


def read_optional_float(parent: Mapping[str, Any], key: str, canonical_field: str) -> float | None:
    """
    Missing: key absent, or value is None → None.
    Present non-null: must parse as finite float or raise.
    """
    parent = _require_mapping(parent, canonical_field)
    if not _contains_key(parent, key):
        return None
    raw = parent[key]
    if raw is None:
        return None
    return strict_float_from_raw(raw, canonical_field)


def read_optional_zone(parent: Mapping[str, Any], key: str, canonical_field: str) -> str | None:
    parent = _require_mapping(parent, canonical_field)
    if not _contains_key(parent, key):
        return None
    raw = parent[key]
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise MvpFeatureSourceError(
            f"{canonical_field}: expected str or null, got {type(raw).__name__!r}"
        )
    t = raw.strip().lower()
    if not t:
        raise MvpFeatureSourceError(
            f"{canonical_field}: empty string is invalid; omit key or use null for missing"
        )
    if t not in ALLOWED_ZONE_VALUES:
        raise MvpFeatureSourceError(
            f"{canonical_field}: value {t!r} not in locked vocabulary {sorted(ALLOWED_ZONE_VALUES)}"
        )
    return t


def read_optional_vwap_side(parent: Mapping[str, Any], key: str, canonical_field: str) -> str | None:
    parent = _require_mapping(parent, canonical_field)
    if not _contains_key(parent, key):
        return None
    raw = parent[key]
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise MvpFeatureSourceError(
            f"{canonical_field}: expected str or null, got {type(raw).__name__!r}"
        )
    t = raw.strip().lower()
    if not t:
        raise MvpFeatureSourceError(
            f"{canonical_field}: empty string is invalid; omit key or use null for missing"
        )
    if t not in ALLOWED_VWAP_SIDE_VALUES:
        raise MvpFeatureSourceError(
            f"{canonical_field}: value {t!r} not in locked vocabulary {sorted(ALLOWED_VWAP_SIDE_VALUES)}"
        )
    return t


def read_liquidity_summary_subdict(l1_payload: Mapping[str, Any]) -> dict[str, Any]:
    """
    Resolve `liquidity_summary` for live payloads.

    Missing key → {} (no absorption/continuation keys).
    Null → {}.
    Non-dict, non-null → MvpFeatureSourceError.
    """
    l1_payload = _require_mapping(l1_payload, "liquidity_summary")
    if not _contains_key(l1_payload, "liquidity_summary"):
        return {}
    raw = l1_payload["liquidity_summary"]
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise MvpFeatureSourceError(
            f"liquidity_summary: expected dict or null, got {type(raw).__name__!r}"
        )
    return raw
