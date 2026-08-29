"""
Multi-horizon decision engine (Issue 18 phase).

Produces a single runtime decision truth from per-horizon forecasts while preserving
canonical safety semantics (downgrades/blocks are allowed; synthetic conviction is not).
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from fusion_contract import is_canonical_tradable
from ml_horizon import PRIMARY_DECISION_HORIZONS
from multi_horizon_ml_bundle import MultiHorizonMLFusionBundle
from numeric_contract import direction_from_normalized_triplet, float_finite_or_none

log = logging.getLogger(__name__)

_TRIPLET_LABEL_TO_FORECAST = {"up": "long", "down": "short", "flat": "wait"}

# Authoritative multi-horizon decision inputs only (must match PRIMARY_DECISION_HORIZONS).
PRODUCT_HORIZONS: tuple[str, ...] = PRIMARY_DECISION_HORIZONS
HORIZON_MINUTES: dict[str, int] = {s: int(s[:-1]) for s in PRIMARY_DECISION_HORIZONS}

# Per-mode primary-horizon search order (permutations of PRIMARY_DECISION_HORIZONS).
PRIMARY_ORDER_BY_MODE: dict[str, tuple[str, ...]] = {
    "scalp": ("1c", "5c", "15c", "60c"),
    "intraday": ("15c", "5c", "1c", "60c"),
    "session": ("60c", "15c", "5c", "1c"),
}

# ── Confidence / tradeable gates (FIND-WIRE2-2/3; Phase 6 ablation tune surface) ──
TRADEABLE_DOM_MIN: float = 0.38
TRADEABLE_MARGIN_MIN: float = 0.03
ENTRY_CONFIRMATION_CONFIDENCE_MIN: float = 0.54
WAIT_CONFIDENCE_CAP: float = 0.45

# ── ALL-card pooled consensus (operator 2026-06-11) ──
# Skill-weighted logarithmic opinion pool over the four horizon fusion triplets.
# Forecast combination per Bates & Granger (1969); log pooling per Genest & Zidek
# (1986). Replaces head-count voting ("2 of 4 agree"): every valid horizon
# contributes its FULL probability triplet, weighted by rolling out-of-sample
# skill (calibration.daily_scoreboard.horizon_skill_weights); a dissenting
# horizon drags the pooled evidence down continuously instead of a binary veto.
CONSENSUS_MIN_VALID_HORIZONS: int = 2
POOL_PROB_FLOOR: float = 1e-6
SKILL_WEIGHTS_TTL_SEC: float = 900.0

# ── Quality ladder ──
QUALITY_BOOST_FULLY_ALIGNED: float = 0.10
QUALITY_BOOST_MOSTLY_ALIGNED: float = 0.05
QUALITY_PENALTY_MIXED: float = 0.08
QUALITY_PENALTY_CONTRADICTORY: float = 0.16
QUALITY_PENALTY_STRUCTURAL_CONTRADICTION: float = 0.18
QUALITY_PENALTY_TACTICAL_CONTRADICTION: float = 0.08
QUALITY_THRESHOLD_A: float = 0.74
QUALITY_THRESHOLD_B_PLUS: float = 0.66
QUALITY_THRESHOLD_B: float = 0.58
QUALITY_THRESHOLD_C: float = 0.50

# ── Alignment state counts ──
ALIGNMENT_FULLY_ALIGNED_MIN_SUPPORT: int = 2
ALIGNMENT_CONTRADICTORY_MIN_COUNT: int = 2
ALIGNMENT_WEAK_MIN_COUNT: int = 2
STRUCTURAL_HORIZONS_FOR_CONTRADICTION: tuple[str, ...] = ("15c", "60c")

# ── Multi-horizon vocabulary (wire/API snake_case; do not reuse across layers) ──
# Trade decision: final_bias / call_signal → LONG | SHORT | WAIT
# Per-horizon call (mhap_rows.call): LONG | SHORT | WAIT | UNAVAILABLE (missing data)
# Per-horizon support (mhap_rows.row_state): primary | aligned | weak | contradictory | missing
# Cross-horizon alignment (alignment_state_display): values below — NOT a trade direction
ALIGNMENT_STATE_FULLY_ALIGNED: str = "fully_aligned"
ALIGNMENT_STATE_MOSTLY_ALIGNED: str = "mostly_aligned"
ALIGNMENT_STATE_MIXED: str = "mixed"
ALIGNMENT_STATE_CONTRADICTORY: str = "contradictory"
ALIGNMENT_STATE_WEAK: str = "weak"
ALIGNMENT_STATE_NO_PRIMARY: str = "no_primary"  # primary horizon not tradeable; not UNAVAILABLE
ALIGNMENT_STATES: tuple[str, ...] = (
    ALIGNMENT_STATE_FULLY_ALIGNED,
    ALIGNMENT_STATE_MOSTLY_ALIGNED,
    ALIGNMENT_STATE_MIXED,
    ALIGNMENT_STATE_CONTRADICTORY,
    ALIGNMENT_STATE_WEAK,
    ALIGNMENT_STATE_NO_PRIMARY,
)
# Legacy wire value (pre-2026-06): kept for calibration rows + filters only
ALIGNMENT_STATE_UNUSABLE_LEGACY: str = "unusable"


def alignment_state_operator_label(state: str | None) -> str:
    """Operator-readable alignment label; internal wire stays snake_case."""
    key = str(state or "").strip().lower()
    if key in (ALIGNMENT_STATE_NO_PRIMARY, ALIGNMENT_STATE_UNUSABLE_LEGACY):
        return "no primary edge"
    if key in (ALIGNMENT_STATE_FULLY_ALIGNED, ALIGNMENT_STATE_MOSTLY_ALIGNED):
        return "aligned"
    if key == ALIGNMENT_STATE_CONTRADICTORY:
        return "split"
    if key == ALIGNMENT_STATE_WEAK:
        return "weak support"
    if key == ALIGNMENT_STATE_MIXED:
        return "mixed"
    return key or "unknown"


def normalize_alignment_state(state: str | None) -> str:
    """Map legacy ``unusable`` rows to ``no_primary``."""
    key = str(state or "").strip().lower()
    if key == ALIGNMENT_STATE_UNUSABLE_LEGACY:
        return ALIGNMENT_STATE_NO_PRIMARY
    return key

# ── Trade mode boundaries (mins-to-close) ──
TRADE_MODE_SCALP_MAX_MINS: int = 75
TRADE_MODE_INTRADAY_MAX_MINS: int = 240

# ── ML consensus voting ──
CONSENSUS_MAJORITY_VOTE_MIN: int = 3
CONSENSUS_DISSENT_VOTE_MAX: int = 1

# ── Sizing modifier factors ──
SIZING_STRUCTURAL_CONTRADICTION_FACTOR: float = 0.5
SIZING_TACTICAL_CONTRADICTION_FACTOR: float = 0.75
SIZING_WEAK_ALIGNMENT_FACTOR: float = 0.75
SIZING_MIN_FLOOR: float = 0.25

# ── Wait reasons (operator-visible; FIND-WIRE2-4; pooled consensus 2026-06-11) ──
WAIT_REASON_INSUFFICIENT_VALID_HORIZONS = (
    f"fewer than {CONSENSUS_MIN_VALID_HORIZONS} horizons with valid probability triplets"
    " — insufficient evidence"
)
WAIT_REASON_POOLED_FLAT = "pooled stack evidence favors flat — no directional edge"
WAIT_REASON_POOLED_INSUFFICIENT_TRADEABLE_ALIGNMENT = (
    f"fewer than {CONSENSUS_MIN_VALID_HORIZONS} tradeable horizons align with pooled direction"
    " — ALL synthesis withheld"
)
WAIT_REASON_CALL_ENGINE_VETO_PREFIX = "call engine veto"


def _wait_reason_pooled_below_gate(dom: float, margin: float) -> str:
    return (
        f"pooled stack evidence below entry gate (top {dom:.2f}, margin {margin:.2f};"
        f" need {TRADEABLE_DOM_MIN:.2f} / {TRADEABLE_MARGIN_MIN:.2f})"
    )


def _wait_reason_from_call_blocker(blocker: Any) -> str:
    """Operator-visible wait_reason when execution stack vetoes a pooled directional setup."""
    if not isinstance(blocker, dict) or not blocker:
        return f"{WAIT_REASON_CALL_ENGINE_VETO_PREFIX} — execution stack WAIT"
    reason = str(blocker.get("reason") or "unknown")
    if reason == "gates":
        gate_reasons = blocker.get("gate_reasons") or []
        if gate_reasons:
            return (
                f"{WAIT_REASON_CALL_ENGINE_VETO_PREFIX} — gated: "
                + "; ".join(str(g) for g in gate_reasons)
            )
    detail = blocker.get("detail") or blocker.get("full_detail")
    if detail:
        return f"{WAIT_REASON_CALL_ENGINE_VETO_PREFIX} — {detail}"
    return f"{WAIT_REASON_CALL_ENGINE_VETO_PREFIX} — {reason}"

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
    no_primary: bool
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
    pool_weights: Optional[dict[str, float]] = None,
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

    # ALL-card pooled consensus (operator 2026-06-11): the consolidated bias is a
    # skill-weighted logarithmic opinion pool over the four horizon triplets —
    # never a relay of the mode-selected primary and never a head-count vote.
    # The primary keeps the trade plan (entry/stop/targets/hold style) but does
    # not own the headline direction.
    if pool_weights is not None:
        pw, pw_fallback = dict(pool_weights), False
    else:
        pw, pw_fallback = _horizon_skill_weights_cached()
    pooled = _pooled_consensus(hmap, pw, pw_fallback)
    final_bias, wait_reason = pooled.final_bias, pooled.wait_reason
    pooled_aligned_tradeable = 0
    if final_bias in ("long", "short"):
        pooled_aligned_tradeable = sum(
            1
            for hz in PRODUCT_HORIZONS
            if hmap[hz].tradeable and hmap[hz].direction == final_bias
        )
        if pooled_aligned_tradeable < CONSENSUS_MIN_VALID_HORIZONS:
            final_bias = "wait"
            wait_reason = WAIT_REASON_POOLED_INSUFFICIENT_TRADEABLE_ALIGNMENT
    tradeable = final_bias in ("long", "short")

    if tradeable:
        # Confidence = pooled dominant probability (evidence strength of the
        # combined forecast — breadth and dissent are already inside the pool).
        conf = max(0.0, min(1.0, pooled.dominant_probability))
    else:
        base = (
            pooled.dominant_probability
            if pooled.prob_up is not None
            else max(0.0, primary.confidence)
        )
        conf = min(max(0.0, base), WAIT_CONFIDENCE_CAP)

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
    size *= (
        SIZING_STRUCTURAL_CONTRADICTION_FACTOR
        if align.contradiction_state == "structural"
        else SIZING_TACTICAL_CONTRADICTION_FACTOR
        if align.contradiction_state == "tactical"
        else 1.0
    )
    if align.alignment_state == "fully_aligned":
        size *= 1.0
    elif align.alignment_state in ("weak", "mixed"):
        size *= SIZING_WEAK_ALIGNMENT_FACTOR
    size = max(SIZING_MIN_FLOOR, min(1.0, size))
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
            "stack_directional_authorized": bool(
                snap and getattr(snap, "stack_directional_authorized", None) is True
            ),
            "stack_directional_authorization_reason": (
                getattr(snap, "stack_directional_authorization_reason", None)
                if snap
                else None
            ),
            "fusion_ml_available": bool(snap and snap.horizon_fusion_available),
            "fusion_dominant_direction": getattr(snap, "dominant_direction", None) if snap else None,
            "fusion_top_probability": round(getattr(snap, "top_probability", 0.0), 4) if snap else None,
            "forecast_direction": hmap[hz].direction,
            "forecast_provenance": hmap[hz].provenance,
            "tradeable": hmap[hz].tradeable,
        }
    ml_live_audit: dict[str, Any] = {
        "contract": (
            "mh_ml_primary_per_horizon_fusion; empirical_ED_MH_EMPIRICAL_SUPPORT;"
            " fallback_ED_MH_FALLBACK_CANONICAL_BLEND;"
            " all_card_skill_weighted_log_opinion_pool"
        ),
        "per_horizon": per_hz_audit,
        "all_card_pool": {
            "prob_up": pooled.prob_up,
            "prob_down": pooled.prob_down,
            "prob_flat": pooled.prob_flat,
            "dominant_probability": round(pooled.dominant_probability, 4),
            "probability_margin": round(pooled.probability_margin, 4),
            "eligible_horizons": list(pooled.eligible_horizons),
            "weights": {h: round(w, 4) for h, w in pooled.weights.items()},
            "weights_fallback_equal": pooled.weights_fallback_equal,
            "tradeable_horizons_aligned_with_pooled_bias": pooled_aligned_tradeable,
        },
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
    ml_live_audit = dict(synth.ml_live_audit)
    call_signal = str(getattr(call, "signal", "wait") or "wait").lower()
    call_engine_veto = tradeable and call_signal == "wait"
    if call_engine_veto:
        tradeable = False
        wait_reason = _wait_reason_from_call_blocker(getattr(call, "wait_blocker", None))
        size = 0.0
    ml_live_audit["call_engine_veto"] = {
        "applied": call_engine_veto,
        "call_signal": call_signal,
        "wait_blocker": getattr(call, "wait_blocker", None),
    }

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
    t1 = _finite_price_optional(target)
    if t1 is not None:
        tlad.append(f"T1: {t1:.2f}")
    else:
        tlad.append("T1: —")
    t2 = _finite_price_optional(target2)
    if t2 is not None:
        tlad.append(f"T2: {t2:.2f}")
        tlad.append(f"Runner: {t2:.2f}")
    else:
        tlad.append("T2: —")
        tlad.append("Runner: —")
    tdisp = " | ".join(tlad)
    stop_px = _finite_price_optional(stop)
    sdisp = "—" if stop_px is None else f"{stop_px:.2f}"
    size_disp = "0.00x" if size <= 0 else f"{size:.2f}x"

    plan = FinalTradePlan(
        entry_state=e_state,
        entry=e_px,
        entry_display_text=e_txt,
        stop=stop_px,
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
    x = float_finite_or_none(v)
    if x is None or not (0.0 <= x <= 1.0):
        return None
    return x


def _finite_price_optional(v: Any) -> Optional[float]:
    """Finite price for display/plan fields; rejects NaN/inf (FIND-MHD-6/7)."""
    return float_finite_or_none(v)


def _norm_triplet(
    u: Optional[float], d: Optional[float], f: Optional[float]
) -> Optional[tuple[float, float, float]]:
    up = _safe_prob_optional(u)
    dn = _safe_prob_optional(d)
    fl = _safe_prob_optional(f)
    if up is None or dn is None or fl is None:
        return None
    s = up + dn + fl
    if s <= 0 or not math.isfinite(s):
        return None
    return (up / s, dn / s, fl / s)


def _confidence_from_probs(up: float, dn: float, fl: float) -> tuple[float, float, str]:
    vals = sorted([up, dn, fl], reverse=True)
    top = vals[0]
    margin = top - vals[1]
    # Product-policy margin gates; direction from numeric_contract triplet authority.
    if top < TRADEABLE_DOM_MIN or margin < TRADEABLE_MARGIN_MIN:
        return top, margin, "wait"
    dom_label = direction_from_normalized_triplet(up, dn, fl)
    call = _TRIPLET_LABEL_TO_FORECAST.get(dom_label, "wait")
    if call == "wait":
        return top, margin, "wait"
    return top, margin, call


def _infer_trade_mode(inp) -> Optional[str]:
    m2c = getattr(inp, "mins_to_close", None)
    if m2c is None:
        return None
    try:
        mins = float(m2c)
    except (TypeError, ValueError):
        return None
    if mins <= TRADE_MODE_SCALP_MAX_MINS:
        return "scalp"
    if mins <= TRADE_MODE_INTRADAY_MAX_MINS:
        return "intraday"
    return "session"


def _primary_order_for_mode(mode: Optional[str]) -> tuple[str, ...]:
    if mode == "scalp":
        return PRIMARY_ORDER_BY_MODE["scalp"]
    if mode == "session":
        return PRIMARY_ORDER_BY_MODE["session"]
    if mode == "intraday":
        return PRIMARY_ORDER_BY_MODE["intraday"]
    return PRIMARY_ORDER_BY_MODE["intraday"]


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

    authorization_map = getattr(pred, "horizon_directional_authorized", None)
    pred_authorized = bool(
        isinstance(authorization_map, dict)
        and authorization_map.get(hz) is True
    )
    ml_snap = mh_ml_bundle.snapshot(hz) if mh_ml_bundle else None
    snapshot_authorized = bool(
        ml_snap and getattr(ml_snap, "stack_directional_authorized", None) is True
    )
    if not pred_authorized or (ml_snap is not None and not snapshot_authorized):
        return HorizonForecast(
            horizon=hz,
            direction="wait",
            probability_up=0.0,
            probability_down=0.0,
            probability_flat=0.0,
            confidence=0.0,
            provenance="predictive_directional_unauthorized",
            tradeable=False,
            unavailable=True,
            missing=True,
            valid_contract=False,
            dominant_probability=0.0,
            probability_margin=0.0,
            expected_move_pts=(float(em) if em is not None else None),
            entry_ref=None,
        )

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

    fusion_ml = bool(ml_snap and ml_snap.horizon_fusion_available)
    provenance = f"predictive_mh_fusion_primary_{hz}"
    if not fusion_ml:
        env_blend = os.environ.get("ED_MH_FALLBACK_CANONICAL_BLEND", "0.0")
        try:
            wfb = float(env_blend)
        except ValueError:
            log.debug(
                "ED_MH_FALLBACK_CANONICAL_BLEND ignored (malformed) value=%r horizon=%s",
                env_blend,
                hz,
            )
            wfb = 0.0
        wfb = max(0.0, min(1.0, wfb))
        if canonical is not None and wfb > 0.0:
            # FIND-MHD-CANONICAL-PROV: gate blend on canonical provenance tradability.
            # Non-tradable canonical (fusion_unavailable / fusion_directional_missing /
            # fusion_directional_invalid / debug_override:*) carries max-entropy 1/3
            # placeholder probs (signal_types.NON_TRADABLE_CANONICAL_PROVENANCE);
            # blending them would inject synthetic conviction into the predictive triplet.
            if not is_canonical_tradable(canonical):
                provenance = f"predictive_empirical_fallback_{hz}_canonical_nontradable"
            else:
                cu = float_finite_or_none(getattr(canonical, "probability_up", None))
                cd = float_finite_or_none(getattr(canonical, "probability_down", None))
                cf = float_finite_or_none(getattr(canonical, "probability_flat", None))
                if cu is not None and cd is not None and cf is not None:
                    up = (1.0 - wfb) * up + wfb * cu
                    dn = (1.0 - wfb) * dn + wfb * cd
                    fl = (1.0 - wfb) * fl + wfb * cf
                    s = up + dn + fl
                    if s > 0 and math.isfinite(s):
                        up, dn, fl = up / s, dn / s, fl / s
                        provenance = f"predictive_empirical_fallback_{hz}_stabilized"
                    else:
                        provenance = f"predictive_empirical_fallback_{hz}_canonical_nonfinite"
                else:
                    provenance = f"predictive_empirical_fallback_{hz}_canonical_nonfinite"
        else:
            provenance = f"predictive_empirical_fallback_{hz}"

    dom, margin, call = _confidence_from_probs(up, dn, fl)
    miss = any(getattr(pred, f"{k}_prob_{hz}", None) is None for k in ("up", "down", "flat"))
    empirical_ok = (not miss) or fusion_ml or (canonical is not None)
    tradeable = (
        (call in ("long", "short"))
        and dom >= TRADEABLE_DOM_MIN
        and margin >= TRADEABLE_MARGIN_MIN
        and empirical_ok
    )
    # Price-action contract (operator 2026-06-11): per-horizon entry reference is
    # current price — never a key level (the old nearest_below/above reference
    # tied horizon rows to options-structure levels).
    entry_ref = (
        float_finite_or_none(getattr(inp, "spot", None)) if call in ("long", "short") else None
    )
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
        score += QUALITY_BOOST_FULLY_ALIGNED
    elif align_state == "mostly_aligned":
        score += QUALITY_BOOST_MOSTLY_ALIGNED
    elif align_state == "mixed":
        score -= QUALITY_PENALTY_MIXED
    elif align_state == "contradictory":
        score -= QUALITY_PENALTY_CONTRADICTORY
    if contradiction == "structural":
        score -= QUALITY_PENALTY_STRUCTURAL_CONTRADICTION
    elif contradiction == "tactical":
        score -= QUALITY_PENALTY_TACTICAL_CONTRADICTION
    score = max(0.0, min(1.0, score))
    if score >= QUALITY_THRESHOLD_A:
        return "A"
    if score >= QUALITY_THRESHOLD_B_PLUS:
        return "B+"
    if score >= QUALITY_THRESHOLD_B:
        return "B"
    if score >= QUALITY_THRESHOLD_C:
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
        state = ALIGNMENT_STATE_NO_PRIMARY
    elif con == 0 and sup >= ALIGNMENT_FULLY_ALIGNED_MIN_SUPPORT:
        state = "fully_aligned"
    elif con <= 1 and sup >= 1:
        state = "mostly_aligned"
    elif con >= ALIGNMENT_CONTRADICTORY_MIN_COUNT:
        state = "contradictory"
    elif weak >= ALIGNMENT_WEAK_MIN_COUNT:
        state = "weak"
    else:
        state = "mixed"

    contradiction_state = "none"
    if con >= ALIGNMENT_CONTRADICTORY_MIN_COUNT and primary.horizon in STRUCTURAL_HORIZONS_FOR_CONTRADICTION:
        contradiction_state = "structural"
    elif con >= 1:
        contradiction_state = "tactical"
    elif weak >= ALIGNMENT_WEAK_MIN_COUNT:
        contradiction_state = "weakness"

    return HorizonAlignmentReport(
        alignment_score=round(align_score, 4),
        contradiction_score=round(contradiction_score, 4),
        support_score=round(support_score, 4),
        conflict_level=(
            "high"
            if con >= ALIGNMENT_CONTRADICTORY_MIN_COUNT
            else "medium"
            if con == 1
            else "low"
        ),
        alignment_state=state,
        contradiction_state=contradiction_state,
        fully_aligned=(state == "fully_aligned"),
        mostly_aligned=(state == "mostly_aligned"),
        mixed=(state == "mixed"),
        contradictory=(state == "contradictory"),
        weak=(state == "weak"),
        no_primary=(state == ALIGNMENT_STATE_NO_PRIMARY),
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
    """
    Price-action entry states (operator 2026-06-11): timing comes from the 1c
    model plus a volatility-scaled band around current price — never key-level
    zones (the old nearest_below/nearest_above band was a key-level dependency).

    filled    → call engine reports ACTIVE with an entry price.
    forming   → 1c is tradeably AGAINST the pooled bias (counter-move running).
    armed     → bias live, waiting on 1c confirmation.
    confirmed → 1c agrees with bias at confirmation confidence.
    """
    if final_bias == "wait" or not tradeable:
        return ("no_setup", None, "No valid setup")
    spot = _finite_price_optional(getattr(inp, "spot", None))
    if spot is None:
        return ("no_setup", None, "missing or invalid spot")
    cs = str(call_state or "WAIT").upper()
    entry_px = _finite_price_optional(call_entry)
    if cs == "ACTIVE" and entry_px is not None:
        return ("filled", entry_px, f"{entry_px:.2f} (FILLED)")
    atr = _finite_price_optional(getattr(inp, "atr", None))
    band = f" (\u00b1{0.5 * atr:.2f})" if atr is not None and atr > 0.0 else ""
    opposing_1c = (
        one_c.tradeable
        and one_c.direction in ("long", "short")
        and one_c.direction != final_bias
    )
    if opposing_1c:
        return ("forming", None, f"Counter-move on 1c \u2014 wait for 1c to turn {final_bias}")
    confirm_1c = (
        one_c.direction == final_bias
        and one_c.confidence >= ENTRY_CONFIRMATION_CONFIDENCE_MIN
    )
    if not confirm_1c:
        return ("armed", None, f"Near {spot:.2f}{band}\nAwaiting 1c confirmation")
    if entry_px is not None:
        return ("confirmed", entry_px, f"{entry_px:.2f} (CONFIRMED)")
    return ("confirmed", spot, f"{spot:.2f} (CONFIRMED)")


@dataclass
class PooledConsensus:
    """ALL-card pooled evidence (operator 2026-06-11) — see pooling constants."""

    prob_up: Optional[float]
    prob_down: Optional[float]
    prob_flat: Optional[float]
    dominant_probability: float
    probability_margin: float
    eligible_horizons: list[str]
    weights: dict[str, float]
    weights_fallback_equal: bool
    final_bias: str  # long | short | wait
    wait_reason: str


def _pooled_consensus(
    hmap: dict[str, HorizonForecast],
    weights: dict[str, float],
    weights_fallback_equal: bool,
) -> PooledConsensus:
    """
    Logarithmic opinion pool over the valid horizon triplets: q_k ∝ Π p_hz,k^w_hz
    (weights normalized over eligible horizons). Entry requires the pooled triplet
    to pass the same dominance/margin gates as an individual horizon — evidence
    strength, not head-count. Fail-closed WAIT when fewer than
    CONSENSUS_MIN_VALID_HORIZONS horizons carry a valid triplet.
    """
    eligible: list[str] = []
    triplets: dict[str, tuple[float, float, float]] = {}
    for hz in PRODUCT_HORIZONS:
        f = hmap[hz]
        if f.missing or f.unavailable or not f.valid_contract:
            continue
        probs = [
            float_finite_or_none(f.probability_up),
            float_finite_or_none(f.probability_down),
            float_finite_or_none(f.probability_flat),
        ]
        if any(p is None or p < 0.0 for p in probs) or sum(p for p in probs) <= 0.0:  # type: ignore[operator]
            continue
        eligible.append(hz)
        triplets[hz] = (probs[0], probs[1], probs[2])  # type: ignore[assignment]

    if len(eligible) < CONSENSUS_MIN_VALID_HORIZONS:
        return PooledConsensus(
            prob_up=None, prob_down=None, prob_flat=None,
            dominant_probability=0.0, probability_margin=0.0,
            eligible_horizons=eligible, weights={}, weights_fallback_equal=weights_fallback_equal,
            final_bias="wait", wait_reason=WAIT_REASON_INSUFFICIENT_VALID_HORIZONS,
        )

    w_raw = {hz: max(0.0, float(weights.get(hz, 0.0))) for hz in eligible}
    w_sum = sum(w_raw.values())
    if w_sum <= 0.0:
        w_norm = {hz: 1.0 / len(eligible) for hz in eligible}
        weights_fallback_equal = True
    else:
        w_norm = {hz: w / w_sum for hz, w in w_raw.items()}

    log_q = [0.0, 0.0, 0.0]
    for hz in eligible:
        for k in range(3):
            log_q[k] += w_norm[hz] * math.log(max(triplets[hz][k], POOL_PROB_FLOOR))
    m = max(log_q)
    q_un = [math.exp(v - m) for v in log_q]
    z = sum(q_un)
    q = [v / z for v in q_un]
    q_sorted = sorted(q, reverse=True)
    dom = q_sorted[0]
    margin = dom - q_sorted[1]
    label = direction_from_normalized_triplet(q[0], q[1], q[2])

    if label is None:
        # RC-363 WITHHELD: non-finite pooled leg — never fall through to a
        # directional bias on a garbage triplet.
        bias, reason = "wait", WAIT_REASON_POOLED_FLAT
    elif label == "flat":
        bias, reason = "wait", WAIT_REASON_POOLED_FLAT
    elif dom < TRADEABLE_DOM_MIN or margin < TRADEABLE_MARGIN_MIN:
        bias, reason = "wait", _wait_reason_pooled_below_gate(dom, margin)
    else:
        bias, reason = ("long" if label == "up" else "short"), ""
    return PooledConsensus(
        prob_up=q[0], prob_down=q[1], prob_flat=q[2],
        dominant_probability=dom, probability_margin=margin,
        eligible_horizons=eligible, weights=w_norm,
        weights_fallback_equal=weights_fallback_equal,
        final_bias=bias, wait_reason=reason,
    )


_skill_weights_cache: dict[str, Any] = {"ts": 0.0, "weights": None, "fallback": True}


def _horizon_skill_weights_cached() -> tuple[dict[str, float], bool]:
    """
    Rolling skill weights from the calibration log (TTL-cached). Fail-closed to
    equal weights when the calibration DB is unavailable or under-sampled.
    """
    import time

    now = time.time()
    if (
        _skill_weights_cache["weights"] is not None
        and (now - float(_skill_weights_cache["ts"])) < SKILL_WEIGHTS_TTL_SEC
    ):
        return _skill_weights_cache["weights"], bool(_skill_weights_cache["fallback"])
    weights = {hz: 1.0 / len(PRODUCT_HORIZONS) for hz in PRODUCT_HORIZONS}
    fallback = True
    try:
        from calibration.daily_scoreboard import horizon_skill_weights
        from calibration.paths import DEFAULT_DB

        res = horizon_skill_weights(DEFAULT_DB)
        weights = dict(res["weights"])
        fallback = bool(res["fallback_equal"])
    except Exception as e:  # noqa: BLE001 — serve path must not die on calibration IO
        log.debug("horizon skill weights unavailable — equal-weight pool: %s", e)
    _skill_weights_cache.update({"ts": now, "weights": weights, "fallback": fallback})
    return weights, fallback


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
    if long_v >= CONSENSUS_MAJORITY_VOTE_MIN and short_v <= CONSENSUS_DISSENT_VOTE_MAX:
        return "long", long_v, short_v
    if short_v >= CONSENSUS_MAJORITY_VOTE_MIN and long_v <= CONSENSUS_DISSENT_VOTE_MAX:
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
