"""
Governed ML horizons — shared contract for stack ordering and Monte Carlo inputs.

Policy evaluation scripts historically read DB movement columns from XGB heads; live
`signals` path runs base models → Monte Carlo → Bayesian fusion. This module holds
small, testable helpers so both paths can converge without silent omission semantics.
"""
from __future__ import annotations

from typing import Any, Optional

from ml_horizon import ALL_GOVERNED_HORIZONS, ML_HORIZON_SLUGS

# ── STACK-WIRE-4: named thresholds (Phase 6 ablation surface) ──
MC_BASE_MODEL_WEIGHT_XGBOOST: float = 0.40
MC_BASE_MODEL_WEIGHT_LSTM: float = 0.35
MC_BASE_MODEL_WEIGHT_TRANSFORMER: float = 0.25
MC_DIRECTION_CONFIDENCE_HIGH_THRESHOLD: float = 0.5
MC_DIRECTION_CONFIDENCE_MEDIUM_THRESHOLD: float = 0.4
# Display-only Key Levels wall-clock EFE/EAE (not used for sizing / fusion / ML features).
MC_DISPLAY_N_PATHS: int = 2000
MC_DISPLAY_WALL_CLOCK_MINUTES: tuple[int, ...] = (5, 15)

# Full inference loop uses all governed slugs (primary + secondary).
GOVERNED_STACK_HORIZONS: tuple[str, ...] = ALL_GOVERNED_HORIZONS
assert GOVERNED_STACK_HORIZONS == ML_HORIZON_SLUGS


def horizon_slug_to_mc_bars(slug: str) -> int:
    """Monte Carlo `horizon_bars` aligned to governed horizon slug (e.g. 13c → 13).

    NOTE (2026-06-01): this maps slug INTEGER → bar COUNT (5c→5 bars). Because the MC
    engine steps ``monte_carlo.BAR_MINUTES`` (currently 5) per bar, the resulting WALL-CLOCK
    forward time is ``bars × BAR_MINUTES`` — i.e. 5c → 25 minutes, NOT 5 minutes. That is a
    known misalignment vs the 1-minute `outcome_Nc` training labels (tracked in the feature
    matrix as a BLOCKING precondition before efe/eae feature-wiring). For TRUE wall-clock
    forward time, use ``wall_clock_minutes_to_mc_bars`` below.
    """
    su = str(slug or "").strip().lower()
    if not su.endswith("c"):
        raise ValueError(f"horizon_slug_to_mc_bars: invalid slug {slug!r}")
    n = int(su[:-1])
    if n < 1:
        raise ValueError(f"horizon_slug_to_mc_bars: non-positive bars in {slug!r}")
    return n


def wall_clock_minutes_to_mc_bars(minutes: int) -> int:
    """Convert a TRUE wall-clock horizon (in minutes) to MC ``horizon_bars``.

    The MC engine advances ``monte_carlo.BAR_MINUTES`` minutes per simulated bar. To get a
    genuine N-minute forward forecast, request ``N / BAR_MINUTES`` bars — e.g. with
    BAR_MINUTES=5: 5 min → 1 bar, 15 min → 3 bars. Used by the Key Levels display-only
    5m/15m EFE/EAE so the rows are labeled by real wall-clock minutes (NOT by the slug-integer
    path, which would over-simulate: horizon_bars=5 would be 25 minutes, the bug to avoid).

    Raises ValueError if ``minutes`` is not a positive whole multiple of BAR_MINUTES (e.g. a
    true 1-minute forecast is NOT representable while BAR_MINUTES=5 — that requires the
    BAR_MINUTES=1 alignment fix, tracked separately).
    """
    from monte_carlo import BAR_MINUTES

    m = int(minutes)
    if m < 1:
        raise ValueError(f"wall_clock_minutes_to_mc_bars: non-positive minutes {minutes!r}")
    if m % int(BAR_MINUTES) != 0:
        raise ValueError(
            f"wall_clock_minutes_to_mc_bars: {m} min is not a whole multiple of "
            f"BAR_MINUTES={BAR_MINUTES}; cannot represent without the BAR_MINUTES alignment fix"
        )
    return m // int(BAR_MINUTES)


def mc_model_direction_inputs(
    *,
    xgb_out: Any,
    lstm_out: Any,
    transformer_out: Any,
    stack_probs: Optional[dict[str, float]],
) -> tuple[float, float, str, dict[str, bool], str]:
    """
    Derive Monte Carlo drift inputs from base-model outputs (never returns None probs).

    Precedence:
    1) Meta / weighted stack triplet in `stack_probs` when present.
    2) Renormalized average of available XGB/LSTM/TR `prob_up` / `prob_down`.
    3) Explicit uniform (1/3, 1/3) with confidence \"low\" when no base tri-class signal exists.

    Returns:
        (model_prob_up, model_prob_down, model_confidence, availability_map, source_note)
    """
    avail = {
        "xgboost": bool(getattr(xgb_out, "available", False)),
        "lstm": bool(getattr(lstm_out, "available", False)),
        "transformer": bool(getattr(transformer_out, "available", False)),
    }
    if stack_probs and isinstance(stack_probs, dict):
        u = stack_probs.get("up")
        d = stack_probs.get("down")
        f = stack_probs.get("flat")
        if u is not None and d is not None and f is not None:
            tot = float(u) + float(d) + float(f)
            if tot > 0:
                nu, nd = float(u) / tot, float(d) / tot
                mx = max(nu, nd, float(f) / tot)
                conf = (
                    "high"
                    if mx >= MC_DIRECTION_CONFIDENCE_HIGH_THRESHOLD
                    else "medium"
                    if mx >= MC_DIRECTION_CONFIDENCE_MEDIUM_THRESHOLD
                    else "low"
                )
                return nu, nd, conf, avail, "stack_probs_meta_or_weighted"

    ups: list[float] = []
    dns: list[float] = []
    weights: list[float] = []
    wmap = {
        "xgboost": MC_BASE_MODEL_WEIGHT_XGBOOST,
        "lstm": MC_BASE_MODEL_WEIGHT_LSTM,
        "transformer": MC_BASE_MODEL_WEIGHT_TRANSFORMER,
    }
    for name, out, w in (
        ("xgboost", xgb_out, wmap["xgboost"]),
        ("lstm", lstm_out, wmap["lstm"]),
        ("transformer", transformer_out, wmap["transformer"]),
    ):
        if not getattr(out, "available", False):
            continue
        pu = float(getattr(out, "prob_up", 0.33) or 0.33)
        pd = float(getattr(out, "prob_down", 0.33) or 0.33)
        ups.append(pu)
        dns.append(pd)
        weights.append(w)

    if ups and weights:
        tw = sum(weights)
        au = sum(p * w for p, w in zip(ups, weights)) / tw
        ad = sum(p * w for p, w in zip(dns, weights)) / tw
        mx = max(au, ad, 1.0 - au - ad)
        conf = (
            "high"
            if mx >= MC_DIRECTION_CONFIDENCE_HIGH_THRESHOLD
            else "medium"
            if mx >= MC_DIRECTION_CONFIDENCE_MEDIUM_THRESHOLD
            else "low"
        )
        return au, ad, conf, avail, "average_available_base_models"

    return (1.0 / 3.0, 1.0 / 3.0, "low", avail, "uniform_no_base_tri_class_signal")


def classify_stack_health(
    *,
    fusion_available: bool,
    mc_available: bool,
    n_base_available: int,
) -> str:
    """
    Coarse health for operator surfaces (not a trading gate on its own).

    INVALID   — fusion unavailable, or MC unavailable (pre-fusion stage missing)
    FULL      — fusion + MC + all three base tabular/sequence models available
    PARTIAL   — fusion + MC + one or two base models available
    DEGRADED  — fusion + MC active but no base tri-class models available (stack runs on uniform MC drift prior)
    """
    if not fusion_available or not mc_available:
        return "INVALID"
    if n_base_available >= 3:
        return "FULL"
    if n_base_available >= 1:
        return "PARTIAL"
    return "DEGRADED"
