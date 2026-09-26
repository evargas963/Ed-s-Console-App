"""
Governed ML horizons — shared contract for stack ordering and Monte Carlo inputs.

Policy evaluation scripts historically read DB movement columns from XGB heads; live
`signals` path runs the unified seven-layer stack (xgb, lstm, transformer, meta,
monte_carlo, regime, fusion) as one team. This module holds small, testable helpers
so offline ablation and live serve converge without silent omission semantics.
"""
from __future__ import annotations


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



























FULL_STACK_MODEL_COUNT: int = len(FULL_STACK_MODEL_LAYERS)
assert FULL_STACK_MODEL_COUNT == 7
assert len(FULL_STACK_MODEL_DISPLAY) == FULL_STACK_MODEL_COUNT



# Full inference loop uses all governed slugs (primary + secondary).
GOVERNED_STACK_HORIZONS: tuple[str, ...] = ALL_GOVERNED_HORIZONS
assert GOVERNED_STACK_HORIZONS == ML_HORIZON_SLUGS
























