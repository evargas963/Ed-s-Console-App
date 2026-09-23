"""db.py dataclass models (RC-REHAB-1, db.py decomposition follow-up).

SnapshotRow and LevelCrossEvent -- pure @dataclass schema definitions, zero methods, zero
coupling to EdDB/connections. Moved out of db.py because there is no structural reason for
a data-only schema to live inside the file that also owns connection lifecycle and mixin
composition. Re-exported from db.py (`from db_models import SnapshotRow, LevelCrossEvent`)
so every existing `from db import SnapshotRow` / `from db import LevelCrossEvent` caller
(db_snapshots.py, db_level_crossing.py, server.py, base_money_path_capture.py,
similarity_feature_universe.py, features/db_feature_adapter.py, tools/phase2_forward_write_verify.py,
and several tests) keeps working unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1


@dataclass
class SnapshotRow:
    """
    One row per refresh per ticker per timeframe.
    Captures everything we know at this moment.
    Outcome fields are NULL until the next bar closes.
    """
    # ── Required fields (no defaults) — must come first ────────────────────────
    ticker:             str
    timeframe:          str             # '1m', '5m', '15m', '1h'
    ts_utc:             float           # unix timestamp UTC
    ts_et:              str             # '2026-02-23 10:47:32 ET' display string
    et_hour:            int             # 0-23 ET hour
    et_minute:          int             # 0-59 ET minute
    market_session:     str             # 'premarket', 'rth', 'afterhours', 'closed'
    spot:               float

    # ── Identity (optional) ────────────────────────────────────────────────────
    expiry:             Optional[str] = None  # '2026-02-23'
    dte:                Optional[int] = None  # days to expiry (ET authority)
    hours_to_expiry:    Optional[float] = None  # hours until session close on expiry date (early-close 13:00 ET)
    candle_open:        Optional[float] = None
    candle_high:        Optional[float] = None
    candle_low:         Optional[float] = None
    candle_close:       Optional[float] = None
    candle_volume:      Optional[float] = None
    candle_direction:   Optional[str] = None  # 'up', 'down', 'flat'
    candle_body_pts:    Optional[float] = None  # abs(close - open)
    candle_range_pts:   Optional[float] = None  # high - low
    spread:             Optional[float] = None   # bid-ask spread (pts)

    # ── execution_identity_v1 (PER_ROW_HISTORICAL_MODEL_ARTIFACT_IDENTITY) ────
    # MODEL_DERIVED rows carry the immutable decision-cycle identity; quote-only
    # rows are explicitly NOT_APPLICABLE with NULL identity.  Linkage integrity
    # is trigger-enforced against model_execution_identities + the persistence
    # ledger (see execution_identity.py).
    decision_id:                Optional[str] = None
    execution_identity_sha256:  Optional[str] = None
    execution_identity_class:   Optional[str] = None  # 'MODEL_DERIVED' | 'NOT_APPLICABLE'

    # ── Raw Schwab quote primitives (CSV-first leaves; not derived) ────────────
    # quotes.{SYM}.bidPrice / askPrice / bidSize / askSize / lastSize / totalVolume.
    # Logged so ablation can judge the primitives that spread / vol_oi_ratio were
    # derived from (order-flow pressure: size imbalance, print size, volume rate).
    bid_price:          Optional[float] = None
    ask_price:          Optional[float] = None
    bid_size:           Optional[float] = None
    ask_size:           Optional[float] = None
    last_size:          Optional[float] = None
    total_volume:       Optional[float] = None

    # ── VWAP ─────────────────────────────────────────────────────────────────
    vwap:               Optional[float] = None
    vwap_side:          Optional[str] = None  # 'above', 'below'
    vwap_dist_pts:      Optional[float] = None  # abs(spot - vwap)

    # ── Price action levels ───────────────────────────────────────────────────
    pdh:                Optional[float] = None
    pdl:                Optional[float] = None
    pdc:                Optional[float] = None
    orb_high:           Optional[float] = None
    orb_low:            Optional[float] = None

    # ── Zone (structural: derive_zone / gamma bias) — NOT regime_primary ───────
    zone:               Optional[str] = None  # pin_bull, pin_bear, pin_neutral, pin_chaos, breakout, breakdown
    zone_since_bars:    Optional[int] = None  # alias for zone_since_bars_1m; populated with 1m value
    zone_since_bars_1m: Optional[int] = None  # execution-layer recency (1m bars)
    zone_since_bars_5m: Optional[int] = None  # structure-layer recency (5m bars)
    prev_zone:          Optional[str] = None  # zone on previous snapshot

    # ── Level distances (signed: positive = above spot, negative = below) ─────
    dist_call_gamma_wall:   Optional[float] = None
    dist_put_gamma_wall:    Optional[float] = None
    dist_call_delta_wall:   Optional[float] = None
    dist_put_delta_wall:    Optional[float] = None
    dist_gamma_inflection:  Optional[float] = None
    dist_delta_inflection:  Optional[float] = None
    dist_call_oi_wall:      Optional[float] = None
    dist_put_oi_wall:       Optional[float] = None
    dist_call_vanna_wall:   Optional[float] = None
    dist_put_vanna_wall:    Optional[float] = None

    # ── Level absolute values ─────────────────────────────────────────────────
    call_gamma_wall:    Optional[float] = None
    put_gamma_wall:     Optional[float] = None
    call_delta_wall:    Optional[float] = None
    put_delta_wall:     Optional[float] = None
    gamma_inflection:   Optional[float] = None
    delta_inflection:   Optional[float] = None
    call_oi_wall:       Optional[float] = None
    put_oi_wall:        Optional[float] = None
    call_vanna_wall:    Optional[float] = None
    put_vanna_wall:     Optional[float] = None
    pin_width_pts:      Optional[float] = None  # call_gamma_wall - put_gamma_wall

    # ── Nearest levels ────────────────────────────────────────────────────────
    nearest_above_name: Optional[str] = None
    nearest_above_val:  Optional[float] = None
    nearest_above_dist: Optional[float] = None
    nearest_below_name: Optional[str] = None
    nearest_below_val:  Optional[float] = None
    nearest_below_dist: Optional[float] = None

    # ── Greeks snapshot ───────────────────────────────────────────────────────
    net_gamma:          Optional[float] = None
    net_delta:          Optional[float] = None
    net_vanna:          Optional[float] = None
    charm_net:          Optional[float] = None
    charm_direction:    Optional[str] = None  # 'buying', 'selling', 'neutral'
    charm_drift_toward: Optional[float] = None
    iv_level:           Optional[float] = None  # avg IV across chain
    iv_direction:       Optional[str] = None  # 'expanding', 'contracting', 'flat'
    charm_magnitude:    Optional[float] = None  # abs charm net, normalized
    session_bucket:     Optional[str] = None  # 'open', 'morning', 'midday', 'afternoon', 'close'
    # vix_bucket: produced by math_volatility.vix_bucket → 'vix_low' | 'vix_normal' | 'vix_elevated' | 'vix_high' | None.
    # COH-SA-VIX-TIER (commit 2c5cef5) consolidated the 15/20/30 cuts in math_volatility.vix_tier_token.
    vix_bucket:         Optional[str] = None
    put_call_oi_ratio:  Optional[float] = None
    oi_center:          Optional[float] = None
    gamma_pin:          Optional[float] = None  # terrain total-gamma after SNAPSHOTS_GAMMA_PIN_WRITER_LAND_TS_UTC (RC-429); earlier rows are selected-expiry net-GEX peak — do not mix eras. COLUMN name is historical (RC-292 renamed the live payload field absolute_gamma_strike; same quantity, no third era)

    # ── Cross-instrument (SPY when not primary, else NULL) ────────────────────
    spy_spot:           Optional[float] = None
    spy_chg_pct:        Optional[float] = None
    spy_zone:           Optional[str] = None
    spy_vwap_side:      Optional[str] = None
    spy_net_delta:      Optional[float] = None

    qqq_spot:           Optional[float] = None
    qqq_chg_pct:        Optional[float] = None
    qqq_zone:           Optional[str] = None
    qqq_vwap_side:      Optional[str] = None
    qqq_net_delta:      Optional[float] = None
    qqq_vs_spy:         Optional[str] = None  # 'leading', 'lagging', 'inline'
    qqq_vs_spy_delta:   Optional[float] = None  # qqq_chg_pct - spy_chg_pct

    iwm_spot:           Optional[float] = None
    iwm_chg_pct:        Optional[float] = None
    iwm_zone:           Optional[str] = None
    iwm_vwap_side:      Optional[str] = None
    iwm_net_delta:      Optional[float] = None
    iwm_vs_spy:         Optional[str] = None  # 'leading', 'lagging', 'inline'
    iwm_risk_signal:    Optional[str] = None  # 'risk_on', 'risk_off', 'neutral'

    # ── SPY constituents (price % change) ─────────────────────────────────────
    nvda_chg_pct:       Optional[float] = None
    aapl_chg_pct:       Optional[float] = None
    msft_chg_pct:       Optional[float] = None
    amzn_chg_pct:       Optional[float] = None
    googl_chg_pct:      Optional[float] = None
    goog_chg_pct:       Optional[float] = None  # RC-UI-3 (2026-09-12): GOOG is Alphabet's OWN
    # class-C share, a distinct instrument from GOOGL (class A) with its own confluence
    # weight in SPY_TOP/QQQ_TOP (market_context.py) -- it must not read GOOGL's column.
    avgo_chg_pct:       Optional[float] = None
    meta_chg_pct:       Optional[float] = None
    tsla_chg_pct:       Optional[float] = None
    spy_weighted_push:  Optional[float] = None  # weighted % contribution from top 9
    qqq_weighted_push:  Optional[float] = None  # Nasdaq-100 top names (qqq_confluence.weighted_push)

    # ── IWM sector proxies (price % change) ───────────────────────────────────
    kre_chg_pct:        Optional[float] = None  # Financials
    xbi_chg_pct:        Optional[float] = None  # Healthcare/Biotech
    psci_chg_pct:       Optional[float] = None  # Industrials
    xrt_chg_pct:        Optional[float] = None  # Consumer Discretionary
    iwm_weighted_push:  Optional[float] = None  # holdings + sector blend (market_context.iwm_blended_participation_push)

    # ── VIX ───────────────────────────────────────────────────────────────────
    vix_level:          Optional[float] = None
    vix_direction:      Optional[str] = None  # 'rising', 'falling', 'flat'
    vix_vs_prev:        Optional[float] = None  # change vs previous snapshot

    # ── Rules engine output ───────────────────────────────────────────────────
    rules_signal:       Optional[str] = None  # 'long', 'short', 'wait'
    rules_conviction:   Optional[str] = None  # 'high', 'medium', 'low'
    rules_entry:        Optional[float] = None
    rules_stop:         Optional[float] = None
    rules_target:       Optional[float] = None
    call_target2:       Optional[float] = None  # second target from Call card
    rules_summary:      Optional[str] = None  # plain English 2-3 sentences

    # ── Model prediction (filled when model has enough data) ──────────────────
    # 1c = next completed 1m bar (empirical similar-set histogram; same contract as other pred_Nc_*)
    pred_1c_up_prob:    Optional[float] = None
    pred_1c_down_prob:  Optional[float] = None
    pred_1c_flat_prob:  Optional[float] = None
    pred_5c_up_prob:    Optional[float] = None
    pred_5c_down_prob:  Optional[float] = None
    pred_5c_flat_prob:  Optional[float] = None
    pred_15c_up_prob:   Optional[float] = None  # 15×1m forward — product 15m clock
    pred_15c_down_prob: Optional[float] = None
    pred_15c_flat_prob: Optional[float] = None
    pred_60c_up_prob:   Optional[float] = None  # 60×1m forward — product 60m clock
    pred_60c_down_prob: Optional[float] = None
    pred_60c_flat_prob: Optional[float] = None
    pred_model_version: Optional[str] = None  # 'statistical_v1', 'xgb_v1', etc.
    pred_model_source:  Optional[str] = None  # 'ml', 'rules', 'statistical'
    pred_override_source: Optional[str] = None  # override source if user overrode
    logger_source:      Optional[str] = None  # base_money_path | background_logger | ui_sse | ui_rest | manual_backfill
    pred_confidence:    Optional[str] = None  # 'low', 'medium', 'high'
    pred_samples_used:  Optional[int] = None  # how many historical snapshots used
    prediction_direction:   Optional[str]   = None  # PredictiveCard.dominant_dir
    prediction_dominant_prob: Optional[float] = None  # PredictiveCard.dominant_prob

    # ── Combined signal ───────────────────────────────────────────────────────
    combined_signal:    Optional[str]   = None  # 'long', 'short', 'wait'
    combined_conviction:Optional[str]   = None  # 'high', 'medium', 'low'
    rules_pred_agree:   Optional[bool]  = None  # do rules and model agree?
    reward_risk:        Optional[float] = None  # R:R to T1 from Call card
    reward_risk2:       Optional[float] = None  # R:R to T2 from Call card

    # ── Regime classification (regime_engine.py env — orthogonal to zone) ─────
    regime_primary:         Optional[str]   = None  # pinning, acceleration, … (not pin_bull/pin_neutral)
    regime_confidence:      Optional[str]   = None  # 'low', 'medium', 'high'
    regime_score:           Optional[float] = None  # 0.0–1.0

    # ── Price-action cone (operator 2026-06-11) — bar-derived primitives so the
    # ML stack can see price movement, not just options-structure distances.
    # Producer: features/signal_layer_v1.compute_price_action_snapshot_columns
    # (leakage-guarded: completed 1m bars with bar_end <= ts_utc only). ─────────
    pa_ret_1m_pct:          Optional[float] = None  # 1m log return ×100
    pa_ret_3m_pct:          Optional[float] = None
    pa_ret_5m_pct:          Optional[float] = None
    pa_ret_15m_pct:         Optional[float] = None
    pa_ret_30m_pct:         Optional[float] = None
    pa_ret_60m_pct:         Optional[float] = None
    pa_trend_slope_log20:   Optional[float] = None  # OLS slope of log close, 20 bars
    pa_trend_slope_log40:   Optional[float] = None
    pa_structure_state:     Optional[float] = None  # +1 HH/HL … -1 LH/LL
    pa_bos_up:              Optional[float] = None  # break of structure above swing high
    pa_bos_down:            Optional[float] = None
    pa_dist_swing_high_atr: Optional[float] = None  # ATR-scaled distance to swing high
    pa_dist_swing_low_atr:  Optional[float] = None
    pa_range_position_n20:  Optional[float] = None  # close position in 20-bar range 0..1
    pa_vwap_zscore:         Optional[float] = None
    pa_atr_pctile_60:       Optional[float] = None
    pa_atr_expansion_5_20:  Optional[float] = None
    pa_realized_vol_ann:    Optional[float] = None  # annualized 1m realized vol proxy
    pa_wick_asymmetry:      Optional[float] = None
    pa_close_location:      Optional[float] = None  # close position within last bar 0..1
    pa_impulse_run_signed:  Optional[float] = None  # ±consecutive close run length
    pa_mtf_trend_1m:        Optional[float] = None  # sign of 1m trend slope
    pa_mtf_trend_5m:        Optional[float] = None
    pa_mtf_bias_15m:        Optional[float] = None
    pa_mtf_alignment:       Optional[float] = None  # +1 aligned / -1 conflicted / 0 mixed
    pa_relative_volume:     Optional[float] = None
    pa_move_efficiency:     Optional[float] = None  # |body| vs 5-bar true-range sum

    # ── Bayesian fusion (from bayesian_fusion.py) ─────────────────────────────
    fusion_dominant:        Optional[str]   = None  # dominant outcome family
    fusion_dominant_prob:   Optional[float] = None  # probability of dominant
    fusion_dominant_direction: Optional[str] = None  # 'up', 'down', 'flat'
    fusion_prob_down:       Optional[float] = None
    fusion_prob_flat:       Optional[float] = None
    fusion_prob_up:         Optional[float] = None
    fusion_confidence:      Optional[str]   = None  # 'low', 'medium', 'high'
    fusion_breakout:        Optional[float] = None  # posterior P(breakout)
    fusion_pinning:         Optional[float] = None  # posterior P(pinning)
    fusion_continuation:    Optional[float] = None  # posterior P(continuation)
    fusion_reversal:        Optional[float] = None  # posterior P(reversal)
    fusion_vol_expansion:   Optional[float] = None  # posterior P(vol expansion)
    fusion_mean_reversion:  Optional[float] = None  # posterior P(mean reversion)
    fusion_model_agreement: Optional[float] = None  # 0.0–1.0
    fusion_n_models_active: Optional[int]   = None  # how many models ran

    # ── Monte Carlo (from monte_carlo.py) ─────────────────────────────────────
    mc_efe:                 Optional[float] = None  # expected favorable excursion (pts)
    mc_eae:                 Optional[float] = None  # expected adverse excursion (pts)
    mc_containment:         Optional[float] = None  # P(stays within EM)
    mc_expansion:           Optional[float] = None  # P(breaks EM boundary)
    mc_upper_50:            Optional[float] = None  # 87.5th percentile terminal
    mc_lower_50:            Optional[float] = None  # 12.5th percentile terminal
    mc_paths:               Optional[int]   = None  # MC path count
    mc_horizon:             Optional[int]   = None  # MC horizon (bars)
    mc_vol_source:          Optional[str]   = None  # VOLATILITY source: 'garch' or 'blend'
    mc_sigma_value:         Optional[float] = None  # ANNUALIZED decimal vol, post regime mult (path-independent)
    # DRIFT source: 'ml_conditioned' (unified-stack team authorized a directional prior) or
    # 'base_neutral' (MC ran with no prior; per_bar_drift == 0). REQUIRED durably: the persisted
    # xgb/lstm/transformer_available columns store layer `available`, while the team gate keys on
    # triplet COMPLETENESS — so a base-neutral row can carry three available layers and would
    # otherwise read as ML-conditioned. NULL on rows written before this column existed.
    mc_conditioning:        Optional[str]   = None

    # ── Individual model outputs ──────────────────────────────────────────────
    xgb_available:          Optional[bool]  = None
    xgb_dominant:           Optional[str]   = None  # 'up', 'down', 'flat'
    xgb_confidence:         Optional[float] = None
    xgb_approved:           Optional[int]   = None  # boolean 0/1
    lstm_available:         Optional[bool]  = None
    lstm_dominant:          Optional[str]   = None
    lstm_confidence:        Optional[float] = None
    lstm_approved:          Optional[int]   = None  # boolean 0/1
    transformer_available:  Optional[bool]  = None
    transformer_dominant:   Optional[str]   = None  # 'up', 'down', 'flat'
    transformer_confidence: Optional[float] = None
    transformer_approved:   Optional[int]   = None  # boolean 0/1

    # ── Volatility signals ────────────────────────────────────────────────────
    iv_skew:                Optional[float] = None  # IV_put - IV_call at ATM
    realized_vol:           Optional[float] = None  # annualized realized vol %
    atr:                    Optional[float] = None  # average true range (pts)
    iv_rank:                Optional[float] = None  # 0-100 rank vs history
    iv_percentile:          Optional[float] = None  # 0-100 percentile vs history

    # ── Section 8 — Predictive Positioning Signals ────────────────────────────
    dpi_raw:                Optional[float] = None  # dealer pressure index raw
    dpi_normalized:         Optional[float] = None  # 0-100 normalized
    dpi_direction:          Optional[str]   = None  # 'buying', 'selling', 'neutral'
    hedging_flow_score:     Optional[float] = None  # 0-100 composite
    hedging_flow_direction: Optional[str]   = None  # 'buying', 'selling', 'neutral'
    gamma_gradient:         Optional[float] = None  # d(GEX)/d(Price)
    breakout_score:         Optional[float] = None  # 0-100
    pin_score:              Optional[float] = None  # 0-100
    vol_expansion_score:    Optional[float] = None  # 0-100
    sweep_score:            Optional[float] = None  # 0-100

    # ── Session levels + liquidity sweeps ─────────────────────────────────────
    session_high:           Optional[float] = None
    session_low:            Optional[float] = None
    last_sweep_type:        Optional[str]   = None  # 'sweep_high', 'sweep_low'
    last_sweep_level:       Optional[float] = None
    last_sweep_held:        Optional[bool]  = None  # True = failed sweep
    n_sweeps_today:         Optional[int]   = None

    # ── Trade Validation Gate ─────────────────────────────────────────────────
    validation_passed:      Optional[bool]  = None
    structure_valid:        Optional[bool]  = None
    probability_valid:      Optional[bool]  = None
    risk_valid:             Optional[bool]  = None
    validation_summary:     Optional[str]   = None

    # ── Formal Position Sizing ────────────────────────────────────────────────
    r_units:                Optional[float] = None  # 0.00 to 1.25
    execution_mode:         Optional[str]   = None  # NO_TRADE, PROBE, REDUCED, STANDARD, MAX

    # ── Volatility Envelope ───────────────────────────────────────────────────
    vol_env_upper:          Optional[float] = None
    vol_env_lower:          Optional[float] = None

    # ── Level Density ─────────────────────────────────────────────────────────
    level_density_count:    Optional[int]   = None
    level_density_label:    Optional[str]   = None  # 'clear', 'light', 'moderate', 'congested'

    # ── Sector Strength ───────────────────────────────────────────────────────
    sector_leader:          Optional[str]   = None
    sector_laggard:         Optional[str]   = None
    sector_breadth:         Optional[float] = None  # 0-1
    sector_risk_signal:     Optional[str]   = None  # 'risk_on', 'risk_off', 'mixed'

    # ── Index Strength (SPY/QQQ/IWM) ─────────────────────────────────────────
    index_leader:           Optional[str]   = None
    index_laggard:          Optional[str]   = None
    index_breadth:          Optional[float] = None
    index_risk_signal:      Optional[str]   = None

    # ── SPY Holdings Strength (top 8) ─────────────────────────────────────────
    spy_holdings_leader:    Optional[str]   = None
    spy_holdings_laggard:   Optional[str]   = None
    spy_holdings_breadth:   Optional[float] = None
    spy_holdings_risk:      Optional[str]   = None

    # ── IWM Deep Confluence ───────────────────────────────────────────────────
    iwm_risk_regime:        Optional[str]   = None  # 'risk_on', 'risk_off', 'neutral'
    iwm_risk_score:         Optional[float] = None  # 0-100 composite
    spy_iwm_divergence:     Optional[float] = None  # IWM - SPY spread
    spy_iwm_fragile:        Optional[bool]  = None  # SPY up + IWM down
    iwm_early_warning:      Optional[bool]  = None  # risk-off forming
    rotation_signal:        Optional[str]   = None  # 'growth_favored', 'value_favored', 'neutral'

    # ── Bond Yields ───────────────────────────────────────────────────────────
    tnx_yield:              Optional[float] = None  # 10Y Treasury yield
    tnx_chg:                Optional[float] = None  # yield change today
    bond_signal:            Optional[str]   = None  # 'flight_to_safety', 'risk_on', 'rate_stress', 'neutral'

    # ── Order Flow Signals ────────────────────────────────────────────────────
    vol_oi_ratio:           Optional[float] = None  # volume/OI near ATM
    flow_imbalance:         Optional[float] = None  # -1 to +1 bid/ask imbalance
    flow_imbalance_source:  Optional[str] = None  # RC-345/F11: 'book'|'volume'|'none' economic identity
    smart_money_score:      Optional[float] = None  # 0-100 composite
    smart_money_direction:  Optional[str]   = None  # 'bullish', 'bearish', 'neutral'
    iv_model_spread:        Optional[float] = None  # market IV - theoretical IV

    # ── ML-facing dealer pressure (maps from DPI / hedging flow; see server + backfill) ──
    pressure_label:       Optional[str]   = None  # buying, selling, neutral (from dpi/hedge)
    pressure_trend:       Optional[str]   = None  # rising, falling, flat (dpi_normalized vs prior)

    # ── Archived option chain (bid/ask per contract at snapshot time — realized contract PnL eval) ──
    option_chain_json:      Optional[str] = None  # JSON list of contract dicts for snapshot.expiry

    # ── Full replay bundle: walls/totals, regime, OE proof, hold policy (JSON) ──
    replay_context_json:    Optional[str] = None

    # ── Institutional behavior + news context (additive layer; optional APIs) ──
    absorption_score:          Optional[float] = None
    continuation_score:        Optional[float] = None
    liquidity_behavior_label:  Optional[str] = None
    sentiment_composite:       Optional[float] = None
    sentiment_buzz:            Optional[float] = None
    sentiment_finnhub:         Optional[float] = None
    sentiment_av:              Optional[float] = None
    breaking_news_flag:        Optional[int] = None   # 0/1
    breaking_news_headline:    Optional[str] = None
    pre_market_sentiment:      Optional[float] = None

    # ── Outcomes (NULL until fill_outcomes — Issue 4 anchor + Issue 3 forward bar close) ─
    outcome_1c:         Optional[str]   = None  # 'up', 'down', 'flat'
    outcome_5c:         Optional[str]   = None
    outcome_1c_pts:     Optional[float] = None  # actual point move
    outcome_5c_pts:     Optional[float] = None
    outcome_15c:        Optional[str]   = None  # 15×1m bars — true 15m label
    outcome_15c_pts:    Optional[float] = None
    outcome_60c:        Optional[str]   = None  # 60×1m bars — true 60m label
    outcome_60c_pts:    Optional[float] = None
    # Movement-target v1 labels (filled by fill_outcomes / refresh; NULL on fresh inserts)
    outcome_dir_1c:     Optional[str]   = None
    outcome_move_1c:    Optional[str]   = None
    outcome_move_thr_pts_1c: Optional[float] = None
    outcome_dir_5c:     Optional[str]   = None
    outcome_move_5c:    Optional[str]   = None
    outcome_move_thr_pts_5c: Optional[float] = None
    outcome_dir_15c:    Optional[str]   = None
    outcome_move_15c:   Optional[str]   = None
    outcome_move_thr_pts_15c: Optional[float] = None
    outcome_dir_60c:    Optional[str]   = None
    outcome_move_60c:   Optional[str]   = None
    outcome_move_thr_pts_60c: Optional[float] = None
    valid_dir_1c:       Optional[int]   = None
    threshold_move_1c:  Optional[float] = None
    valid_dir_5c:       Optional[int]   = None
    threshold_move_5c:  Optional[float] = None
    valid_dir_15c:      Optional[int]   = None
    threshold_move_15c: Optional[float] = None
    valid_dir_60c:      Optional[int]   = None
    threshold_move_60c: Optional[float] = None
    # XGB movement-head probabilities (product ML horizons — legacy / features / comparison only; not policy authority)
    pred_dir_up_prob_1c: Optional[float] = None
    pred_dir_down_prob_1c: Optional[float] = None
    pred_move_prob_1c: Optional[float] = None
    pred_no_move_prob_1c: Optional[float] = None
    pred_dir_up_prob_5c: Optional[float] = None
    pred_dir_down_prob_5c: Optional[float] = None
    pred_move_prob_5c: Optional[float] = None
    pred_no_move_prob_5c: Optional[float] = None
    pred_dir_up_prob_15c: Optional[float] = None
    pred_dir_down_prob_15c: Optional[float] = None
    pred_move_prob_15c: Optional[float] = None
    pred_no_move_prob_15c: Optional[float] = None
    pred_dir_up_prob_60c: Optional[float] = None
    pred_dir_down_prob_60c: Optional[float] = None
    pred_move_prob_60c: Optional[float] = None
    pred_no_move_prob_60c: Optional[float] = None
    pred_1c_dir_up_prob:   Optional[float] = None
    pred_1c_dir_down_prob: Optional[float] = None
    pred_1c_move_prob:     Optional[float] = None
    pred_1c_no_move_prob:  Optional[float] = None
    pred_5c_dir_up_prob:   Optional[float] = None
    pred_5c_dir_down_prob: Optional[float] = None
    pred_5c_move_prob:     Optional[float] = None
    pred_5c_no_move_prob:  Optional[float] = None
    pred_15c_dir_up_prob:   Optional[float] = None
    pred_15c_dir_down_prob: Optional[float] = None
    pred_15c_move_prob:     Optional[float] = None
    pred_15c_no_move_prob:  Optional[float] = None
    pred_60c_dir_up_prob:   Optional[float] = None
    pred_60c_dir_down_prob: Optional[float] = None
    pred_60c_move_prob:     Optional[float] = None
    pred_60c_no_move_prob:  Optional[float] = None
    # Fusion policy substrate (signals: per-horizon stack → MC → fuse); Phase 8/9 authority
    fused_move_prob_1c: Optional[float] = None
    fused_dir_up_prob_1c: Optional[float] = None
    fused_confidence_1c: Optional[float] = None
    fused_contributing_models_1c: Optional[str] = None
    fused_stack_status_1c: Optional[str] = None
    fused_move_prob_5c: Optional[float] = None
    fused_dir_up_prob_5c: Optional[float] = None
    fused_confidence_5c: Optional[float] = None
    fused_contributing_models_5c: Optional[str] = None
    fused_stack_status_5c: Optional[str] = None
    fused_move_prob_15c: Optional[float] = None
    fused_dir_up_prob_15c: Optional[float] = None
    fused_confidence_15c: Optional[float] = None
    fused_contributing_models_15c: Optional[str] = None
    fused_stack_status_15c: Optional[str] = None
    fused_move_prob_60c: Optional[float] = None
    fused_dir_up_prob_60c: Optional[float] = None
    fused_confidence_60c: Optional[float] = None
    fused_contributing_models_60c: Optional[str] = None
    fused_stack_status_60c: Optional[str] = None
    # Replay/backfill aggregate (optional): FULL | PARTIAL | DEGRADED — does not gate rows
    fusion_replay_stack_grade_v1: Optional[str] = None
    outcome_filled:     bool            = False  # all OUTCOME_BAR_SPECS horizons populated (backfill); not used for ML eligibility
    # 3 = bar-close anchor + bar-forward close (Issue 4+3); 2 = invalidated spot-anchor contract
    horizon_outcome_schema_version: int = HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1

    # ── Internal ──────────────────────────────────────────────────────────────
    snapshot_id:        Optional[int]   = None  # set by DB after insert


@dataclass
class LevelCrossEvent:
    """
    Logged every time price crosses a key level.
    Used for breach log + pattern detection.
    """
    ticker:         str
    ts_utc:         float
    ts_et:          str
    level_name:     str         # 'Call Gamma Wall', 'VWAP', etc.
    level_value:    float
    direction:      str         # 'up', 'down'
    spot_at_cross:  float
    zone_before:    Optional[str]
    zone_after:     Optional[str]
    timeframe:      str
