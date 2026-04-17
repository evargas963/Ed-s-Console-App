"""
Parallel stack runtime — structured model outputs (production architecture).

All base models run independently; outputs share this schema for fusion and UI.
"""

from __future__ import annotations

from typing import Any, TypedDict


PARALLEL_STACK_SCHEMA_VERSION = "1"


class ParallelBaseModelOutput(TypedDict, total=False):
    """Single base model (XGB / LSTM / Transformer) output for parallel runtime."""

    schema_version: str
    architecture: str  # always "parallel" for this path
    available: bool
    prob_up: float
    prob_down: float
    prob_flat: float
    confidence_score: float
    dominant: str
    approved: bool
    metadata: dict[str, Any]
    error: str


def empty_parallel_output(*, reason: str = "unavailable") -> ParallelBaseModelOutput:
    return {
        "schema_version": PARALLEL_STACK_SCHEMA_VERSION,
        "architecture": "parallel",
        "available": False,
        "prob_up": 0.33,
        "prob_down": 0.33,
        "prob_flat": 0.34,
        "confidence_score": 0.0,
        "dominant": "flat",
        "approved": False,
        "metadata": {},
        "error": reason,
    }


def build_parallel_base_output(
    *,
    probs: dict[str, float] | None,
    approved: bool,
    metadata: dict[str, Any] | None = None,
) -> ParallelBaseModelOutput:
    if probs is None:
        o = empty_parallel_output(reason="no_prediction")
        if metadata:
            o["metadata"] = metadata
        return o
    up = float(probs.get("up", 0.333))
    down = float(probs.get("down", 0.333))
    flat = float(probs.get("flat", 0.334))
    dom = max(("up", "down", "flat"), key=lambda c: probs.get(c, 0.0))
    conf = round(float(probs.get(dom, 0.333)) - 0.333, 4)
    return {
        "schema_version": PARALLEL_STACK_SCHEMA_VERSION,
        "architecture": "parallel",
        "available": True,
        "prob_up": round(up, 4),
        "prob_down": round(down, 4),
        "prob_flat": round(flat, 4),
        "confidence_score": conf,
        "dominant": dom,
        "approved": approved,
        "metadata": dict(metadata or {}),
    }
