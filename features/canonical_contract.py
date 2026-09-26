"""
1-minute-first canonical feature contract (MVP).

Strict validation at the contract boundary: exact keys, types, finiteness, and categorical vocab.
Order flow, readiness, and L1 instrumentation are explicitly out of scope for v1.
"""

from __future__ import annotations

import math
from typing import Any

CANONICAL_FEATURE_CONTRACT_VERSION = "v1_1m_mvp"
CANONICAL_FEATURE_TIMEFRAME = "1m"

# Locked vocabulary (lowercase). Live/DB may use any casing; adapters normalize before validation.
# Aligned with lstm_data.ZONE_MAP keys / structural zones in the codebase.
ALLOWED_ZONE_VALUES: frozenset[str] = frozenset(
    {
        "pin_bull",
        "pin_bear",
        "pin_neutral",
        "pin_chaos",
        "breakout",
        "breakdown",
    }
)

ALLOWED_VWAP_SIDE_VALUES: frozenset[str] = frozenset({"above", "below"})

INFERENCE_SNAPSHOT_TYPE = "InferenceSnapshotV1"
INFERENCE_SNAPSHOT_SOURCE_LIVE_L1 = "live_l1_tier_b"

_MVP_FEATURE_ORDER: tuple[str, ...] = (
    "price.spot",
    "price.spread_pts",
    "structure.zone",
    "structure.nearest_above_dist",
    "structure.nearest_below_dist",
    "structure.net_gamma",
    "anchor.vwap_side",
    "anchor.vwap_dist_pts",
    "liquidity.absorption_score",
    "liquidity.continuation_score",
)

_FLOAT_KEYS = frozenset(
    {
        "price.spot",
        "price.spread_pts",
        "structure.nearest_above_dist",
        "structure.nearest_below_dist",
        "structure.net_gamma",
        "anchor.vwap_dist_pts",
        "liquidity.absorption_score",
        "liquidity.continuation_score",
    }
)
_STR_ENUM_KEYS = frozenset({"structure.zone", "anchor.vwap_side"})

# canonical_name -> spec (metadata for docs / tooling)
_MVP_SPECS: dict[str, dict[str, Any]] = {
    "price.spot": {
        "canonical_name": "price.spot",
        "dtype": "float",
        "allow_none": True,
        "when_non_null": "finite, strictly positive (spot > 0)",
        "missing_semantics": "None = no usable spot",
        "source_category": "price",
        "live_supported": True,
        "db_supported": True,
        "training_supported": True,
        "inference_supported": True,
    },
    "price.spread_pts": {
        "canonical_name": "price.spread_pts",
        "dtype": "float",
        "allow_none": True,
        "when_non_null": "finite, nonnegative (spread >= 0)",
        "missing_semantics": "None = spread unknown",
        "source_category": "price",
        "live_supported": True,
        "db_supported": True,
        "training_supported": True,
        "inference_supported": True,
    },
    "structure.zone": {
        "canonical_name": "structure.zone",
        "dtype": "str",
        "allow_none": True,
        "when_non_null": f"must be one of {sorted(ALLOWED_ZONE_VALUES)}; empty string forbidden",
        "missing_semantics": "None = zone unavailable",
        "source_category": "structure",
        "live_supported": True,
        "db_supported": True,
        "training_supported": True,
        "inference_supported": True,
    },
    "structure.nearest_above_dist": {
        "canonical_name": "structure.nearest_above_dist",
        "dtype": "float",
        "allow_none": True,
        "when_non_null": "finite (signed distance allowed; negative not used for 'above' in normal data)",
        "missing_semantics": "None = no level / unknown",
        "source_category": "structure",
        "live_supported": True,
        "db_supported": True,
        "training_supported": True,
        "inference_supported": True,
    },
    "structure.nearest_below_dist": {
        "canonical_name": "structure.nearest_below_dist",
        "dtype": "float",
        "allow_none": True,
        "when_non_null": "finite (signed distance; negative values allowed per exchange convention)",
        "missing_semantics": "None = no level / unknown",
        "source_category": "structure",
        "live_supported": True,
        "db_supported": True,
        "training_supported": True,
        "inference_supported": True,
    },
    "structure.net_gamma": {
        "canonical_name": "structure.net_gamma",
        "dtype": "float",
        "allow_none": True,
        "when_non_null": "finite (any sign)",
        "missing_semantics": "None = unknown",
        "source_category": "structure",
        "live_supported": True,
        "db_supported": True,
        "training_supported": True,
        "inference_supported": True,
    },
    "anchor.vwap_side": {
        "canonical_name": "anchor.vwap_side",
        "dtype": "str",
        "allow_none": True,
        "when_non_null": f"must be one of {sorted(ALLOWED_VWAP_SIDE_VALUES)}; empty string forbidden",
        "missing_semantics": "None = side unknown",
        "source_category": "anchor",
        "live_supported": True,
        "db_supported": True,
        "training_supported": True,
        "inference_supported": True,
    },
    "anchor.vwap_dist_pts": {
        "canonical_name": "anchor.vwap_dist_pts",
        "dtype": "float",
        "allow_none": True,
        "when_non_null": "finite (signed: spot - VWAP)",
        "missing_semantics": "None = VWAP distance unknown",
        "source_category": "anchor",
        "live_supported": True,
        "db_supported": True,
        "training_supported": True,
        "inference_supported": True,
    },
    "liquidity.absorption_score": {
        "canonical_name": "liquidity.absorption_score",
        "dtype": "float",
        "allow_none": True,
        "when_non_null": "finite (any sign unless source constrains)",
        "missing_semantics": "None = no liquidity slice",
        "source_category": "liquidity",
        "live_supported": True,
        "db_supported": True,
        "training_supported": True,
        "inference_supported": True,
    },
    "liquidity.continuation_score": {
        "canonical_name": "liquidity.continuation_score",
        "dtype": "float",
        "allow_none": True,
        "when_non_null": "finite (any sign unless source constrains)",
        "missing_semantics": "None = no liquidity slice",
        "source_category": "liquidity",
        "live_supported": True,
        "db_supported": True,
        "training_supported": True,
        "inference_supported": True,
    },
}

_EXCLUDED_FROM_MVP: frozenset[str] = frozenset(
    {
        "order_flow.*",
        "readiness.*",
        "live freshness diagnostics (order_flow_stale, quote_overlay_age_sec, …)",
        "l1_generation",
        "l1_projection / l1_instrumentation",
    }
)

# Per-field semantics at the contract boundary (canonical row + adapter coercion).
# "Missing" and "invalid" are distinct: invalid values must never be laundered into None.
_MVP_FIELD_SEMANTICS: dict[str, dict[str, str]] = {
    "price.spot": {
        "missing": "Source key absent, or source value is null → canonical None.",
        "invalid": "Present non-null: wrong type for numeric (e.g. bool, dict, list), unparseable string, non-finite float; or canonical validation fails (spot ≤ 0).",
        "valid": "Finite numeric > 0 after strict parse; canonical row holds float.",
    },
    "price.spread_pts": {
        "missing": "Source key absent, or source value is null → canonical None.",
        "invalid": "Present non-null: wrong type, unparseable string, non-finite float; or canonical validation fails (spread < 0).",
        "valid": "Finite numeric ≥ 0; canonical row holds float.",
    },
    "structure.zone": {
        "missing": "Source key absent, or source value is null → canonical None.",
        "invalid": "Present non-null: not a string, empty/whitespace-only after strip, or not in ALLOWED_ZONE_VALUES.",
        "valid": "Non-empty str matching vocabulary after strip+lowercase; canonical row holds lowercase token.",
    },
    "structure.nearest_above_dist": {
        "missing": "Source key absent, or source value is null → canonical None.",
        "invalid": "Present non-null: wrong type for numeric, unparseable string, non-finite float.",
        "valid": "Finite signed numeric; canonical row holds float.",
    },
    "structure.nearest_below_dist": {
        "missing": "Source key absent, or source value is null → canonical None.",
        "invalid": "Present non-null: wrong type for numeric, unparseable string, non-finite float.",
        "valid": "Finite signed numeric; canonical row holds float.",
    },
    "structure.net_gamma": {
        "missing": "Source key absent, or source value is null → canonical None.",
        "invalid": "Present non-null: wrong type for numeric, unparseable string, non-finite float.",
        "valid": "Finite signed numeric; canonical row holds float.",
    },
    "anchor.vwap_side": {
        "missing": "Source key absent, or source value is null → canonical None.",
        "invalid": "Present non-null: not a string, empty/whitespace-only, or not in ALLOWED_VWAP_SIDE_VALUES.",
        "valid": "Non-empty str matching vocabulary after strip+lowercase; canonical row holds lowercase token.",
    },
    "anchor.vwap_dist_pts": {
        "missing": "Source key absent, or source value is null → canonical None.",
        "invalid": "Present non-null: wrong type for numeric, unparseable string, non-finite float.",
        "valid": "Finite signed numeric; canonical row holds float.",
    },
    "liquidity.absorption_score": {
        "missing": "Live: key absent under `liquidity_summary` or summary key absent / null; DB: column absent or null → canonical None.",
        "invalid": "Present non-null: wrong type, unparseable string, non-finite float; live: `liquidity_summary` present but not dict/null.",
        "valid": "Finite signed numeric; canonical row holds float.",
    },
    "liquidity.continuation_score": {
        "missing": "Same as liquidity.absorption_score for the paired field.",
        "invalid": "Same as liquidity.absorption_score.",
        "valid": "Finite signed numeric; canonical row holds float.",
    },
}


def get_mvp_feature_names() -> tuple[str, ...]:
    """Ordered tuple of MVP canonical feature names."""
    return _MVP_FEATURE_ORDER


def get_feature_spec(name: str) -> dict[str, Any]:
    """Return the spec dict for a canonical feature name."""
    if name not in _MVP_SPECS:
        raise KeyError(f"Unknown MVP feature: {name!r}")
    return dict(_MVP_SPECS[name])


def get_mvp_field_semantics(name: str) -> dict[str, str]:
    """Return missing / invalid / valid semantics for one MVP canonical field."""
    if name not in _MVP_FIELD_SEMANTICS:
        raise KeyError(f"Unknown MVP feature: {name!r}")
    return dict(_MVP_FIELD_SEMANTICS[name])


def validate_feature_contract_row(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Strict validation:
    - Exactly the MVP key set (no missing, no extra).
    - None is allowed for any field (optional / missing-at-tick).
    - Non-None: exact Python types (float-like for numerics via int/float, never bool).
    - Non-None numerics: finite (reject NaN, inf).
    - Non-None strings: non-empty and must match locked categorical vocabulary where applicable.
    - price.spot: must be > 0 when present.
    - price.spread_pts: must be >= 0 when present.

    Returns (ok, error_messages).
    """
    errors: list[str] = []
    expected = list(_MVP_FEATURE_ORDER)
    got = list(row.keys())
    if set(got) != set(expected):
        missing = sorted(set(expected) - set(got))
        extra = sorted(set(got) - set(expected))
        if missing:
            errors.append(f"missing keys: {missing}")
        if extra:
            errors.append(f"extra keys: {extra}")
        return (False, errors)

    # Stable order check: adapters should preserve order; enforce for drift safety
    if got != expected:
        errors.append(f"key order mismatch: expected {expected}, got {got}")

    for k in expected:
        v = row[k]
        if v is None:
            continue

        if k in _FLOAT_KEYS:
            if isinstance(v, bool):
                errors.append(f"{k}: bool is not a valid numeric type (use int/float)")
                continue
            if not isinstance(v, (int, float)):
                errors.append(f"{k}: expected int, float, or None, got {type(v).__name__}")
                continue
            vf = float(v)
            if not math.isfinite(vf):
                errors.append(f"{k}: must be finite (reject NaN/inf), got {vf!r}")
                continue
            if k == "price.spot" and not (vf > 0.0):
                errors.append(f"{k}: when present must be > 0, got {vf!r}")
            elif k == "price.spread_pts" and vf < 0.0:
                errors.append(f"{k}: when present must be >= 0, got {vf!r}")

        elif k in _STR_ENUM_KEYS:
            if not isinstance(v, str):
                errors.append(f"{k}: expected str or None, got {type(v).__name__}")
                continue
            if not v.strip():
                errors.append(f"{k}: empty string is forbidden; use None for missing")
                continue
            token = v.strip().lower()
            if token != v:
                errors.append(f"{k}: must be normalized lowercase canonical token, got {v!r}")
            if k == "structure.zone":
                if token not in ALLOWED_ZONE_VALUES:
                    errors.append(
                        f"{k}: value {token!r} not in allowed set {sorted(ALLOWED_ZONE_VALUES)}"
                    )
            elif k == "anchor.vwap_side":
                if token not in ALLOWED_VWAP_SIDE_VALUES:
                    errors.append(
                        f"{k}: value {token!r} not in allowed set {sorted(ALLOWED_VWAP_SIDE_VALUES)}"
                    )

    return (len(errors) == 0, errors)


def excluded_from_mvp() -> frozenset[str]:
    """Human-readable exclusion list for documentation."""
    return _EXCLUDED_FROM_MVP
