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

from fusion_contract import fusion_direction_is_authorized


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





def _triplet(p: Tuple[float, float, float]) -> Optional[Tuple[float, float, float]]:

    u, d, f = float(p[0]), float(p[1]), float(p[2])

    if not all(math.isfinite(x) for x in (u, d, f)):

        return None

    t = u + d + f

    if t <= 0 or not math.isfinite(t):

        return None

    return u / t, d / t, f / t





def _argmax_dir(u: float, d: float, f: float) -> str:
    from numeric_contract import direction_from_normalized_triplet

    return direction_from_normalized_triplet(u, d, f)





def _blend_uniform(u0: float, d0: float, f0: float, lam: float) -> Tuple[float, float, float]:

    tri = _triplet(

        (

            (1.0 - lam) * u0 + lam / 3.0,

            (1.0 - lam) * d0 + lam / 3.0,

            (1.0 - lam) * f0 + lam / 3.0,

        )

    )

    if tri is None:

        return u0, d0, f0

    return tri





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

    tri = _triplet((pu, pd, pf))

    if tri is None:

        return u, d, f

    return tri





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

    tri = _triplet((pu, pd, pf))

    if tri is None:

        log.debug("apply_mc_adjustment: bias step degenerate triplet; skipping bias")

        return u, d, f

    u2, d2, f2 = tri

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

    norm = _triplet(probs)

    if norm is None:

        log.debug("apply_mc_adjustment: degenerate input triplet; no adjustment")

        return probs

    u0, d0, f0 = norm

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

        renorm = _triplet((u, d, f))

        if renorm is not None:

            u, d, f = renorm



    return u, d, f





def fuse_payload_apply_mc_adjustment(fusion: Any, mc_out: Any, spot_price: Optional[float]) -> Any:

    """

    If MC is available and fusion is live, apply post-fusion MC adjustment in-place

    on a FusionPayload-like object (dataclass replace).

    """

    # Setup fusion availability is not directional authority. MC may only soften a triplet whose
    # approved runtime computation was authorized by the producer.
    if not fusion_direction_is_authorized(fusion):

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



    pu_f, pd_f, pf_f = float(pu0), float(pd0), float(pf0)

    if not all(math.isfinite(x) for x in (pu_f, pd_f, pf_f)):

        log.debug("fuse_payload_apply_mc_adjustment: non-finite fusion triplet; skip MC adjust")

        return fusion

    if pu_f + pd_f + pf_f <= 0:

        log.debug("fuse_payload_apply_mc_adjustment: degenerate fusion triplet sum; skip MC adjust")

        return fusion



    fd = getattr(mc_out, "mc_feature_dict", None)

    raw_in: Mapping[str, Any] = fd() if callable(fd) else {}

    raw = dict(raw_in) if isinstance(raw_in, dict) else {}

    mc_bundle_source = raw.pop("source", None)



    mc_n = normalize_mc(raw, sp)

    if mc_n is None:

        return fusion



    pre = (pu_f, pd_f, pf_f)

    u, d, fl = apply_mc_adjustment(pre, mc_n)

    # ── MC IS ONE-WAY: it may soften an authorized opportunity, never manufacture conviction ──
    # Preserving argmax is NOT sufficient. Multi-horizon tradeability reads TWO scalars —
    # multi_horizon_decision.py:863-864, `dom >= TRADEABLE_DOM_MIN` and
    # `margin >= TRADEABLE_MARGIN_MIN` — so an adjustment that keeps the winner while RAISING the
    # dominant probability or WIDENING the margin can carry a non-tradeable state across .38/.03
    # and make it tradeable. That is MC creating predictive authority, which it must never do.
    # This is a monotonicity constraint on exactly the two quantities that gate reads. It is not a
    # second argmax guard (the existing one below is untouched) and it neither reads nor tunes the
    # thresholds. It matches the engine's own written policy, multi_horizon_decision.py:5 —
    # "downgrades/blocks are allowed; synthetic conviction is not."
    # WHY A CAP AND NOT A VETO. The first version of this guard DISCARDED the whole adjustment
    # whenever either scalar rose. That was wrong in both directions, measured on this tree:
    #   * It BLOCKED genuine downgrades. Over 20,775 exact-sum-1 triplets driven by the real
    #     feature keys (mc_volatility / mc_tail_risk / mc_bias), 73.7% of adjustments were
    #     discarded and 211 (1.02%) of those discards RESTORED tradeability that MC had removed —
    #     e.g. pre=(0.25,0.39,0.36) (dom .39, margin .03 => tradeable) softened by MC to
    #     (0.2301,0.3999,0.3700) (margin .0299 => WAIT) was thrown away because dominance rose,
    #     so the tradeable original was stored. That is the veto manufacturing conviction.
    #   * Its comparison was not like-for-like. `pre` comes from bayesian_fusion, which rounds each
    #     leg to 3dp INDEPENDENTLY, so it often sums to 0.999/1.001, while apply_mc_adjustment
    #     normalises. A completely NEUTRAL MC then "raised" dominance: pre=(0.298,0.325,0.376)
    #     -> post=(0.298298,0.325325,0.376376). Worse, reverting stored the un-normalised tuple,
    #     which line ~616 renormalises anyway — so the STORED dominance (0.376376) exceeded pre's
    #     (0.376000) and the veto violated its own invariant on the value actually written.
    #
    # The cap blends the adjusted triplet toward uniform by the SMALLEST lambda that restores both
    # ceilings. Blending toward uniform is the engine's own softening primitive: it preserves
    # argmax and moves dominance and margin monotonically DOWN, so lambda solves in closed form.
    # When the adjustment is already no more authoritative than pre, lambda is exactly 0 and the
    # adjustment passes through untouched — a softening can never be reverted.
    #
    # Admission safety is preserved and is now provable: multi_horizon tradeability is
    # `dom >= TRADEABLE_DOM_MIN AND margin >= TRADEABLE_MARGIN_MIN`. Since post <= pre on BOTH
    # scalars, post admissible implies pre admissible — MC can never carry an inadmissible state
    # across. No threshold is read or tuned here.
    _pre_n = _triplet(pre) or pre
    _pre_sorted = sorted(_pre_n, reverse=True)
    _post_sorted = sorted((u, d, fl), reverse=True)
    _pre_dom, _pre_margin = _pre_sorted[0], _pre_sorted[0] - _pre_sorted[1]
    _post_dom, _post_margin = _post_sorted[0], _post_sorted[0] - _post_sorted[1]
    _third = 1.0 / 3.0
    _lam = 0.0
    if _post_margin > _pre_margin and _post_margin > 0.0:
        _lam = max(_lam, 1.0 - (_pre_margin / _post_margin))
    if _post_dom > _pre_dom and _post_dom > _third:
        _lam = max(_lam, 1.0 - ((_pre_dom - _third) / (_post_dom - _third)))
    _lam = min(1.0, max(0.0, _lam))
    _mc_authority_capped = _lam > 0.0
    if _mc_authority_capped:
        u = (1.0 - _lam) * u + _lam * _third
        d = (1.0 - _lam) * d + _lam * _third
        fl = (1.0 - _lam) * fl + _lam * _third

        # Closed-form lambda is exact over real numbers, but the downstream gate compares binary
        # floats with hard >= thresholds. A mathematically equal margin can therefore move from
        # 0.02999999999999997 to 0.030000000000000027 and manufacture tradeability. Add the
        # smallest practical uniform softening only when float arithmetic leaves such a residue.
        # This is threshold-independent and preserves every non-residual downgrade.
        _strict_soften = 1e-12
        for _ in range(8):
            _cap_sorted = sorted((u, d, fl), reverse=True)
            if (
                _cap_sorted[0] <= _pre_dom
                and (_cap_sorted[0] - _cap_sorted[1]) <= _pre_margin
            ):
                break
            u = (1.0 - _strict_soften) * u + _strict_soften * _third
            d = (1.0 - _strict_soften) * d + _strict_soften * _third
            fl = (1.0 - _strict_soften) * fl + _strict_soften * _third
            _lam = 1.0 - (1.0 - _lam) * (1.0 - _strict_soften)
            _strict_soften *= 10.0

    final_winner = _argmax_dir(u, d, fl)

    # Round for storage, then renormalize so stored legs sum to exactly 1.0.
    # Fail-closed on TWO invariants: rounding may flip argmax, and rounding-then-renormalising can
    # nudge dominance/margin back UP past the cap (measured max +9.75e-07 across 20,775 triplets,
    # e.g. pre=(0.985,0.005,0.01) margin 0.975000 -> stored 0.975001). Both are rejected here, so
    # the value actually WRITTEN carries the invariant, not merely the intermediate.
    rounded_tri = _triplet((round(u, 6), round(d, 6), round(fl, 6)))
    _rt_sorted = sorted(rounded_tri, reverse=True) if rounded_tri is not None else None
    _rt_keeps_authority = _rt_sorted is not None and (
        _rt_sorted[0] <= _pre_dom
        and (_rt_sorted[0] - _rt_sorted[1]) <= _pre_margin
    )

    if rounded_tri is not None and _argmax_dir(*rounded_tri) == final_winner and _rt_keeps_authority:

        u_out, d_out, fl_out = rounded_tri

    else:

        u_out, d_out, fl_out = u, d, fl

    audit = {

        "pre_triplet": {"up": round(pre[0], 6), "down": round(pre[1], 6), "flat": round(pre[2], 6)},

        "post_triplet": {"up": u_out, "down": d_out, "flat": fl_out},

        "normalized_mc": {k: round(float(v), 6) for k, v in mc_n.items()},

        "base_argmax": _argmax_dir(*pre),

        "final_argmax": _argmax_dir(u_out, d_out, fl_out),

        "mc_feature_source": mc_bundle_source or "derived_mc_normalized",

        # True when the adjustment was CAPPED (blended toward uniform) because it would otherwise
        # have raised dominant probability or widened margin above the pre-adjustment values —
        # i.e. MC tried to increase directional authority rather than soften it. The adjustment is
        # capped, never discarded: discarding it would restore conviction MC had just removed.
        "authority_increase_capped": bool(_mc_authority_capped),
        # How much uniform blending the cap required (0.0 = adjustment passed through untouched).
        "authority_cap_lambda": round(float(_lam), 9),

    }

    try:

        return replace(

            fusion,

            prob_up=u_out,

            prob_down=d_out,

            prob_flat=fl_out,

            mc_post_fusion_audit=audit,

        )

    except TypeError:

        setattr(fusion, "prob_up", u_out)

        setattr(fusion, "prob_down", d_out)

        setattr(fusion, "prob_flat", fl_out)

        setattr(fusion, "mc_post_fusion_audit", audit)

        return fusion


