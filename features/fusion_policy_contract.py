"""
Canonical fusion → policy DB columns (per governed ML horizon).

Movement-target XGB columns (pred_move_prob_*, pred_dir_* on snapshots) remain **legacy**
feature / training / comparison surfaces — not policy authority.

Policy calibration (Phase 8/9) and reliability gates read fused_* only.
"""
from __future__ import annotations

import json
from typing import Any


def fusion_payload_to_policy_columns(hz: str, fusion: Any) -> dict[str, Any]:
    """
    Map a FusionPayload (or duck-typed fusion output) to snapshot column dict.

    Semantics:
      fused_move_prob_{hz}     := 1 - P(flat)  — mass on directional outcomes
      fused_dir_up_prob_{hz}   := P(up)        — aligns with prior pred_dir_up_prob_* role
      fused_confidence_{hz}    := fusion_confidence_score (0–1)
      fused_contributing_models_{hz} : JSON list string
      fused_stack_status_{hz}  : short audit string (availability + dominant direction)
    """
    pu = float(getattr(fusion, "prob_up", 1.0 / 3.0) or 0.0)
    pd_ = float(getattr(fusion, "prob_down", 1.0 / 3.0) or 0.0)
    pf = float(getattr(fusion, "prob_flat", 1.0 / 3.0) or 0.0)
    t = pu + pd_ + pf
    if t > 0:
        pu, pd_, pf = pu / t, pd_ / t, pf / t
    move_prob = max(0.0, min(1.0, 1.0 - pf))
    conf = float(getattr(fusion, "fusion_confidence_score", 0.0) or 0.0)
    conf = max(0.0, min(1.0, conf))
    cm = getattr(fusion, "contributing_models", None) or []
    try:
        cm_json = json.dumps(list(cm), separators=(",", ":"))[:8000]
    except (TypeError, ValueError):
        cm_json = "[]"
    avail = bool(getattr(fusion, "available", False))
    dom = str(getattr(fusion, "dominant_direction", "?") or "?")
    fconf = str(getattr(fusion, "fusion_confidence", "?") or "?")
    if avail:
        status = f"fusion_ok|dir={dom}|lbl={fconf}"
    else:
        summary = (getattr(fusion, "fusion_summary", None) or "")[:200]
        status = f"fusion_unavailable|{summary}"[:500]

    return {
        f"fused_move_prob_{hz}": move_prob,
        f"fused_dir_up_prob_{hz}": max(0.0, min(1.0, pu)),
        f"fused_confidence_{hz}": conf,
        f"fused_contributing_models_{hz}": cm_json,
        f"fused_stack_status_{hz}": status[:500],
    }


def policy_move_column(hz: str) -> str:
    return f"fused_move_prob_{hz}"


def policy_dir_up_column(hz: str) -> str:
    return f"fused_dir_up_prob_{hz}"
