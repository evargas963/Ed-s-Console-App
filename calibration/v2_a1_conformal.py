"""Build A1 conformal probability-band artifacts for v2 Pilot 1B.

Scope is intentionally training/evaluation-time only: the scaffold wraps an
existing A1 isotonic calibration artifact, reports approximate-guarantee
diagnostics, and leaves runtime v2 adapter fields unchanged.

When no separate evaluation rows are supplied, empirical coverage is measured
on the same holdout rows used to fit the conformal quantile. That diagnostic is
useful for scaffolding but can be optimistic; honest out-of-sample evaluation
requires a separate post-fit set before any runtime promotion.
"""

from __future__ import annotations

from typing import Any


A1_CONFORMAL_METHOD = "split_conformal_probability_band"




def apply_a1_conformal_interval(interval_model: dict[str, Any], calibrated_probability: float) -> tuple[float, float]:
    """Apply a conformal probability band model to one calibrated probability."""
    if not interval_model or interval_model.get("type") != A1_CONFORMAL_METHOD:
        raise ValueError("invalid A1 conformal interval model")
    q = float(interval_model["score_quantile"])
    p = _bounded_probability(calibrated_probability)
    return round(max(0.0, p - q), 6), round(min(1.0, p + q), 6)


















def _bounded_probability(value: float) -> float:
    return min(1.0, max(0.0, float(value)))






