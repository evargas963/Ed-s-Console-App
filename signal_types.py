"""
signal_types.py
Corrected shared dataclasses for Phase 1 split.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime

from micro_structure import Candle, MicroRead

@dataclass
class SignalInput:
    """
    Current market state passed into the signals engine each refresh.
    Built by market_state.build_market_state from existing data structures.
    """
    # ── Identity ──────────────────────────────────────────────────────────────
    ticker:             str
    timeframe:          str             # primary timeframe (canonical: '1m')
    expiry:             Optional[str]
    dte:                Optional[int]

    # ── Price (empirical — highest weight) ────────────────────────────────────
    spot:               float
    candle_open:        Optional[float]
    candle_high:        Optional[float]
    candle_low:         Optional[float]
    candle_close:       Optional[float]
    candle_direction:   Optional[str]   # 'up', 'down', 'flat'
    candle_body_pts:    Optional[float]
    candle_range_pts:   Optional[float]

    # ── VWAP ─────────────────────────────────────────────────────────────────
    vwap:               Optional[float]
    vwap_side:          Optional[str]   # 'above', 'below'
    vwap_dist_pts:      Optional[float]

    # ── Zone ─────────────────────────────────────────────────────────────────
    zone:               Optional[str]   # 'pin_bull', 'pin_bear', 'pin_neutral', 'pin_chaos', 'breakout', 'breakdown'
    prev_zone:          Optional[str]
    zone_since_bars:    Optional[int]   # alias for zone_since_bars_1m (model/DB backward compat)

    # ── Key levels (absolute strikes) ────────────────────────────────────────
    call_gamma_wall:    Optional[float]
    put_gamma_wall:     Optional[float]
    call_delta_wall:    Optional[float]
    put_delta_wall:     Optional[float]
    gamma_inflection:   Optional[float]
    delta_inflection:   Optional[float]
    call_oi_wall:       Optional[float]
    put_oi_wall:        Optional[float]
    call_vanna_wall:    Optional[float]
    put_vanna_wall:     Optional[float]
    pin_width_pts:      Optional[float]

    # ── Level distances (positive = above spot, negative = below) ────────────
    dist_call_gamma_wall:   Optional[float]
    dist_put_gamma_wall:    Optional[float]
    dist_call_delta_wall:   Optional[float]
    dist_put_delta_wall:    Optional[float]
    dist_gamma_inflection:  Optional[float]
    dist_delta_inflection:  Optional[float]
    dist_call_oi_wall:      Optional[float]
    dist_put_oi_wall:       Optional[float]
    dist_call_vanna_wall:   Optional[float] = None
    dist_put_vanna_wall:    Optional[float] = None

    # ── Nearest levels ────────────────────────────────────────────────────────
    nearest_above_name: Optional[str]  = None
    nearest_above_val:  Optional[float] = None
    nearest_above_dist: Optional[float] = None
    nearest_below_name: Optional[str]  = None
    nearest_below_val:  Optional[float] = None
    nearest_below_dist: Optional[float] = None

    # ── Greeks (structural forces — medium weight) ────────────────────────────
    net_gamma:          Optional[float] = None
    net_delta:          Optional[float] = None
    net_vanna:          Optional[float] = None
    charm_net:          Optional[float] = None
    charm_direction:    Optional[str]   = None   # 'buying', 'selling', 'neutral'
    charm_drift_toward: Optional[float] = None
    charm_magnitude:    Optional[str] = None   # 'large', 'moderate', 'small', 'negligible'
    dex_magnitude:      Optional[str] = None   # 'large', 'moderate', 'small', 'negligible'
    iv_level:           Optional[float] = None
    iv_direction:       Optional[str] = None   # 'expanding', 'contracting', 'flat'
    realized_vol:       Optional[float] = None  # annualized realized vol (decimal)
    atr:                Optional[float] = None  # ATR in price points
    garch_sigma_bars:   Optional[list]  = None  # per-bar GARCH+blend sigma forecast
    put_call_oi_ratio:  Optional[float] = None
    oi_center:          Optional[float] = None

    # ── Level crossing events since last refresh ──────────────────────────────
    recent_crosses:     list = field(default_factory=list)
    # Each cross: {'level_name': str, 'direction': 'up'/'down', 'bars_ago': int}

    # ── Level test counts today ───────────────────────────────────────────────
    ceiling_tests_today:    int = 0   # times price tested call gamma wall
    floor_tests_today:      int = 0   # times price tested put gamma wall

    # ── Cross-instrument (lower weight) ──────────────────────────────────────
    spy_zone:           Optional[str]  = None
    spy_vwap_side:      Optional[str]  = None
    spy_chg_pct:        Optional[float] = None

    qqq_zone:           Optional[str]  = None
    qqq_vwap_side:      Optional[str]  = None
    qqq_chg_pct:        Optional[float] = None
    qqq_vs_spy:         Optional[str]  = None   # 'leading', 'lagging', 'inline'
    qqq_vs_spy_delta:   Optional[float] = None

    iwm_zone:           Optional[str]  = None
    iwm_vwap_side:      Optional[str]  = None
    iwm_chg_pct:        Optional[float] = None
    iwm_risk_signal:    Optional[str]  = None   # 'risk_on', 'risk_off', 'neutral'

    spy_weighted_push:  Optional[float] = None
    qqq_weighted_push:  Optional[float] = None
    iwm_weighted_push:  Optional[float] = None  # blend: holdings + sector proxies (see market_state)

    # ── Event / calendar (stack gating) ─────────────────────────────────────
    event_risk_level:   str             = "none"   # none | elevated | high
    event_risk_detail:  str             = ""

    # ── VIX ───────────────────────────────────────────────────────────────────
    vix_level:          Optional[float] = None
    vix_direction:      Optional[str]   = None
    vix_vs_prev:        Optional[float] = None   # VIX change vs previous close

    # ── Expected Move boundaries ──────────────────────────────────────────────
    em_upper:           Optional[float] = None   # expected move upper boundary (price)
    em_lower:           Optional[float] = None   # expected move lower boundary (price)

    # ── Time context ──────────────────────────────────────────────────────────
    et_hour:            Optional[int] = None
    et_minute:          Optional[int] = None
    mins_to_close:      Optional[float] = None
    session_bucket:     Optional[str] = None  # 'open','morning','midday','afternoon','close'
    vix_bucket:         Optional[str] = None  # 'vix_low','vix_normal','vix_elevated','vix_high'

    # Authoritative UTC epoch seconds for this refresh — same value as snapshots.ts_utc when server inserts.
    refresh_ts_utc:     Optional[float] = None

    # ── DB snapshot counts ────────────────────────────────────────────────────
    total_snapshots:    int = 0
    filled_snapshots:   int = 0

    # ── Order Flow (from order_flow_engine — stack input for The Call) ────────
    order_flow_score:      Optional[float] = None   # -1 to 1
    order_flow_direction:  Optional[str]   = None  # 'bullish', 'bearish', 'neutral'
    order_flow_readiness:  Optional[str]   = None  # 'green', 'yellow', 'red'

    # ── Zone recency (no mixed-clock) — optional, see timeframe_config ──────────
    zone_since_bars_1m: Optional[int] = None   # execution-layer (1m bars), primary
    zone_since_bars_5m: Optional[int] = None   # structure-layer (5m bars), structure context only

    # ── ML / high-value features ──────────────────────────────────────────────
    candle_volume:         Optional[float] = None   # last completed bar volume
    flow_imbalance:        Optional[float] = None   # -1 to 1 or 0-1; alias bid_ask_imbalance
    spread:                Optional[float] = None   # bid-ask spread (pts)
    iv_rank:               Optional[float] = None   # 0-100
    smart_money_score:     Optional[float] = None   # 0-100
    breakout_score:        Optional[float] = None   # 0-100 normalized
    pin_score:             Optional[float] = None   # 0-100 normalized

    # ── Candle history (for micro-structure analysis) ──────────────────────────
    candles_5m:     list = field(default_factory=list)   # list of Candle objects (last 20 bars)
    candles_1m:     list = field(default_factory=list)

@dataclass
class CanonicalForecast:
    """
    Single forward directional belief for the decision stack (ML + MC + rules via Bayesian fusion).
    All stack votes, pred_agree checks, probability gates, and readiness direction must use this — not empirical histograms.
    """
    direction: str            # "up" | "down" | "flat"
    probability_up: float
    probability_down: float
    probability_flat: float
    confidence: str           # "low" | "medium" | "high" — fusion forward confidence (not empirical tier)
    provenance: str           # e.g. "bayesian_fusion", "fusion_unavailable", "debug_override:..."

    def dominant_probability(self) -> float:
        d = (self.direction or "flat").lower()
        if d == "up":
            return float(self.probability_up)
        if d == "down":
            return float(self.probability_down)
        return float(self.probability_flat)


# Uniform 1/3 placeholders in canonical_forecast_from_fusion are non-tradable; do not treat as real mass.
NON_TRADABLE_CANONICAL_PROVENANCE: frozenset[str] = frozenset(
    {
        "fusion_unavailable",
        "fusion_directional_missing",
        "fusion_directional_invalid",
        "missing_canonical_fallback",
    }
)


@dataclass
class RulesCard:
    """Card 1 — Right Now (micro price-action cockpit)

    Reports what the candles are DOING — not a directional trade call.
    Structure, patterns, BOS/CHoCH, compression, chop.
    The Call uses this to decide what to DO about it.
    """
    headline:       str     # 5-min structure read
    headline_1m:    str     # 1-min pattern read
    detail:         str     # 2-3 sentences — what to watch for
    zone_label:     str     # micro regime badge: 'TREND UP', 'BOS ↑', 'CHOP', etc.
    zone_color:     str     # hex color for the badge
    signal:         str     # structural bias: 'long', 'short', 'wait' (lean, not trade call)
    conviction:     str     # 'high', 'medium', 'low'
    alerts:         list    # urgent strings — BOS, CHoCH, compression, level tests
    micro:          Optional[object] = None

@dataclass
class PredictiveCard:
    """Card 3 — What the Data Says (prediction cockpit)

    **Historical** columns are empirical DB histograms per horizon (no standby 33/34 fiction).
    **Forward** fields mirror CanonicalForecast for display only — decisions use SignalOutput.canonical_forecast.
    """
    headline:           str             # narrative; separates historical vs forward where relevant
    prediction_dir:     str             # aligned with forward direction / target semantics ('up','down','flat','none')
    prediction_target:  Optional[float]  # level from historical avg move when forward lean exists
    # Historical match quality (outcome_5c similar-set — NOT the trade decision driver)
    historical_5c_dominant_dir: Optional[str]  # 'up', 'down', 'flat' when labeled 5c sufficient; None when withheld
    historical_5c_dominant_prob: Optional[float]
    empirical_confidence: Optional[str]  # 'low', 'medium', 'high' from tier/samples on 5c empirical only
    # Forward forecast (copy of canonical for card rendering)
    forward_direction:          str     # 'up', 'down', 'flat'
    forward_prob_up:            float
    forward_prob_down:          float
    forward_prob_flat:          float
    forward_confidence:         str     # fusion forward confidence
    forward_provenance:         str
    samples_used:       int
    model_note:         str             # full explanation (tier, reasoning, models)
    timeframe_reads:    dict
    # Probabilities per horizon — None when labeled count < MIN_SAMPLES_STATISTICAL (withheld, not neutral fiction)
    up_prob_1c:         Optional[float] = None
    down_prob_1c:       Optional[float] = None
    flat_prob_1c:       Optional[float] = None
    up_prob_5c:         Optional[float] = None
    down_prob_5c:       Optional[float] = None
    flat_prob_5c:       Optional[float] = None
    avg_5c_pts:         Optional[float] = None
    move_range_lo:      Optional[float] = None   # expected move range low (pts)
    move_range_hi:      Optional[float] = None   # expected move range high (pts)
    reversal_risk:      Optional[float] = None   # 0.0-1.0, probability of opposite direction
    reversal_label:     str             = ""     # 'low', 'moderate', 'high'
    reversal_shortfall: Optional[float] = None   # avg pts move when reversal occurs (negative = loss)
    reversal_severity:  str             = ""     # 'mild', 'moderate', 'severe'
    match_tier:         int             = 7      # which relaxation tier matched (1-7)
    tier_label:         str             = ""     # "exact setup match", "zone + VWAP match", etc.
    model_source:       str             = "empirical_histogram_plus_fusion_forward"  # empirical bars + forward from fusion
    model_version:      str             = "rules_v1"
    pred_action:        str             = ""
    # Individual model outputs (from ml_predict.get_model_outputs) for stack visibility
    model_outputs:      Optional[dict]  = None  # {xgb,lstm,transformer}: {available,dominant,confidence}
    # Strict UI contract: keys 1m,5m,15m,60m → {up,down,flat,source}
    horizon_prob_bars: Optional[dict[str, Any]] = None
    # Last full-RTH eval (from eval_dashboard_metrics.json) — not training metrics
    eval_accuracy_oos:  Optional[float] = None
    eval_log_loss_oos:  Optional[float] = None
    eval_pnl_realized_contract_oos: Optional[float] = None
    eval_realized_contract_metrics_oos: Optional[dict[str, Any]] = None
    # Product 15m / 60m clocks — empirical outcome_15c / outcome_60c only (or explicit insufficient neutral)
    up_prob_15c:        Optional[float] = None
    down_prob_15c:      Optional[float] = None
    flat_prob_15c:      Optional[float] = None
    avg_15c_pts:        Optional[float] = None
    up_prob_60c:        Optional[float] = None
    down_prob_60c:      Optional[float] = None
    flat_prob_60c:      Optional[float] = None
    avg_60c_pts:        Optional[float] = None
    # Movement-target v1 (XGB binary heads; pred_{hz}_* keys from ml_predict) — legacy / features
    movement_head_probs: Optional[dict[str, float]] = None
    # Flat snapshot columns fused_move_prob_{hz}, fused_dir_up_prob_{hz}, ... (policy authority)
    fusion_policy_snapshot_cols: Optional[dict[str, Any]] = None
    # Multi-horizon ML (per-horizon fusion) audit: empirical triplets before ML overlay (product horizons only)
    mh_empirical_product_triplets: Optional[dict[str, tuple[Optional[float], Optional[float], Optional[float]]]] = None
    # Per product horizon: fusion_ml_primary | empirical_support_blend | empirical_histogram
    mh_prob_source_by_horizon: Optional[dict[str, str]] = None
    # Machine-visible degradation / fallback audit (see features/stack_integrity_v1.py)
    stack_integrity_v1: Optional[dict[str, Any]] = None

@dataclass
class TheCall:
    """Card 2 — The Call (the trade order)

    Takes micro regime from Right Now + prediction from What the Data Says
    + Greeks + levels and produces a specific actionable trade.
    """
    signal:             str             # 'long', 'short', 'wait'
    conviction:         str             # 'high', 'medium', 'low'
    entry:              Optional[float]
    stop:               Optional[float]
    target:             Optional[float]     # T1: conservative structural target
    target2:            Optional[float]     # T2: runner target
    reward_risk:        Optional[float]     # R:R to T1
    reward_risk2:       Optional[float]     # R:R to T2
    headline:           str                 # plain English — what to do
    reasoning:          str                 # plain English — why
    trade_type:         str                 # 'trend_continuation', 'fade', 'breakout',
                                            # 'reversal', 'mean_reversion', 'none'
    invalidation:       str                 # "Invalid if 5min closes below 692.20"
    confluence_count:   int                 # X of Y signals aligned
    confluence_total:   int                 # total signal sources checked
    confluence_detail:  str                 # "micro trend + Greeks + data"
    time_qualifier:     str                 # "Setup valid ~15min" or ""
    size_cue:           str                 # "FULL" | "HALF" | "QUARTER" | "SKIP"
    rules_pred_agree:   bool
    time_warning:       Optional[str]       # None or warning if <2hrs to close
    size_note:          str
    # ── Trade Validation Gate — None until call_engine populates (no fabricated pass)
    validation_passed:  Optional[bool]  = None
    structure_valid:    Optional[bool]  = None
    probability_valid:  Optional[bool]  = None
    risk_valid:         Optional[bool]  = None
    validation_summary: str             = ""
    # ── Formal Position Sizing ────────────────────────────────────────────────
    r_units:            float           = 0.0     # 0.00 to 1.25
    execution_mode:     str             = "NO_TRADE"  # NO_TRADE, PROBE, REDUCED, STANDARD, MAX
    sizing_multipliers: dict            = field(default_factory=dict)
    sizing_reasons:     list            = field(default_factory=list)
    sizing_summary:     str             = ""
    # ── Call Readiness (V1 deterministic model from setup_readiness) ───────────
    readiness_score:    int             = 0      # 0–100
    call_state:         str             = "WAIT"  # WAIT | WATCH | ACTIVE
    wait_blocker:       Optional[dict]  = None   # when signal=wait: {reason, long_count?, short_count?, threshold?, gate_reasons?, detail?}
    forecast_state:     str             = "dormant"  # dormant | forming | near_trigger | active
    readiness_reasons:  list            = field(default_factory=list)
    missing_conditions: list            = field(default_factory=list)
    readiness_component_scores: dict    = field(default_factory=dict)
    # ── Put Readiness (V1, bearish mirror) ─────────────────────────────────────
    put_readiness_score: int           = 0
    put_state:           str           = "WAIT"
    put_forecast_state:  str           = "dormant"
    put_readiness_reasons: list        = field(default_factory=list)
    put_missing_conditions: list       = field(default_factory=list)
    put_readiness_component_scores: dict = field(default_factory=dict)
    # ── Replay / eval (1m bars cap for time_expiry; from Call policy, not inferred in isolation) ──
    replay_max_hold_bars: int          = 0

# ═══════════════════════════════════════════════════════════════════════════════
# STACK DECISION PATH
# ═══════════════════════════════════════════════════════════════════════════════
# Fixed order: XGBoost → LSTM → Transformer → Monte Carlo → Fusion → Final Call

@dataclass
class StackStage:
    """One stage in the stack decision path."""
    stage_id:   str             # 'xgboost', 'lstm', 'transformer', 'monte_carlo', 'fusion', 'final_call'
    status:     str             # 'active' | 'inactive'
    direction:  Optional[str]   = None   # 'up' | 'down' | 'flat' | bias string
    confidence: Optional[str]   = None   # 'high' | 'medium' | 'low'
    probability: Optional[float] = None  # 0–1 when available
    note:       str             = ""     # short contribution summary


@dataclass
class StackDecisionPath:
    """Explicit ordered path through the model stack."""
    xgboost:      StackStage
    lstm:         StackStage
    transformer:  StackStage
    monte_carlo:  StackStage    # first-class stage: expansion/containment, skew, directional support
    fusion:       StackStage
    final_call:   StackStage


@dataclass
class SignalOutput:
    """Complete output from the signals engine."""
    rules:      RulesCard
    predictive: PredictiveCard
    call:       TheCall
    snapshot:   dict
    canonical_forecast: CanonicalForecast  # single truth for votes/gates/readiness (Issue 13)
    regime:     Optional[object] = None  # RegimePayload from regime_engine.py
    fusion:     Optional[object] = None  # FusionPayload from bayesian_fusion.py
    stack_decision_path: Optional[StackDecisionPath] = None
    vol_regime: Optional[object] = None  # VolRegimePayload from volatility_regime.py (policy layer)
    pred_override_source: Optional[str] = None  # set only when ED_CONSOLE_ALLOW_PRED_OVERRIDE=1
    multi_horizon_bundle: Optional[object] = None  # MultiHorizonForecastBundle (multi_horizon_decision.py)
    calibration_payload: Optional[dict[str, Any]] = None  # writer inputs; server owns persistence timing
