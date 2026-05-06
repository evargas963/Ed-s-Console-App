# market_state.py
"""
MarketState — single source of truth for the Ed Console UI.

Built once per refresh from raw inputs (quote, chain, greeks, signals).
Every card reads from this object. No card computes its own version of
any value. This eliminates discrepancies between cards.

Build order (dependencies flow downward):
  1. Raw inputs    — spot, bid, ask, contracts, walls, totals
  2. Regime        — zone, bias, pin_strength, net_delta
  3. Bias gate     — bias_resolved (exact match only)
  4. OE strike     — rec_strike, rec_side
  5. Signals       — entry, stop, target, R/R (via signals engine)
  6. OE gate pills — liq_ok, ratio, vol_oi (from strike scoring)
  7. Entry zone    — entry_zone_lo/hi from signals entry ± 0.25
  8. Display       — colors, labels, formatted strings
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from canonical_distances import canonical_nearest_distances
from math_probabilities import OE_SPREAD_TIGHT_MAX
from timeframe_config import CANONICAL_TIMEFRAME


# ─────────────────────────────────────────────────────────────────────────────
# ACTIONABLE BIAS — single definition used everywhere
# Tilt Bull, Tilt Bear, Chaos Zone etc. are NOT actionable.
# ─────────────────────────────────────────────────────────────────────────────
ACTIONABLE_BIAS = {"bull", "bear", "expansion"}

def is_bias_actionable(bias_signal: str | None) -> bool:
    """True only for Bull, Bear, Expansion — exact match, case-insensitive."""
    return (bias_signal or "").strip().lower() in ACTIONABLE_BIAS


# ─────────────────────────────────────────────────────────────────────────────
# ZONE DERIVATION — single definition used everywhere
# Derived from bias_signal + net_delta.
# ─────────────────────────────────────────────────────────────────────────────
def derive_zone(bias_signal: str | None, net_delta: float | None) -> str:
    """
    Map bias_signal → zone string consumed by signals engine and prediction DB.

    EXPANDED ZONES (preserves directional information for prediction matching):
      pin_bull    — positive gamma pin with bullish lean (Bull, Tilt Bull)
      pin_bear    — positive gamma pin with bearish lean (Bear, Tilt Bear)
      pin_neutral — positive gamma pin, balanced (Balanced, Neutral)
      pin_chaos   — very low pin strength, no structure (Chaos Zone)
      breakout    — negative gamma, expansion up (net_delta >= 0)
      breakdown   — negative gamma, expansion down (net_delta < 0)

    Why this matters: the prediction engine matches by zone. Old "pin" lumped
    bullish-pin against bearish-pin — fundamentally different setups treated
    identically. Now pin_bull only matches historical pin_bull setups.
    """
    b = (bias_signal or "").strip().lower()
    if b in ("bull", "tilt bull"):
        return "pin_bull"
    if b in ("bear", "tilt bear"):
        return "pin_bear"
    if b in ("balanced", "neutral"):
        return "pin_neutral"
    if b == "chaos zone":
        return "pin_chaos"
    if b == "expansion":
        nd = net_delta or 0.0
        return "breakout" if nd >= 0 else "breakdown"
    return "pin_neutral"  # safe default


# is_pin_zone() lives in math_exposure.py — centralized


# ─────────────────────────────────────────────────────────────────────────────
# COLOR HELPERS — single definition, no inline hex strings in UI
# ─────────────────────────────────────────────────────────────────────────────
def bias_color(bias_signal: str | None) -> str:
    b = (bias_signal or "").lower()
    if "bull" in b:  return "#166534"
    if "bear" in b:  return "#991b1b"
    if "expansion" in b: return "#92400e"
    return "#9ca3af"

def pin_color(pin_strength: str | None) -> str:
    p = (pin_strength or "")
    if p == "High":            return "#166534"
    if p == "Med":             return "#92400e"
    if p in ("Low","Very Low"): return "#9ca3af"
    return "#1a1a1a"

def nd_color(net_delta: float | None) -> str:
    if net_delta is None: return "#9ca3af"
    if net_delta > 0:     return "#166534"
    if net_delta < 0:     return "#991b1b"
    return "#9ca3af"

def zone_badge_color(zone_label: str | None) -> str:
    z = (zone_label or "").lower()
    if "breakdown" in z:  return "#92400e"
    if "breakout" in z:   return "#065f46"
    if "pin_bull" in z:   return "#166534"
    if "pin_bear" in z:   return "#991b1b"
    if "pin_chaos" in z:  return "#6d28d9"
    if "pin" in z:        return "#374151"  # neutral pin
    if "sell" in z:       return "#92400e"
    if "buy" in z:        return "#065f46"
    if "flip" in z or "regime" in z: return "#6d28d9"
    return "#374151"

def dte_style(dte: int | None) -> tuple[str, str]:
    """Returns (warn_text, color)."""
    if dte is None:  return ("", "#9ca3af")
    if dte == 0:     return ("⚠ 0DTE — size down, high decay", "#991b1b")
    if dte <= 2:     return (f"⚡ {dte}DTE — intraday only",   "#b45309")
    if dte <= 5:     return (f"📅 {dte}DTE — standard",         "#92400e")
    return               (f"📅 {dte}DTE — full structure ok",  "#166534")


# ─────────────────────────────────────────────────────────────────────────────
# MARKET STATE DATACLASS
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class MarketState:
    """
    Single source of truth for all UI cards.
    Built once per refresh by build_market_state().
    All fields have safe defaults so partial builds never crash the UI.
    """

    # ── Identity ─────────────────────────────────────────────────────────────
    ticker:             str             = ""
    selected_exp:       Optional[str]   = None
    session_label:      str             = "RTH"

    # ── Price ─────────────────────────────────────────────────────────────────
    spot:               Optional[float] = None
    bid:                Optional[float] = None
    ask:                Optional[float] = None
    spot_disp:          str             = "—"
    bid_disp:           str             = "—"
    ask_disp:           str             = "—"

    # ── Regime ────────────────────────────────────────────────────────────────
    bias_signal:        str             = "Neutral"
    pin_strength:       str             = "Very Low"
    net_delta:          Optional[float] = None      # share-equivalent
    net_gamma:          Optional[float] = None
    gex_magnitude:      str             = "negligible"  # large/moderate/small/negligible
    dex_magnitude:      str             = "negligible"
    zone:               str             = "pin"     # pin | breakout | breakdown

    # Regime colors (derived, not computed inline in UI)
    bias_color_css:     str             = "#9ca3af"
    pin_color_css:      str             = "#9ca3af"
    nd_color_css:       str             = "#9ca3af"
    nd_disp:            str             = "—"       # formatted with sign + commas

    # ── VIX / PCR ─────────────────────────────────────────────────────────────
    vix:                Optional[float] = None
    vix_regime:         str             = ""
    vix_color:          str             = "#9ca3af"
    vix_implication:    str             = ""
    pcr_val:            Optional[float] = None
    pcr_arrow:          str             = ""
    pcr_color:          str             = "#9ca3af"
    pcr_label:          str             = ""

    # ── IV Direction (for vanna context) ──────────────────────────────────────
    iv_direction:       str             = "flat"     # expanding | contracting | flat

    # ── Bias gate (single authoritative flag) ─────────────────────────────────
    bias_resolved:      bool            = False     # True only for Bull/Bear/Expansion
    nd_resolved:        bool            = False     # True when net_delta != 0

    # ── Options Expression ────────────────────────────────────────────────────
    rec_strike:         Optional[float] = None
    rec_side:           Optional[str]   = None      # "CALL" | "PUT"
    call_option_expiry: Optional[str]   = None      # YYYY-MM-DD from chain (The Call contract)
    call_option_right:  Optional[str]   = None      # CALL | PUT | WAIT
    is_no_trade:        bool            = True
    dte_warn:           str             = ""
    dte_color:          str             = "#9ca3af"

    # OE gate pills (all from score_option_expression on rec_strike)
    liq_ok:             bool            = False
    ratio:              Optional[float] = None      # delta/gamma ratio
    vol_oi:             Optional[float] = None      # volume/OI ratio
    spread:             Optional[float] = None

    # ── Entry zone — SINGLE SOURCE, wired to signals engine ───────────────────
    entry_zone_lo:      Optional[float] = None
    entry_zone_hi:      Optional[float] = None
    entry_zone_str:     str             = "—"

    # ── Signals engine outputs ────────────────────────────────────────────────
    # Right Now card
    rules_signal:       str             = "wait"
    rules_conviction:   str             = "low"
    zone_label:         str             = "—"
    zone_badge_css:     str             = "#374151"
    rules_headline:     str             = ""
    rules_headline_1m:  str             = ""
    rules_detail:       str             = ""
    rules_alerts:       list            = field(default_factory=list)
    # Session levels + sweeps from micro_structure
    session_high:       Optional[float] = None
    session_low:        Optional[float] = None
    last_sweep_type:    Optional[str]   = None   # 'sweep_high' or 'sweep_low'
    last_sweep_level:   Optional[float] = None
    last_sweep_held:    Optional[bool]  = None   # True = failed sweep (reversal)
    n_sweeps_today:     int             = 0
    # Trade Validation Gate
    validation_passed:  bool            = True
    structure_valid:    bool            = True
    probability_valid:  bool            = True
    risk_valid:         bool            = True
    validation_summary: str             = ""
    # Formal Position Sizing
    r_units:            float           = 0.0
    execution_mode:     str             = "NO_TRADE"
    sizing_summary:     str             = ""
    # The Call card — entry/stop/target are THE authoritative values
    call_signal:        str             = "wait"
    call_conviction:    str             = "low"
    entry:              Optional[float] = None
    stop:               Optional[float] = None
    target:             Optional[float] = None
    target2:            Optional[float] = None
    reward_risk:        Optional[float] = None
    reward_risk2:       Optional[float] = None
    entry_disp:         str             = "—"
    stop_disp:          str             = "—"
    target_disp:        str             = "—"
    target2_disp:       str             = "—"
    rr_disp:            str             = "—"
    rr2_disp:           str             = "—"
    call_headline:      str             = ""
    call_reasoning:     str             = ""
    trade_type:         str             = "none"
    trade_type_label:   str             = ""
    invalidation:       str             = ""
    confluence_count:   int             = 0
    confluence_total:   int             = 4
    confluence_detail:  str             = ""
    time_qualifier:     str             = ""
    replay_max_hold_bars: int           = 0   # 1m bars for eval time_expiry (Call policy)
    size_cue:           str             = "SKIP"
    rules_pred_agree:   bool            = False
    time_warning:       Optional[str]   = None
    size_note:          str             = ""
    # Contract/event (desk framing — not part of OE scoring)
    contract_context:   str             = ""
    event_risk_level:   str             = "none"   # none | elevated | high
    event_risk_detail:  str             = ""
    # ── Call Readiness (from TheCall / setup_readiness) ───────────────────────
    call_readiness_score:    int         = 0
    call_state:             str         = "WAIT"   # WAIT | WATCH | ACTIVE
    call_forecast_state:    str         = "dormant"
    call_readiness_reasons: list        = field(default_factory=list)
    call_missing_conditions: list        = field(default_factory=list)
    call_readiness_component_scores: dict = field(default_factory=dict)
    call_wait_blocker:     Optional[dict] = None   # when call_signal=wait: {reason, long_count?, short_count?, gate_reasons?, ...}
    # ── Put Readiness ─────────────────────────────────────────────────────────
    put_readiness_score:    int         = 0
    put_state:             str         = "WAIT"
    put_forecast_state:     str         = "dormant"
    put_readiness_reasons:  list        = field(default_factory=list)
    put_missing_conditions: list        = field(default_factory=list)
    put_readiness_component_scores: dict = field(default_factory=dict)

    # ── Multi-horizon decision engine (single authority + MHAP explainability) ─
    final_bias:          str             = "WAIT"
    final_confidence:    Optional[float] = None
    final_quality:       str             = "D"
    final_tradeable:     bool            = False
    primary_horizon:     str             = "1c"
    trade_mode:          str             = "intraday"
    alignment_state_display: str         = "unusable"
    conflict_level_display: str          = "high"
    contradiction_state: str             = "none"
    supporting_horizon_summary: str      = ""
    entry_state:         str             = "no_setup"  # no_setup|forming|armed|confirmed|filled
    entry_display_text:  str             = "No valid setup"
    stop_display_text:   str             = "—"
    targets_display:     str             = "—"
    hold_style:          str             = "Wait / no setup"
    size_modifier_display: str           = "0.00x"
    risk_note:           str             = ""
    wait_reason:         str             = ""
    decision_provenance: str             = ""
    mhap_rows:           list            = field(default_factory=list)  # [{horizon, role, call, confidence, entry_ref, effect, row_state}]
    mhap_legend:         dict            = field(default_factory=lambda: {
        "primary": "Blue = Primary horizon",
        "aligned": "Green = Aligned/supportive",
        "weak": "Yellow = Weak/mixed",
        "contradictory": "Red = Contradictory",
    })

    # What the Data Says — horizon bars (strict contract: only this card renders them)
    horizon_prob_bars:  Optional[dict]  = None
    eval_accuracy_oos:  Optional[float] = None
    eval_log_loss_oos:  Optional[float] = None
    eval_pnl_realized_contract_oos: Optional[float] = None
    eval_realized_contract_metrics_oos: Optional[dict] = None

    # What the Data Says card — None when signals failed/unavailable (do not render fake 33/34/33)
    pred_headline:      str             = ""
    up_prob_1c:         Optional[float] = None
    down_prob_1c:       Optional[float] = None
    flat_prob_1c:       Optional[float] = None
    up_prob_3c:         Optional[float] = None
    down_prob_3c:       Optional[float] = None
    flat_prob_3c:       Optional[float] = None
    up_prob_5c:         Optional[float] = None
    down_prob_5c:       Optional[float] = None
    flat_prob_5c:       Optional[float] = None
    up_prob_8c:         Optional[float] = None
    down_prob_8c:       Optional[float] = None
    flat_prob_8c:       Optional[float] = None
    up_prob_13c:        Optional[float] = None
    down_prob_13c:      Optional[float] = None
    flat_prob_13c:      Optional[float] = None
    up_prob_15c:        Optional[float] = None
    down_prob_15c:      Optional[float] = None
    flat_prob_15c:      Optional[float] = None
    up_prob_60c:        Optional[float] = None
    down_prob_60c:      Optional[float] = None
    flat_prob_60c:      Optional[float] = None
    # Movement-target v1 XGB heads: pred_{hz}_dir_* / pred_{hz}_move_* (legacy features)
    movement_head_probs: Optional[dict] = None
    fusion_policy_snapshot_cols: Optional[dict] = None
    # Predictive card — Issue 13: dominant_* = canonical forward (decision-aligned); historical_* = empirical 5c only
    dominant_dir:       Optional[str]   = None
    dominant_prob:      Optional[float] = None
    confidence:         str             = "low"   # forward (fusion) confidence for trader-facing fallback
    historical_5c_dominant_dir: Optional[str] = None
    historical_5c_dominant_prob: Optional[float] = None
    empirical_confidence: str = "low"
    forward_prob_up:    float = 0.33
    forward_prob_down:  float = 0.33
    forward_prob_flat:  float = 0.34
    forward_provenance: str = ""
    canonical_provenance: str = ""  # SignalOutput.canonical_forecast.provenance (decision driver; fusion policy)
    samples_used:       int             = 0
    model_note:         str             = ""
    model_version:      str             = "rules_v1"
    pred_model_source:  Optional[str]   = None   # 'ml', 'rules', 'statistical' — which engine produced probs
    pred_override_source: Optional[str] = None   # 'user', 'manual' — when user overrode prediction
    timeframe_reads:    dict            = field(default_factory=dict)
    avg_3c_pts:         Optional[float] = None
    avg_5c_pts:         Optional[float] = None
    avg_8c_pts:         Optional[float] = None
    avg_13c_pts:        Optional[float] = None
    avg_15c_pts:        Optional[float] = None
    avg_60c_pts:        Optional[float] = None

    # ── Reversal risk + expected shortfall ────────────────────────────────────
    reversal_risk:      Optional[float] = None   # probability of opposite direction
    reversal_label:     str             = ""     # 'low', 'moderate', 'high'
    reversal_shortfall: Optional[float] = None   # avg pts move when reversal occurs
    reversal_severity:  str             = ""     # 'mild', 'moderate', 'severe'

    # ── Volatility regime (from volatility_regime.py — policy layer) ─────────
    vol_regime:         str             = "unknown"  # compression | expansion | unstable
    vol_regime_summary: str             = ""
    vol_regime_conviction_mult: float   = 1.0
    vol_regime_risk_mult: float         = 1.0

    # ── Order Flow (from order_flow_engine.py — inside Market Regime) ────────────
    order_flow_score:              Optional[float] = None
    order_flow_direction:          str             = "neutral"
    order_flow_regime:             str             = "neutral"
    order_flow_readiness:          str             = "red"
    book_imbalance_5:              Optional[float] = None
    cum_delta_proxy:               Optional[float] = None
    options_flow_score:            Optional[float] = None
    institutional_flow_proxy_score: Optional[float] = None
    # Flow Verdict (composite headline)
    order_flow_verdict:            str             = "FLOW NEUTRAL"
    order_flow_verdict_color:      str             = "gray"
    order_flow_arrow:              str             = "→"
    order_flow_agreement:          str             = "weak | conflicted"
    # Per-field arrows and labels
    order_flow_score_arrow:        str             = "→"
    order_flow_score_label:        str             = "neutral"
    order_flow_book_arrow:         str             = "→"
    order_flow_book_label:         str             = "balanced"
    order_flow_delta_arrow:        str             = "→"
    order_flow_opt_arrow:          str             = "→"
    order_flow_opt_label:          str             = "neutral"

    # ── Market regime (from regime_engine.py) ─────────────────────────────────
    regime_primary:     str             = "unknown"  # pinning, acceleration, breakout, etc.
    regime_secondary:   list            = field(default_factory=list)  # secondary tags
    regime_confidence:  str             = "low"
    regime_score:       float           = 0.0
    regime_summary:     str             = ""
    regime_support:     list            = field(default_factory=list)
    regime_contradiction: list          = field(default_factory=list)

    # ── Bayesian fusion (from bayesian_fusion.py) ─────────────────────────────
    fusion_available:       bool            = False
    fusion_dominant:        str             = "unknown"
    fusion_dominant_prob:   float           = 0.0
    fusion_confidence:      str             = "low"
    fusion_confidence_score: float          = 0.0
    fusion_summary:         str             = ""
    fusion_breakout:        float           = 0.0
    fusion_pinning:         float           = 0.0
    fusion_continuation:    float           = 0.0
    fusion_reversal:        float           = 0.0
    fusion_vol_expansion:   float           = 0.0
    fusion_mean_reversion:  float           = 0.0
    fusion_model_agreement: float           = 0.0
    fusion_agreement_label: str             = "low"
    fusion_n_models_active: int             = 0
    fusion_prob_up:         float           = 0.33
    fusion_prob_down:       float           = 0.33
    fusion_prob_flat:       float           = 0.34
    fusion_dominant_direction: str          = "flat"
    fusion_evidence:        list            = field(default_factory=list)
    fusion_contradictions:  list            = field(default_factory=list)
    fusion_mc_contribution: Optional[dict]  = None

    option_chain_selection_proof: Optional[dict] = None
    # Monte Carlo pass-through
    mc_available:           bool            = False
    mc_containment:         Optional[float] = None
    mc_expansion:           Optional[float] = None
    mc_efe:                 Optional[float] = None
    mc_eae:                 Optional[float] = None
    mc_upper_50:            Optional[float] = None
    mc_lower_50:            Optional[float] = None
    mc_paths:               Optional[int]   = None
    mc_horizon:             Optional[int]   = None
    mc_vol_source:          Optional[str]   = None
    mc_sigma_value:         Optional[float] = None

    # ── Individual model outputs (stack visibility from ml_predict) ───────────
    xgb_available:          Optional[bool]  = None
    xgb_dominant:           Optional[str]   = None   # 'up', 'down', 'flat'
    xgb_confidence:         Optional[float] = None
    xgb_approved:           Optional[bool]  = None
    lstm_available:         Optional[bool]  = None
    lstm_dominant:          Optional[str]   = None
    lstm_confidence:        Optional[float] = None
    lstm_approved:          Optional[bool]  = None
    transformer_available:  Optional[bool]  = None
    transformer_dominant:   Optional[str]   = None
    transformer_confidence: Optional[float] = None
    transformer_approved:   Optional[bool]  = None
    # Raw P(up)/P(down)/P(flat) per base model for WDS mini-bars (JSON to UI)
    layer1_probs: Optional[dict] = None  # {"xgb": {up,down,flat}|None, "lstm": ..., "transformer": ...}

    # ── Stack decision path (ordered: XGB → LSTM → Transformer → MC → Fusion → Call) ───
    stack_decision_path:    Optional[list]  = None   # list of {stage_id, status, direction, confidence, probability, note}

    # ── Nearest levels (used by DB for similar-setup matching) ───────────────
    nearest_above_name: Optional[str]   = None
    nearest_above_val:  Optional[float] = None
    nearest_above_dist: Optional[float] = None   # non-negative: |nearest_above_val - spot|
    nearest_below_name: Optional[str]   = None
    nearest_below_val:  Optional[float] = None
    nearest_below_dist: Optional[float] = None   # non-negative: |spot - nearest_below_val|

    # ── VWAP side (used by DB for similar-setup matching) ─────────────────────
    vwap_side:          Optional[str]   = None   # 'above' | 'below'

    # ── Charm (time-decay drift) ──────────────────────────────────────────────
    # charm_direction is the raw signals-engine string: "buying" | "selling" | "neutral"
    # charm_direction_display is the UI string: "Bullish" | "Bearish" | "Neutral"
    charm_net:               Optional[float] = None
    charm_direction:         str             = "neutral"
    charm_direction_display: str             = "Neutral"
    charm_drift_toward:      Optional[float] = None
    charm_magnitude:         str             = "negligible"  # large/moderate/small/negligible
    charm_top_drivers:       list            = field(default_factory=list)

    # ── Feed card ─────────────────────────────────────────────────────────────
    live_on:            bool            = False

    # ── Additive context (liquidity behavior + news/sentiment; non-authoritative) ──
    liquidity_behavior: Optional[dict] = None
    news_context:       Optional[dict] = None


# ─────────────────────────────────────────────────────────────────────────────
# OE RECOMMENDATION — lives here so market_state has no circular imports
# Direction driven exclusively by The Call signal (long/short/wait)
# ─────────────────────────────────────────────────────────────────────────────
def _f_ms(v):
    """Safe float conversion."""
    try: return float(v)
    except: return None


def _oe_chain_row_snapshot(ct: dict | None) -> dict | None:
    """Subset of Schwab option row for audit/API (chain selection proof)."""
    if not ct:
        return None
    keys = (
        "symbol", "expirationDate", "expiration", "strikePrice", "putCall",
        "bid", "ask", "totalVolume", "volume", "openInterest", "gamma", "delta",
    )
    return {k: ct.get(k) for k in keys}


def _oe_first_contract_row(contracts: list, strike: float, side: str) -> dict | None:
    side_up = str(side).upper().strip()
    for ct in contracts:
        if (ct.get("putCall") or "").upper().strip() != side_up:
            continue
        sp = _f_ms(ct.get("strikePrice"))
        if sp is None or abs(float(sp) - float(strike)) >= 0.01:
            continue
        return ct
    return None


def _oe_composite_strike_row(
    *,
    contracts: list,
    spot: float,
    k: float,
    side: str,
    walls: list | None,
) -> tuple[float | None, list[str], dict]:
    """
    Single-strike OE audit row + composite score (same scoring as selection loop).
    Returns (score or None if unscorable, reasons, audit dict).
    """
    from math_exposure import score_option_expression

    row = _oe_first_contract_row(contracts, k, side)
    snap = _oe_chain_row_snapshot(row)
    oe = score_option_expression(contracts, spot, k, side, walls=walls)
    if oe is None:
        return None, [], {
            "strike": float(k),
            "side": side,
            "scored": False,
            "in_selection_pool": False,
            "chain_row": snap,
            "note": "score_option_expression returned None (missing strike/Greeks row?)",
        }

    score = float(oe.total_score_after_walls)
    reasons: list[str] = []

    if oe.liq_gate:
        reasons.append(f"Tight spread (${oe.spread:.2f} ≤ {OE_SPREAD_TIGHT_MAX})")
    elif oe.spread is not None:
        reasons.append(f"Wide spread (${oe.spread:.2f}) — partial liquidity score only")
    if oe.gamma_is_max:
        reasons.append("Max gamma strike")
    if (oe.wall_score_component or 0) > 0:
        reasons.append(
            f"Walls +{oe.wall_score_component:.3f} "
            f"(prox {oe.wall_proximity_component:.3f}, bias {oe.wall_bias_component:.3f})"
        )

    audit = {
        "strike": float(k),
        "side": side,
        "scored": True,
        "composite_score": round(score, 4),
        "total_score_before_walls": oe.total_score_before_walls,
        "total_score_after_walls": oe.total_score_after_walls,
        "wall_proximity_component": oe.wall_proximity_component,
        "wall_bias_component": oe.wall_bias_component,
        "wall_score_component": oe.wall_score_component,
        "wall_contribution_detail": oe.wall_contribution_detail,
        "reasons": reasons,
        "spread": oe.spread,
        "liq_gate_pass": oe.liq_gate,
        "spread_filter_pass": bool(oe.liq_gate),
        "delta_gamma_ratio": oe.delta_gamma_ratio,
        "vol_oi_ratio": oe.vol_oi_ratio,
        "volume": oe.volume,
        "open_interest": oe.open_interest,
        "gamma": oe.gamma,
        "delta": oe.delta,
        "chain_row": snap,
    }
    return score, reasons, audit


def recommend_option_expression(
    *,
    contracts: list,
    spot: float,
    call_signal: str | None,
    walls: list | None = None,
    selected_expiry: str | None = None,
) -> tuple[str, list[str], dict]:
    """
    Recommend CALL or PUT strike driven by The Call signal direction.
      long  → CALL (ATM or 1-strike ITM, best score via score_option_expression)
      short → PUT  (ATM or 1-strike ITM, best score)
      wait  → NO TRADE

    Third return value is an audit dict (chain rows, spread filter, why winner won).
    Uses score_option_expression() (math_probabilities via math_exposure) everywhere.
    """
    sig = (call_signal or "").strip().lower()
    base_proof: dict = {
        "code_path": "market_state.recommend_option_expression → math_probabilities.score_option_expression",
        "selected_expiry": selected_expiry,
        "spot": spot,
        "liquidity_spread_filter": {
            "max_spread_dollars": OE_SPREAD_TIGHT_MAX,
            "liq_gate": f"bid/ask spread ≤ {OE_SPREAD_TIGHT_MAX} → +5 liquidity points; else partial credit only",
        },
        "fallback_policy": (
            "NO TRADE if signal is wait, no contracts for side/expiry slice, or every candidate fails scoring. "
            "If quotes are missing so score_option_expression returns None for all strikes → NO TRADE. "
            "Otherwise highest composite score wins even when no strike passes liq_gate (wide spread)."
        ),
    }
    if sig == "long":
        side = "CALL"
    elif sig == "short":
        side = "PUT"
    else:
        return (
            "NO TRADE",
            ["No actionable signal — The Call says wait"],
            {**base_proof, "status": "no_trade", "reason": "call_signal_wait_or_unknown"},
        )

    side_contracts = [c for c in contracts if (c.get("putCall") or "").upper() == side]
    strikes = sorted({float(c["strikePrice"]) for c in side_contracts
                      if _f_ms(c.get("strikePrice")) is not None})
    if not strikes:
        return (
            "NO TRADE",
            [f"No {side} contracts in selected expiry"],
            {**base_proof, "status": "no_trade", "reason": "no_contracts_for_side", "side": side},
        )

    atm = min(strikes, key=lambda s: (abs(s - spot), s))
    if side == "CALL":
        itm_cands = [s for s in strikes if s <= spot]
        itm = max(itm_cands) if itm_cands else None
    else:
        itm_cands = [s for s in strikes if s >= spot]
        itm = min(itm_cands) if itm_cands else None

    candidates: list[float] = []
    for s in (atm, itm):
        if s is not None and s not in candidates:
            candidates.append(s)

    best_strike = None
    best_score = -999.0
    best_reasons: list[str] = []
    scored_rows: list[dict] = []
    pool_set = {float(x) for x in candidates}

    for k in candidates:
        score, reasons, audit = _oe_composite_strike_row(
            contracts=contracts, spot=spot, k=float(k), side=side, walls=walls
        )
        audit["in_selection_pool"] = float(k) in pool_set
        scored_rows.append(audit)
        if score is None:
            continue

        if score > best_score:
            best_score = score
            best_strike = k
            best_reasons = list(reasons)

    full_ranked: list[tuple[float, dict]] = []
    for k in strikes:
        sc, _reasons, audit = _oe_composite_strike_row(
            contracts=contracts, spot=spot, k=float(k), side=side, walls=walls
        )
        audit["in_selection_pool"] = float(k) in pool_set
        if sc is not None:
            full_ranked.append((sc, audit))
    full_ranked.sort(key=lambda x: x[0], reverse=True)
    ranked_top = [dict(r[1]) for r in full_ranked[:5]]

    proof_out = {
        **base_proof,
        "status": "no_trade" if best_strike is None else "ok",
        "call_signal": sig,
        "side": side,
        "candidates": {
            "atm": float(atm),
            "one_strike_itm": float(itm) if itm is not None else None,
            "evaluated_strikes": [float(x) for x in candidates],
        },
        "chain_rows_scored": scored_rows,
        "ranked_candidates_top5": ranked_top,
        "ranked_universe": "all strikes for side in selected expiry, sorted by composite_score",
    }

    if best_strike is None:
        return (
            "NO TRADE",
            ["Unable to score candidate strikes"],
            {**proof_out, "reason": "all_candidates_unscorable"},
        )

    txt = str(int(best_strike)) if float(best_strike).is_integer() else str(best_strike)
    if not best_reasons:
        best_reasons = ["ATM / ITM candidate with best composite liquidity+gamma score"]
    proof_out["winner"] = {
        "expression": f"{txt} {side}",
        "strike": float(best_strike),
        "side": side,
        "composite_score": round(best_score, 4),
        "win_reasons": best_reasons,
        "selection_rule": "max composite_score among ATM + one ITM candidate vs spot",
    }
    any_liq = any(r.get("liq_gate_pass") for r in scored_rows if r.get("scored"))
    proof_out["liquidity_summary"] = {
        "any_candidate_passed_liq_gate": any_liq,
        "note": "Recommendation may still stand without liq_gate — see fallback_policy",
    }
    try:
        _bs = float(best_strike)
        _, _, _aud_w = _oe_composite_strike_row(
            contracts=contracts, spot=spot, k=_bs, side=side, walls=walls,
        )
        _, _, _aud_n = _oe_composite_strike_row(
            contracts=contracts, spot=spot, k=_bs, side=side, walls=None,
        )
        proof_out["wall_ablation_winner"] = {
            "with_walls_total_after": _aud_w.get("total_score_after_walls"),
            "without_walls_total_after": _aud_n.get("total_score_after_walls"),
            "wall_delta_on_winner": round(
                float(_aud_w.get("total_score_after_walls") or 0)
                - float(_aud_n.get("total_score_after_walls") or 0),
                4,
            ),
        }
    except Exception:
        proof_out["wall_ablation_winner"] = {"error": "ablation_compute_failed"}

    return (f"{txt} {side}", best_reasons, proof_out)


def _oe_bid_ask_mid(contracts, strike: float, side: str):
    su = str(side).upper().strip()
    try:
        kf = float(strike)
    except Exception:
        return None, None, None
    for ct in contracts or []:
        if str(ct.get("putCall", "")).upper().strip() != su:
            continue
        sp = ct.get("strikePrice")
        if sp is None:
            continue
        try:
            if abs(float(sp) - kf) >= 0.01:
                continue
        except Exception:
            continue
        try:
            b = float(ct.get("bid")) if ct.get("bid") is not None else None
            a = float(ct.get("ask")) if ct.get("ask") is not None else None
        except (TypeError, ValueError):
            b = a = None
        mid = (b + a) / 2.0 if b is not None and a is not None else None
        return b, a, mid
    return None, None, None


def _build_contract_context_ms(ms: "MarketState", contracts: list) -> str:
    """Contract-first framing: DTE, strike/right, breakeven when bid/ask exist."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    exp = ms.call_option_expiry or ms.selected_exp
    k = ms.rec_strike
    side = (ms.call_option_right or ms.rec_side or "").upper().strip()
    t = (ms.ticker or "").upper().strip()
    csig = (ms.call_signal or "wait").strip().lower()
    if csig == "wait" or ms.is_no_trade or side not in ("CALL", "PUT") or k is None or not exp:
        return ""
    try:
        d_exp = datetime.strptime(str(exp)[:10], "%Y-%m-%d").date()
        d0 = datetime.now(ZoneInfo("America/New_York")).date()
        dte = (d_exp - d0).days
    except Exception:
        dte = None
    dte_part = " · 0DTE" if dte == 0 else (f" · {dte}DTE" if dte is not None and dte > 0 else "")
    try:
        kf = float(k)
        strike_disp = str(int(kf)) if kf.is_integer() else str(kf)
    except Exception:
        strike_disp = str(k)
    leg = f"{t} {str(exp)[:10]} {strike_disp}{'C' if side == 'CALL' else 'P'}{dte_part}"
    bid, ask, mid = _oe_bid_ask_mid(contracts, float(k), side)
    try:
        spot_f = float(ms.spot) if ms.spot is not None else None
    except (TypeError, ValueError):
        spot_f = None
    parts = [leg]
    if mid is not None and spot_f is not None:
        fk = float(k)
        be = fk + mid if side == "CALL" else fk - mid
        parts.append(f"mid≈{mid:.2f} → BE≈{be:.2f} vs spot {spot_f:.2f}")
    elif bid is not None and ask is not None:
        parts.append(f"bid/ask {bid:.2f}/{ask:.2f} (mid needed for breakeven)")
    else:
        parts.append("marks missing — no breakeven")
    return " · ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# BUILDER — the one function that populates MarketState
# ─────────────────────────────────────────────────────────────────────────────
def build_market_state(
    *,
    ticker: str,
    selected_exp: str | None,
    session_label: str,
    spot: float | None,
    bid: float | None,
    ask: float | None,
    consensus_summary,          # ExposureRow from math_exposure
    contracts_use: list,        # filtered contract list
    walls: list,                # WallsRow list
    totals: list,               # TotalsRow list
    price_levels,               # PriceLevels from market_context
    mkt_ctx,                    # MarketContext from market_context
    live_on: bool,
    zone_since_bars: int,       # zone_since_bars_1m value (alias param for backward compat)
    zone_since_bars_5m: int = 0, # 5m, structure-layer recency
    prev_zone: str | None,
    # DB counts
    ceiling_tests_today: int = 0,
    floor_tests_today: int = 0,
    recent_crosses: list = None,
    total_snapshots: int = 0,
    filled_snapshots: int = 0,
    # Time
    et_hour: int = 9,
    et_minute: int = 30,
    mins_to_close: float = 390.0,
    # Charm — computed by server BEFORE calling this function, passed in directly
    # so the signals engine receives real charm values (not placeholders)
    charm_net: float | None = None,
    charm_direction: str = "neutral",        # "buying" | "selling" | "neutral"
    charm_drift_toward: float | None = None, # gamma pin strike
    charm_magnitude: str = "negligible",     # "large" | "moderate" | "small" | "negligible"
    charm_top_drivers: list | None = None,   # top 5 strikes driving charm flow
    # IV direction — computed by server from _IVTracker
    iv_direction: str = "flat",             # "expanding" | "contracting" | "flat"
    # Candle momentum — derived from prev_spot in server.py
    candle_direction: str | None = None,  # 'up', 'down', 'flat'
    candle_body_pts: float | None = None, # absolute point move since last refresh
    # Candle history — OHLCV bars from Schwab price history API
    candles_5m: list = None,   # list of Candle objects (5-min bars, last 20)
    candles_1m: list = None,   # list of Candle objects (1-min bars, last 20)
    # Expected Move boundaries (for MC simulation)
    em_upper: float | None = None,
    em_lower: float | None = None,
    # Volatility context for MC v2
    realized_vol: float | None = None,
    atr: float | None = None,
    garch_sigma_bars: list | None = None,
    # ML / high-value features (from server)
    candle_volume: float | None = None,
    flow_imbalance: float | None = None,
    spread: float | None = None,
    iv_rank: float | None = None,
    smart_money_score: float | None = None,
    breakout_score: float | None = None,
    pin_score: float | None = None,
    # Order Flow Engine input (built by server from quote, chain, candles)
    order_flow_data: dict | None = None,
    # Optional DB handle for signals
    db=None,
    # User prediction override — {direction: "up"|"flat"|"down", source: str}
    pred_override: dict | None = None,
    # Same instant as snapshots.ts_utc for this refresh (server: db.utc_ts() once per fetch)
    refresh_ts_utc: float | None = None,
) -> MarketState:
    """
    Build and return a fully-populated MarketState.
    This is the ONLY place any derived value is computed.
    """
    from math_exposure import (
        _f, score_option_expression,
        OE_DELTA_GAMMA_RATIO_MIN, OE_DELTA_GAMMA_RATIO_MAX,
        OE_VOL_OI_MIN,
        session_bucket as _sb_fn,
        vix_bucket as _vb_fn,
    )

    ms = MarketState()

    # ── 1. Identity + price ──────────────────────────────────────────────────
    ms.ticker       = ticker
    ms.selected_exp = selected_exp
    ms.call_option_expiry = selected_exp
    ms.session_label = session_label
    from event_risk import assess_event_risk
    ms.event_risk_level, ms.event_risk_detail = assess_event_risk(ticker)
    ms.live_on      = live_on
    ms.spot         = spot
    ms.bid          = bid
    ms.ask          = ask
    ms.spot_disp    = f"{spot:.2f}" if spot is not None else "—"
    ms.bid_disp     = f"{bid:.2f}"  if bid  is not None else "—"
    ms.ask_disp     = f"{ask:.2f}"  if ask  is not None else "—"
    spot_f          = float(spot) if spot is not None else 0.0

    # ── 2. Regime — from consensus_summary ──────────────────────────────────
    if consensus_summary is not None:
        ms.bias_signal  = str(getattr(consensus_summary, "bias_signal",  "") or "Neutral")
        ms.pin_strength = str(getattr(consensus_summary, "pin_strength", "") or "Very Low")
        _nd             = _f(getattr(consensus_summary, "net_delta", None))
        _ng             = _f(getattr(consensus_summary, "net_gamma", None))
        ms.net_delta    = _nd
        ms.net_gamma    = _ng
        ms.gex_magnitude = str(getattr(consensus_summary, "gex_magnitude", "negligible") or "negligible")
        ms.dex_magnitude = str(getattr(consensus_summary, "dex_magnitude", "negligible") or "negligible")
    else:
        ms.bias_signal  = "Neutral"
        ms.pin_strength = "Very Low"
        _nd             = None
        _ng             = None

    ms.bias_color_css = bias_color(ms.bias_signal)
    ms.pin_color_css  = pin_color(ms.pin_strength)
    ms.nd_color_css   = nd_color(ms.net_delta)
    ms.nd_disp        = f"{ms.net_delta:+,.0f}" if ms.net_delta is not None else "—"

    # ── 3. Zone — single derivation ─────────────────────────────────────────
    ms.zone = derive_zone(ms.bias_signal, ms.net_delta)

    # ── 3b. Order Flow Engine (inside Market Regime) ──────────────────────────
    if order_flow_data and isinstance(order_flow_data, dict):
        try:
            from order_flow_engine import OrderFlowEngine
            _of_result = OrderFlowEngine().compute(order_flow_data)
            ms.order_flow_score              = _of_result.get("order_flow_score")
            ms.order_flow_direction          = _of_result.get("order_flow_direction") or "neutral"
            ms.order_flow_regime             = _of_result.get("order_flow_regime") or "neutral"
            ms.order_flow_readiness          = _of_result.get("order_flow_readiness") or "red"
            ms.book_imbalance_5              = _of_result.get("book_imbalance_5")
            ms.cum_delta_proxy               = _of_result.get("cum_delta_proxy")
            ms.options_flow_score            = _of_result.get("options_flow_score")
            ms.institutional_flow_proxy_score = _of_result.get("institutional_flow_proxy_score")
            ms.order_flow_verdict             = _of_result.get("order_flow_verdict") or "FLOW NEUTRAL"
            ms.order_flow_verdict_color       = _of_result.get("order_flow_verdict_color") or "gray"
            ms.order_flow_arrow              = _of_result.get("order_flow_arrow") or "→"
            ms.order_flow_agreement          = _of_result.get("order_flow_agreement") or "weak | conflicted"
            ms.order_flow_score_arrow        = _of_result.get("order_flow_score_arrow") or "→"
            ms.order_flow_score_label        = _of_result.get("order_flow_score_label") or "neutral"
            ms.order_flow_book_arrow         = _of_result.get("order_flow_book_arrow") or "→"
            ms.order_flow_book_label         = _of_result.get("order_flow_book_label") or "balanced"
            ms.order_flow_delta_arrow        = _of_result.get("order_flow_delta_arrow") or "→"
            ms.order_flow_opt_arrow          = _of_result.get("order_flow_opt_arrow") or "→"
            ms.order_flow_opt_label          = _of_result.get("order_flow_opt_label") or "neutral"
        except Exception as _of_e:
            import logging
            logging.getLogger(__name__).warning(f"Order Flow Engine error: {_of_e}")

    # ── 4. VIX / PCR — from mkt_ctx ─────────────────────────────────────────
    ms.vix             = getattr(mkt_ctx, "vix",            None)
    ms.vix_regime      = getattr(mkt_ctx, "vix_regime",     "")
    ms.vix_color       = getattr(mkt_ctx, "vix_color",      "#9ca3af")
    ms.vix_implication = getattr(mkt_ctx, "vix_implication","")
    _pcr               = getattr(mkt_ctx, "pcr",            None)
    ms.pcr_val         = _f(_pcr)
    ms.pcr_arrow       = getattr(mkt_ctx, "pcr_arrow",      "")
    ms.pcr_color       = getattr(mkt_ctx, "pcr_color",      "#9ca3af")
    ms.pcr_label       = getattr(mkt_ctx, "pcr_label",      "")
    ms.iv_direction    = iv_direction or "flat"

    # ── 5. Bias gate — exact match only ─────────────────────────────────────
    ms.bias_resolved = is_bias_actionable(ms.bias_signal)
    ms.nd_resolved   = (ms.net_delta is not None) and (abs(ms.net_delta) > 1e-6)

    # ── 6. DTE styling (independent of direction) ───────────────────────────
    try:
        from datetime import datetime as _dt
        if selected_exp:
            _exp_date = _dt.strptime(selected_exp, "%Y-%m-%d").date()
            _dte      = (_exp_date - _dt.now().date()).days
            ms.dte_warn, ms.dte_color = dte_style(_dte)
    except Exception:
        pass

    # ── 7. Signals engine: enforces STACK ORDER 1–10 ──────────────────────────
    # compute_signals runs: vol_regime → regime → model stack → fusion → call (8,9,10)
    _sig_out = None
    _charm_dir = charm_direction if charm_direction in ("buying", "selling", "neutral") else "neutral"
    try:
        from crash_trace import step as _dstep, step_done as _ddone, trace_crash as _dcrash, _on as _don
    except ImportError:
        _don = lambda: False
        _dstep = _ddone = lambda n, t="": None
        def _dcrash(_sn, _ex, _t=""): pass
    try:
        if _don():
            _dstep("market_state_pre_signals", ticker)
        from signals import SignalInput, compute_signals
        from market_context import iwm_blended_participation_push

        _vwap_val  = getattr(price_levels, "vwap", None)
        _vwap_side = None
        if _vwap_val and spot_f:
            _vwap_side = "above" if spot_f > _vwap_val else "below"

        def _dist(lvl):
            if lvl is None or spot_f is None: return None
            return round(lvl - spot_f, 4)

        # Extract key levels from walls/price_levels
        _cgw = _pgw = _gi = _cdw = _pdw = _di = _coi = _poi = _cvw = _pvw = None
        if walls:
            w0 = walls[0]
            _cgw = _f(getattr(w0, "call_gamma_wall",  None))
            _pgw = _f(getattr(w0, "put_gamma_wall",   None))
            _cdw = _f(getattr(w0, "call_delta_wall",  None))
            _pdw = _f(getattr(w0, "put_delta_wall",   None))
            _coi = _f(getattr(w0, "call_oi_wall",     None))
            _poi = _f(getattr(w0, "put_oi_wall",      None))
            _cvw = _f(getattr(w0, "call_vanna_wall",  None))
            _pvw = _f(getattr(w0, "put_vanna_wall",   None))
        # Inflections come from ExposureRow (consensus_summary), not WallsRow
        if consensus_summary is not None:
            _gi = _f(getattr(consensus_summary, "gamma_inflection", None))
            _di = _f(getattr(consensus_summary, "delta_inflection", None))

        _pin_w = ((_cgw - _pgw) if _cgw and _pgw else None)

        # Nearest above/below
        _nearest_above_name = _nearest_above_val = None
        _nearest_below_name = _nearest_below_val = None
        _all_lvls = [
            (_cgw, "Call g-Wall"), (_pgw, "Put g-Wall"),
            (_gi,  "g-Inflection"), (_cdw, "Call d-Wall"),
            (_pdw, "Put d-Wall"),  (_di,  "D-Inflection"),
            (_coi, "Call OI Wall"),(_poi, "Put OI Wall"),
            (_vwap_val, "VWAP"),
        ]
        for _lv, _ln in _all_lvls:
            if _lv is None: continue
            if _lv > spot_f:
                if _nearest_above_val is None or _lv < _nearest_above_val:
                    _nearest_above_val  = _lv
                    _nearest_above_name = _ln
            elif _lv < spot_f:
                if _nearest_below_val is None or _lv > _nearest_below_val:
                    _nearest_below_val  = _lv
                    _nearest_below_name = _ln

        _nearest_above_dist, _nearest_below_dist = canonical_nearest_distances(
            spot_f, _nearest_above_val, _nearest_below_val
        )

        # ── Store nearest levels and vwap_side on MarketState for DB logging ──
        ms.nearest_above_name = _nearest_above_name
        ms.nearest_above_val  = _nearest_above_val
        ms.nearest_above_dist = _nearest_above_dist
        ms.nearest_below_name = _nearest_below_name
        ms.nearest_below_val  = _nearest_below_val
        ms.nearest_below_dist = _nearest_below_dist
        ms.vwap_side          = _vwap_side

        # Greeks — net gamma/delta from ExposureRow; charm passed in from server
        _net_gamma = _net_delta_sig = _net_vanna = None
        _iv_level  = _pcr_ratio = _oi_center = None
        if consensus_summary is not None:
            _oi_center = _f_ms(getattr(consensus_summary, "oi_center", None))
        if consensus_summary:
            _net_gamma     = _f(getattr(consensus_summary, "net_gamma", None)) or None
            _net_delta_sig = _f(getattr(consensus_summary, "net_delta", None)) or None
        if totals:
            t0 = totals[0]
            _iv_level  = _f(getattr(t0, "atm_iv", None)) or None
            _pcr_ratio = _f(getattr(t0, "pcr_oi", None)) or None
        # Charm: use values passed in from server (computed via compute_net_charm before this call)
        # "neutral"/"buying"/"selling" — signals engine needs exact these strings
        _charm_net = charm_net
        _charm_dir = charm_direction if charm_direction in ("buying", "selling", "neutral") else "neutral"
        _charm_toward = charm_drift_toward

        # Cross-instrument
        _spy_chg  = getattr(mkt_ctx, "spy_chg_pct",  None) or 0
        _qqq_chg  = getattr(mkt_ctx, "qqq_chg_pct",  None) or 0
        _iwm_chg  = getattr(mkt_ctx, "iwm_chg_pct",  None) or 0
        _qqq_delta = round(_qqq_chg - _spy_chg, 4) if (mkt_ctx.spy_chg_pct and mkt_ctx.qqq_chg_pct) else None
        _qqq_vs_spy = (None if _qqq_delta is None else
                       "leading" if _qqq_delta > 0.10 else
                       "lagging" if _qqq_delta < -0.10 else "inline")
        _iwm_risk = (None if mkt_ctx.iwm_chg_pct is None else
                     "risk_on"  if _iwm_chg > 0.10 else
                     "risk_off" if _iwm_chg < -0.10 else "neutral")

        # Time and volatility regime buckets for prediction matching
        _session_bkt = _sb_fn(et_hour, et_minute)
        _vix_bkt     = _vb_fn(mkt_ctx.vix) if mkt_ctx.vix is not None else None

        sig_inp = SignalInput(
            ticker=ticker, timeframe=CANONICAL_TIMEFRAME,
            expiry=selected_exp, dte=None,
            spot=spot_f,
            candle_open=getattr(price_levels, "today_open", None),
            candle_high=getattr(price_levels, "today_high", None),
            candle_low=getattr(price_levels,  "today_low",  None),
            candle_close=spot_f,
            candle_direction=candle_direction, candle_body_pts=candle_body_pts, candle_range_pts=None,
            vwap=_vwap_val, vwap_side=_vwap_side,
            vwap_dist_pts=round(abs(spot_f - _vwap_val), 4) if _vwap_val else None,
            zone=ms.zone, prev_zone=(prev_zone or ms.zone),
            zone_since_bars=zone_since_bars,           # alias (model compat)
            zone_since_bars_1m=zone_since_bars,        # execution-layer (1m)
            zone_since_bars_5m=zone_since_bars_5m,     # 5m structure context
            call_gamma_wall=_cgw, put_gamma_wall=_pgw,
            call_delta_wall=_cdw, put_delta_wall=_pdw,
            gamma_inflection=_gi, delta_inflection=_di,
            call_oi_wall=_coi, put_oi_wall=_poi,
            call_vanna_wall=_cvw, put_vanna_wall=_pvw,
            pin_width_pts=_pin_w,
            dist_call_gamma_wall=_dist(_cgw), dist_put_gamma_wall=_dist(_pgw),
            dist_call_delta_wall=_dist(_cdw), dist_put_delta_wall=_dist(_pdw),
            dist_gamma_inflection=_dist(_gi),  dist_delta_inflection=_dist(_di),
            dist_call_oi_wall=_dist(_coi),     dist_put_oi_wall=_dist(_poi),
            dist_call_vanna_wall=_dist(_cvw),  dist_put_vanna_wall=_dist(_pvw),
            nearest_above_name=_nearest_above_name, nearest_above_val=_nearest_above_val,
            nearest_above_dist=_nearest_above_dist,
            nearest_below_name=_nearest_below_name, nearest_below_val=_nearest_below_val,
            nearest_below_dist=_nearest_below_dist,
            net_gamma=_net_gamma, net_delta=_net_delta_sig, net_vanna=_net_vanna,
            charm_net=_charm_net, charm_direction=_charm_dir,
            charm_drift_toward=_charm_toward,
            charm_magnitude=charm_magnitude,      # use function param — ms.charm_magnitude not set yet at this point
            dex_magnitude=ms.dex_magnitude,
            iv_level=_iv_level, iv_direction=iv_direction,
            realized_vol=realized_vol, atr=atr,
            garch_sigma_bars=garch_sigma_bars,
            put_call_oi_ratio=_pcr_ratio, oi_center=_oi_center,
            recent_crosses=(recent_crosses or []),
            ceiling_tests_today=ceiling_tests_today,
            floor_tests_today=floor_tests_today,
            spy_zone=None, spy_vwap_side=None,
            spy_chg_pct=mkt_ctx.spy_chg_pct,
            qqq_zone=None, qqq_vwap_side=None,
            qqq_chg_pct=mkt_ctx.qqq_chg_pct,
            qqq_vs_spy=_qqq_vs_spy, qqq_vs_spy_delta=_qqq_delta,
            iwm_zone=None, iwm_vwap_side=None,
            iwm_chg_pct=mkt_ctx.iwm_chg_pct,
            iwm_risk_signal=_iwm_risk,
            spy_weighted_push=getattr(getattr(mkt_ctx, "confluence", None), "weighted_push", None),
            qqq_weighted_push=getattr(getattr(mkt_ctx, "qqq_confluence", None), "weighted_push", None),
            iwm_weighted_push=iwm_blended_participation_push(mkt_ctx),
            event_risk_level=ms.event_risk_level,
            event_risk_detail=ms.event_risk_detail or "",
            vix_level=mkt_ctx.vix, vix_direction=None,
            et_hour=et_hour, et_minute=et_minute,
            mins_to_close=mins_to_close,
            session_bucket=_session_bkt,
            vix_bucket=_vix_bkt,
            refresh_ts_utc=refresh_ts_utc,
            total_snapshots=total_snapshots,
            filled_snapshots=filled_snapshots,
            candles_5m=candles_5m or [],
            candles_1m=candles_1m or [],
            em_upper=em_upper,
            em_lower=em_lower,
            candle_volume=candle_volume,
            flow_imbalance=flow_imbalance,
            spread=spread,
            order_flow_score=ms.order_flow_score,
            order_flow_direction=ms.order_flow_direction,
            order_flow_readiness=ms.order_flow_readiness,
            iv_rank=iv_rank,
            smart_money_score=smart_money_score,
            breakout_score=breakout_score,
            pin_score=pin_score,
        )

        _sig_out = compute_signals(sig_inp, db=db, pred_override=pred_override)
        ms._calibration_payload = getattr(_sig_out, "calibration_payload", None)
        if _don():
            _ddone("compute_signals", ticker)

    except Exception as _e:
        if _don():
            _dcrash("compute_signals", _e, ticker)
        import logging, traceback
        _tb = traceback.format_exc()
        logging.warning(f"market_state: signals engine error: {_e}\n{_tb}")
        _sig_out = None
        # Surface the crash on all three cards — silent WAIT is invisible and misleading
        _err_short = f"{type(_e).__name__}: {str(_e)[:120]}"
        ms.rules_headline  = f"⚠ Signal engine error: {_err_short}"
        ms.rules_detail    = "Check server console for full traceback. Restart server if this persists."
        ms.rules_alerts    = [f"ENGINE CRASH — {_err_short}"]
        ms.call_headline   = f"⚠ Signal engine error: {_err_short}"
        ms.call_reasoning  = "Cards in error state — no signals until engine recovers."
        ms.pred_headline   = f"⚠ Signal engine error: {_err_short}"
        ms.zone_label      = "ERROR"
        ms.zone_badge_css  = "#dc2626"
        ms._calibration_payload = None

    # ── 9. Populate card fields from signals output ──────────────────────────
    if _sig_out is not None:
        # Right Now
        _rules = _sig_out.rules
        if _rules:
            ms.rules_signal     = _rules.signal
            ms.rules_conviction = _rules.conviction
            ms.zone_label       = _rules.zone_label
            ms.zone_badge_css   = _rules.zone_color or zone_badge_color(_rules.zone_label)
            ms.rules_headline   = _rules.headline
            ms.rules_headline_1m = getattr(_rules, 'headline_1m', '') or ''
            ms.rules_detail     = _rules.detail
            ms.rules_alerts     = list(_rules.alerts or [])

            # Session levels + sweeps from micro
            _micro = getattr(_rules, 'micro', None)
            if _micro:
                ms.session_high = getattr(_micro, 'session_high', None)
                ms.session_low = getattr(_micro, 'session_low', None)
                _sweeps = getattr(_micro, 'sweeps', [])
                ms.n_sweeps_today = len(_sweeps)
                _last_sw = getattr(_micro, 'last_sweep', None)
                if _last_sw:
                    ms.last_sweep_type = _last_sw.type
                    ms.last_sweep_level = _last_sw.level
                    ms.last_sweep_held = _last_sw.held

        # The Call — entry/stop/target + new fields
        _call = _sig_out.call
        if _call:
            ms.call_signal      = _call.signal
            ms.call_conviction  = _call.conviction
            ms.entry            = _call.entry
            ms.stop             = _call.stop
            ms.target           = _call.target
            ms.target2          = _call.target2
            ms.reward_risk      = _call.reward_risk
            ms.reward_risk2     = getattr(_call, 'reward_risk2', None)
            ms.entry_disp       = f"{_call.entry:.2f}"  if _call.entry  else "—"
            ms.stop_disp        = f"{_call.stop:.2f}"   if _call.stop   else "—"
            ms.target_disp      = f"{_call.target:.2f}" if _call.target else "—"
            ms.target2_disp     = f"{_call.target2:.2f}" if _call.target2 else "—"
            ms.rr_disp          = f"{_call.reward_risk:.1f}x" if _call.reward_risk else "—"
            ms.rr2_disp         = f"{_call.reward_risk2:.1f}x" if getattr(_call, 'reward_risk2', None) else "—"
            ms.call_headline    = _call.headline
            ms.call_reasoning   = _call.reasoning
            ms.trade_type       = getattr(_call, 'trade_type', 'none')
            _tt = getattr(_call, 'trade_type', 'none')
            ms.trade_type_label = _tt.replace('_', ' ').title() if _tt and _tt != 'none' else ''
            ms.invalidation     = getattr(_call, 'invalidation', '')
            ms.confluence_count = getattr(_call, 'confluence_count', 0)
            ms.confluence_total = getattr(_call, 'confluence_total', 4)
            ms.confluence_detail = getattr(_call, 'confluence_detail', '')
            ms.time_qualifier   = getattr(_call, 'time_qualifier', '')
            ms.replay_max_hold_bars = int(getattr(_call, 'replay_max_hold_bars', 0) or 0)
            ms.size_cue         = getattr(_call, 'size_cue', 'SKIP')
            ms.rules_pred_agree = _call.rules_pred_agree
            ms.time_warning     = _call.time_warning
            ms.size_note        = _call.size_note
            # Validation gate
            ms.validation_passed  = getattr(_call, 'validation_passed', True)
            ms.structure_valid    = getattr(_call, 'structure_valid', True)
            ms.probability_valid  = getattr(_call, 'probability_valid', True)
            ms.risk_valid         = getattr(_call, 'risk_valid', True)
            ms.validation_summary = getattr(_call, 'validation_summary', '')
            # Position sizing
            ms.r_units          = getattr(_call, 'r_units', 0.0)
            ms.execution_mode   = getattr(_call, 'execution_mode', 'NO_TRADE')
            ms.sizing_summary   = getattr(_call, 'sizing_summary', '')
            # Call Readiness
            ms.call_readiness_score   = getattr(_call, 'readiness_score', 0)
            ms.call_state             = getattr(_call, 'call_state', 'WAIT')
            ms.call_forecast_state    = getattr(_call, 'forecast_state', 'dormant')
            ms.call_readiness_reasons = list(getattr(_call, 'readiness_reasons', []) or [])
            ms.call_missing_conditions = list(getattr(_call, 'missing_conditions', []) or [])
            ms.call_readiness_component_scores = dict(getattr(_call, 'readiness_component_scores', {}) or {})
            ms.call_wait_blocker = getattr(_call, 'wait_blocker', None)
            # Put Readiness
            ms.put_readiness_score   = getattr(_call, 'put_readiness_score', 0)
            ms.put_state             = getattr(_call, 'put_state', 'WAIT')
            ms.put_forecast_state    = getattr(_call, 'put_forecast_state', 'dormant')
            ms.put_readiness_reasons = list(getattr(_call, 'put_readiness_reasons', []) or [])
            ms.put_missing_conditions = list(getattr(_call, 'put_missing_conditions', []) or [])
            ms.put_readiness_component_scores = dict(getattr(_call, 'put_readiness_component_scores', {}) or {})

        # Multi-horizon decision payload (authoritative call synthesis + MHAP rows)
        _mhb = getattr(_sig_out, "multi_horizon_bundle", None)
        if _mhb is not None and getattr(_mhb, "final_decision", None) is not None:
            _mhd = _mhb.final_decision
            _mr = getattr(_mhd, "alignment_report", None)
            _pt = getattr(_mhd, "final_trade_plan", None)
            ms.final_bias = str(getattr(_mhd, "final_bias", "WAIT") or "WAIT")
            ms.final_confidence = float(getattr(_mhd, "final_confidence", 0.0) or 0.0)
            ms.final_quality = str(getattr(_mhd, "final_quality", "D") or "D")
            ms.final_tradeable = bool(getattr(_mhd, "final_tradeable", False))
            ms.primary_horizon = str(getattr(_mhd, "primary_horizon", "1c") or "1c")
            ms.trade_mode = str(getattr(_mhd, "trade_mode", "intraday") or "intraday")
            ms.supporting_horizon_summary = str(getattr(_mhd, "supporting_horizon_summary", "") or "")
            ms.alignment_state_display = str(getattr(_mhd, "alignment_state", "unusable") or "unusable")
            ms.contradiction_state = str(getattr(_mhd, "contradiction_state", "none") or "none")
            ms.conflict_level_display = str(getattr(_mr, "conflict_level", "high") or "high")
            ms.entry_state = str(getattr(_mhd, "entry_state", "no_setup") or "no_setup")
            ms.risk_note = str(getattr(_mhd, "risk_note", "") or "")
            ms.wait_reason = str(getattr(_mhd, "wait_reason", "") or "")
            ms.decision_provenance = str(getattr(_mhd, "decision_provenance", "") or "")
            if _pt is not None:
                ms.entry_display_text = str(getattr(_pt, "entry_display_text", ms.entry_display_text) or ms.entry_display_text)
                ms.stop_display_text = str(getattr(_pt, "stop_display_text", "—") or "—")
                ms.targets_display = str(getattr(_pt, "targets_display", "—") or "—")
                ms.hold_style = str(getattr(_pt, "hold_style", ms.hold_style) or ms.hold_style)
                ms.size_modifier_display = str(getattr(_pt, "size_modifier_display", "0.00x") or "0.00x")
            _rows = []
            for _a in list(getattr(_mhd, "supporting_assessments", []) or []):
                _rows.append(
                    {
                        "horizon": str(getattr(_a, "horizon", "")),
                        "role": str(getattr(_a, "role", "")),
                        "call": str(getattr(_a, "call", "")),
                        "confidence": float(getattr(_a, "confidence", 0.0) or 0.0),
                        "entry_ref": getattr(_a, "entry_ref", None),
                        "effect": str(getattr(_a, "effect", "")),
                        "row_state": str(getattr(_a, "row_state", "weak")),
                    }
                )
            _rank = {"1c": 0, "5c": 1, "15c": 2, "60c": 3}
            _rows.sort(key=lambda x: _rank.get(x.get("horizon", ""), 99))
            ms.mhap_rows = _rows

        # What the Data Says
        _pred = _sig_out.predictive
        if _pred:
            ms.horizon_prob_bars = getattr(_pred, "horizon_prob_bars", None)
            ms.eval_accuracy_oos = getattr(_pred, "eval_accuracy_oos", None)
            ms.eval_log_loss_oos = getattr(_pred, "eval_log_loss_oos", None)
            ms.eval_pnl_realized_contract_oos = getattr(_pred, "eval_pnl_realized_contract_oos", None)
            ms.eval_realized_contract_metrics_oos = getattr(
                _pred, "eval_realized_contract_metrics_oos", None
            )
            ms.pred_headline   = _pred.headline
            ms.up_prob_1c      = getattr(_pred, "up_prob_1c", None)
            ms.down_prob_1c    = getattr(_pred, "down_prob_1c", None)
            ms.flat_prob_1c    = getattr(_pred, "flat_prob_1c", None)
            ms.up_prob_3c      = _pred.up_prob_3c
            ms.down_prob_3c    = _pred.down_prob_3c
            ms.flat_prob_3c    = _pred.flat_prob_3c
            ms.up_prob_5c      = _pred.up_prob_5c
            ms.down_prob_5c    = _pred.down_prob_5c
            ms.flat_prob_5c    = _pred.flat_prob_5c
            ms.up_prob_8c      = _pred.up_prob_8c
            ms.down_prob_8c    = _pred.down_prob_8c
            ms.flat_prob_8c    = _pred.flat_prob_8c
            ms.up_prob_13c     = _pred.up_prob_13c
            ms.down_prob_13c   = _pred.down_prob_13c
            ms.flat_prob_13c   = _pred.flat_prob_13c
            ms.up_prob_15c     = getattr(_pred, "up_prob_15c", None)
            ms.down_prob_15c   = getattr(_pred, "down_prob_15c", None)
            ms.flat_prob_15c   = getattr(_pred, "flat_prob_15c", None)
            ms.up_prob_60c     = getattr(_pred, "up_prob_60c", None)
            ms.down_prob_60c   = getattr(_pred, "down_prob_60c", None)
            ms.flat_prob_60c   = getattr(_pred, "flat_prob_60c", None)
            ms.movement_head_probs = getattr(_pred, "movement_head_probs", None)
            ms.fusion_policy_snapshot_cols = getattr(_pred, "fusion_policy_snapshot_cols", None)
            ms.historical_5c_dominant_dir = _pred.historical_5c_dominant_dir
            ms.historical_5c_dominant_prob = _pred.historical_5c_dominant_prob
            ms.empirical_confidence = _pred.empirical_confidence
            ms.forward_prob_up = float(_pred.forward_prob_up)
            ms.forward_prob_down = float(_pred.forward_prob_down)
            ms.forward_prob_flat = float(_pred.forward_prob_flat)
            ms.forward_provenance = _pred.forward_provenance or ""
            _cf = getattr(_sig_out, "canonical_forecast", None)
            if _cf is not None:
                ms.dominant_dir = _cf.direction
                ms.dominant_prob = round(_cf.dominant_probability(), 4)
                ms.confidence = _cf.confidence
                ms.canonical_provenance = str(getattr(_cf, "provenance", "") or "")
            else:
                ms.dominant_dir = _pred.forward_direction
                ms.dominant_prob = float(
                    _pred.forward_prob_up
                    if _pred.forward_direction == "up"
                    else (
                        _pred.forward_prob_down
                        if _pred.forward_direction == "down"
                        else _pred.forward_prob_flat
                    )
                )
                ms.confidence = _pred.forward_confidence
                ms.canonical_provenance = ms.forward_provenance or ""
            ms.samples_used    = _pred.samples_used
            ms.model_note      = _pred.model_note
            ms.model_version   = getattr(_pred, 'model_version', 'rules_v1')
            ms.pred_model_source = getattr(_pred, 'model_source', None)
            ms.pred_override_source = getattr(_sig_out, 'pred_override_source', None)
            ms.avg_3c_pts      = _pred.avg_3c_pts
            ms.avg_5c_pts      = _pred.avg_5c_pts
            ms.avg_8c_pts      = _pred.avg_8c_pts
            ms.avg_13c_pts     = _pred.avg_13c_pts
            ms.avg_15c_pts     = getattr(_pred, "avg_15c_pts", None)
            ms.avg_60c_pts     = getattr(_pred, "avg_60c_pts", None)
            ms.timeframe_reads = dict(_pred.timeframe_reads or {})
            ms.reversal_risk      = _pred.reversal_risk
            ms.reversal_label     = _pred.reversal_label
            ms.reversal_shortfall = getattr(_pred, 'reversal_shortfall', None)
            ms.reversal_severity  = getattr(_pred, 'reversal_severity', '')
            # Individual model outputs (stack visibility)
            _mo = getattr(_pred, 'model_outputs', None)
            if _mo:
                _x = _mo.get("xgb", {})
                _l = _mo.get("lstm", {})
                _t = _mo.get("transformer", {})

                def _pack_probs(z: dict):
                    if not z.get("available"):
                        return None
                    u, dn, fl = z.get("up"), z.get("down"), z.get("flat")
                    if u is None or dn is None or fl is None:
                        return None
                    return {"up": float(u), "down": float(dn), "flat": float(fl)}

                ms.layer1_probs = {
                    "xgb": _pack_probs(_x),
                    "lstm": _pack_probs(_l),
                    "transformer": _pack_probs(_t),
                }
                ms.xgb_available   = _x.get("available")
                ms.xgb_dominant    = _x.get("dominant")
                ms.xgb_confidence = _x.get("confidence")
                ms.xgb_approved    = _x.get("approved")
                ms.lstm_available   = _l.get("available")
                ms.lstm_dominant    = _l.get("dominant")
                ms.lstm_confidence  = _l.get("confidence")
                ms.lstm_approved    = _l.get("approved")
                ms.transformer_available  = _t.get("available")
                ms.transformer_dominant   = _t.get("dominant")
                ms.transformer_confidence = _t.get("confidence")
                ms.transformer_approved   = _t.get("approved")

        # Regime classification
        _regime = getattr(_sig_out, 'regime', None)
        if _regime:
            ms.regime_primary       = getattr(_regime, 'primary', 'unknown')
            ms.regime_secondary     = list(getattr(_regime, 'secondary_tags', []))
            ms.regime_confidence    = getattr(_regime, 'confidence', 'low')
            ms.regime_score         = getattr(_regime, 'confidence_score', 0.0)
            ms.regime_summary       = getattr(_regime, 'summary', '')
            ms.regime_support       = list(getattr(_regime, 'support_factors', []))
            ms.regime_contradiction = list(getattr(_regime, 'contradiction_factors', []))

        # Bayesian fusion
        _fusion = getattr(_sig_out, 'fusion', None)
        if _fusion and getattr(_fusion, 'available', False):
            ms.fusion_available       = True
            ms.fusion_dominant        = getattr(_fusion, 'dominant_outcome', 'unknown')
            ms.fusion_dominant_prob   = getattr(_fusion, 'dominant_probability', 0.0)
            ms.fusion_confidence      = getattr(_fusion, 'fusion_confidence', 'low')
            ms.fusion_confidence_score = getattr(_fusion, 'fusion_confidence_score', 0.0)
            ms.fusion_summary         = getattr(_fusion, 'fusion_summary', '')
            ms.fusion_breakout        = getattr(_fusion, 'breakout_posterior', 0.0)
            ms.fusion_pinning         = getattr(_fusion, 'pinning_posterior', 0.0)
            ms.fusion_continuation    = getattr(_fusion, 'continuation_posterior', 0.0)
            ms.fusion_reversal        = getattr(_fusion, 'reversal_posterior', 0.0)
            ms.fusion_vol_expansion   = getattr(_fusion, 'vol_expansion_posterior', 0.0)
            ms.fusion_mean_reversion  = getattr(_fusion, 'mean_reversion_posterior', 0.0)
            ms.fusion_model_agreement = getattr(_fusion, 'model_agreement', 0.0)
            ms.fusion_agreement_label = getattr(_fusion, 'model_agreement_label', 'low')
            ms.fusion_n_models_active = getattr(_fusion, 'n_sources_active', 0)
            ms.fusion_prob_up         = getattr(_fusion, 'prob_up', 0.33)
            ms.fusion_prob_down       = getattr(_fusion, 'prob_down', 0.33)
            ms.fusion_prob_flat       = getattr(_fusion, 'prob_flat', 0.34)
            ms.fusion_dominant_direction = getattr(_fusion, 'dominant_direction', 'flat')
            ms.fusion_evidence        = list(getattr(_fusion, 'evidence_summary', []))
            ms.fusion_contradictions  = list(getattr(_fusion, 'contradiction_summary', []))
            ms.fusion_mc_contribution = getattr(_fusion, "fusion_mc_contribution", None)
            # Monte Carlo pass-through
            ms.mc_available     = getattr(_fusion, 'mc_available', False)
            ms.mc_containment   = getattr(_fusion, 'mc_containment', None)
            ms.mc_expansion     = getattr(_fusion, 'mc_expansion', None)
            ms.mc_efe           = getattr(_fusion, 'mc_efe', None)
            ms.mc_eae           = getattr(_fusion, 'mc_eae', None)
            ms.mc_upper_50      = getattr(_fusion, 'mc_upper_50', None)
            ms.mc_lower_50      = getattr(_fusion, 'mc_lower_50', None)
            ms.mc_paths         = getattr(_fusion, 'mc_paths', None)
            ms.mc_horizon       = getattr(_fusion, 'mc_horizon', None)
            ms.mc_vol_source    = getattr(_fusion, 'mc_vol_source', None)
            ms.mc_sigma_value   = getattr(_fusion, 'mc_sigma_value', None)

        # Volatility regime (policy layer — influences The Call)
        _vr = getattr(_sig_out, 'vol_regime', None)
        if _vr is not None:
            ms.vol_regime = getattr(_vr, 'vol_regime', 'unknown')
            ms.vol_regime_summary = getattr(_vr, 'summary', '')
            ms.vol_regime_conviction_mult = getattr(_vr, 'conviction_multiplier', 1.0) or 1.0
            ms.vol_regime_risk_mult = getattr(_vr, 'risk_multiplier', 1.0) or 1.0

        # Stack decision path (ordered: XGB → LSTM → Transformer → MC → Fusion → Call)
        _path = getattr(_sig_out, 'stack_decision_path', None)
        if _path is not None:
            _stages = [
                getattr(_path, 'xgboost', None),
                getattr(_path, 'lstm', None),
                getattr(_path, 'transformer', None),
                getattr(_path, 'monte_carlo', None),
                getattr(_path, 'fusion', None),
                getattr(_path, 'final_call', None),
            ]
            ms.stack_decision_path = []
            for s in _stages:
                if s is not None:
                    ms.stack_decision_path.append({
                        "stage_id": getattr(s, 'stage_id', ''),
                        "status": getattr(s, 'status', 'inactive'),
                        "direction": getattr(s, 'direction', None),
                        "confidence": getattr(s, 'confidence', None),
                        "probability": getattr(s, 'probability', None),
                        "note": getattr(s, 'note', ''),
                    })

    # ── 9b. Store charm on MarketState — single source for ms_dict ─────────
    ms.charm_net               = charm_net
    ms.charm_direction         = _charm_dir
    ms.charm_direction_display = ("Bullish" if _charm_dir == "buying"
                                  else "Bearish" if _charm_dir == "selling"
                                  else "Neutral")
    ms.charm_drift_toward      = charm_drift_toward
    ms.charm_magnitude         = charm_magnitude
    ms.charm_top_drivers       = charm_top_drivers or []

    # ── 10. OE recommendation — direction from The Call, not bias ───────────
    # The Call has already run. Its signal (long/short/wait) drives OE direction.
    # This guarantees both cards always tell the same directional story.
    try:
        _reco, _, _oe_proof = recommend_option_expression(
            contracts=contracts_use,
            spot=spot_f,
            call_signal=ms.call_signal,
            walls=walls,
            selected_expiry=selected_exp,
        )
        ms.option_chain_selection_proof = _oe_proof
        _reco_str      = (_reco or "").strip()
        ms.is_no_trade = _reco_str.upper().startswith("NO TRADE")
        if not ms.is_no_trade:
            _parts = _reco_str.split()
            if len(_parts) >= 2:
                ms.rec_strike = float(_parts[0])
                ms.rec_side   = _parts[1].upper()
    except Exception as _oe_e:
        import logging
        logging.warning(f"market_state: OE recommendation error: {_oe_e}")
        ms.is_no_trade = True

    csig = (ms.call_signal or "wait").strip().lower()
    if csig == "wait" or ms.is_no_trade:
        ms.call_option_right = "WAIT"
    else:
        ms.call_option_right = (ms.rec_side or ("CALL" if csig == "long" else "PUT" if csig == "short" else "WAIT"))

    # ── 11. OE gate pill scoring ─────────────────────────────────────────────
    if ms.rec_strike is not None and ms.rec_side is not None:
        _oe_score = score_option_expression(
            contracts_use, spot_f, ms.rec_strike, ms.rec_side, walls=walls
        )
        if _oe_score:
            ms.liq_ok  = _oe_score.liq_gate
            ms.ratio   = _oe_score.delta_gamma_ratio
            ms.vol_oi  = _oe_score.vol_oi_ratio
            ms.spread  = _oe_score.spread

    # ── 12. Entry zone — always from signals entry, never recomputed ─────────
    if ms.entry is not None:
        ms.entry_zone_lo  = round(ms.entry - 0.25, 2)
        ms.entry_zone_hi  = round(ms.entry + 0.25, 2)
        ms.entry_zone_str = f"Spot {ms.entry_zone_lo:.2f}–{ms.entry_zone_hi:.2f}"
    elif ms.rec_strike is not None:
        ms.entry_zone_lo  = round(ms.rec_strike - 0.25, 2)
        ms.entry_zone_hi  = round(ms.rec_strike + 0.25, 2)
        ms.entry_zone_str = f"{ms.entry_zone_lo:.2f}–{ms.entry_zone_hi:.2f}"

    ms.contract_context = _build_contract_context_ms(ms, contracts_use)

    return ms
