"""
Unified stack layer outputs — structured xgb/lstm/transformer records for fusion and UI.

Each ML stack layer runs independently; outputs share this schema for the seven-layer team.
"""

from __future__ import annotations

from typing import Any, Optional, TypedDict


PARALLEL_STACK_SCHEMA_VERSION = "1"


class UnifiedStackLayerOutput(TypedDict, total=False):
    """Single unified-stack ML layer (xgb / lstm / transformer) output."""

    schema_version: str
    architecture: str  # always "parallel" for this path
    available: bool
    prob_up: Optional[float]
    prob_down: Optional[float]
    prob_flat: Optional[float]
    confidence_score: Optional[float]
    dominant: Optional[str]
    approved: bool
    metadata: dict[str, Any]
    error: str


def _normalize_triplet(probs: dict[str, Any]) -> Optional[tuple[float, float, float]]:
    u, d, f = probs.get("up"), probs.get("down"), probs.get("flat")
    if u is None or d is None or f is None:
        return None
    try:
        pu, pd, pf = float(u), float(d), float(f)
    except (TypeError, ValueError):
        return None
    t = pu + pd + pf
    if t <= 0:
        return None
    return pu / t, pd / t, pf / t


def empty_parallel_output(*, reason: str = "unavailable") -> UnifiedStackLayerOutput:
    return {
        "schema_version": PARALLEL_STACK_SCHEMA_VERSION,
        "architecture": "parallel",
        "available": False,
        "prob_up": None,
        "prob_down": None,
        "prob_flat": None,
        "confidence_score": None,
        "dominant": None,
        "approved": False,
        "metadata": {},
        "error": reason,
    }


def build_unified_stack_layer_output(
    *,
    probs: dict[str, float] | None,
    approved: bool,
    metadata: dict[str, Any] | None = None,
) -> UnifiedStackLayerOutput:
    if probs is None:
        o = empty_parallel_output(reason="no_prediction")
        if metadata:
            o["metadata"] = metadata
        return o
    tri = _normalize_triplet(probs)
    if tri is None:
        o = empty_parallel_output(reason="incomplete_triplet")
        if metadata:
            o["metadata"] = metadata
        return o
    pu, pd, pf = tri
    dom = max(("up", "down", "flat"), key=lambda c: {"up": pu, "down": pd, "flat": pf}[c])
    conf = round(max(pu, pd, pf) - (1.0 / 3.0), 4)
    return {
        "schema_version": PARALLEL_STACK_SCHEMA_VERSION,
        "architecture": "parallel",
        "available": True,
        "prob_up": round(pu, 4),
        "prob_down": round(pd, 4),
        "prob_flat": round(pf, 4),
        "confidence_score": conf,
        "dominant": dom,
        "approved": approved,
        "metadata": dict(metadata or {}),
    }


# Deprecated aliases — mechanical lock: new code must use canonical names above.
ParallelBaseModelOutput = UnifiedStackLayerOutput
build_parallel_base_output = build_unified_stack_layer_output
