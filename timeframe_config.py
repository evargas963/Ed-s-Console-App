"""
timeframe_config.py — Canonical Timeframe Configuration
========================================================
Central source of truth for the system's default/primary candle timeframe.
Used by server, db, lstm_data, transformer_train, ml_scheduler, signals, etc.

1m is the canonical timeframe: live state, snapshots, features, and model training
all use 1m by default. 5m remains available as derived/higher-timeframe context.

Zone recency semantics (no mixed-clock):
  zone_since_bars_1m  — execution-layer recency (1m bars).
  zone_since_bars_5m  — structure-layer recency (5m bars).
  zone_since_bars     — alias for zone_since_bars_1m (model/DB backward compat).

System-wide 1m canonical:
  - Snapshots, features, training: timeframe=1m
  - Order flow candles: 1m only (execution-aligned; no 5m fallback)
  - recent_crosses.bars_ago: 60s per bar (1m)
  - outcome_Nc: N bars at snapshot timeframe (~N min with 1m)
  - LSTM/Transformer: both streams use 1m snapshots (naming 5m/1m is legacy)

Readiness structure inputs (setup_readiness.py; NOT 5m):
  - structure_confirmation ← pred.timeframe_reads["15m"]  (~15m structure role)
  - structure_higher_tf    ← pred.timeframe_reads["1h"]   (~1h trend role)

Stack / ML horizon alignment (trader policy — 1 / 5 / 15 / 60 minute clocks on 1m snapshots):
  - **Product horizons:** 1m + 5m = primary **day-trade** execution; 15m = **intraday swing** context; 60m = **intraday swing / short swing** (still RTH stack, not multi-day).
  - **Target architecture:** For **each** clock (1, 5, 15, 60), run a **parallel copy** of the stack: every model family that votes direction is **trained/calibrated on that horizon’s label** (outcome or sim horizon), then fused **at that same H**. Four clocks ⇒ four directional composites (four “stacks”), not one stack smeared across mismatched labels.
  - **Tracer-bullet slice (same idea):** One thin vertical path per H — data labeled at H, models trained for H, inference and stack votes consumed at H, then (when built) Call at H — proves the pipeline without mixing horizons in one head.
  - **Call card (future):** Once above exists, the Call can show **four horizon-specific decisions** (or one primary + three confidence bands); today the Call is still **one** synthesis tied mainly to the **prediction card’s primary head** (see prediction_engine).

  **RETRAIN REMINDER — do after horizon/schema work is complete:**
  Retrain **each** stack-integrated model (and MC/fusion where applicable) **per** product horizon (1, 5, 15, 60) so WDS rows and stack votes are apples-to-apples. Until then, probabilities by timeframe are **not** guaranteed to be four independent aligned stacks.

  **`outcome_Nc` / `pred_Nc`:** Universal **bar-based** contract (Issues 3–4): anchor = **close** of the last completed **1m** canonical bar in `price_bars_1m` with `<= ts_utc` (`bar_end_ts_utc`); forward reference = **close** of the canonical **1m** bar keyed by `bar_start_ts_utc` (UTC grid). Never `snapshots.spot`. See `horizon_outcomes.py`, `db.fill_outcomes`, `db.upsert_1m_bars`. One-time invalidations: `ed_schema_flags.horizon_bar_v1_legacy_poll_invalidated`, `horizon_outcome_anchor_bar_close_v1`. Sparse similar-sets still use **explicit neutral thirds** (`insufficient_labeled_*`).

  **Running gaps:** see project root **`OPEN_ITEMS.md`** (stays open until each row is resolved in code).
"""

# Canonical timeframe — primary candle source for live state, snapshots, features, training
CANONICAL_TIMEFRAME: str = "1m"

# Derived context timeframe — used for structure analysis, LSTM secondary stream
DERIVED_TIMEFRAME: str = "5m"

# Table for 1m training data — normalized from sub-minute snapshots (never raw timeframe='5m')
SNAPSHOT_TABLE_1M: str = "snapshots_1m_normalized"

# Outcome horizon semantics (when using CANONICAL_TIMEFRAME='1m'):
#   outcome_1c: 1 × 1m bar = ~1 min ahead (was 5 min with 5m)
#   outcome_5c: 5 × 1m bars = ~5 min ahead (was 25 min with 5m)
#   outcome_13c: **13** × 1m bars — **legacy name**; product label “15m” targets **15** bars after migration to outcome_15c.
# See MIGRATION_OUTCOME_HORIZONS in this file for full mapping.
MIGRATION_OUTCOME_HORIZONS: dict = {
    "outcome_1c": "1m: ~1 min ahead | 5m (legacy): ~5 min ahead",
    "outcome_5c": "1m: ~5 min ahead | 5m (legacy): ~25 min ahead",
    "outcome_13c": "LEGACY: 13×1m bars (~13 min) — retained for history; prefer outcome_15c for 15m product clock",
    "outcome_15c": "PRODUCT: 15×1m bars (~15 min ahead on canonical 1m clock)",
}

# Tri-class empirical horizons persisted on snapshots as pred_{slug}_* (canonical 1m clock).
# Keep in sync with prediction_engine empirical heads and governed audits.
EMPIRICAL_TRI_CLASS_HORIZONS: tuple[str, ...] = (
    "1c",
    "3c",
    "5c",
    "8c",
    "13c",
    "15c",
    "60c",
)
