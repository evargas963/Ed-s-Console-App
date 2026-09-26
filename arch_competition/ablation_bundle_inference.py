"""
Unified ablation stack scoring — one contiguous path, wire-row surface only.

All seven layers (xgb, lstm, transformer, meta, monte_carlo, regime, fusion) score
from the same permuted DB row dict. No production ``production_fusion_payload_for_stack``
branch, no ``ml_predict`` ablation forks, no DB history windows for LSTM/TR.
"""
from __future__ import annotations















def validate_ablation_scoring_bundle_meta(meta: dict, family: str) -> tuple[bool, str]:
    """Minimal on-disk bundle checks for offline ablation — not production contract drift."""
    if not isinstance(meta, dict):
        return False, "meta is not a dict"
    fam = (family or "").strip().lower()
    if fam == "xgb":
        feats = meta.get("features")
        if not isinstance(feats, list) or not feats:
            return False, "xgb features[] missing"
        imp = meta.get("impute_medians")
        if not isinstance(imp, dict):
            return False, "xgb impute_medians missing"
        if not all(f in imp for f in feats):
            return False, "xgb impute_medians incomplete"
    return True, ""


























