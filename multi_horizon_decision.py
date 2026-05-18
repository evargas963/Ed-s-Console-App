"""
Multi-horizon decision engine (Issue 18 phase).

Produces a single runtime decision truth from per-horizon forecasts while preserving
canonical safety semantics (downgrades/blocks are allowed; synthetic conviction is not).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from ml_horizon import PRIMARY_DECISION_HORIZONS
from multi_horizon_ml_bundle import MultiHorizonMLFusionBundle

# Authoritative multi-horizon decision inputs only (must match PRIMARY_DECISION_HORIZONS).
PRODUCT_HORIZONS: tuple[str, ...] = PRIMARY_DECISION_HORIZONS
HORIZON_MINUTES: dict[str, int] = {"1c": 1, "5c": 5, "15c": 15, "60c": 60}

# Stable reason codes for operator surfaces (mirrors arch_competition REASON_* pattern).
REASON_PRIMARY_HORIZON_DATA_MISSING = "PRIMARY_HORIZON_DATA_MISSING"


@dataclass
class HorizonForecast:
    horizon: str
    direction: str
    probability_up: float
    probability_down: float
    probability_flat: float
    confidence: float
    provenance: str
    tradeable: bool
    unavailable: bool
    missing: bool
    valid_contract: bool
    dominant_probability: float
    probability_margin: float
    expected_move_pts: Optional[float] = None
    entry_ref: Optional[float] = None
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PrimaryHorizonSelection:
    trade_mode: str
    requested_primary: str
    selected_primary: str
    fallback_used: bool
    fallback_reason: str
    candidates_checked: list[str] = field(default_factory=list)


@dataclass
class SupportingHorizonAssessment:
    horizon: str
    role: str
    call: str
    confidence: float
    entry_ref: Optional[float]
    supports_primary: bool
    contradicts_primary: bool
    timing_only: bool
    risk_modifier: bool
    effect: str
    row_state: str
    missing: bool = False
    reason_code: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class HorizonAlignmentReport:
    alignment_score: float
    contradiction_score: float
    support_score: float
    conflict_level: str
    alignment_state: str
    contradiction_state: str
    fully_aligned: bool
    mostly_aligned: bool
    mixed: bool
    contradictory: bool
    weak: bool
    unusable: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class FinalTradePlan:
    entry_state: str
    entry: Optional[float]
    entry_display_text: str
    stop: Optional[float]
    stop_display_text: str
    target_ladder: list[str]
    targets_display: str
    hold_style: str
    size_modifier: float
    size_modifier_display: str


@dataclass
class MultiHorizonDecision:
    final_bias: str
    final_confidence: float
    final_quality: str
    final_tradeable: bool
    primary_horizon: str
    trade_mode: str
    supporting_horizon_summary: str
    alignment_state: str
    contradiction_state: str
    entry_state: str
    entry: Optional[float]
    stop: Optional[float]
    target_ladder: list[str]
    hold_style: str
    sizing_modifier: float
    risk_note: str
    wait_reason: str
    decision_provenance: str
    alignment_report: HorizonAlignmentReport
    primary_selection: PrimaryHorizonSelection
    supporting_assessments: list[SupportingHorizonAssessment]
    final_trade_plan: FinalTradePlan


@dataclass
class MultiHorizonForecastBundle:
    canonical_1c: HorizonForecast
    canonical_5c: HorizonForecast
    canonical_15c: HorizonForecast
    canonical_60c: HorizonForecast
    completeness: str
    missing_horizons: list[str]
    notes: list[str]
    selected_primary_horizon: str
    alignment_summary: str
    contradiction_summary: str
    final_decision: MultiHorizonDecision
    # Provable audit: ML vs empirical per horizon, consensus, roles (Issue 18+ MH ML authority)
    ml_live_audit: dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiHorizonSynthesis:
    """
    Multi-horizon alignment outcome before The Call (no entry/stop/target plan).
    Passed into compute_call as mh_policy; finalize_multi_horizon_bundle attaches plan from call.
    """

    mode: str
    hmap: dict[str, HorizonForecast]
    order: tuple[str, ...]
    selected: str
    primary: HorizonForecast
    psel: PrimaryHorizonSelection
    assessments: list[SupportingHorizonAssessment]
    align: HorizonAlignmentReport
    final_bias: str
    tradeable: bool
    wait_reason: str
    conf: float
    qual: str
    size_modifier: float
    hold_style: str
    consensus_dir: Optional[str]
    cv_long: int
    cv_short: int
    ml_live_audit: dict[str, Any]
    missing_horizons: list[str]
    completeness: str
    mh_src: dict[str, str]

    @property
    def final_tradeable_decision(self) -> bool:
        return bool(self.tradeable and self.final_bias in ("long", "short"))

    def mh_directional_vote(self) -> int:
        if self.final_tradeable_decision:
            return 1 if self.final_bias == "long" else -1
        return 0

    def mh_veto_stack_directional(self, stack_sig: str) -> bool:
        if stack_sig == "wait":
            return False
        if not self.final_tradeable_decision or self.final_bias == "wait":
            return True
        return stack_sig != self.final_bias


def compute_multi_horizon_synthesis(
    inp,
    pred,
    canonical,
    mh_ml_bundle: Optional[MultiHorizonMLFusionBundle] = None,
) -> MultiHorizonSynthesis:
    raw_mode = _infer_trade_mode(inp)
    mode = raw_mode if raw_mode is not None else "unknown"
    hmap = {
        hz: _forecast_horizon_live(pred, inp, hz, canonical=canonical, mh_ml_bundle=mh_ml_bundle)
        for hz in PRODUCT_HORIZONS
    }
    mh_src = getattr(pred, "mh_prob_source_by_horizon", None) or {}
    if not isinstance(mh_src, dict):
        mh_src = {}
    consensus_dir, cv_long, cv_short = _ml_consensus_vote(hmap)
    order = _primary_order_for_mode(mode)
    selected = None
    checked: list[str] = []
    for hz in order:
        checked.append(hz)
        if hmap[hz].tradeable:
            selected = hz
            break
    if selected is None:
        selected = order[0]
    primary = hmap[selected]
    psel = PrimaryHorizonSelection(
        trade_mode=mode,
        requested_primary=order[0],
        selected_primary=selected,
        fallback_used=(selected != order[0]),
        fallback_reason=("" if selected == order[0] else "requested primary unavailable/non-tradeable"),
        candidates_checked=checked,
    )

    assessments: list[SupportingHorizonAssessment] = []
    for hz in PRODUCT_HORIZONS:
        f = hmap[hz]
        if f.missing:
            assessments.append(
                SupportingHorizonAssessment(
                    horizon=hz,
                    role="Unavailable",
                    call="UNAVAILABLE",
                    confidence=0.0,
                    entry_ref=None,
                    supports_primary=False,
                    contradicts_primary=False,
                    timing_only=False,
                    risk_modifier=False,
                    effect="Native horizon data missing",
                    row_state="missing",
                    missing=True,
                    reason_code=REASON_PRIMARY_HORIZON_DATA_MISSING,
                    notes=[f"predictive probs unavailable for {hz}"],
                )
            )
            continue
        role, sup, con, tr = _support_role(mode, selected, hz, f, primary.direction)
        eff = "Governs" if role == "Primary" else "Conflicts" if con else "Supports" if sup else "Timing weak" if role == "Timing" else "Low conviction"
        assessments.append(
            SupportingHorizonAssessment(
                horizon=hz,
                role=role,
                call=("LONG" if f.direction == "long" else "SHORT" if f.direction == "short" else "WAIT" if not f.unavailable else "UNAVAILABLE"),
                confidence=round(f.confidence, 4),
                entry_ref=f.entry_ref,
                supports_primary=sup,
                contradicts_primary=con,
                timing_only=(role == "Timing"),
                risk_modifier=(role == "Risk"),
                effect=eff,
                row_state=_row_state(role, sup, con),
                missing=False,
                reason_code="",
            )
        )

    align = _alignment_state(primary, [a for a in assessments if a.horizon != selected])
    final_bias = primary.direction
    tradeable = primary.tradeable and final_bias in ("long", "short")
    wait_reason = ""
    if align.unusable or not tradeable:
        final_bias = "wait"
        tradeable = False
        wait_reason = "no valid primary horizon"
    elif align.contradiction_state == "structural":
        final_bias = "wait"
        tradeable = False
        wait_reason = "severe structural contradiction"
    elif align.alignment_state in ("weak", "mixed") and primary.confidence < 0.34:
        final_bias = "wait"
        tradeable = False
        wait_reason = "weak multi-horizon support"
    elif (
        consensus_dir is not None
        and primary.direction in ("long", "short")
        and primary.direction != consensus_dir
        and (cv_long >= 3 or cv_short >= 3)
    ):
        final_bias = "wait"
        tradeable = False
        wait_reason = "multi_horizon ML consensus disagrees with mode-selected primary"

    conf = primary.confidence
    conf += 0.04 * align.support_score
    conf -= 0.08 * align.contradiction_score
    conf = max(0.0, min(1.0, conf))
    if final_bias == "wait":
        conf = min(conf, 0.45)

    qual = _quality_from_alignment(conf, align.alignment_state, align.contradiction_state)
    hold_style = (
        "Scalp tactical"
        if mode == "scalp"
        else "Session continuation"
        if mode == "session"
        else "Intraday continuation"
        if mode == "intraday"
        else "Mode unknown — default intraday horizon stack"
    )
    if align.contradiction_state in ("structural", "tactical"):
        hold_style = "Tactical / reduced hold"
    size = 1.0
    size *= 0.5 if align.contradiction_state == "structural" else 0.75 if align.contradiction_state == "tactical" else 1.0
    if align.alignment_state == "fully_aligned":
        size *= 1.0
    elif align.alignment_state in ("weak", "mixed"):
        size *= 0.75
    size = max(0.25, min(1.0, size))
    if final_bias == "wait":
        size = 0.0

    missing = [hz for hz in PRODUCT_HORIZONS if hmap[hz].missing]
    completeness = "complete" if not missing else "partial"

    per_hz_audit: dict[str, Any] = {}
    for hz in PRODUCT_HORIZONS:
        snap = mh_ml_bundle.snapshot(hz) if mh_ml_bundle else None
        per_hz_audit[hz] = {
            "semantic_role": HORIZON_SEMANTIC_ROLE.get(hz, ""),
            "predictive_probability_source": mh_src.get(hz, "unknown"),
            "fusion_ml_available": bool(snap and snap.fusion_available),
            "fusion_dominant_direction": getattr(snap, "dominant_direction", None) if snap else None,
            "fusion_top_probability": round(getattr(snap, "top_probability", 0.0), 4) if snap else None,
            "forecast_direction": hmap[hz].direction,
            "forecast_provenance": hmap[hz].provenance,
            "tradeable": hmap[hz].tradeable,
        }
    ml_live_audit: dict[str, Any] = {
        "contract": "mh_ml_primary_per_horizon_fusion; empirical_ED_MH_EMPIRICAL_SUPPORT; fallback_ED_MH_FALLBACK_CANONICAL_BLEND",
        "per_horizon": per_hz_audit,
        "consensus_direction": consensus_dir,
        "consensus_long_votes_tradeable": cv_long,
        "consensus_short_votes_tradeable": cv_short,
        "live_canonical_horizon_slug": getattr(mh_ml_bundle, "live_canonical_horizon_slug", None)
        if mh_ml_bundle
        else None,
        "selected_primary_horizon": selected,
        "primary_order_for_mode": list(order),
    }

    return MultiHorizonSynthesis(
        mode=mode,
        hmap=hmap,
        order=order,
        selected=selected,
        primary=primary,
        psel=psel,
        assessments=assessments,
        align=align,
        final_bias=final_bias,
        tradeable=tradeable,
        wait_reason=wait_reason,
        conf=conf,
        qual=qual,
        size_modifier=size,
        hold_style=hold_style,
        consensus_dir=consensus_dir,
        cv_long=cv_long,
        cv_short=cv_short,
        ml_live_audit=ml_live_audit,
        missing_horizons=missing,
        completeness=completeness,
        mh_src=dict(mh_src),
    )


def finalize_multi_horizon_bundle(
    synth: MultiHorizonSynthesis,
    call,
    inp,
    mh_ml_bundle: Optional[MultiHorizonMLFusionBundle] = None,
) -> MultiHorizonForecastBundle:
    """Attach call-derived plan to a precomputed MultiHorizonSynthesis (single MH compute per tick)."""
    hmap = synth.hmap
    selected = synth.selected
    assessments = synth.assessments
    align = synth.align
    final_bias = synth.final_bias
    tradeable = synth.tradeable
    wait_reason = synth.wait_reason
    conf = synth.conf
    qual = synth.qual
    size = synth.size_modifier
    hold_style = synth.hold_style
    psel = synth.psel
    mode = synth.mode
    ml_live_audit = synth.ml_live_audit

    e_state, e_px, e_txt = _entry_state_machine(
        final_bias,
        tradeable,
        inp,
        hmap["1c"],
        getattr(call, "entry", None),
        getattr(call, "call_state", None) or getattr(call, "signal", "WAIT"),
    )
    stop = getattr(call, "stop", None)
    target = getattr(call, "target", None)
    target2 = getattr(call, "target2", None)
    tlad = []
    if target is not None:
        tlad.append(f"T1: {float(target):.2f}")
    else:
        tlad.append("T1: —")
    if target2 is not None:
        tlad.append(f"T2: {float(target2):.2f}")
        tlad.append(f"Runner: {float(target2):.2f}")
    else:
        tlad.append("T2: —")
        tlad.append("Runner: —")
    tdisp = " | ".join(tlad)
    sdisp = "—" if stop is None else f"{float(stop):.2f}"
    size_disp = "0.00x" if size <= 0 else f"{size:.2f}x"

    plan = FinalTradePlan(
        entry_state=e_state,
        entry=e_px,
        entry_display_text=e_txt,
        stop=(float(stop) if stop is not None else None),
        stop_display_text=sdisp if final_bias != "wait" else "—",
        target_ladder=tlad,
        targets_display=tdisp if final_bias != "wait" else "—",
        hold_style=hold_style if final_bias != "wait" else "Wait / no setup",
        size_modifier=size,
        size_modifier_display=size_disp,
    )

    decision = MultiHorizonDecision(
        final_bias=("LONG" if final_bias == "long" else "SHORT" if final_bias == "short" else "WAIT"),
        final_confidence=round(conf, 4),
        final_quality=qual,
        final_tradeable=tradeable and final_bias in ("long", "short"),
        primary_horizon=selected,
        trade_mode=mode,
        supporting_horizon_summary=", ".join(
            f"{a.horizon}:{a.effect}" for a in assessments if a.horizon != selected
        ),
        alignment_state=align.alignment_state,
        contradiction_state=align.contradiction_state,
        entry_state=plan.entry_state,
        entry=plan.entry,
        stop=plan.stop,
        target_ladder=plan.target_ladder,
        hold_style=plan.hold_style,
        sizing_modifier=plan.size_modifier,
        risk_note=(
            "Primary aligned with higher horizons"
            if align.alignment_state in ("fully_aligned", "mostly_aligned")
            else "Contradiction present; reduce aggressiveness"
            if align.contradiction_state in ("tactical", "structural")
            else "Low-confidence mixed horizon state"
        ),
        wait_reason=wait_reason,
        decision_provenance="multi_horizon_decision_engine_v2_mh_ml_primary",
        alignment_report=align,
        primary_selection=psel,
        supporting_assessments=assessments,
        final_trade_plan=plan,
    )

    return MultiHorizonForecastBundle(
        canonical_1c=hmap["1c"],
        canonical_5c=hmap["5c"],
        canonical_15c=hmap["15c"],
        canonical_60c=hmap["60c"],
        completeness=synth.completeness,
        missing_horizons=synth.missing_horizons,
        notes=[],
        selected_primary_horizon=selected,
        alignment_summary=align.alignment_state,
        contradiction_summary=align.contradiction_state,
        final_decision=decision,
        ml_live_audit=ml_live_audit,
    )


def _safe_prob_optional(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= x <= 1.0):
        return None
    return x


def _norm_triplet(
    u: Optional[float], d: Optional[float], f: Optional[float]
) -> Optional[tuple[float, float, float]]:
    up = _safe_prob_optional(u)
    dn = _safe_prob_optional(d)
    fl = _safe_prob_optional(f)
    if up is None or dn is None or fl is None:
        return None
    s = up + dn + fl
    if s <= 0:
        return None
    return (up / s, dn / s, fl / s)


def _confidence_from_probs(up: float, dn: float, fl: float) -> tuple[float, float, str]:
    vals = sorted([up, dn, fl], reverse=True)
    top = vals[0]
    margin = top - vals[1]
    # Slightly looser vs legacy so fusion+signal_layer canonical blends can resolve a side.
    if top < 0.37 or margin < 0.025:
        return top, margin, "wait"
    if up >= dn and up >= fl:
        return top, margin, "long"
    if dn >= up and dn >= fl:
        return top, margin, "short"
    return top, margin, "wait"


def _infer_trade_mode(inp) -> Optional[str]:
    m2c = getattr(inp, "mins_to_close", None)
    if m2c is None:
        return None
    try:
        mins = float(m2c)
    except (TypeError, ValueError):
        return None
    if mins <= 75:
        return "scalp"
    if mins <= 240:
        return "intraday"
    return "session"


def _primary_order_for_mode(mode: Optional[str]) -> tuple[str, ...]:
    if mode == "scalp":
        return ("1c", "5c", "15c", "60c")
    if mode == "session":
        return ("60c", "15c", "5c", "1c")
    # intraday + unknown: same default stack (no fabricated mins_to_close)
    return ("15c", "5c", "1c", "60c")


HORIZON_SEMANTIC_ROLE: dict[str, str] = {
    "1c": "execution_bias",
    "5c": "short_term_directional_bias",
    "15c": "structural_intraday_bias",
    "60c": "session_bias",
}


def _forecast_horizon_live(
    pred,
    inp,
    hz: str,
    canonical: Optional[Any] = None,
    mh_ml_bundle: Optional[MultiHorizonMLFusionBundle] = None,
) -> HorizonForecast:
    """
    Per-horizon forecast: PredictiveCard fields are already ML-primary for product horizons
    (compute_prediction). Do **not** inject the single live (1c) canonical triplet into every horizon.
    When fusion is unavailable for a horizon, optional ED_MH_FALLBACK_CANONICAL_BLEND stabilizes
    empirical-only triplets (default 0.0 — empirical + fusion per horizon only).
    """
    if hz == "1c":
        triplet = _norm_triplet(
            getattr(pred, "up_prob_1c", None),
            getattr(pred, "down_prob_1c", None),
            getattr(pred, "flat_prob_1c", None),
        )
        em = getattr(pred, "avg_5c_pts", None)
    elif hz == "5c":
        triplet = _norm_triplet(
            getattr(pred, "up_prob_5c", None),
            getattr(pred, "down_prob_5c", None),
            getattr(pred, "flat_prob_5c", None),
        )
        em = getattr(pred, "avg_5c_pts", None)
    elif hz == "15c":
        triplet = _norm_triplet(
            getattr(pred, "up_prob_15c", None),
            getattr(pred, "down_prob_15c", None),
            getattr(pred, "flat_prob_15c", None),
        )
        em = getattr(pred, "avg_15c_pts", None)
    else:
        triplet = _norm_triplet(
            getattr(pred, "up_prob_60c", None),
            getattr(pred, "down_prob_60c", None),
            getattr(pred, "flat_prob_60c", None),
        )
        em = getattr(pred, "avg_60c_pts", None)

    if triplet is None:
        miss = True
        return HorizonForecast(
            horizon=hz,
            direction="wait",
            probability_up=0.0,
            probability_down=0.0,
            probability_flat=0.0,
            confidence=0.0,
            provenance="predictive_probs_unavailable",
            tradeable=False,
            unavailable=True,
            missing=True,
            valid_contract=False,
            dominant_probability=0.0,
            probability_margin=0.0,
            expected_move_pts=(float(em) if em is not None else None),
            entry_ref=None,
        )
    up, dn, fl = triplet

    ml_snap = mh_ml_bundle.snapshot(hz) if mh_ml_bundle else None
    fusion_ml = bool(ml_snap and ml_snap.fusion_available)
    provenance = f"predictive_mh_fusion_primary_{hz}"
    if not fusion_ml:
        try:
            wfb = float(os.environ.get("ED_MH_FALLBACK_CANONICAL_BLEND", "0.0"))
        except ValueError:
            wfb = 0.0
        wfb = max(0.0, min(1.0, wfb))
        if canonical is not None and wfb > 0.0:
            cu = getattr(canonical, "probability_up", None)
            cd = getattr(canonical, "probability_down", None)
            cf = getattr(canonical, "probability_flat", None)
            if cu is not None and cd is not None and cf is not None:
                cu, cd, cf = float(cu), float(cd), float(cf)
            else:
                cu = cd = cf = None
            if cu is not None and cd is not None and cf is not None:
                up = (1.0 - wfb) * up + wfb * cu
                dn = (1.0 - wfb) * dn + wfb * cd
                fl = (1.0 - wfb) * fl + wfb * cf
                s = up + dn + fl
                if s > 0:
                    up, dn, fl = up / s, dn / s, fl / s
                provenance = f"predictive_empirical_fallback_{hz}_stabilized"
        else:
            provenance = f"predictive_empirical_fallback_{hz}"

    dom, margin, call = _confidence_from_probs(up, dn, fl)
    miss = any(getattr(pred, f"{k}_prob_{hz}", None) is None for k in ("up", "down", "flat"))
    empirical_ok = (not miss) or fusion_ml or (canonical is not None)
    tradeable = (
        (call in ("long", "short"))
        and dom >= 0.38
        and margin >= 0.03
        and empirical_ok
    )
    up_ref = getattr(inp, "nearest_below_val", None)
    dn_ref = getattr(inp, "nearest_above_val", None)
    entry_ref = up_ref if call == "long" else dn_ref if call == "short" else None
    return HorizonForecast(
        horizon=hz,
        direction=call,
        probability_up=up,
        probability_down=dn,
        probability_flat=fl,
        confidence=dom,
        provenance=provenance,
        tradeable=tradeable,
        unavailable=miss,
        missing=miss,
        valid_contract=True,
        dominant_probability=dom,
        probability_margin=margin,
        expected_move_pts=(float(em) if em is not None else None),
        entry_ref=(float(entry_ref) if entry_ref is not None else None),
    )


def _quality_from_alignment(base_conf: float, align_state: str, contradiction: str) -> str:
    score = base_conf
    if align_state == "fully_aligned":
        score += 0.10
    elif align_state == "mostly_aligned":
        score += 0.05
    elif align_state == "mixed":
        score -= 0.08
    elif align_state == "contradictory":
        score -= 0.16
    if contradiction == "structural":
        score -= 0.18
    elif contradiction == "tactical":
        score -= 0.08
    score = max(0.0, min(1.0, score))
    if score >= 0.74:
        return "A"
    if score >= 0.66:
        return "B+"
    if score >= 0.58:
        return "B"
    if score >= 0.50:
        return "C"
    return "D"


def _alignment_state(primary: HorizonForecast, supports: list[SupportingHorizonAssessment]) -> HorizonAlignmentReport:
    usable = [s for s in supports if s.call in ("long", "short", "wait")]
    sup = sum(1 for s in usable if s.supports_primary)
    con = sum(1 for s in usable if s.contradicts_primary)
    weak = sum(1 for s in usable if s.row_state == "weak")
    n = max(1, len(usable))
    align_score = (sup - con) / n
    contradiction_score = con / n
    support_score = sup / n

    if not primary.tradeable:
        state = "unusable"
    elif con == 0 and sup >= 2:
        state = "fully_aligned"
    elif con <= 1 and sup >= 1:
        state = "mostly_aligned"
    elif con >= 2:
        state = "contradictory"
    elif weak >= 2:
        state = "weak"
    else:
        state = "mixed"

    contradiction_state = "none"
    if con >= 2 and primary.horizon in ("15c", "60c"):
        contradiction_state = "structural"
    elif con >= 1:
        contradiction_state = "tactical"
    elif weak >= 2:
        contradiction_state = "weakness"

    return HorizonAlignmentReport(
        alignment_score=round(align_score, 4),
        contradiction_score=round(contradiction_score, 4),
        support_score=round(support_score, 4),
        conflict_level=("high" if con >= 2 else "medium" if con == 1 else "low"),
        alignment_state=state,
        contradiction_state=contradiction_state,
        fully_aligned=(state == "fully_aligned"),
        mostly_aligned=(state == "mostly_aligned"),
        mixed=(state == "mixed"),
        contradictory=(state == "contradictory"),
        weak=(state == "weak"),
        unusable=(state == "unusable"),
        reasons=[],
    )


def _support_role(mode: str, primary: str, hz: str, f: HorizonForecast, primary_dir: str) -> tuple[str, bool, bool, bool]:
    supports = f.direction == primary_dir and f.direction in ("long", "short")
    contradicts = f.direction in ("long", "short") and f.direction != primary_dir
    timing = hz in ("1c", "5c") and primary in ("15c", "60c")
    risk = hz == "60c" and primary != "60c"
    if hz == primary:
        role = "Primary"
    elif contradicts:
        role = "Contradiction"
    elif timing:
        role = "Timing"
    elif risk:
        role = "Risk"
    elif supports:
        role = "Confirm"
    elif f.direction == "wait":
        role = "Ignore"
    else:
        role = "Structure"
    return role, supports, contradicts, (timing or risk)


def _row_state(role: str, supports: bool, contradicts: bool) -> str:
    if role == "Primary":
        return "primary"
    if contradicts:
        return "contradictory"
    if supports:
        return "aligned"
    return "weak"


def _entry_state_machine(
    final_bias: str,
    tradeable: bool,
    inp,
    one_c: HorizonForecast,
    call_entry: Optional[float],
    call_state: str,
) -> tuple[str, Optional[float], str]:
    if final_bias == "wait" or not tradeable:
        return ("no_setup", None, "No valid setup")
    zl = getattr(inp, "nearest_below_val", None)
    zh = getattr(inp, "nearest_above_val", None)
    spot = getattr(inp, "spot", None)
    if zl is None or zh is None or spot is None:
        return ("forming", None, "Wait for pullback into —\u2014—\n(1c confirmation required)")
    lo = float(min(zl, zh))
    hi = float(max(zl, zh))
    in_zone = lo <= float(spot) <= hi
    confirm_1c = one_c.direction == final_bias and one_c.confidence >= 0.54
    cs = str(call_state or "WAIT").upper()
    if cs == "ACTIVE" and call_entry is not None:
        return ("filled", float(call_entry), f"{float(call_entry):.2f} (FILLED)")
    if not in_zone:
        return ("forming", None, f"Wait for pullback into {lo:.2f}\u2013{hi:.2f}\n(1c confirmation required)")
    if in_zone and not confirm_1c:
        return ("armed", None, f"In zone ({lo:.2f}\u2013{hi:.2f})\nWaiting for 1c confirmation")
    if call_entry is not None:
        return ("confirmed", float(call_entry), f"{float(call_entry):.2f} (CONFIRMED)")
    return ("confirmed", float(spot), f"{float(spot):.2f} (CONFIRMED)")


def _ml_consensus_vote(hmap: dict[str, HorizonForecast]) -> tuple[Optional[str], int, int]:
    """Returns (consensus_direction or None, long_votes among tradeable, short_votes)."""
    long_v = short_v = 0
    for hz in PRODUCT_HORIZONS:
        f = hmap[hz]
        if not f.tradeable or f.direction not in ("long", "short"):
            continue
        if f.direction == "long":
            long_v += 1
        else:
            short_v += 1
    if long_v >= 3 and short_v <= 1:
        return "long", long_v, short_v
    if short_v >= 3 and long_v <= 1:
        return "short", long_v, short_v
    return None, long_v, short_v


def build_multi_horizon_bundle(
    inp,
    pred,
    canonical,
    call,
    mh_ml_bundle: Optional[MultiHorizonMLFusionBundle] = None,
) -> MultiHorizonForecastBundle:
    return finalize_multi_horizon_bundle(
        compute_multi_horizon_synthesis(inp, pred, canonical, mh_ml_bundle),
        call,
        inp,
        mh_ml_bundle,
    )
