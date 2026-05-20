"""

First-class runtime bundle: per-horizon Bayesian fusion outputs for **primary decision** horizons only.



Canonical data remains 1m-based; parallel model stacks run per **governed** horizon slug (all 7),

but only PRIMARY_DECISION_HORIZONS may appear in this bundle or influence policy.

"""

from __future__ import annotations



import logging

from dataclasses import dataclass, field

from typing import Any, Optional



from fusion_contract import fusion_is_authoritative
from ml_horizon import PRIMARY_DECISION_HORIZONS



log = logging.getLogger(__name__)



# Backward-compatible name: product horizons for MH fusion authority (primary only).

MH_PRODUCT_HORIZONS: tuple[str, ...] = PRIMARY_DECISION_HORIZONS





def _safe_norm_triplet(pu: float, pd: float, pf: float) -> tuple[float, float, float]:

    s = pu + pd + pf

    if s <= 0:

        t = 1.0 / 3.0

        return t, t, t

    return pu / s, pd / s, pf / s





@dataclass(frozen=True)

class HorizonMLFusionSnapshot:

    horizon_slug: str

    fusion_available: bool

    prob_up: float

    prob_down: float

    prob_flat: float

    dominant_direction: str

    top_probability: float

    fusion_confidence_label: str

    fusion_confidence_score: float

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



    def fusion_available(self, hz: str) -> bool:

        s = self.by_horizon.get(hz)

        return bool(s and s.fusion_available)





def fusion_payload_to_horizon_snapshot(hz: str, fus: Any) -> HorizonMLFusionSnapshot:

    if not fusion_is_authoritative(fus):

        t = 1.0 / 3.0

        return HorizonMLFusionSnapshot(

            horizon_slug=hz,

            fusion_available=False,

            prob_up=t,

            prob_down=t,

            prob_flat=t,

            dominant_direction="flat",

            top_probability=t,

            fusion_confidence_label="low",

            fusion_confidence_score=0.0,

            mc_available=False,

            contributing_models=(),

            missing_models=(),

            provenance="fusion_unavailable",

            horizon_tier="primary_decision",

        )

    pu = float(getattr(fus, "prob_up", 1.0 / 3.0))

    pd = float(getattr(fus, "prob_down", 1.0 / 3.0))

    pf = float(getattr(fus, "prob_flat", 1.0 / 3.0))

    pu, pd, pf = _safe_norm_triplet(pu, pd, pf)

    dom = str(getattr(fus, "dominant_direction", "flat") or "flat").strip().lower()

    if dom not in ("up", "down", "flat"):

        dom = "flat"

    vals = sorted([pu, pd, pf], reverse=True)

    top = float(vals[0])

    fcl = str(getattr(fus, "fusion_confidence", "low") or "low").strip().lower()

    if fcl not in ("low", "medium", "high"):

        fcl = "low"

    fcs = float(getattr(fus, "fusion_confidence_score", 0.0) or 0.0)

    cm = tuple(str(x) for x in (getattr(fus, "contributing_models", None) or []) if x)

    mm = tuple(str(x) for x in (getattr(fus, "missing_models", None) or []) if x)

    return HorizonMLFusionSnapshot(

        horizon_slug=hz,

        fusion_available=True,

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

        provenance="bayesian_fusion",

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

