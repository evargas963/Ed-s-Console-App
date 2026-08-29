"""
First-class runtime bundle: per-horizon Bayesian fusion outputs for **primary decision** horizons only.

Canonical data remains 1m-based; parallel model stacks run per **governed** horizon slug (all 7),
but only PRIMARY_DECISION_HORIZONS may appear in this bundle or influence policy.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from fusion_contract import fusion_direction_is_authorized, fusion_is_authoritative
from ml_horizon import PRIMARY_DECISION_HORIZONS
from numeric_contract import direction_from_normalized_triplet, float_finite_or_none

log = logging.getLogger(__name__)

# Backward-compatible name: product horizons for MH fusion authority (primary only).
MH_PRODUCT_HORIZONS: tuple[str, ...] = PRIMARY_DECISION_HORIZONS

_RENORM_SUM_EPS = 0.01

# ── Fusion temperature calibration (operator 2026-06-10) ────────────────────────
# One door: calibration applies HERE, on the per-horizon fusion triplet, and nowhere
# else in the stack. The artifact only exists after the operator runs
# `python -m calibration.fusion_temperature`; absent/invalid artifact = identity
# (fail-closed, no env flag). prob_*_raw is preserved on every snapshot so refits
# always fit on raw probabilities (no calibrate-the-calibrated feedback loop).
_calibration_cache: dict[str, Any] = {"mtime": None, "temps": {}}


def _applied_fusion_temperatures() -> dict[str, float]:
    """mtime-cached per-horizon temperatures from the calibration artifact."""
    from calibration.fusion_temperature import DEFAULT_ARTIFACT_PATH, load_applied_temperatures

    try:
        mtime = os.path.getmtime(DEFAULT_ARTIFACT_PATH)
    except OSError:
        _calibration_cache["mtime"] = None
        _calibration_cache["temps"] = {}
        return {}
    if _calibration_cache["mtime"] != mtime:
        _calibration_cache["temps"] = load_applied_temperatures(DEFAULT_ARTIFACT_PATH)
        _calibration_cache["mtime"] = mtime
        if _calibration_cache["temps"]:
            log.info(
                "fusion temperature calibration active: %s", _calibration_cache["temps"]
            )
    return _calibration_cache["temps"]


def fusion_calibration_status() -> dict[str, Any]:
    """Host-visible calibration provenance (ticker-agnostic lock, 2026-07-06).

    The temperature artifact is host-local (models/** is gitignored), so a
    production host could silently serve raw probabilities if the artifact was
    never fitted there. This accessor exposes the loader state for the payload
    diagnostic block: artifact_loaded=False + applied_horizons=[] IS the
    fail-closed raw-serving state, made observable instead of silent.
    Horizon-keyed only — there is no per-ticker calibration surface.
    """
    temps = _applied_fusion_temperatures()
    return {
        "artifact_loaded": bool(temps),
        "applied_horizons": sorted(temps.keys()),
        "applied_temperatures": {k: float(v) for k, v in sorted(temps.items())},
        "keying": "horizon_only",
    }


def _unavailable_horizon_snapshot(
    hz: str,
    *,
    provenance: str,
    authorization_reason: str | None = None,
) -> HorizonMLFusionSnapshot:
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
        stack_directional_authorized=False,
        stack_directional_authorization_reason=authorization_reason,
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
    # The producer verdict for this exact horizon. Never reconstructed from availability/probs.
    stack_directional_authorized: bool = False
    stack_directional_authorization_reason: str | None = None
    # Always "primary_decision" for rows in MultiHorizonMLFusionBundle (secondary never admitted).
    horizon_tier: str = "primary_decision"
    # Raw (pre-calibration) triplet — logged alongside the served triplet so the
    # temperature fitter always trains on raw probabilities. None = no calibration ran.
    prob_up_raw: float | None = None
    prob_down_raw: float | None = None
    prob_flat_raw: float | None = None
    # "none" or "temperature:<T>" — operator-legible provenance of the served triplet.
    calibration: str = "none"


@dataclass
class MultiHorizonMLFusionBundle:
    by_horizon: dict[str, HorizonMLFusionSnapshot]
    live_canonical_horizon_slug: str

    def snapshot(self, hz: str) -> Optional[HorizonMLFusionSnapshot]:
        return self.by_horizon.get(hz)

    def horizon_fusion_available(self, hz: str) -> bool:
        s = self.by_horizon.get(hz)
        return bool(s and s.horizon_fusion_available)

    def directional_authorization_map(self) -> dict[str, bool]:
        return {
            hz: bool(s.stack_directional_authorized)
            for hz, s in self.by_horizon.items()
        }

    def directional_authorization_reason_map(self) -> dict[str, str | None]:
        return {
            hz: s.stack_directional_authorization_reason
            for hz, s in self.by_horizon.items()
        }

    def fusion_availability_map(self) -> dict[str, bool]:
        return {
            hz: bool(s.horizon_fusion_available)
            for hz, s in self.by_horizon.items()
        }


def fusion_payload_to_horizon_snapshot(hz: str, fus: Any) -> HorizonMLFusionSnapshot:
    if not fusion_is_authoritative(fus):
        return _unavailable_horizon_snapshot(hz, provenance="fusion_unavailable")
    if not fusion_direction_is_authorized(fus):
        return _unavailable_horizon_snapshot(
            hz,
            provenance="fusion_directional_unauthorized",
            authorization_reason=getattr(
                fus, "stack_directional_authorization_reason", None
            ),
        )

    pu = float_finite_or_none(getattr(fus, "prob_up", None))
    pd = float_finite_or_none(getattr(fus, "prob_down", None))
    pf = float_finite_or_none(getattr(fus, "prob_flat", None))
    if pu is None or pd is None or pf is None:
        return _unavailable_horizon_snapshot(
            hz, provenance="fusion_unavailable_non_finite_probs"
        )

    pu, pd, pf, prov = _safe_norm_triplet(pu, pd, pf)
    pu_raw, pd_raw, pf_raw = pu, pd, pf
    calibration = "none"
    temp = _applied_fusion_temperatures().get(hz)
    if temp is not None:
        from calibration.fusion_temperature import apply_temperature

        pu, pd, pf = apply_temperature(pu, pd, pf, temp)
        calibration = f"temperature:{temp}"
        prov = f"{prov}+temperature_calibrated"
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
        stack_directional_authorized=True,
        stack_directional_authorization_reason=getattr(
            fus, "stack_directional_authorization_reason", None
        ),
        prob_up_raw=pu_raw,
        prob_down_raw=pd_raw,
        prob_flat_raw=pf_raw,
        calibration=calibration,
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
