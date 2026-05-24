"""
First-class runtime bundle: per-horizon Bayesian fusion outputs for **primary decision** horizons only.

Canonical data remains 1m-based; parallel model stacks run per **governed** horizon slug (all 7),
but only PRIMARY_DECISION_HORIZONS may appear in this bundle or influence policy.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Optional

from fusion_contract import fusion_is_authoritative
from ml_horizon import PRIMARY_DECISION_HORIZONS
from numeric_contract import direction_from_normalized_triplet, float_finite_or_none

log = logging.getLogger(__name__)

# Backward-compatible name: product horizons for MH fusion authority (primary only).
MH_PRODUCT_HORIZONS: tuple[str, ...] = PRIMARY_DECISION_HORIZONS

_RENORM_SUM_EPS = 0.01


def _unavailable_horizon_snapshot(hz: str, *, provenance: str) -> HorizonMLFusionSnapshot:
    t = 1.0 / 3.0
    return HorizonMLFusionSnapshot(
        horizon_slug=hz,
        horizon_fusion_available=False,
        prob_up=t,
        prob_down=t,
        prob_flat=t,
        dominant_direction="flat",
        top_probability=t,
        fusion_confidence_label="low",
        fusion_confidence_score=None,
        mc_available=False,
        contributing_models=(),
        missing_models=(),
        provenance=provenance,
        horizon_tier="primary_decision",
    )


def _safe_norm_triplet(
    pu: float, pd: float, pf: float
) -> tuple[float, float, float, str]:
    """Normalize finite triplet; return provenance tag when upstream sum drifts from 1."""
    s = pu + pd + pf
    if s <= 0 or not math.isfinite(s):
        t = 1.0 / 3.0
        return t, t, t, "bayesian_fusion"
    prov = "bayesian_fusion"
    if abs(s - 1.0) > _RENORM_SUM_EPS:
        log.debug(
            "multi_horizon_ml_fusion_bundle: renormalized fusion triplet raw_sum=%s",
            s,
        )
        prov = "bayesian_fusion_renormalized"
    return pu / s, pd / s, pf / s, prov


@dataclass(frozen=True)
class HorizonMLFusionSnapshot:
    horizon_slug: str
    horizon_fusion_available: bool
    prob_up: float
    prob_down: float
    prob_flat: float
    dominant_direction: str
    top_probability: float
    fusion_confidence_label: str
    fusion_confidence_score: float | None
    mc_available: bool
    contributing_models: tuple[str, ...] = field(default_factory=tuple)
    missing_models: tuple[str, ...] = field(default_factory=tuple)
    provenance: str = "bayesian_fusion"
    # Always "primary_decision" for rows in MultiHorizonMLFusionBundle (secondary never admitted).
    horizon_tier: str = "primary_decision"


@dataclass
class MultiHorizonMLFusionBundle:
    by_horizon: dict[str, HorizonMLFusionSnapshot]
    live_canonical_horizon_slug: str

    def snapshot(self, hz: str) -> Optional[HorizonMLFusionSnapshot]:
        return self.by_horizon.get(hz)

    def horizon_fusion_available(self, hz: str) -> bool:
        s = self.by_horizon.get(hz)
        return bool(s and s.horizon_fusion_available)


def fusion_payload_to_horizon_snapshot(hz: str, fus: Any) -> HorizonMLFusionSnapshot:
    if not fusion_is_authoritative(fus):
        return _unavailable_horizon_snapshot(hz, provenance="fusion_unavailable")

    pu = float_finite_or_none(getattr(fus, "prob_up", None))
    pd = float_finite_or_none(getattr(fus, "prob_down", None))
    pf = float_finite_or_none(getattr(fus, "prob_flat", None))
    if pu is None or pd is None or pf is None:
        return _unavailable_horizon_snapshot(
            hz, provenance="fusion_unavailable_non_finite_probs"
        )

    pu, pd, pf, prov = _safe_norm_triplet(pu, pd, pf)
    dom = direction_from_normalized_triplet(pu, pd, pf)
    vals = sorted([pu, pd, pf], reverse=True)
    top = float(vals[0])
    fcl = str(getattr(fus, "fusion_confidence", "low") or "low").strip().lower()
    if fcl not in ("low", "medium", "high"):
        fcl = "low"
    fcs = float_finite_or_none(getattr(fus, "fusion_confidence_score", None))
    cm = tuple(str(x) for x in (getattr(fus, "contributing_models", None) or []) if x)
    mm = tuple(str(x) for x in (getattr(fus, "missing_models", None) or []) if x)
    return HorizonMLFusionSnapshot(
        horizon_slug=hz,
        horizon_fusion_available=True,
        prob_up=pu,
        prob_down=pd,
        prob_flat=pf,
        dominant_direction=dom,
        top_probability=top,
        fusion_confidence_label=fcl,
        fusion_confidence_score=fcs,
        mc_available=bool(getattr(fus, "mc_available", False)),
        contributing_models=cm,
        missing_models=mm,
        provenance=prov,
        horizon_tier="primary_decision",
    )


def build_multi_horizon_ml_fusion_bundle(
    fusion_by_hz: dict[str, Any],
    *,
    live_canonical_horizon_slug: str,
) -> MultiHorizonMLFusionBundle:
    """Build authoritative bundle from **primary decision** horizons only; secondary keys ignored."""
    extras = set(fusion_by_hz) - set(PRIMARY_DECISION_HORIZONS)
    if extras:
        log.debug(
            "multi_horizon_ml_fusion_bundle: ignoring non-primary fusion_by_hz keys %s",
            sorted(extras),
        )
    by_h: dict[str, HorizonMLFusionSnapshot] = {}
    for hz in PRIMARY_DECISION_HORIZONS:
        by_h[hz] = fusion_payload_to_horizon_snapshot(hz, fusion_by_hz.get(hz))
    bundle = MultiHorizonMLFusionBundle(
        by_horizon=by_h,
        live_canonical_horizon_slug=live_canonical_horizon_slug,
    )
    if set(bundle.by_horizon.keys()) != set(PRIMARY_DECISION_HORIZONS):
        raise RuntimeError(
            "multi_horizon_ml_fusion_bundle: incomplete primary horizons "
            f"missing={sorted(set(PRIMARY_DECISION_HORIZONS) - set(bundle.by_horizon))!r}"
        )
    for _snap in bundle.by_horizon.values():
        if getattr(_snap, "horizon_tier", None) != "primary_decision":
            raise RuntimeError(
                f"multi_horizon_ml_fusion_bundle: unexpected tier {getattr(_snap, 'horizon_tier', None)!r}"
            )
    return bundle
