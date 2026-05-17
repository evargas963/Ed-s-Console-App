"""
Post-fusion Monte Carlo context: normalize path-level MC features and apply a
bounded adjustment to directional probabilities AFTER base Bayesian fusion.

Monte Carlo is not a probability model here; it only modulates confidence / flat
mass / small directional nudge without changing the base fusion argmax.
"""
from __future__ import annotations

import logging
import math
from dataclasses import replace
from typing import Any, Mapping, Optional, Tuple

log = logging.getLogger(__name__)


def normalize_mc(mc_output: Mapping[str, Any], spot_price: float) -> Optional[dict[str, float]]:
    """
    Map raw MC feature outputs to bounded, scale-normalized inputs for adjustment.

    Returns None when any required feature is missing (fail-closed — no fabricated zeros).
    """
    _em = mc_output.get("expected_move")
    _vol = mc_output.get("volatility")
    _sk = mc_output.get("skew")
    _tr = mc_output.get("tail_risk")
    _b = mc_output.get("directional_bias")
    if any(v is None for v in (_em, _vol, _sk, _tr, _b)):
        return None

    try:
        em = float(_em)
        vol = float(_vol)
        sk = float(_sk)
        tr = float(_tr)
        b = float(_b)
    except (TypeError, ValueError):
        return None
    if any(not math.isfinite(x) for x in (em, vol, sk, tr, b)):
        return None

    sp = float(spot_price) if spot_price is not None else 0.0
    if sp <= 0 or not math.isfinite(sp):
        return None

    return {
        "mc_expected_move": em / sp,
        "mc_volatility": vol / sp,
        "mc_skew": max(-3.0, min(3.0, sk)),
        "mc_tail_risk": max(0.0, min(1.0, tr)),
        "mc_bias": max(-1.0, min(1.0, b)),
    }


def _triplet(p: Tuple[float, float, float]) -> Tuple[float, float, float]:
    u, d, f = float(p[0]), float(p[1]), float(p[2])
    t = u + d + f
    if t <= 0 or not math.isfinite(t):
        return (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)
    return u / t, d / t, f / t


def _argmax_dir(u: float, d: float, f: float) -> str:
    return max("up", "down", "flat", key=lambda lab: {"up": u, "down": d, "flat": f}[lab])


def _blend_uniform(u0: float, d0: float, f0: float, lam: float) -> Tuple[float, float, float]:
    return _triplet(
        (
            (1.0 - lam) * u0 + lam / 3.0,
            (1.0 - lam) * d0 + lam / 3.0,
            (1.0 - lam) * f0 + lam / 3.0,
        )
    )


def _max_uniform_blend_preserving_argmax(
    u0: float, d0: float, f0: float, winner: str, max_lam: float
) -> float:
    """Largest lam in [0, max_lam] such that _blend_uniform keeps the same argmax as winner."""
    if max_lam <= 0:
        return 0.0
    lo, hi = 0.0, max_lam
    best = 0.0
    for _ in range(22):
        mid = 0.5 * (lo + hi)
        u, d, f = _blend_uniform(u0, d0, f0, mid)
        if _argmax_dir(u, d, f) == winner:
            best = mid
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-7:
            break
    return best


def _add_to_flat_from_others(
    u: float, d: float, f: float, winner: str, delta: float
) -> Tuple[float, float, float]:
    """Increase flat by up to delta mass taken from non-winner classes first."""
    if delta <= 1e-15:
        return u, d, f
    rem = delta
    pu, pd, pf = float(u), float(d), float(f)
    u0, d0, f0 = pu, pd, pf

    def pool_order() -> list[str]:
        if winner == "up":
            return ["d", "f", "u"]
        if winner == "down":
            return ["u", "f", "d"]
        return ["u", "d"]

    for lab in pool_order():
        if rem <= 1e-15:
            break
        if lab == "u":
            take = min(rem, max(0.0, pu) * 0.95)
            pu -= take
            rem -= take
        elif lab == "d":
            take = min(rem, max(0.0, pd) * 0.95)
            pd -= take
            rem -= take
        else:
            take = min(rem, max(0.0, pf) * 0.95)
            pf -= take
            rem -= take
    drained = (u0 - pu) + (d0 - pd) + (f0 - pf)
    pf = pf + drained
    return _triplet((pu, pd, pf))


def _max_tail_flat_delta(u: float, d: float, f: float, winner: str, cap: float) -> float:
    """Binary-search max delta in [0, cap] so _add_to_flat_from_others preserves argmax."""
    if cap <= 0:
        return 0.0
    lo, hi = 0.0, cap
    best = 0.0
    for _ in range(22):
        mid = 0.5 * (lo + hi)
        nu, nd, nf = _add_to_flat_from_others(u, d, f, winner, mid)
        if _argmax_dir(nu, nd, nf) == winner:
            best = mid
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-7:
            break
    return best


def _apply_directional_bias(
    u: float, d: float, f: float, winner: str, bias: float, max_shift: float
) -> Tuple[float, float, float]:
    """Move at most max_shift total mass toward up (bias>0) or down (bias<0) without changing argmax."""
    if abs(bias) < 1e-12 or max_shift <= 1e-12:
        return u, d, f
    shift = min(max_shift, abs(bias) * max_shift)
    pu, pd, pf = float(u), float(d), float(f)
    if bias > 0:
        need = shift
        take_d = min(need, pd * 0.9)
        pd -= take_d
        need -= take_d
        take_f = min(need, pf * 0.9)
        pf -= take_f
        need -= take_f
        pu += shift - need
    else:
        need = shift
        take_u = min(need, pu * 0.9)
        pu -= take_u
        need -= take_u
        take_f = min(need, pf * 0.9)
        pf -= take_f
        need -= take_f
        pd += shift - need
    u2, d2, f2 = _triplet((pu, pd, pf))
    if _argmax_dir(u2, d2, f2) != winner:
        log.debug("apply_mc_adjustment: bias step would flip argmax; skipping bias")
        return u, d, f
    return u2, d2, f2


def apply_mc_adjustment(
    probs: Tuple[float, float, float],
    mc_features: Mapping[str, float],
) -> Tuple[float, float, float]:
    """
    Adjust (prob_up, prob_down, prob_flat) using normalized MC context.

    Rules:
    - High volatility: blend toward uniform up to a searched cap (reduces confidence, preserves argmax).
    - Tail risk: add mass to flat by drawing from non-winner buckets (searched cap, preserves argmax).
    - Directional bias: move at most 5% total mass toward up or down if argmax stays the base winner.
    - Output sums to 1; values in [0,1]. On any invariant violation, revert to base (with warning).
    """
    u0, d0, f0 = _triplet(probs)
    base_winner = _argmax_dir(u0, d0, f0)

    if any(mc_features.get(k) is None for k in ("mc_volatility", "mc_tail_risk", "mc_bias")):
        log.debug("apply_mc_adjustment: missing MC feature(s); no adjustment")
        return u0, d0, f0
    vol = float(mc_features["mc_volatility"])
    tail = float(mc_features["mc_tail_risk"])
    bias = float(mc_features["mc_bias"])

    max_lam = min(0.22, 0.14 * max(0.0, vol))
    lam = _max_uniform_blend_preserving_argmax(u0, d0, f0, base_winner, max_lam)
    u, d, f = _blend_uniform(u0, d0, f0, lam)

    tail_cap = min(0.18, 0.10 * max(0.0, tail) + 0.06 * max(0.0, tail) * max(0.0, vol))
    d_tail = _max_tail_flat_delta(u, d, f, base_winner, tail_cap)
    u, d, f = _add_to_flat_from_others(u, d, f, base_winner, d_tail)

    u, d, f = _apply_directional_bias(u, d, f, base_winner, bias, max_shift=0.05)

    u = max(0.0, min(1.0, u))
    d = max(0.0, min(1.0, d))
    f = max(0.0, min(1.0, f))
    s = u + d + f
    if s <= 0 or not math.isfinite(s):
        log.warning("apply_mc_adjustment: invalid sum after adjustment; reverting to base")
        return u0, d0, f0
    u, d, f = u / s, d / s, f / s

    if _argmax_dir(u, d, f) != base_winner:
        log.warning("apply_mc_adjustment: post-adjustment argmax mismatch; reverting to base fusion triplet")
        return u0, d0, f0

    if abs((u + d + f) - 1.0) > 1e-6:
        u, d, f = _triplet((u, d, f))

    return u, d, f


def fuse_payload_apply_mc_adjustment(fusion: Any, mc_out: Any, spot_price: Optional[float]) -> Any:
    """
    If MC is available and fusion is live, apply post-fusion MC adjustment in-place
    on a FusionPayload-like object (dataclass replace).
    """
    if fusion is None or not getattr(fusion, "available", False):
        return fusion
    if not getattr(mc_out, "available", False):
        return fusion
    sp = float(spot_price) if spot_price is not None and float(spot_price) > 0 else 0.0
    if sp <= 0:
        return fusion

    pu0 = getattr(fusion, "prob_up", None)
    pd0 = getattr(fusion, "prob_down", None)
    pf0 = getattr(fusion, "prob_flat", None)
    if pu0 is None or pd0 is None or pf0 is None:
        return fusion

    fd = getattr(mc_out, "mc_feature_dict", None)
    raw_in: Mapping[str, Any] = fd() if callable(fd) else {}
    raw = dict(raw_in) if isinstance(raw_in, dict) else {}
    mc_bundle_source = raw.pop("source", None)

    mc_n = normalize_mc(raw, sp)
    if mc_n is None:
        return fusion

    pre = (float(pu0), float(pd0), float(pf0))
    u, d, fl = apply_mc_adjustment(pre, mc_n)
    audit = {
        "pre_triplet": {"up": round(pre[0], 6), "down": round(pre[1], 6), "flat": round(pre[2], 6)},
        "post_triplet": {"up": round(u, 6), "down": round(d, 6), "flat": round(fl, 6)},
        "normalized_mc": {k: round(float(v), 6) for k, v in mc_n.items()},
        "base_argmax": _argmax_dir(*pre),
        "final_argmax": _argmax_dir(u, d, fl),
        "mc_feature_source": mc_bundle_source or "derived_mc_normalized",
    }
    try:
        return replace(
            fusion,
            prob_up=round(u, 6),
            prob_down=round(d, 6),
            prob_flat=round(fl, 6),
            mc_post_fusion_audit=audit,
        )
    except TypeError:
        setattr(fusion, "prob_up", round(u, 6))
        setattr(fusion, "prob_down", round(d, 6))
        setattr(fusion, "prob_flat", round(fl, 6))
        setattr(fusion, "mc_post_fusion_audit", audit)
        return fusion
