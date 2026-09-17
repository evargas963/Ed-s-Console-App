"""
Unified semantic contract for all trained inference artifacts (Issue 7 continuation).

Loaders must not register a model unless *_meta.json declares every field below
and each value matches the current system constants. Absence or mismatch = incompatible.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from training_provenance import (
    FEATURE_SCHEMA_VERSION,
    LABEL_CONFIG_VERSION,
    PREPROCESSING_VERSION,
)

# ── Current system contract (bump when semantics change; retrain all families) ──
CURRENT_LABEL_CONFIG_VERSION = LABEL_CONFIG_VERSION
CURRENT_HORIZON_OUTCOME_SCHEMA_VERSION = "bar_forward_close_v1"
CURRENT_ANCHOR_CONTRACT_VERSION = "bar_close_anchor_v1"
CURRENT_FEATURE_SCHEMA_VERSION = FEATURE_SCHEMA_VERSION
# No-fallback lock (2026-09-17): v1 required XGB models to median-impute missing
# feature readings (fit on the train partition) before training/serving -- a specific,
# meaningful value substituted for "never observed." v2 requires XGB models to train on
# raw NaN and rely on XGBoost's own native missing-value handling instead (no imputation
# at all). Per this contract's own established purpose ("bump when semantics change;
# retrain all families"), this bump means no bundle trained under v1 can pass
# meta_matches_system_contract until it is retrained under v2 -- the deliberate
# consequence of a genuine missingness-semantics change, not an oversight. See
# ml_train.py's apply_xgb_imputation_matrix docstring and _xgb_impute_complete below for
# the v1/v2 shape distinction (a complete impute_medians dict vs. a deliberately empty one).
CURRENT_MISSINGNESS_CONTRACT_VERSION = "issue7_v2_xgb_native_nan_no_impute"
# Closeout #1 follow-on (2026-05-31): preprocessing_version is a serving-compatibility axis —
# engineer_single_snapshot (serving) must stay lockstep with engineer_features (training). A
# preprocessing-only change (e.g. the B3 train-only fit) alters feature VALUES, so a bundle trained
# under an older preprocessing version is stale even when feature_schema_version (column set) is
# unchanged. Including it here makes such a change fail-close serving like LABEL_CONFIG_VERSION, not
# just invalidate the training cache. All three families already stamp it via TrainingProvenance.
CURRENT_PREPROCESSING_VERSION = PREPROCESSING_VERSION

CONTRACT_FIELDS = (
    "label_config_version",
    "horizon_outcome_schema_version",
    "anchor_contract_version",
    "feature_schema_version",
    "missingness_contract_version",
    "preprocessing_version",
)


def contract_metadata_dict() -> Dict[str, str]:
    """Written into every XGB / LSTM / Transformer meta (and embedded provenance where saved)."""
    return {
        "label_config_version": CURRENT_LABEL_CONFIG_VERSION,
        "horizon_outcome_schema_version": CURRENT_HORIZON_OUTCOME_SCHEMA_VERSION,
        "anchor_contract_version": CURRENT_ANCHOR_CONTRACT_VERSION,
        "feature_schema_version": CURRENT_FEATURE_SCHEMA_VERSION,
        "missingness_contract_version": CURRENT_MISSINGNESS_CONTRACT_VERSION,
        "preprocessing_version": CURRENT_PREPROCESSING_VERSION,
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
    """True for either valid missingness shape: a deliberately empty impute_medians
    (issue7_v2 -- this model trained on raw NaN, XGBoost's own native handling applies,
    no median fill exists to be complete or incomplete) or a fully-populated one
    (issue7_v1 -- legacy; harmless to also accept under v2 since current training code
    never produces this shape, and it is byte-identical to the always-required v1
    check). A PARTIAL dict (some but not all features covered) is neither shape and
    fails -- that's a malformed artifact, not a valid missingness design."""
    feats, imp = meta.get("features"), meta.get("impute_medians")
    if not isinstance(feats, list) or not isinstance(imp, dict):
        return False
    if not imp:
        return True
    return all(f in imp for f in feats)


def validate_artifact_contract(meta: dict, family: str) -> Tuple[bool, str]:
    """
    family: 'xgb' | 'lstm' | 'transformer'
    XGB additionally requires an impute_medians dict shaped as either fully empty
    (issue7_v2 -- native XGBoost NaN handling, no imputation) or fully populated
    (issue7_v1 -- legacy median fill); a partial dict is rejected either way.
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
