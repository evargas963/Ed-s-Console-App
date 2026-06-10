"""
Governed ML horizons — shared contract for stack ordering and Monte Carlo inputs.

Policy evaluation scripts historically read DB movement columns from XGB heads; live
`signals` path runs the unified seven-layer stack (xgb, lstm, transformer, meta,
monte_carlo, regime, fusion) as one team. This module holds small, testable helpers
so offline ablation and live serve converge without silent omission semantics.
"""
from __future__ import annotations

from typing import Any, Optional

from ml_horizon import ALL_GOVERNED_HORIZONS, ML_HORIZON_SLUGS

# ── Authoritative inference stack (operator binding 2026-06-04) ──
# All seven layers MUST appear in ablation manifests, stack eval, and agent docs.
# Do not omit a layer when describing the ML stack (mechanical lock:
# check_full_stack_models_contract in tools/check_fix_everything_we_touch.py).
FULL_STACK_MODEL_LAYERS: tuple[str, ...] = (
    "xgb",
    "lstm",
    "transformer",
    "meta",
    "monte_carlo",
    "regime",
    "fusion",
)
FULL_STACK_MODEL_DISPLAY: tuple[str, ...] = (
    "XGB",
    "LSTM",
    "Transformer",
    "Meta",
    "Monte Carlo",
    "Regime",
    "Bayesian Fusion",
)
FEATURE_ABLATION_ML_STACK_LAYERS: tuple[str, ...] = ("xgb", "lstm", "transformer")
FEATURE_ABLATION_BASE_MODELS = FEATURE_ABLATION_ML_STACK_LAYERS  # deprecated alias
STACK_AUTHORITY_LAYERS: tuple[str, ...] = ("meta", "monte_carlo", "regime", "fusion")
FEATURE_ABLATION_ALL_MODELS: tuple[str, ...] = FULL_STACK_MODEL_LAYERS

# Snapshot columns each stack layer reads for ablation placement (one layer per cell).
# Upper layers MUST NOT delegate to FEATURE_ABLATION_ML_STACK_LAYERS union knockouts.
REGIME_LAYER_SNAPSHOT_COLUMNS: frozenset[str] = frozenset(
    {
        "zone",
        "prev_zone",
        "vwap_side",
        "nearest_above_dist",
        "nearest_below_dist",
        "net_gamma",
        "spot",
        "pin_width_pts",
        "charm_direction",
        "charm_drift_toward",
        "candle_body_pts",
        "candle_range_pts",
        "dist_call_gamma_wall",
        "dist_put_gamma_wall",
        "iv_direction",
        "vix_bucket",
        "vix_level",
        "zone_since_bars",
        "zone_since_bars_1m",
    }
)

MONTE_CARLO_LAYER_SNAPSHOT_COLUMNS: frozenset[str] = frozenset(
    {
        "spot",
        "call_gamma_wall",
        "put_gamma_wall",
        "em_upper",
        "em_lower",
        "realized_vol",
        "atr",
        "garch_sigma_bars",
    }
)

# build_fusion_model_overlay raw keys minus MVP tabular + ticker + empirical pred_* outputs.
FUSION_OVERLAY_SNAPSHOT_COLUMNS: frozenset[str] = frozenset(
    {
        "et_hour",
        "et_minute",
        "candle_body_pts",
        "candle_range_pts",
        "zone_since_bars",
        "dist_call_gamma_wall",
        "dist_put_gamma_wall",
        "dist_call_delta_wall",
        "dist_put_delta_wall",
        "dist_gamma_inflection",
        "dist_delta_inflection",
        "dist_call_oi_wall",
        "dist_put_oi_wall",
        "dist_call_vanna_wall",
        "dist_put_vanna_wall",
        "pin_width_pts",
        "net_delta",
        "net_vanna",
        "charm_net",
        "iv_level",
        "put_call_oi_ratio",
        "spy_chg_pct",
        "qqq_chg_pct",
        "iwm_chg_pct",
        "spy_weighted_push",
        "qqq_weighted_push",
        "iwm_weighted_push",
        "vix_level",
        "vix_vs_prev",
        "prev_zone",
        "candle_direction",
        "session_bucket",
        "vix_bucket",
        "charm_direction",
        "charm_magnitude",
        "iv_direction",
        "qqq_vs_spy",
        "iwm_risk_signal",
        "candle_volume",
        "bid_ask_imbalance",
        "combined_signal",
        "combined_conviction",
        "atr",
        "iv_rank",
        "smart_money_score",
        "breakout_score",
        "pin_score",
        "minutes_since_open",
    }
)

# Meta-learner v2 tabular context — same raw overlay keys as fusion (minus pred_* / ticker).
# Ablation placement + production ingest share this registry (Fix-1 equal consumers).
META_LAYER_SNAPSHOT_COLUMNS: frozenset[str] = FUSION_OVERLAY_SNAPSHOT_COLUMNS

META_STACK_PROB_DIM: int = 9


def meta_tabular_feature_order() -> tuple[str, ...]:
    """Stable column order for meta tabular vector (ablation-aligned raw snapshot keys)."""
    return tuple(sorted(META_LAYER_SNAPSHOT_COLUMNS))

_STACK_LAYER_ABLATION_COLUMNS: dict[str, frozenset[str]] = {
    "regime": REGIME_LAYER_SNAPSHOT_COLUMNS,
    "monte_carlo": MONTE_CARLO_LAYER_SNAPSHOT_COLUMNS,
    "fusion": FUSION_OVERLAY_SNAPSHOT_COLUMNS,
    "meta": META_LAYER_SNAPSHOT_COLUMNS,
}


def stack_layer_ablation_snapshot_columns(model_family: str) -> frozenset[str]:
    """Registered snapshot columns a stack layer reads directly (ablation placement registry)."""
    key = str(model_family or "").strip().lower()
    if key in _STACK_LAYER_ABLATION_COLUMNS:
        return _STACK_LAYER_ABLATION_COLUMNS[key]
    if key in FEATURE_ABLATION_ML_STACK_LAYERS:
        from tools.build_feature_assignment_matrix_v2 import _registered_ml_columns

        reg = _registered_ml_columns()
        if key == "xgb":
            return frozenset(reg.get("xgb", set()))
        if key == "lstm":
            return frozenset(reg.get("lstm_5m", set()) | reg.get("lstm_1m", set()))
        if key == "transformer":
            try:
                from features.lstm_sequence_input import ENCODED_FEATURES_5M
            except ImportError:
                ENCODED_FEATURES_5M = ()
            return frozenset(ENCODED_FEATURES_5M)
    raise ValueError(f"stack_layer_ablation_snapshot_columns: unknown model_family {model_family!r}")


def atomic_column_consumed_by_stack_layer(column: str, model_family: str) -> bool:
    """True when ``column`` is in the layer's ablation snapshot registry."""
    col = str(column or "").strip()
    if not col:
        return False
    if col.startswith("cf_") and model_family in (
        "xgb",
        "regime",
        "monte_carlo",
        "fusion",
        "meta",
    ):
        return True
    return col in stack_layer_ablation_snapshot_columns(model_family)
# Tickers pooled into Stage 3 whole-stack scoring (not a grid axis).
ABLATION_ANCHOR_TICKERS: tuple[str, ...] = ("SPY", "QQQ", "IWM")
STAGE3_ABLATION_HORIZONS: tuple[str, ...] = ("1c", "5c", "15c", "60c")
FULL_STACK_MODEL_COUNT: int = len(FULL_STACK_MODEL_LAYERS)
assert FULL_STACK_MODEL_COUNT == 7
assert len(FULL_STACK_MODEL_DISPLAY) == FULL_STACK_MODEL_COUNT

# ── Production fused prediction path (operator binding 2026-06-05) ──
# The operator-facing probability is NOT per-base-model output. It is the contiguous
# production inference graph ending in bayesian_fusion.fuse + mc_fusion_adjustment.
#
# Layer roles (all seven in FULL_STACK_MODEL_LAYERS participate):
#   xgb, lstm, transformer — ML stack layers; direct evidence to bayesian_fusion.fuse
#   meta — stack_probs from base triplets; feeds monte_carlo drift via
#          mc_model_direction_inputs inside _run_model_stack (NOT a fuse() argument)
#   monte_carlo — simulate after bases+meta; post-fusion adjustment via mc_fusion_adjustment
#   regime — direct context to bayesian_fusion.fuse (with rules)
#   fusion — bayesian_fusion posterior + mc_fusion_adjustment (final triplet)
#
# Ablation whole-stack scoring MUST use the same entrypoints as live signals:
#   live: signals._compute_signals_impl → _run_model_stack → fuse → mc adjustment
#   ablation: stack_bundle_eval_v1._full_fusion_prob_for_row (same sequence)
PRODUCTION_FUSION_SCORE_LAYERS: tuple[str, ...] = FULL_STACK_MODEL_LAYERS
PRODUCTION_FUSION_LIVE_ENTRYPOINT = "signals._compute_signals_impl"
PRODUCTION_FUSION_ABLATION_ENTRYPOINT = (
    "arch_competition.stack_bundle_eval_v1._full_fusion_prob_for_row"
)
PRODUCTION_FUSION_FINAL_PREDICTION = (
    "bayesian_fusion.fuse + mc_fusion_adjustment.fuse_payload_apply_mc_adjustment"
)
META_PRODUCTION_ROLE = "stack_probs_feeds_monte_carlo_drift_not_bayesian_fuse_input"

# ── STACK-WIRE-4: named thresholds (Phase 6 ablation surface) ──
MC_ML_LAYER_WEIGHT_XGBOOST: float = 0.40
MC_ML_LAYER_WEIGHT_LSTM: float = 0.35
MC_ML_LAYER_WEIGHT_TRANSFORMER: float = 0.25
MC_BASE_MODEL_WEIGHT_XGBOOST = MC_ML_LAYER_WEIGHT_XGBOOST  # deprecated alias
MC_BASE_MODEL_WEIGHT_LSTM = MC_ML_LAYER_WEIGHT_LSTM  # deprecated alias
MC_BASE_MODEL_WEIGHT_TRANSFORMER = MC_ML_LAYER_WEIGHT_TRANSFORMER  # deprecated alias
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
    Derive Monte Carlo drift inputs from unified-stack ML layer outputs (never returns None probs).

    Precedence:
    1) Meta / weighted stack triplet in `stack_probs` when present.
    2) Renormalized average of available xgb/lstm/transformer ``prob_up`` / ``prob_down``.
    3) Explicit uniform (1/3, 1/3) with confidence \"low\" when no ML-layer tri-class signal exists.

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
        "xgboost": MC_ML_LAYER_WEIGHT_XGBOOST,
        "lstm": MC_ML_LAYER_WEIGHT_LSTM,
        "transformer": MC_ML_LAYER_WEIGHT_TRANSFORMER,
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
        return au, ad, conf, avail, "average_available_ml_layers"

    return (1.0 / 3.0, 1.0 / 3.0, "low", avail, "uniform_no_stack_tri_class_signal")


# Backward-compatible aliases for audit JSON / older callers.
UNIFORM_NO_STACK_TRI_CLASS_SIGNAL = "uniform_no_stack_tri_class_signal"
LEGACY_UNIFORM_MC_SOURCE = "uniform_no_base_tri_class_signal"
LEGACY_AVERAGE_AVAILABLE_ML_LAYERS = "average_available_base_models"


def _model_out_triplet_complete(out: Any) -> bool:
    if not getattr(out, "available", False):
        return False
    for key in ("prob_up", "prob_down", "prob_flat"):
        if getattr(out, key, None) is None:
            return False
    return True


def stack_probs_triplet_complete(stack_probs: Optional[dict[str, float]]) -> bool:
    if not isinstance(stack_probs, dict):
        return False
    for key in ("up", "down", "flat"):
        if stack_probs.get(key) is None:
            return False
    return True


def count_unified_stack_ml_layers_available(
    xgb_out: Any,
    lstm_out: Any,
    transformer_out: Any,
) -> int:
    """Count xgb/lstm/transformer layers that produced complete directional triplets this tick."""
    return sum(
        1
        for out in (xgb_out, lstm_out, transformer_out)
        if _model_out_triplet_complete(out)
    )


def unified_stack_team_can_authorize(
    *,
    xgb_out: Any,
    lstm_out: Any,
    transformer_out: Any,
    stack_probs: Optional[dict[str, float]],
) -> tuple[bool, str]:
    """Unified stack team gate — all three ML layers + meta/weighted stack_probs, or withhold together."""
    if stack_probs_triplet_complete(stack_probs):
        return True, "stack_probs_meta_or_weighted"
    if all(_model_out_triplet_complete(o) for o in (xgb_out, lstm_out, transformer_out)):
        return True, "unified_stack_ml_triplets"
    n = count_unified_stack_ml_layers_available(xgb_out, lstm_out, transformer_out)
    return False, f"unified_stack_incomplete_layers={n}"


def mc_team_should_fail_closed(
    team_ok: bool,
    mc_probability_source: str | None,
) -> bool:
    """Monte Carlo must not solo-green when the unified stack did not authorize scoring."""
    if not team_ok:
        return True
    src = (mc_probability_source or "").strip()
    if src in (UNIFORM_NO_STACK_TRI_CLASS_SIGNAL, LEGACY_UNIFORM_MC_SOURCE):
        return True
    return False


def mc_stack_probability_source_from_mapping(bundle: Optional[dict[str, Any]]) -> str | None:
    """Read canonical MC stack source from ml_bundle or ablation audit dict (legacy key fallback)."""
    if not isinstance(bundle, dict):
        return None
    src = bundle.get("mc_stack_probability_source")
    if src is not None:
        return str(src)
    legacy = bundle.get("mc_base_probability_source")
    return str(legacy) if legacy is not None else None


def derive_stack_layers_scored(
    *,
    xgb_out: Any,
    lstm_out: Any,
    transformer_out: Any,
    mc_out: Any,
    ml_bundle: Optional[dict[str, Any]],
    regime: Any,
    fusion_payload: Any,
) -> list[str]:
    """Layers that actually participated in one production fusion score (ordered subset of the 7).

    Meta is scored when stack_probs from the meta/weighted combiner fed MC drift
    (``mc_stack_probability_source == stack_probs_meta_or_weighted``) — the production path.
    Never return a hardcoded full list; only layers with evidence on this row.
    """
    from fusion_contract import fusion_is_authoritative
    from ml_predict import stack_probs_bundle_key

    scored: list[str] = []
    if getattr(xgb_out, "available", False):
        scored.append("xgb")
    if getattr(lstm_out, "available", False):
        scored.append("lstm")
    if getattr(transformer_out, "available", False):
        scored.append("transformer")

    bundle = ml_bundle if isinstance(ml_bundle, dict) else {}
    spk = stack_probs_bundle_key()
    stack_probs = bundle.get(spk)
    mc_src = mc_stack_probability_source_from_mapping(bundle)
    if (
        isinstance(stack_probs, dict)
        and stack_probs.get("up") is not None
        and stack_probs.get("down") is not None
        and stack_probs.get("flat") is not None
        and mc_src == "stack_probs_meta_or_weighted"
    ):
        scored.append("meta")

    if getattr(mc_out, "available", False):
        scored.append("monte_carlo")

    reg_primary = getattr(regime, "primary", None) if regime is not None else None
    if reg_primary not in (None, "", "unknown"):
        scored.append("regime")

    if fusion_payload is not None and fusion_is_authoritative(fusion_payload):
        scored.append("fusion")

    order = {name: idx for idx, name in enumerate(FULL_STACK_MODEL_LAYERS)}
    return sorted(scored, key=lambda name: order[name])


def classify_stack_health(
    *,
    fusion_available: bool,
    mc_available: bool,
    n_ml_layers_available: int,
    unified_stack_team_ok: bool | None = None,
) -> str:
    """
    Coarse health for operator surfaces (not a trading gate on its own).

    INVALID — unified stack team did not score together, fusion/MC withheld, or partial ML
    FULL    — tradable fusion + MC + all three xgb/lstm/transformer layers scored as one team
    """
    team_ok = unified_stack_team_ok
    if team_ok is None:
        team_ok = n_ml_layers_available >= 3 and fusion_available
    if not team_ok or not fusion_available or not mc_available:
        return "INVALID"
    if n_ml_layers_available >= 3:
        return "FULL"
    return "INVALID"
