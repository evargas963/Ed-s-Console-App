"""
Unified semantic contract for all trained inference artifacts (Issue 7 continuation).

Loaders must not register a model unless *_meta.json declares every field below
and each value matches the current system constants. Absence or mismatch = incompatible.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from training_provenance import FEATURE_SCHEMA_VERSION, LABEL_CONFIG_VERSION

# ── Current system contract (bump when semantics change; retrain all families) ──
CURRENT_LABEL_CONFIG_VERSION = LABEL_CONFIG_VERSION
CURRENT_HORIZON_OUTCOME_SCHEMA_VERSION = "bar_forward_close_v1"
CURRENT_ANCHOR_CONTRACT_VERSION = "bar_close_anchor_v1"
CURRENT_FEATURE_SCHEMA_VERSION = FEATURE_SCHEMA_VERSION
CURRENT_MISSINGNESS_CONTRACT_VERSION = "issue7_v1_empirical_nan_impute"

CONTRACT_FIELDS = (
    "label_config_version",
    "horizon_outcome_schema_version",
    "anchor_contract_version",
    "feature_schema_version",
    "missingness_contract_version",
)


def contract_metadata_dict() -> Dict[str, str]:
    """Written into every XGB / LSTM / Transformer meta (and embedded provenance where saved)."""
    return {
        "label_config_version": CURRENT_LABEL_CONFIG_VERSION,
        "horizon_outcome_schema_version": CURRENT_HORIZON_OUTCOME_SCHEMA_VERSION,
        "anchor_contract_version": CURRENT_ANCHOR_CONTRACT_VERSION,
        "feature_schema_version": CURRENT_FEATURE_SCHEMA_VERSION,
        "missingness_contract_version": CURRENT_MISSINGNESS_CONTRACT_VERSION,
    }


def meta_matches_system_contract(meta: dict) -> Tuple[bool, str]:
    if not isinstance(meta, dict):
        return False, "meta is not a dict"
    expected = contract_metadata_dict()
    for key, need in expected.items():
        got = meta.get(key)
        if got != need:
            return False, f"{key}: artifact={got!r} required={need!r}"
    return True, ""


def _xgb_impute_complete(meta: dict) -> bool:
    feats, imp = meta.get("features"), meta.get("impute_medians")
    if not isinstance(feats, list) or not isinstance(imp, dict):
        return False
    return all(f in imp for f in feats)


def validate_artifact_contract(meta: dict, family: str) -> Tuple[bool, str]:
    """
    family: 'xgb' | 'lstm' | 'transformer'
    XGB additionally requires impute_medians (tabular missingness implementation).
    """
    fam = (family or "").strip().lower()
    ok, msg = meta_matches_system_contract(meta)
    if not ok:
        return False, msg
    if fam == "xgb":
        if not _xgb_impute_complete(meta):
            return (
                False,
                "XGB requires impute_medians dict with one numeric entry per features[] name",
            )
    elif fam not in ("lstm", "transformer"):
        return False, f"unknown model family {family!r}"
    return True, ""


def provenance_dict_with_contract(prov_dict: dict) -> Dict[str, Any]:
    """Merge training provenance dict with current contract fields (single source of truth)."""
    out = dict(prov_dict)
    out.update(contract_metadata_dict())
    return out
