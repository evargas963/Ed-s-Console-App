"""EdDB schema creation + migrations, extracted from EdDB (RC-REHAB-1, db.py
decomposition, 2026-09-21, slice 2).

Everything here answers: what does the database look like, and how does an older on-disk
database get brought up to today's shape. Pure DDL (_init_schema) plus additive/idempotent
migrations (_migrate_schema and its one-time sub-migrations) -- no snapshot/outcome business
logic, which stays in EdDB itself (the next slice's own scope).

SchemaMixin is mixed into EdDB (db.py), exactly like LoggingUniverseMixin (slice 1):
every method here already assumed self._connect() from the host class, so keeping that
contract intact means db.__init__'s own self._init_schema()/self._migrate_schema() calls
are unchanged by this move -- same behavior, different file.
"""
from __future__ import annotations

import logging
import sqlite3
import time as _wall_time

from horizon_outcomes import (
    HORIZON_OUTCOME_SCHEMA_BAR_V1,
    HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
    OUTCOME_BAR_SPECS,
    OUTCOME_MOVEMENT_V1_SPECS,
)

log = logging.getLogger(__name__)


class SchemaMixin:
    """Mixed into EdDB. Assumes ``self._connect()`` from the host class."""

    def _init_schema(self):
        """Create all tables if they don't exist. Safe to call on every startup."""
        with self._connect() as conn:
            conn.executescript("""

            -- ── Snapshots ─────────────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id         INTEGER PRIMARY KEY AUTOINCREMENT,

                -- Identity
                ticker              TEXT    NOT NULL,
                timeframe           TEXT    NOT NULL,
                expiry              TEXT,
                dte                 INTEGER,
                hours_to_expiry     REAL,

                -- Timestamp
                ts_utc              REAL    NOT NULL,
                ts_et               TEXT    NOT NULL,
                et_hour             INTEGER,
                et_minute           INTEGER,
                market_session      TEXT,

                -- Price action
                spot                REAL    NOT NULL,
                candle_open         REAL,
                candle_high         REAL,
                candle_low          REAL,
                candle_close        REAL,
                candle_volume       REAL,
                candle_direction    TEXT,
                candle_body_pts     REAL,
                candle_range_pts    REAL,
                spread              REAL,

                -- VWAP
                vwap                REAL,
                vwap_side           TEXT,
                vwap_dist_pts       REAL,

                -- Price action levels
                pdh                 REAL,
                pdl                 REAL,
                pdc                 REAL,
                orb_high            REAL,
                orb_low             REAL,

                -- Zone
                zone                TEXT,
                zone_since_bars     INTEGER,
                prev_zone           TEXT,

                -- Level distances
                dist_call_gamma_wall    REAL,
                dist_put_gamma_wall     REAL,
                dist_call_delta_wall    REAL,
                dist_put_delta_wall     REAL,
                dist_gamma_inflection   REAL,
                dist_delta_inflection   REAL,
                dist_call_oi_wall       REAL,
                dist_put_oi_wall        REAL,
                dist_call_vanna_wall    REAL,
                dist_put_vanna_wall     REAL,

                -- Level absolute values
                call_gamma_wall     REAL,
                put_gamma_wall      REAL,
                call_delta_wall     REAL,
                put_delta_wall      REAL,
                gamma_inflection    REAL,
                delta_inflection    REAL,
                call_oi_wall        REAL,
                put_oi_wall         REAL,
                call_vanna_wall     REAL,
                put_vanna_wall      REAL,
                pin_width_pts       REAL,

                -- Nearest levels
                nearest_above_name  TEXT,
                nearest_above_val   REAL,
                nearest_above_dist  REAL,
                nearest_below_name  TEXT,
                nearest_below_val   REAL,
                nearest_below_dist  REAL,

                -- Greeks
                net_gamma           REAL,
                net_delta           REAL,
                net_vanna           REAL,
                charm_net           REAL,
                charm_direction     TEXT,
                charm_drift_toward  REAL,
                iv_level            REAL,
                iv_direction        TEXT,
                charm_magnitude     REAL,
                session_bucket      TEXT,
                vix_bucket          TEXT,
                put_call_oi_ratio   REAL,
                oi_center           REAL,
                gamma_pin           REAL,

                -- Cross-instrument SPY
                spy_spot            REAL,
                spy_chg_pct         REAL,
                spy_zone            TEXT,
                spy_vwap_side       TEXT,
                spy_net_delta       REAL,

                -- Cross-instrument QQQ
                qqq_spot            REAL,
                qqq_chg_pct         REAL,
                qqq_zone            TEXT,
                qqq_vwap_side       TEXT,
                qqq_net_delta       REAL,
                qqq_vs_spy          TEXT,
                qqq_vs_spy_delta    REAL,

                -- Cross-instrument IWM
                iwm_spot            REAL,
                iwm_chg_pct         REAL,
                iwm_zone            TEXT,
                iwm_vwap_side       TEXT,
                iwm_net_delta       REAL,
                iwm_vs_spy          TEXT,
                iwm_risk_signal     TEXT,

                -- SPY constituents
                nvda_chg_pct        REAL,
                aapl_chg_pct        REAL,
                msft_chg_pct        REAL,
                amzn_chg_pct        REAL,
                googl_chg_pct       REAL,
                goog_chg_pct        REAL,
                avgo_chg_pct        REAL,
                meta_chg_pct        REAL,
                tsla_chg_pct        REAL,
                spy_weighted_push   REAL,
                qqq_weighted_push   REAL,

                -- IWM sector proxies
                kre_chg_pct         REAL,
                xbi_chg_pct         REAL,
                psci_chg_pct        REAL,
                xrt_chg_pct         REAL,
                iwm_weighted_push   REAL,

                -- VIX
                vix_level           REAL,
                vix_direction       TEXT,
                vix_vs_prev         REAL,

                -- Rules engine output
                rules_signal        TEXT,
                rules_conviction    TEXT,
                rules_entry         REAL,
                rules_stop          REAL,
                rules_target        REAL,
                call_target2        REAL,
                rules_summary       TEXT,

                -- Model predictions
                pred_1c_up_prob     REAL,
                pred_1c_down_prob   REAL,
                pred_1c_flat_prob   REAL,
                pred_5c_up_prob     REAL,
                pred_5c_down_prob   REAL,
                pred_5c_flat_prob   REAL,
                pred_15c_up_prob    REAL,
                pred_15c_down_prob  REAL,
                pred_15c_flat_prob  REAL,
                pred_60c_up_prob    REAL,
                pred_60c_down_prob  REAL,
                pred_60c_flat_prob  REAL,
                pred_model_version  TEXT,
                pred_confidence     TEXT,
                pred_samples_used   INTEGER,
                prediction_direction    TEXT,
                prediction_dominant_prob REAL,

                -- Combined signal
                combined_signal     TEXT,
                combined_conviction TEXT,
                rules_pred_agree    INTEGER,    -- 0/1 boolean

                -- Regime classification
                regime_primary          TEXT,
                regime_confidence       TEXT,
                regime_score            REAL,

                -- Bayesian fusion
                fusion_dominant         TEXT,
                fusion_dominant_prob    REAL,
                fusion_confidence       TEXT,
                fusion_breakout         REAL,
                fusion_pinning          REAL,
                fusion_continuation     REAL,
                fusion_reversal         REAL,
                fusion_vol_expansion    REAL,
                fusion_mean_reversion   REAL,
                fusion_model_agreement  REAL,
                fusion_n_models_active  INTEGER,

                -- Monte Carlo
                mc_efe                  REAL,
                mc_eae                  REAL,
                mc_containment          REAL,
                mc_expansion            REAL,
                mc_upper_50             REAL,
                mc_lower_50             REAL,
                mc_paths                 INTEGER,
                mc_horizon               INTEGER,
                mc_vol_source            TEXT,
                mc_sigma_value           REAL,
                mc_conditioning          TEXT,

                -- Individual model outputs
                xgb_available           INTEGER,
                xgb_dominant            TEXT,
                xgb_confidence          REAL,
                lstm_available          INTEGER,
                lstm_dominant           TEXT,
                lstm_confidence         REAL,
                transformer_available   INTEGER,
                transformer_dominant    TEXT,
                transformer_confidence  REAL,

                -- Volatility signals
                iv_skew                 REAL,
                realized_vol            REAL,
                atr                     REAL,
                iv_rank                 REAL,
                iv_percentile           REAL,

                -- Section 8 predictive signals
                dpi_raw                 REAL,
                dpi_normalized          REAL,
                dpi_direction           TEXT,
                hedging_flow_score      REAL,
                hedging_flow_direction  TEXT,
                gamma_gradient          REAL,
                breakout_score          REAL,
                pin_score               REAL,
                vol_expansion_score     REAL,
                sweep_score             REAL,

                -- Session levels + sweeps
                session_high            REAL,
                session_low             REAL,
                last_sweep_type         TEXT,
                last_sweep_level        REAL,
                last_sweep_held         INTEGER,
                n_sweeps_today          INTEGER,

                -- Trade Validation Gate
                validation_passed       INTEGER,
                structure_valid         INTEGER,
                probability_valid       INTEGER,
                risk_valid              INTEGER,
                validation_summary      TEXT,

                -- Position Sizing
                r_units                 REAL,
                execution_mode          TEXT,

                -- Volatility Envelope
                vol_env_upper           REAL,
                vol_env_lower           REAL,

                -- Level Density
                level_density_count     INTEGER,
                level_density_label     TEXT,

                -- Sector Strength
                sector_leader           TEXT,
                sector_laggard          TEXT,
                sector_breadth          REAL,
                sector_risk_signal      TEXT,

                -- Index Strength
                index_leader            TEXT,
                index_laggard           TEXT,
                index_breadth           REAL,
                index_risk_signal       TEXT,

                -- SPY Holdings Strength
                spy_holdings_leader     TEXT,
                spy_holdings_laggard    TEXT,
                spy_holdings_breadth    REAL,
                spy_holdings_risk       TEXT,

                -- IWM Deep Confluence
                iwm_risk_regime         TEXT,
                iwm_risk_score          REAL,
                spy_iwm_divergence      REAL,
                spy_iwm_fragile         INTEGER,
                iwm_early_warning       INTEGER,
                rotation_signal         TEXT,

                -- Bond Yields
                tnx_yield               REAL,
                tnx_chg                 REAL,
                bond_signal             TEXT,

                -- Order Flow Signals
                vol_oi_ratio            REAL,
                flow_imbalance          REAL,
                flow_imbalance_source   TEXT,   -- RC-345/F11: book|volume|none economic identity
                smart_money_score       REAL,
                smart_money_direction   TEXT,
                iv_model_spread         REAL,

                -- Outcomes (NULL until filled)
                outcome_1c          TEXT,
                outcome_5c          TEXT,
                outcome_1c_pts      REAL,
                outcome_5c_pts      REAL,
                outcome_15c         TEXT,
                outcome_15c_pts     REAL,
                outcome_60c         TEXT,
                outcome_60c_pts     REAL,
                horizon_outcome_schema_version INTEGER NOT NULL DEFAULT 3,
                outcome_filled      INTEGER DEFAULT 0,

                -- Metadata
                created_at          TEXT DEFAULT (datetime('now'))
            );

            -- Canonical 1m OHLC closes (Schwab history + live accumulator) for bar-based horizon labels
            CREATE TABLE IF NOT EXISTS price_bars_1m (
                ticker              TEXT    NOT NULL,
                bar_start_ts_utc    REAL    NOT NULL,
                bar_end_ts_utc      REAL    NOT NULL,
                open                REAL,
                high                REAL,
                low                 REAL,
                close               REAL    NOT NULL,
                volume              REAL,
                source              TEXT    NOT NULL DEFAULT 'schwab_1m_accumulator_sqlite',
                PRIMARY KEY (ticker, bar_start_ts_utc)
            );
            CREATE INDEX IF NOT EXISTS idx_bars_1m_ticker_start
                ON price_bars_1m(ticker, bar_start_ts_utc);

            CREATE TABLE IF NOT EXISTS ed_schema_flags (
                flag_key    TEXT PRIMARY KEY,
                flag_value  TEXT NOT NULL,
                set_ts_utc  REAL
            );

            -- Indexes for fast lookup
            CREATE INDEX IF NOT EXISTS idx_snap_ticker_tf_ts
                ON snapshots(ticker, timeframe, ts_utc);
            CREATE INDEX IF NOT EXISTS idx_snap_outcome_unfilled
                ON snapshots(ticker, timeframe, outcome_filled)
                WHERE outcome_filled = 0;
            CREATE INDEX IF NOT EXISTS idx_snap_ts
                ON snapshots(ts_utc);
            -- idx_snap_similarity_zone_vwap (get_similar_setups' hot-path index) is created
            -- further down, guarded, after the legacy-column ALTER TABLE migration -- NOT
            -- here. This executescript's own CREATE TABLE above already carries zone/vwap_side
            -- for a fresh DB, but a pre-existing snapshots table missing either column made
            -- this CREATE INDEX IF NOT EXISTS raise sqlite3.OperationalError: no such column:
            -- zone and abort _init_db entirely (caught live by
            -- test_migration_issue4_clears_v2_labels' minimal legacy fixture).

            -- ── Level cross events ────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS level_crosses (
                cross_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker          TEXT    NOT NULL,
                ts_utc          REAL    NOT NULL,
                ts_et           TEXT    NOT NULL,
                level_name      TEXT    NOT NULL,
                level_value     REAL    NOT NULL,
                direction       TEXT    NOT NULL,
                spot_at_cross   REAL    NOT NULL,
                zone_before     TEXT,
                zone_after      TEXT,
                timeframe       TEXT,
                created_at      TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_cross_ticker_ts
                ON level_crosses(ticker, ts_utc);

            -- ── RC-354: daily ATM-IV history (IV Rank / IV Percentile burn-in) ──
            -- One row per (ticker, ET date); the writer UPSERTs so the LAST write of the
            -- session wins — the banked value converges to the day's CLOSING ATM IV, the
            -- convention IVR/IVP are defined against. Source = the terrain sigma-band's
            -- own ATM-IV computation (one faucet, zero added vendor calls).
            CREATE TABLE IF NOT EXISTS iv_daily (
                ticker        TEXT NOT NULL,
                date_et       TEXT NOT NULL,
                atm_iv_pct    REAL NOT NULL,
                dte_used      INTEGER,
                method        TEXT,
                ts_utc        REAL NOT NULL,
                PRIMARY KEY (ticker, date_et)
            );

            -- ── RC-359: daily per-strike OI (ΔOI walls: fresh vs stale positioning) ──
            -- One row per (ticker, ET date, strike); last write of the session wins. The
            -- overnight diff vs the prior banked session is the ΔOI read — computable only
            -- once two sessions exist (honest burn-in, same doctrine as iv_daily).
            CREATE TABLE IF NOT EXISTS oi_daily (
                ticker   TEXT NOT NULL,
                date_et  TEXT NOT NULL,
                strike   REAL NOT NULL,
                call_oi  REAL,
                put_oi   REAL,
                ts_utc   REAL NOT NULL,
                PRIMARY KEY (ticker, date_et, strike)
            );

            -- ── Model accuracy tracking ───────────────────────────────────────
            CREATE TABLE IF NOT EXISTS model_accuracy (
                acc_id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc              REAL    NOT NULL,
                ticker              TEXT    NOT NULL,
                timeframe           TEXT    NOT NULL,
                model_version       TEXT    NOT NULL,
                horizon             TEXT    NOT NULL,   -- '1c', '3c', '5c'
                total_predictions   INTEGER,
                correct_direction   INTEGER,
                accuracy_pct        REAL,
                avg_confidence      REAL,
                computed_at         TEXT DEFAULT (datetime('now'))
            );

            -- ── Options/Gamma heatmap restart-durable snapshot (operator directive,
            -- 2026-09-15, canonical input-validity rules; DB ownership review, 2026-09-15,
            -- fourth pass) ── Per (ticker, strike, expiry) last-known-VALID gex/dex/vanna, so
            -- a genuine current-cycle vendor failure (invalid greeks, or a whole-surface OI
            -- outage) can display the latest valid timestamped snapshot instead of erasing the
            -- cell, and that snapshot survives a process restart. ALWAYS-LATEST, not a time
            -- series (INSERT OR REPLACE on this exact primary key) -- a display-durability
            -- checkpoint only ever needs the newest known-good value per cell, never a history.
            -- Not a duplicate of option_chain_accrual (RC-159): that table is a per-STRIKE
            -- aggregate collapsed across every expiry (a session gamma-ladder time series);
            -- this table is the per-CELL (strike × expiry) analogue the Options/Gamma heatmap
            -- grid actually needs, which nothing else in this schema persists at that
            -- granularity. Owned here (schema + read/write), not by server.py independently
            -- opening its own raw connections -- this IS the canonical database interface.
            CREATE TABLE IF NOT EXISTS gamma_surface_last_valid (
                ticker          TEXT NOT NULL,
                strike          REAL NOT NULL,
                expiry          TEXT NOT NULL,
                gex             REAL,
                dex             REAL,
                vanna           REAL,
                captured_ts_utc REAL NOT NULL,
                PRIMARY KEY (ticker, strike, expiry)
            );

            """)
        log.info("Schema initialized")


    def _migrate_schema(self):
        """Add columns that may be missing from older databases.
        Safe to call repeatedly — silently skips columns that already exist."""
        NEW_COLUMNS = [
            # (column_name, column_type)
            ("charm_magnitude",     "REAL"),
            ("session_bucket",      "TEXT"),
            ("vix_bucket",          "TEXT"),
            ("pred_15c_up_prob",    "REAL"),
            ("pred_15c_down_prob",  "REAL"),
            ("pred_15c_flat_prob",  "REAL"),
            ("outcome_15c",         "TEXT"),
            ("outcome_15c_pts",     "REAL"),
            ("outcome_60c",         "TEXT"),
            ("outcome_60c_pts",     "REAL"),
            ("pred_60c_up_prob",    "REAL"),
            ("pred_60c_down_prob",  "REAL"),
            ("pred_60c_flat_prob",  "REAL"),
            ("horizon_outcome_schema_version", "INTEGER"),
            ("call_target2",            "REAL"),
            # ── Model stack (added Session 5) ─────────────────────────
            ("regime_primary",          "TEXT"),
            ("regime_confidence",       "TEXT"),
            ("regime_score",            "REAL"),
            ("fusion_dominant",         "TEXT"),
            ("fusion_dominant_prob",    "REAL"),
            ("fusion_dominant_direction", "TEXT"),
            ("fusion_prob_down",        "REAL"),
            ("fusion_prob_flat",        "REAL"),
            ("fusion_prob_up",          "REAL"),
            ("fusion_confidence",       "TEXT"),
            ("fusion_breakout",         "REAL"),
            ("fusion_pinning",          "REAL"),
            ("fusion_continuation",     "REAL"),
            ("fusion_reversal",         "REAL"),
            ("fusion_vol_expansion",    "REAL"),
            ("fusion_mean_reversion",   "REAL"),
            ("fusion_model_agreement",  "REAL"),
            ("fusion_n_models_active",  "INTEGER"),
            ("mc_efe",                  "REAL"),
            ("mc_eae",                  "REAL"),
            ("mc_containment",          "REAL"),
            ("mc_expansion",            "REAL"),
            ("mc_upper_50",             "REAL"),
            ("mc_lower_50",             "REAL"),
            ("xgb_available",           "INTEGER"),
            ("xgb_dominant",            "TEXT"),
            ("xgb_confidence",          "REAL"),
            ("xgb_approved",            "INTEGER"),
            ("lstm_available",          "INTEGER"),
            ("lstm_dominant",           "TEXT"),
            ("lstm_confidence",         "REAL"),
            ("lstm_approved",           "INTEGER"),
            ("transformer_available",   "INTEGER"),
            ("transformer_dominant",    "TEXT"),
            ("transformer_confidence",  "REAL"),
            ("transformer_approved",    "INTEGER"),
            # ── Volatility signals ─────────────────────────────────
            ("iv_skew",                 "REAL"),
            ("realized_vol",            "REAL"),
            ("atr",                     "REAL"),
            ("iv_rank",                 "REAL"),
            ("iv_percentile",           "REAL"),
            # ── Section 8 predictive signals ───────────────────────
            ("dpi_raw",                 "REAL"),
            ("dpi_normalized",          "REAL"),
            ("dpi_direction",           "TEXT"),
            ("hedging_flow_score",      "REAL"),
            ("hedging_flow_direction",  "TEXT"),
            ("gamma_gradient",          "REAL"),
            ("breakout_score",          "REAL"),
            ("pin_score",               "REAL"),
            ("vol_expansion_score",     "REAL"),
            ("sweep_score",             "REAL"),
            # ── Session levels + sweeps ────────────────────────────
            ("session_high",            "REAL"),
            ("session_low",             "REAL"),
            ("last_sweep_type",         "TEXT"),
            ("last_sweep_level",        "REAL"),
            ("last_sweep_held",         "INTEGER"),
            ("n_sweeps_today",          "INTEGER"),
            # ── Trade Validation Gate ──────────────────────────────
            ("validation_passed",       "INTEGER"),
            ("structure_valid",         "INTEGER"),
            ("probability_valid",       "INTEGER"),
            ("risk_valid",              "INTEGER"),
            ("validation_summary",      "TEXT"),
            # ── Position Sizing ────────────────────────────────────
            ("r_units",                 "REAL"),
            ("execution_mode",          "TEXT"),
            # ── Volatility Envelope ────────────────────────────────
            ("vol_env_upper",           "REAL"),
            ("vol_env_lower",           "REAL"),
            # ── Level Density ──────────────────────────────────────
            ("level_density_count",     "INTEGER"),
            ("level_density_label",     "TEXT"),
            # ── Sector Strength ────────────────────────────────────
            ("sector_leader",           "TEXT"),
            ("sector_laggard",          "TEXT"),
            ("sector_breadth",          "REAL"),
            ("sector_risk_signal",      "TEXT"),
            # ── Index Strength ─────────────────────────────────────
            ("index_leader",            "TEXT"),
            ("index_laggard",           "TEXT"),
            ("index_breadth",           "REAL"),
            ("index_risk_signal",       "TEXT"),
            # ── SPY Holdings Strength ──────────────────────────────
            ("spy_holdings_leader",     "TEXT"),
            ("spy_holdings_laggard",    "TEXT"),
            ("spy_holdings_breadth",    "REAL"),
            ("spy_holdings_risk",       "TEXT"),
            # ── IWM Deep Confluence ────────────────────────────────
            ("iwm_risk_regime",         "TEXT"),
            ("iwm_risk_score",          "REAL"),
            ("spy_iwm_divergence",      "REAL"),
            ("spy_iwm_fragile",         "INTEGER"),
            ("iwm_early_warning",       "INTEGER"),
            ("rotation_signal",         "TEXT"),
            # ── Bond Yields ────────────────────────────────────────
            ("tnx_yield",               "REAL"),
            ("tnx_chg",                 "REAL"),
            ("bond_signal",             "TEXT"),
            # ── Order Flow Signals ─────────────────────────────────
            ("vol_oi_ratio",            "REAL"),
            ("flow_imbalance",          "REAL"),
            ("flow_imbalance_source",   "TEXT"),   # RC-345/F11: economic book identity
            ("smart_money_score",       "REAL"),
            ("smart_money_direction",   "TEXT"),
            ("iv_model_spread",         "REAL"),
            ("spread",                  "REAL"),
            # ── DTE / hours to expiry (ET authority) ───────────────────────────
            ("hours_to_expiry",         "REAL"),
            # ── Prediction direction + MC metadata (persistence fix) ───────────
            ("prediction_direction",    "TEXT"),
            ("prediction_dominant_prob", "REAL"),
            ("mc_paths",                "INTEGER"),
            ("mc_horizon",              "INTEGER"),
            ("mc_vol_source",           "TEXT"),
            ("mc_sigma_value",          "REAL"),
            ("mc_conditioning",         "TEXT"),
            # ── Zone recency (no mixed-clock) ──────────────────────────────────
            ("zone_since_bars_1m",      "INTEGER"),   # execution-layer (1m bars)
            ("zone_since_bars_5m",      "INTEGER"),   # structure-layer (5m bars)
            # ── Option chain archive (realized contract-level eval) ───────────
            ("option_chain_json",       "TEXT"),
            ("replay_context_json",     "TEXT"),
            # ── Institutional behavior + news context ──────────────────────────
            ("absorption_score",         "REAL"),
            ("continuation_score",       "REAL"),
            ("liquidity_behavior_label", "TEXT"),
            ("sentiment_composite",      "REAL"),
            ("sentiment_buzz",           "REAL"),
            ("sentiment_finnhub",        "REAL"),
            ("sentiment_av",             "REAL"),
            ("breaking_news_flag",       "INTEGER"),
            ("breaking_news_headline",   "TEXT"),
            ("pre_market_sentiment",     "REAL"),
            ("qqq_weighted_push",        "REAL"),
            # ── Raw Schwab quote primitives (2026-06-10, operator: log leaves, not
            # only derivations — order-flow ablation candidates) ────────────────
            ("bid_price",                "REAL"),
            ("ask_price",                "REAL"),
            ("bid_size",                 "REAL"),
            ("ask_size",                 "REAL"),
            ("last_size",                "REAL"),
            ("total_volume",             "REAL"),
            # ── SnapshotRow fields absent from fresh-DB schema (FIND 2026-06-10):
            # insert_snapshot writes every dataclass field, so a fresh DB failed
            # with "no column named pred_model_source". Canonical DB only worked
            # because these columns were added historically outside this list. ──
            ("pred_model_source",        "TEXT"),
            ("pred_override_source",     "TEXT"),
            ("reward_risk",              "REAL"),
            ("reward_risk2",             "REAL"),
            # ── Price-action cone (operator 2026-06-11) — see SnapshotRow pa_* block.
            # Names must match features/signal_layer_v1.SNAPSHOT_PRICE_ACTION_COLUMNS.
            ("pa_ret_1m_pct",            "REAL"),
            ("pa_ret_3m_pct",            "REAL"),
            ("pa_ret_5m_pct",            "REAL"),
            ("pa_ret_15m_pct",           "REAL"),
            ("pa_ret_30m_pct",           "REAL"),
            ("pa_ret_60m_pct",           "REAL"),
            ("pa_trend_slope_log20",     "REAL"),
            ("pa_trend_slope_log40",     "REAL"),
            ("pa_structure_state",       "REAL"),
            ("pa_bos_up",                "REAL"),
            ("pa_bos_down",              "REAL"),
            ("pa_dist_swing_high_atr",   "REAL"),
            ("pa_dist_swing_low_atr",    "REAL"),
            ("pa_range_position_n20",    "REAL"),
            ("pa_vwap_zscore",           "REAL"),
            ("pa_atr_pctile_60",         "REAL"),
            ("pa_atr_expansion_5_20",    "REAL"),
            ("pa_realized_vol_ann",      "REAL"),
            ("pa_wick_asymmetry",        "REAL"),
            ("pa_close_location",        "REAL"),
            ("pa_impulse_run_signed",    "REAL"),
            ("pa_mtf_trend_1m",          "REAL"),
            ("pa_mtf_trend_5m",          "REAL"),
            ("pa_mtf_bias_15m",          "REAL"),
            ("pa_mtf_alignment",         "REAL"),
            ("pa_relative_volume",       "REAL"),
            ("pa_move_efficiency",       "REAL"),
        ]
        # Normalized training table must carry the same price-action columns or the
        # normalizer's column-intersection INSERT silently drops them (Issue 16 class).
        _PA_NEW_COLUMNS = [(c, t) for c, t in NEW_COLUMNS if c.startswith("pa_")]

        added = 0
        with self._connect() as conn:
            for col_name, col_type in NEW_COLUMNS:
                try:
                    conn.execute(
                        f"ALTER TABLE snapshots ADD COLUMN {col_name} {col_type}"
                    )
                    added += 1
                    log.info(f"DB migration: added column {col_name}")
                except sqlite3.OperationalError:
                    pass  # column already exists
        if added:
            log.info(f"Schema migration: added {added} new columns to snapshots")

        # RC spot/gamma-360-audit (2026-09-14): get_similar_setups' tiers 1-4 filter on
        # (ticker, timeframe, zone, vwap_side, outcome_1c IS NOT NULL), then ORDER BY
        # ts_utc DESC LIMIT n. idx_snap_ticker_tf_ts covers only (ticker, timeframe, ts_utc),
        # so SQLite must walk the WHOLE ticker+timeframe partition in ts_utc order, reading
        # every row's on-disk page (each row carries two large JSON blob columns -- reading
        # them off disk costs the same whether or not they end up SELECTed) until it finds
        # n_similar (500) matches on the far narrower zone+vwap_side+outcome_1c predicate.
        # MEASURED live (406,532-row snapshots table, 72,285 SPY/1m rows): a single real
        # get_similar_setups call took 11.1-13.8s -- run from 3-4 background threads on every
        # analytics cycle, this is the dominant, proven source of the "app is slow" and "spot
        # has latency" symptoms reported live during RTH (py-spy caught these threads parked
        # here at the exact moments ordinary quote reads stalled 1-7s).
        # Partial (WHERE outcome_1c IS NOT NULL, mirroring idx_snap_outcome_unfilled's own
        # precedent) so the ~half of rows that can never qualify are never indexed at all, and
        # ts_utc last so tier queries' ORDER BY ts_utc DESC LIMIT n is satisfied directly from
        # the index without a separate sort step. Guarded (not in the executescript above):
        # runs after the ALTER TABLE column-patch loop just above, so a legacy/minimal
        # snapshots table genuinely missing zone or vwap_side skips the index instead of
        # aborting _init_db (see the executescript's own note at this index's old location).
        try:
            with self._connect() as conn:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_snap_similarity_zone_vwap "
                    "ON snapshots(ticker, timeframe, zone, vwap_side, ts_utc) "
                    "WHERE outcome_1c IS NOT NULL"
                )
        except sqlite3.OperationalError:
            pass  # zone/vwap_side not present on this schema

        for tbl in ("snapshots_1m_normalized",):
            try:
                with self._connect() as conn:
                    conn.execute(
                        "ALTER TABLE snapshots_1m_normalized ADD COLUMN qqq_weighted_push REAL"
                    )
                log.info("DB migration: added qqq_weighted_push to snapshots_1m_normalized")
            except sqlite3.OperationalError:
                pass

        for col_name, col_type in (
            ("pred_15c_up_prob", "REAL"),
            ("pred_15c_down_prob", "REAL"),
            ("pred_15c_flat_prob", "REAL"),
            ("outcome_15c", "TEXT"),
            ("outcome_15c_pts", "REAL"),
            ("outcome_60c", "TEXT"),
            ("outcome_60c_pts", "REAL"),
            ("pred_60c_up_prob", "REAL"),
            ("pred_60c_down_prob", "REAL"),
            ("pred_60c_flat_prob", "REAL"),
        ):
            try:
                with self._connect() as conn:
                    conn.execute(
                        f"ALTER TABLE snapshots_1m_normalized ADD COLUMN {col_name} {col_type}"
                    )
                log.info("DB migration: added %s to snapshots_1m_normalized", col_name)
            except sqlite3.OperationalError:
                pass

        # Issue 16: keep snapshots_1m_normalized aligned with snapshots for materialize INSERT.
        # Missing this column caused INSERT to fail silently (transaction rollback) and left
        # training table with NULL outcome_15c / outcome_60c while snapshots were populated.
        try:
            with self._connect() as conn:
                conn.execute(
                    "ALTER TABLE snapshots_1m_normalized ADD COLUMN "
                    "horizon_outcome_schema_version INTEGER NOT NULL DEFAULT "
                    f"{int(HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1)}"
                )
                log.info(
                    "DB migration: added horizon_outcome_schema_version to snapshots_1m_normalized"
                )
        except sqlite3.OperationalError:
            pass

        for tbl in ("snapshots_1m_normalized",):
            for col_name, col_type in (
                # RC-6 (reopened 2026-07-28): option_chain_json and replay_context_json are
                # DELIBERATELY ABSENT from this list. They are the normalized table's SECOND
                # copy of multi-MB blobs the cull ledger retired — yet this migrate re-ADDed
                # them on every boot where they were missing, and the normalizer's
                # column-intersection INSERT refilled them (measured regrowth: 1,097 rows /
                # 187,193,762 bytes). The intersection DROPS absent columns silently by
                # design, so their absence is safe; the raw `snapshots` table keeps the one
                # authoritative copy. Re-introducing them here requires the supervised
                # migration (operator, due 2026-08-09) — never a silent boot-time ADD.
                # Raw Schwab quote primitives — must exist here too or the
                # normalizer's column-intersection INSERT silently drops them.
                ("bid_price", "REAL"),
                ("ask_price", "REAL"),
                ("bid_size", "REAL"),
                ("ask_size", "REAL"),
                ("last_size", "REAL"),
                ("total_volume", "REAL"),
            ):
                try:
                    with self._connect() as conn:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                    log.info("DB migration: added %s to %s", col_name, tbl)
                except sqlite3.OperationalError:
                    pass

        for col_name, col_type in _PA_NEW_COLUMNS:
            try:
                with self._connect() as conn:
                    conn.execute(
                        f"ALTER TABLE snapshots_1m_normalized ADD COLUMN {col_name} {col_type}"
                    )
                log.info("DB migration: added %s to snapshots_1m_normalized", col_name)
            except sqlite3.OperationalError:
                pass

        for col_name, col_type in (
            ("pressure_label", "TEXT"),
            ("pressure_trend", "TEXT"),
        ):
            for tbl in ("snapshots", "snapshots_1m_normalized"):
                try:
                    with self._connect() as conn:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                    log.info("DB migration: added %s to %s", col_name, tbl)
                except sqlite3.OperationalError:
                    pass

        for col_name, col_type in (("logger_source", "TEXT"),):
            for tbl in ("snapshots", "snapshots_1m_normalized"):
                try:
                    with self._connect() as conn:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                    log.info("DB migration: added %s to %s", col_name, tbl)
                except sqlite3.OperationalError:
                    pass

        # Independent-review finding (2026-09-12), REPRODUCED: market_context.py's
        # SYMBOL_TO_SNAPSHOT_CHG_COL aliased GOOG onto this same googl_chg_pct column
        # (there was no goog_chg_pct to point to), so every confluence recompute silently
        # substituted GOOGL's change for GOOG's own -- double-counting GOOGL's move at both
        # symbols' weights in SPY_TOP/QQQ_TOP and dropping GOOG's real, independently
        # diverging price action entirely. GOOG is Alphabet's class-C share, a distinct
        # instrument from GOOGL (class A); it gets its own column, same as every other
        # constituent.
        for col_name, col_type in (("goog_chg_pct", "REAL"),):
            for tbl in ("snapshots", "snapshots_1m_normalized"):
                try:
                    with self._connect() as conn:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                    log.info("DB migration: added %s to %s", col_name, tbl)
                except sqlite3.OperationalError:
                    pass

        _ctx_cols = (
            ("absorption_score", "REAL"),
            ("continuation_score", "REAL"),
            ("liquidity_behavior_label", "TEXT"),
            ("sentiment_composite", "REAL"),
            ("sentiment_buzz", "REAL"),
            ("sentiment_finnhub", "REAL"),
            ("sentiment_av", "REAL"),
            ("breaking_news_flag", "INTEGER"),
            ("breaking_news_headline", "TEXT"),
            ("pre_market_sentiment", "REAL"),
        )
        for col_name, col_type in _ctx_cols:
            for tbl in ("snapshots", "snapshots_1m_normalized"):
                try:
                    with self._connect() as conn:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                    log.info("DB migration: added %s to %s", col_name, tbl)
                except sqlite3.OperationalError:
                    pass

        # Movement-target v1/v2: dir, move, valid_dir, threshold_move (+ legacy outcome_move_thr_pts)
        for _dcol, _mcol, _vdcol, _tmcol, _legtcol, _, _slug in OUTCOME_MOVEMENT_V1_SPECS:
            for tbl in ("snapshots", "snapshots_1m_normalized"):
                for col_name, col_type in (
                    (_dcol, "TEXT"),
                    (_mcol, "TEXT"),
                    (_vdcol, "INTEGER"),
                    (_tmcol, "REAL"),
                    (_legtcol, "REAL"),
                ):
                    try:
                        with self._connect() as conn:
                            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                        log.info("DB migration: added %s to %s", col_name, tbl)
                    except sqlite3.OperationalError:
                        pass

        try:
            from ml_horizon import ML_HORIZON_SLUGS

            _ml_hz = ML_HORIZON_SLUGS
        except Exception:
            _ml_hz = ("1c", "5c", "15c", "60c")
        for _hz in _ml_hz:
            for tbl in ("snapshots", "snapshots_1m_normalized"):
                for col_name, col_type in (
                    (f"pred_{_hz}_dir_up_prob", "REAL"),
                    (f"pred_{_hz}_dir_down_prob", "REAL"),
                    (f"pred_{_hz}_move_prob", "REAL"),
                    (f"pred_{_hz}_no_move_prob", "REAL"),
                    (f"pred_dir_up_prob_{_hz}", "REAL"),
                    (f"pred_dir_down_prob_{_hz}", "REAL"),
                    (f"pred_move_prob_{_hz}", "REAL"),
                    (f"pred_no_move_prob_{_hz}", "REAL"),
                ):
                    try:
                        with self._connect() as conn:
                            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                        log.info("DB migration: added %s to %s", col_name, tbl)
                    except sqlite3.OperationalError:
                        pass

        # Fusion policy columns (per governed horizon; policy/calibration authority)
        for _hz in _ml_hz:
            for tbl in ("snapshots", "snapshots_1m_normalized"):
                for col_name, col_type in (
                    (f"fused_move_prob_{_hz}", "REAL"),
                    (f"fused_dir_up_prob_{_hz}", "REAL"),
                    (f"fused_confidence_{_hz}", "REAL"),
                    (f"fused_contributing_models_{_hz}", "TEXT"),
                    (f"fused_stack_status_{_hz}", "TEXT"),
                ):
                    try:
                        with self._connect() as conn:
                            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}")
                        log.info("DB migration: added %s to %s", col_name, tbl)
                    except sqlite3.OperationalError:
                        pass

        for tbl in ("snapshots", "snapshots_1m_normalized"):
            try:
                with self._connect() as conn:
                    conn.execute(
                        f"ALTER TABLE {tbl} ADD COLUMN fusion_replay_stack_grade_v1 TEXT"
                    )
                log.info("DB migration: added fusion_replay_stack_grade_v1 to %s", tbl)
            except sqlite3.OperationalError:
                pass

        self._migrate_horizon_bar_contract_v1()
        self._migrate_outcome_anchor_bar_canonical()
        self._migrate_drop_session_log_v1()
        self._migrate_drop_confluence_log_v1()
        self._migrate_drop_news_events_v1()

        # execution_identity_v1 (PER_ROW_HISTORICAL_MODEL_ARTIFACT_IDENTITY_V1):
        # additive — identity tables + (decision_id, execution_identity_sha256,
        # execution_identity_class) columns + linkage triggers.  Legacy rows keep
        # NULL identity forever (no backfill of any kind).
        # EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1: the dependent tables MUST
        # exist BEFORE the identity schema runs, or a FRESH database gets no
        # linkage triggers on the decision-record and calibration decision-log
        # tables and identity-less governed rows can land ungoverned (caught by
        # the 2026-07-13 noncanonical runtime proof: 2 decision rows persisted
        # with a decision_id and no identity on a fresh proof DB). Existence is
        # checked read-only first so an already-migrated database never starts
        # a write transaction here (a held BEGIN IMMEDIATE elsewhere must keep
        # aborting preflights gracefully, not leak a locked error from init).
        try:
            from calibration.schema import CALIBRATION_DECISION_LOG_TABLE
            from execution_identity import ensure_execution_identity_schema

            with self._connect() as conn:
                existing = {
                    r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "production_decision_records" not in existing:
                    from decision_record import ensure_production_decision_schema

                    ensure_production_decision_schema(conn)
                if CALIBRATION_DECISION_LOG_TABLE not in existing:
                    from calibration.schema import ensure_calibration_schema

                    ensure_calibration_schema(conn)
                ensure_execution_identity_schema(conn)
        except sqlite3.OperationalError as exc:
            log.error("execution identity schema migration failed: %s", exc)
            raise

    def _migrate_horizon_bar_contract_v1(self) -> None:
        """
        Issue 3: one-time auditable invalidation of poll-window outcomes + schema flag.
        All active outcome_* labels use bar-based universal contract (schema version 2).
        """
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS price_bars_1m (
                    ticker              TEXT    NOT NULL,
                    bar_start_ts_utc    REAL    NOT NULL,
                    bar_end_ts_utc      REAL    NOT NULL,
                    open                REAL,
                    high                REAL,
                    low                 REAL,
                    close               REAL    NOT NULL,
                    volume              REAL,
                    source              TEXT    NOT NULL DEFAULT 'schwab_1m_accumulator_sqlite',
                    PRIMARY KEY (ticker, bar_start_ts_utc)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ed_schema_flags (
                    flag_key    TEXT PRIMARY KEY,
                    flag_value  TEXT NOT NULL,
                    set_ts_utc  REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_bars_1m_ticker_start ON price_bars_1m(ticker, bar_start_ts_utc)"
            )
            row = conn.execute(
                "SELECT flag_value FROM ed_schema_flags WHERE flag_key = ?",
                ("horizon_bar_v1_legacy_poll_invalidated",),
            ).fetchone()
            if row is not None:
                return
            log.warning(
                "Issue 3 migration: clearing all outcome_* labels written under legacy poll windows; "
                "recomputing only from price_bars_1m (bar close, UTC 1m grid). "
                "Rows set horizon_outcome_schema_version=%s.",
                HORIZON_OUTCOME_SCHEMA_BAR_V1,
            )
            _null_outcomes = ", ".join(
                f"{odir} = NULL, {opt} = NULL"
                for odir, opt, _n in OUTCOME_BAR_SPECS
            )
            conn.execute(
                f"""
                UPDATE snapshots SET
                    {_null_outcomes},
                    outcome_filled = 0,
                    horizon_outcome_schema_version = {int(HORIZON_OUTCOME_SCHEMA_BAR_V1)}
                """
            )
            conn.execute(
                """
                INSERT INTO ed_schema_flags (flag_key, flag_value, set_ts_utc)
                VALUES (?, ?, ?)
                """,
                (
                    "horizon_bar_v1_legacy_poll_invalidated",
                    "1",
                    _wall_time.time(),
                ),
            )

    def _migrate_outcome_anchor_bar_canonical(self) -> None:
        """
        Issue 4: one-time invalidation of outcomes whose anchor was snapshots.spot.
        Active contract: schema version 3 — anchor_close from price_bars_1m (bar_end_ts_utc <= ts_utc).
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT flag_value FROM ed_schema_flags WHERE flag_key = ?",
                ("horizon_outcome_anchor_bar_close_v1",),
            ).fetchone()
            if row is not None:
                return
            log.warning(
                "Issue 4 migration: clearing outcome_* / outcome_*_pts that used snapshots.spot as anchor; "
                "anchor is now last completed price_bars_1m close (bar_end_ts_utc <= ts_utc). "
                "Rows set horizon_outcome_schema_version=%s.",
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            )
            _null_outcomes = ", ".join(
                f"{odir} = NULL, {opt} = NULL"
                for odir, opt, _n in OUTCOME_BAR_SPECS
            )
            conn.execute(
                f"""
                UPDATE snapshots SET
                    {_null_outcomes},
                    outcome_filled = 0,
                    horizon_outcome_schema_version = {int(HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1)}
                WHERE COALESCE(horizon_outcome_schema_version, 0) < {int(HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1)}
                """
            )
            conn.execute(
                """
                INSERT INTO ed_schema_flags (flag_key, flag_value, set_ts_utc)
                VALUES (?, ?, ?)
                """,
                (
                    "horizon_outcome_anchor_bar_close_v1",
                    "1",
                    _wall_time.time(),
                ),
            )

    def _ensure_normalized_table(self):
        """
        Ensure snapshots_1m_normalized exists for training on resampled 1m data.
        Created from snapshots schema + normalized_from_subminute.
        Historical sub-minute snapshots (timeframe='5m') are resampled here.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='snapshots_1m_normalized'"
            )
            if cur.fetchone() is not None:
                return

            # Create table with same structure as snapshots + normalized_from_subminute
            conn.execute("""
                CREATE TABLE snapshots_1m_normalized AS
                SELECT s.*, 1 AS normalized_from_subminute
                FROM snapshots s WHERE 0
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_snap1m_ticker_ts
                ON snapshots_1m_normalized(ticker, ts_utc)
            """)
            log.info("Created snapshots_1m_normalized table for resampled 1m training data")

    def _migrate_drop_session_log_v1(self) -> None:
        """Pass 6 — drop the session_log table.

        session_log was scaffolded with start_session / end_session /
        update_session_counts writers but zero production callers (one of the
        4 originally-known dormants). verification/daily_health.py already
        covers richer per-ticker session telemetry, so the table delivers
        no incremental value. Drop is idempotent (IF EXISTS).
        """
        with self._connect() as conn:
            try:
                conn.execute("DROP TABLE IF EXISTS session_log")
            except sqlite3.OperationalError as exc:
                log.warning("drop session_log failed: %s", exc)

    def _migrate_drop_news_events_v1(self) -> None:
        """Pass 8 — drop the news_events table.

        news_events was scaffolded with insert_news_event writer and a single
        guarded call site in news_sentiment.py:refresh_and_context, but zero
        production readers. Operator-authorized drop 2026-05-26 after Cursor
        identified it as the only remaining table-level dormancy with a live
        writer post-Pass 7. News headlines reach the operator UI via
        ms.news_context (live aggregator), persistence added no value.
        """
        with self._connect() as conn:
            try:
                conn.execute("DROP INDEX IF EXISTS idx_news_ticker_ts")
                conn.execute("DROP INDEX IF EXISTS idx_news_impact_ts")
                conn.execute("DROP TABLE IF EXISTS news_events")
            except sqlite3.OperationalError as exc:
                log.warning("drop news_events failed: %s", exc)

    def _migrate_drop_confluence_log_v1(self) -> None:
        """Pass 7 — drop the confluence_log table.

        confluence_log was scaffolded with log_confluence writer + ConfluenceLog
        dataclass but zero production callers / zero readers. Cross-instrument
        confluence state (spy_state / qqq_state / iwm_state / vix_state) is
        already computed live per refresh in market_state and surfaced through
        ms_dict for /api/state consumers; persisting it added no incremental
        value because no analyzer ever read confluence_log rows back. Drop is
        idempotent (IF EXISTS).
        """
        with self._connect() as conn:
            try:
                conn.execute("DROP TABLE IF EXISTS confluence_log")
            except sqlite3.OperationalError as exc:
                log.warning("drop confluence_log failed: %s", exc)
