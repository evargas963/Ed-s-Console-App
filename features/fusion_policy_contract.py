"""
Canonical fusion → policy DB columns (per governed ML horizon).

Movement-target XGB columns (pred_move_prob_*, pred_dir_* on snapshots) remain **legacy**
feature / training / comparison surfaces — not policy authority.

Policy calibration (Phase 8/9) and reliability gates read fused_* only.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fusion_contract import (
    fusion_direction_is_authorized,
    fusion_has_tradable_direction,
    fusion_is_authoritative,
)

# COH-I-G: contributing-models JSON column truncation guard.
# Max chars retained when serializing fusion.contributing_models for the snapshot column;
# replay layer must parse the (possibly-truncated) JSON tolerantly. Sized to fit the
# longest expected stack (xgb / lstm / transformer / meta + future cascade variants) with
# headroom for forward extension.
FUSION_CONTRIBUTING_MODELS_JSON_MAX_CHARS: int = 8000
# COH-I-G: stack-status string truncation guard. The status column is a short audit string;
# the cap exists to bound DB row width on degraded paths (fusion_unavailable with a long summary).
FUSION_STACK_STATUS_MAX_CHARS: int = 500


def _fusion_triplet(fusion: Any) -> Optional[tuple[float, float, float]]:
    """Normalized (up, down, flat) or None when fusion unavailable or probs incomplete."""
    if not fusion_has_tradable_direction(fusion):
        return None
    pu = getattr(fusion, "prob_up", None)
    pd_ = getattr(fusion, "prob_down", None)
    pf = getattr(fusion, "prob_flat", None)
    if pu is None or pd_ is None or pf is None:
        return None
    try:
        pu, pd_, pf = float(pu), float(pd_), float(pf)
    except (TypeError, ValueError):
        return None
    t = pu + pd_ + pf
    if t <= 0:
        return None
    return pu / t, pd_ / t, pf / t


def _stack_status(fusion: Any, *, avail: bool, dom: str, fconf: str) -> str:
    if avail:
        return f"fusion_ok|dir={dom}|lbl={fconf}"
    if fusion_is_authoritative(fusion):
        reason = (
            getattr(fusion, "stack_directional_authorization_reason", None)
            or "directional authorization absent"
        )
        return (
            f"fusion_directional_unauthorized|{reason}"
            [:FUSION_STACK_STATUS_MAX_CHARS]
        )
    summary = (getattr(fusion, "fusion_summary", None) or "")[:200]
    return f"fusion_unavailable|{summary}"[:FUSION_STACK_STATUS_MAX_CHARS]


def fusion_policy_columns_horizon_failed(hz: str, *, reason: str) -> dict[str, Any]:
    """Explicit NULL policy columns when per-horizon stack+fusion raised (replay discrimination)."""
    status = f"stack_failed|{reason}"[:FUSION_STACK_STATUS_MAX_CHARS]
    return {
        f"fused_move_prob_{hz}": None,
        f"fused_dir_up_prob_{hz}": None,
        f"fused_confidence_{hz}": None,
        f"fused_contributing_models_{hz}": None,
        f"fused_stack_status_{hz}": status,
    }


def fusion_payload_to_policy_columns(hz: str, fusion: Any) -> dict[str, Any]:
    """
    Map a FusionPayload (or duck-typed fusion output) to snapshot column dict.

    Semantics:
      fused_move_prob_{hz}     := 1 - P(flat)  — mass on directional outcomes
      fused_dir_up_prob_{hz}   := P(up)        — aligns with prior pred_dir_up_prob_* role
      fused_confidence_{hz}    := fusion_confidence_score (0–1)
      fused_contributing_models_{hz} : JSON list string
      fused_stack_status_{hz}  : short audit string (availability + dominant direction)

    When fusion is unavailable or directional probabilities are incomplete, probability
    columns are None (not fabricated from 1/3 placeholders or ``or 0.0`` coercion).
    """
    avail = fusion_has_tradable_direction(fusion)
    dom = str(getattr(fusion, "dominant_direction", "?") or "?") if fusion is not None else "?"
    fconf = str(getattr(fusion, "fusion_confidence", "?") or "?") if fusion is not None else "?"
    status = _stack_status(fusion, avail=avail, dom=dom, fconf=fconf)[:FUSION_STACK_STATUS_MAX_CHARS]

    tri = _fusion_triplet(fusion)
    if tri is None:
        cm_json: Optional[str] = None
        if fusion is not None and fusion_direction_is_authorized(fusion):
            cm = getattr(fusion, "contributing_models", None) or []
            try:
                cm_json = json.dumps(list(cm), separators=(",", ":"))[:FUSION_CONTRIBUTING_MODELS_JSON_MAX_CHARS]
            except (TypeError, ValueError):
                cm_json = "[]"
        return {
            f"fused_move_prob_{hz}": None,
            f"fused_dir_up_prob_{hz}": None,
            f"fused_confidence_{hz}": None,
            f"fused_contributing_models_{hz}": cm_json,
            f"fused_stack_status_{hz}": status,
        }

    pu, pd_, pf = tri
    move_prob = max(0.0, min(1.0, 1.0 - pf))
    conf_raw = getattr(fusion, "fusion_confidence_score", None)
    conf: Optional[float] = None
    if conf_raw is not None:
        try:
            conf = max(0.0, min(1.0, float(conf_raw)))
        except (TypeError, ValueError):
            conf = None
    cm = getattr(fusion, "contributing_models", None) or []
    try:
        cm_json = json.dumps(list(cm), separators=(",", ":"))[:FUSION_CONTRIBUTING_MODELS_JSON_MAX_CHARS]
    except (TypeError, ValueError):
        cm_json = "[]"

    return {
        f"fused_move_prob_{hz}": move_prob,
        f"fused_dir_up_prob_{hz}": max(0.0, min(1.0, pu)),
        f"fused_confidence_{hz}": conf,
        f"fused_contributing_models_{hz}": cm_json,
        f"fused_stack_status_{hz}": status,
    }


def policy_move_column(hz: str) -> str:
    return f"fused_move_prob_{hz}"


def policy_dir_up_column(hz: str) -> str:
    return f"fused_dir_up_prob_{hz}"
