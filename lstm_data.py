# lstm_data.py — LSTM Data Pipeline for Ed Console
# ==================================================
# Inference path: MVP columns for each bar are merged via `features.lstm_sequence_input`
# (canonical contract) before `encode_snapshot_5m` / `encode_snapshot_1m` — see that module.
#
# Extracts candle sequences from the snapshot database and builds
# training-ready arrays for the dual-stream LSTM.
#
# STANDALONE MODULE — does not modify any existing files.
# Read-only access to the database.
#
# Usage:
#   python lstm_data.py              ← runs self-test with diagnostics
#   from lstm_data import build_lstm_dataset  ← import for training
#
# Architecture (both streams use 1m snapshots from DB; naming is legacy):
#   Stream 1 (X_1m): last 20 snapshots — micro / entry-timing context
#   Stream 2 (X_5m): 60 snapshots — structure / longer lookback context
#   Target: default product ML horizon (outcome_{slug}) for last bar — see ml_horizon.outcome_column
#
# Snapshot timeframe = CANONICAL_TIMEFRAME (1m). No 5m candle aggregation.
# All features are normalized per-window to prevent lookahead bias.

import sqlite3
import numpy as np
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

log = logging.getLogger("lstm_data")


def _positive_float_or_none(value) -> Optional[float]:
    from numeric_contract import float_positive_or_none

    return float_positive_or_none(value)

# ── Database location (same resolver as db.DB_PATH / ED_CONSOLE_DB) ─────────
from db import DB_PATH

# ── Canonical timeframe ───────────────────────────────────────────────────────
from timeframe_config import CANONICAL_TIMEFRAME
from ml_horizon import (
    DEFAULT_ML_HORIZON_SLUG,
    DEFAULT_TRAINING_LABEL_COLUMN,
    normalize_ml_horizon_slug,
    outcome_column,
    target_definition as horizon_target_definition,
)

# ── Constants ─────────────────────────────────────────────────────────────────
STREAM_1M_LOOKBACK  = 20    # 1-min bars: ~20 min of micro context
STREAM_5M_LOOKBACK  = 60    # 5-min bars: ~5 hours (full RTH session)
TARGET_HORIZON      = DEFAULT_TRAINING_LABEL_COLUMN  # Default label column; callers pass outcome_column(slug) for non-default horizons.
TARGET_CLASSES      = {"up": 0, "down": 1, "flat": 2}
RTH_START_HOUR      = 9
RTH_START_MIN       = 30
RTH_END_HOUR        = 16
RTH_END_MIN         = 0

# ── Feature definitions ───────────────────────────────────────────────────────
# FEATURES_5M: full feature set for structure stream (60 snapshots, 1m each)
# FEATURES_1M: subset for micro stream (20 snapshots); both from same 1m snapshot DB

FEATURES_5M = [
    # Price dynamics (will be normalized as % of first bar's spot)
    "spot",
    "candle_body_pts",
    "candle_range_pts",
    "vwap_dist_pts",
    # Greek structure
    "dist_call_gamma_wall",
    "dist_put_gamma_wall",
    "dist_gamma_inflection",
    "dist_delta_inflection",
    "dist_call_oi_wall",
    "dist_put_oi_wall",
    "net_gamma",
    "net_delta",
    "charm_net",
    # Cross-instrument
    "spy_chg_pct",
    "qqq_chg_pct",
    "iwm_chg_pct",
    "spy_weighted_push",
    "qqq_weighted_push",
    "iwm_weighted_push",
    # Volatility
    "vix_level",
    "iv_level",
    # Zone encoding (will be one-hot later)
    "zone",
    # VWAP side (binary)
    "vwap_side",
]

# Extended features for next retrain (add to FEATURES_5M when retraining LSTM/Transformer):
# "atr", "iv_rank", "flow_imbalance", "smart_money_score", "breakout_score", "pin_score", "candle_volume"

# Subset for 1m stream (fields that change bar-to-bar)
# Most Greek/cross-instrument data doesn't change on 1m granularity
FEATURES_1M = [
    "spot",
    "candle_body_pts",
    "candle_range_pts",
    "vwap_dist_pts",
    "net_gamma",
    "net_delta",
    "spy_chg_pct",
    "qqq_chg_pct",
    "vix_level",
    "iv_level",
    "zone",
    "vwap_side",
]

# Categorical columns that need encoding
CATEGORICAL_COLS = {"zone", "vwap_side"}

# Zone encoding map
ZONE_MAP = {
    "pin_bull": 0, "pin_bear": 1, "pin_neutral": 2, "pin_chaos": 3,
    "breakout": 4, "breakdown": 5,
}
VWAP_SIDE_MAP = {"above": 1.0, "below": -1.0}
# Missing categorical sentinels (aligned with features/lstm_sequence_input.py).
ZONE_MISSING_ENCODED = -1.0
VWAP_SIDE_UNKNOWN_ENCODED = 2.0


def _encode_zone_feature(snap: dict) -> float:
    zr = snap.get("zone")
    if zr is None:
        return ZONE_MISSING_ENCODED
    return float(ZONE_MAP.get(str(zr).lower(), 2))


def _encode_vwap_side_feature(snap: dict) -> float:
    vs = snap.get("vwap_side")
    if vs is None:
        return VWAP_SIDE_UNKNOWN_ENCODED
    return float(VWAP_SIDE_MAP.get(str(vs).lower(), VWAP_SIDE_UNKNOWN_ENCODED))

# Columns that should be log-transformed (large magnitude, sign matters)
LOG_TRANSFORM_COLS = {"net_gamma", "net_delta", "charm_net"}

# Nullable numerics: NULL in DB must not be confused with 0.0 (especially centered
# cross-asset fields). Each emits value + ``__present`` mask (1=present, 0=missing).
NULLABLE_NUMERIC_COLS_5M = frozenset({
    "spy_chg_pct",
    "qqq_chg_pct",
    "iwm_chg_pct",
    "spy_weighted_push",
    "qqq_weighted_push",
    "iwm_weighted_push",
    "vix_level",
    "iv_level",
})
NULLABLE_NUMERIC_COLS_1M = frozenset({
    "spy_chg_pct",
    "qqq_chg_pct",
    "vix_level",
    "iv_level",
})

# Bump when encoder layout changes (requires full LSTM/Transformer retrain).
LSTM_ENCODER_SCHEMA_VERSION = 2


def _build_encoded_feature_names(base: list[str], nullable: frozenset[str]) -> list[str]:
    names: list[str] = []
    for col in base:
        names.append(col)
        if col in nullable:
            names.append(f"{col}__present")
    return names


ENCODED_FEATURES_5M = _build_encoded_feature_names(FEATURES_5M, NULLABLE_NUMERIC_COLS_5M)
ENCODED_FEATURES_1M = _build_encoded_feature_names(FEATURES_1M, NULLABLE_NUMERIC_COLS_1M)


def encoded_width_5m() -> int:
    return len(ENCODED_FEATURES_5M)


def encoded_width_1m() -> int:
    return len(ENCODED_FEATURES_1M)


def assert_lstm_encoder_checkpoint_compatible(checkpoint: Mapping[str, Any]) -> None:
    """Fail closed when checkpoint predates mask-channel encoder (requires retrain)."""
    enc_ver = int(checkpoint.get("encoder_schema_version", 1))
    if enc_ver < LSTM_ENCODER_SCHEMA_VERSION:
        raise ValueError(
            f"LSTM encoder schema v{enc_ver} < required v{LSTM_ENCODER_SCHEMA_VERSION}; retrain"
        )
    pre5 = checkpoint.get("encoder_width_5m_pre_mask")
    pre1 = checkpoint.get("encoder_width_1m_pre_mask")
    if pre5 is not None and int(pre5) != encoded_width_5m():
        raise ValueError(
            f"encoder_width_5m_pre_mask={pre5} != current {encoded_width_5m()}"
        )
    if pre1 is not None and int(pre1) != encoded_width_1m():
        raise ValueError(
            f"encoder_width_1m_pre_mask={pre1} != current {encoded_width_1m()}"
        )


# ════════════════════════════════════════════════════════════════════════════════
# CONFLUENCE FEATURES — computed per snapshot from raw data
# ════════════════════════════════════════════════════════════════════════════════

def compute_confluence_features(snapshots_5m: list[dict], current_idx: int) -> dict:
    """
    Compute multi-timeframe confluence features for a given snapshot.

    Uses the 5m snapshot history to derive higher-timeframe reads:
      - 1m/5m momentum:  from last 3 bars (candle direction)
      - 15m structure:   from last 3-6 groups of 3 bars (swing pattern)
      - 1h trend:        from last 12 bars (directional drift)
      - VWAP confluence:  distance + direction of distance
      - Greek support:    do Greeks confirm the direction?
      - Timeframe alignment score: -4 to +4

    Args:
        snapshots_5m: list of snapshot dicts ordered by ts_utc ascending
        current_idx:  index of the current (most recent) snapshot

    Returns:
        dict of confluence feature values
    """
    result = {
        "cf_momentum_5m": 0.0,       # -1 to +1: recent 5m direction
        "cf_structure_15m": 0.0,      # -1 to +1: 15m structural lean
        "cf_trend_1h": 0.0,           # -1 to +1: hourly trend
        "cf_vwap_distance_pct": 0.0,  # signed: + above, - below
        "cf_greek_support": 0.0,      # -1 to +1: Greeks confirm/resist
        "cf_alignment_score": 0.0,    # -4 to +4: all timeframes
    }

    if current_idx < 12:
        # Not enough history for meaningful confluence
        return result

    snaps = snapshots_5m[max(0, current_idx - 59):current_idx + 1]
    if len(snaps) < 12:
        return result

    current = snaps[-1]
    spot = _positive_float_or_none(current.get("spot"))
    if spot is None:
        return result

    # ── 5m momentum (last 3 bars: ~15 min) ────────────────────────────────
    recent_3 = snaps[-3:]
    spot_start = _positive_float_or_none(recent_3[0].get("spot"))
    if spot_start is None:
        spot_start = spot
    mom_5m = (spot - spot_start) / spot_start if spot_start > 0 else 0.0
    # Normalize to roughly -1 to +1 range (0.5% move = strong)
    result["cf_momentum_5m"] = max(-1.0, min(1.0, mom_5m / 0.005))

    # ── 15m structure (last 12 bars = 4 groups of 3 = four 15m periods) ───
    if len(snaps) >= 12:
        bars_12 = snaps[-12:]
        # Look at direction of each 3-bar group
        group_dirs = []
        for i in range(0, 12, 3):
            group = bars_12[i:i+3]
            if len(group) == 3:
                g_start = _positive_float_or_none(group[0].get("spot"))
                g_end = _positive_float_or_none(group[-1].get("spot"))
                if g_start is not None and g_end is not None:
                    group_dirs.append(1 if g_end > g_start else -1 if g_end < g_start else 0)

        if group_dirs:
            # Are groups making higher highs (bullish structure) or lower lows?
            result["cf_structure_15m"] = max(-1.0, min(1.0, sum(group_dirs) / len(group_dirs)))

    # ── 1h trend (last 12 bars = 60 min of 5m data) ──────────────────────
    if len(snaps) >= 12:
        trend_start = _positive_float_or_none(snaps[-12].get("spot"))
        if trend_start is None:
            trend_start = spot
        trend_pct = (spot - trend_start) / trend_start if trend_start > 0 else 0.0
        result["cf_trend_1h"] = max(-1.0, min(1.0, trend_pct / 0.01))

    # ── VWAP confluence ───────────────────────────────────────────────────
    vwap = current.get("vwap")
    if vwap and vwap > 0 and spot > 0:
        vwap_dist_pct = (spot - vwap) / spot
        result["cf_vwap_distance_pct"] = max(-0.02, min(0.02, vwap_dist_pct))

    # ── Greek support score ───────────────────────────────────────────────
    # Do the options Greeks confirm the price direction?
    greek_score = 0.0
    net_delta = current.get("net_delta")
    charm_dir = current.get("charm_direction") or ""
    pcr = current.get("put_call_oi_ratio")

    # Net delta: positive = bullish flow, negative = bearish
    if net_delta is not None:
        if net_delta > 0:
            greek_score += 0.33
        elif net_delta < 0:
            greek_score -= 0.33

    # Charm: buying = bullish drift, selling = bearish drift
    if charm_dir == "buying":
        greek_score += 0.33
    elif charm_dir == "selling":
        greek_score -= 0.33

    # PCR: > 1.2 = heavy put hedging (bearish), < 0.8 = call heavy (bullish)
    if pcr is not None:
        if pcr > 1.2:
            greek_score -= 0.34
        elif pcr < 0.8:
            greek_score += 0.34

    result["cf_greek_support"] = max(-1.0, min(1.0, greek_score))

    # ── Alignment score (sum of directional reads) ────────────────────────
    def _sign(v, threshold=0.1):
        if v > threshold: return 1
        if v < -threshold: return -1
        return 0

    alignment = (
        _sign(result["cf_momentum_5m"], 0.15) +
        _sign(result["cf_structure_15m"], 0.2) +
        _sign(result["cf_trend_1h"], 0.15) +
        _sign(result["cf_greek_support"], 0.2)
    )
    result["cf_alignment_score"] = float(alignment)

    return result


CONFLUENCE_FEATURES = [
    "cf_momentum_5m", "cf_structure_15m", "cf_trend_1h",
    "cf_vwap_distance_pct", "cf_greek_support", "cf_alignment_score",
]


# ════════════════════════════════════════════════════════════════════════════════
# DATA EXTRACTION — read sequences from the database
# ════════════════════════════════════════════════════════════════════════════════

def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Read-only connection to the snapshot database."""
    if not db_path.exists():
        raise FileNotFoundError("Database not found: " + str(db_path))
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _is_rth(et_hour: int, et_minute: int) -> bool:
    """True if the timestamp falls within RTH (9:30 AM - 4:00 PM ET)."""
    mins = et_hour * 60 + et_minute
    return (RTH_START_HOUR * 60 + RTH_START_MIN) <= mins < (RTH_END_HOUR * 60 + RTH_END_MIN)


def _snapshot_table_for_timeframe(timeframe: str) -> str:
    """
    Return table name for snapshot queries.
    Canonical 1m only: snapshots_1m_normalized (resampled from sub-minute snapshots).
    """
    from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M

    if timeframe != CANONICAL_TIMEFRAME:
        raise ValueError(
            f"_snapshot_table_for_timeframe: canonical 1m only; got timeframe={timeframe!r}"
        )
    return SNAPSHOT_TABLE_1M


def extract_rth_snapshots(
    ticker: str,
    timeframe: str = CANONICAL_TIMEFRAME,
    db_path: Path = DB_PATH,
    require_outcome: bool = True,
    allowed_et_dates: Optional[set] = None,
    target_column: str = TARGET_HORIZON,
) -> dict:
    """
    Extract RTH snapshots grouped by trading day.
    For 1m: reads from snapshots_1m_normalized (normalized from sub-minute snapshots).

    Returns:
        {
          "2026-03-04": [snap_dict, snap_dict, ...],   # ordered by ts_utc
          "2026-03-05": [snap_dict, snap_dict, ...],
          ...
        }

    Each snap_dict includes all columns from the snapshot table.
    Only includes rows where et_hour/et_minute fall within RTH.
    If require_outcome=True, only includes rows where target_column is not NULL
    (Issue 14: per-horizon SQL via training_label_where_clause — not outcome_filled).
    """
    if timeframe != CANONICAL_TIMEFRAME:
        raise ValueError(
            f"extract_rth_snapshots: canonical 1m only; got timeframe={timeframe!r}"
        )
    if timeframe == CANONICAL_TIMEFRAME:
        try:
            from normalized_training_sync import ensure_normalized_training_table

            _ns = ensure_normalized_training_table(str(db_path), force=False, logger=log)
            if not _ns.get("ok"):
                log.warning("extract_rth_snapshots: normalized sync failed: %s", _ns.get("errors"))
        except Exception as e:
            log.warning("extract_rth_snapshots: normalized sync error: %s", e)

    conn = _connect(db_path)
    table = _snapshot_table_for_timeframe(timeframe)

    from ml_data_common import training_label_where_clause

    outcome_filter = (
        " AND " + training_label_where_clause(target_column)
        if require_outcome else ""
    )
    from ml_data_common import weekday_where_clause
    weekday_sql = " AND (" + weekday_where_clause() + ")"

    rows = conn.execute(
        f"SELECT * FROM {table} "
        "WHERE ticker = ? AND timeframe = ?"
        + outcome_filter +
        weekday_sql +
        " ORDER BY ts_utc ASC",
        (ticker, timeframe)
    ).fetchall()
    conn.close()

    # Group by date, filter to RTH only
    days = {}
    total_rows = 0
    rth_rows = 0
    skipped_non_rth = 0

    for row in rows:
        total_rows += 1
        d = dict(row)
        ts_u = d.get("ts_utc")
        if ts_u is not None:
            try:
                from time_et import et_clock_from_ts_utc, et_date_str_from_ts_utc, is_rth_ts_utc

                if not is_rth_ts_utc(float(ts_u)):
                    skipped_non_rth += 1
                    continue
                h, m, _ = et_clock_from_ts_utc(float(ts_u))
                day_key = et_date_str_from_ts_utc(float(ts_u))
            except (TypeError, ValueError):
                skipped_non_rth += 1
                continue
        else:
            h = d.get("et_hour", 0)
            m = d.get("et_minute", 0)
            if not _is_rth(h, m):
                skipped_non_rth += 1
                continue
            ts_et = d.get("ts_et", "")
            day_key = ts_et[:10] if len(ts_et) >= 10 else "unknown"

        rth_rows += 1

        if day_key not in days:
            days[day_key] = []
        days[day_key].append(d)

    if allowed_et_dates is not None:
        days = {k: v for k, v in days.items() if k in allowed_et_dates}

    log.info(
        "extract_rth_snapshots: ticker=%s total=%d rth=%d skipped_non_rth=%d days=%d",
        ticker, total_rows, rth_rows, skipped_non_rth, len(days)
    )

    return days


# ════════════════════════════════════════════════════════════════════════════════
# FEATURE ENCODING — convert raw snapshot values to model-ready numbers
# ════════════════════════════════════════════════════════════════════════════════

def _safe_float(v) -> float:
    """Convert any value to float, returning 0.0 for None/invalid (non-nullable columns only)."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def _raw_finite_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return f


def _encode_nullable_chg_or_push(raw) -> tuple[float, float]:
    """Value channel + present mask for % / push fields."""
    f = _raw_finite_float(raw)
    if f is None:
        return 0.0, 0.0
    return max(-5.0, min(5.0, f)), 1.0


def _encode_nullable_level(raw) -> tuple[float, float]:
    """Value channel + present mask for level fields (vix, iv)."""
    f = _raw_finite_float(raw)
    if f is None:
        return 0.0, 0.0
    return f, 1.0


def _append_nullable_numeric(features: list, snap: dict, col: str) -> None:
    if col.endswith("_chg_pct") or col.endswith("_push"):
        val, mask = _encode_nullable_chg_or_push(snap.get(col))
    else:
        val, mask = _encode_nullable_level(snap.get(col))
    features.extend([val, mask])


def canonical_reference_spot_from_sequence_window_first_bar(window: list) -> float:
    """
    Explicit reference spot for sequence encoders: first bar's ``spot`` column only.

    Used for training windows (raw DB rows) and inference (merged MVP rows). No fallback to the
    last bar — that was legacy behavior and is not allowed on production-relevant paths.
    """
    if not window:
        raise ValueError("sequence window must be non-empty")
    r = _safe_float(window[0].get("spot"))
    if r <= 0:
        raise ValueError("sequence window first bar must have spot > 0")
    return float(r)


# Alias for inference code paths that pass a merged canonical window.
canonical_reference_spot_from_merged_window = canonical_reference_spot_from_sequence_window_first_bar


def _signed_log(v: float) -> float:
    """Signed log transform: preserves sign, compresses magnitude.
    log(1 + |x|) * sign(x). Maps large values like net_delta=-112500
    to manageable range while keeping directionality.
    """
    if v == 0.0:
        return 0.0
    return np.sign(v) * np.log1p(abs(v))


def encode_snapshot_5m(snap: dict, ref_spot: float) -> list:
    """
    Encode a snapshot (1m canonical) into structure-stream feature vector.

    Name is legacy; input is a 1m snapshot from DB. Uses FEATURES_5M (full set).
    Called for each bar in the 60-bar structure stream.

    Args:
        snap: snapshot dict from the database (timeframe=1m)
        ref_spot: reference spot price for normalization (first bar in window)

    Returns:
        list of float values, one per feature
    """
    features = []
    spot = _safe_float(snap.get("spot"))

    for col in FEATURES_5M:
        if col in CATEGORICAL_COLS:
            # Encode categoricals
            if col == "zone":
                features.append(_encode_zone_feature(snap))
            elif col == "vwap_side":
                features.append(_encode_vwap_side_feature(snap))
        elif col == "spot":
            # Normalize spot as % change from reference
            if ref_spot > 0:
                features.append((spot - ref_spot) / ref_spot)
            else:
                features.append(0.0)
        elif col in ("candle_body_pts", "candle_range_pts", "vwap_dist_pts"):
            # Normalize point values by spot
            val = _safe_float(snap.get(col))
            features.append(val / ref_spot if ref_spot > 0 else 0.0)
        elif col.startswith("dist_"):
            # Distance features: normalize by spot
            val = _safe_float(snap.get(col))
            features.append(val / ref_spot if ref_spot > 0 else 0.0)
        elif col in LOG_TRANSFORM_COLS:
            # Large magnitude + signed: use signed log
            val = _safe_float(snap.get(col))
            features.append(_signed_log(val))
        elif col in NULLABLE_NUMERIC_COLS_5M:
            _append_nullable_numeric(features, snap, col)
        else:
            # Everything else: safe float
            features.append(_safe_float(snap.get(col)))

    return features


def encode_snapshot_1m(snap: dict, ref_spot: float) -> list:
    """Encode a single snapshot using the 1m feature subset."""
    features = []
    spot = _safe_float(snap.get("spot"))

    for col in FEATURES_1M:
        if col in CATEGORICAL_COLS:
            if col == "zone":
                features.append(_encode_zone_feature(snap))
            elif col == "vwap_side":
                features.append(_encode_vwap_side_feature(snap))
        elif col == "spot":
            if ref_spot > 0:
                features.append((spot - ref_spot) / ref_spot)
            else:
                features.append(0.0)
        elif col in ("candle_body_pts", "candle_range_pts", "vwap_dist_pts"):
            val = _safe_float(snap.get(col))
            features.append(val / ref_spot if ref_spot > 0 else 0.0)
        elif col in LOG_TRANSFORM_COLS:
            val = _safe_float(snap.get(col))
            features.append(_signed_log(val))
        elif col in NULLABLE_NUMERIC_COLS_1M:
            _append_nullable_numeric(features, snap, col)
        else:
            features.append(_safe_float(snap.get(col)))

    return features


# ════════════════════════════════════════════════════════════════════════════════
# SEQUENCE BUILDER — slide windows across daily data
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class LSTMDataset:
    """Container for training-ready LSTM data with full diagnostics."""
    # Both streams use 1m snapshots. Naming (5m/1m) is legacy for structure vs micro.
    # Stream 2 (structure): 60 consecutive 1m snapshots, full features
    X_5m: np.ndarray            # shape: (N, STREAM_5M_LOOKBACK, n_features_5m)
    # Stream 1 (micro): last 20 of those snapshots, subset features
    X_1m: np.ndarray            # shape: (N, STREAM_1M_LOOKBACK, n_features_1m)
    # Confluence features for each sample
    X_conf: np.ndarray          # shape: (N, n_confluence_features)
    # Targets
    y: np.ndarray               # shape: (N,) — class indices 0=up, 1=down, 2=flat
    # Metadata for diagnostics
    tickers: list               # ticker for each sample
    timestamps: list            # ts_et for each sample
    days: list                  # trading day for each sample

    # Dataset metadata (for purity and model metadata)
    training_timeframe: str = ""   # e.g. "1m" — snapshot cadence
    target_column: str = ""        # e.g. outcome_5c
    ml_horizon_slug: str = ""      # e.g. "5c"
    target_definition: str = ""    # provenance string from ml_horizon.target_definition

    # Diagnostics
    n_features_5m: int = 0
    n_features_1m: int = 0
    n_confluence: int = 0
    n_samples: int = 0
    n_days: int = 0
    n_tickers: int = 0
    class_distribution: dict = field(default_factory=dict)
    nan_counts: dict = field(default_factory=dict)
    skipped_reasons: dict = field(default_factory=dict)

    def summary(self) -> str:
        """Human-readable summary of the dataset."""
        lines = [
            "=" * 60,
            "LSTM DATASET SUMMARY",
            "=" * 60,
            "Samples:        {:,}".format(self.n_samples),
            "Trading days:   {}".format(self.n_days),
            "Tickers:        {}".format(self.n_tickers),
            "",
            "Stream 5m:      {} x {} (lookback x features)".format(
                STREAM_5M_LOOKBACK, self.n_features_5m),
            "Stream 1m:      {} x {} (lookback x features)".format(
                STREAM_1M_LOOKBACK, self.n_features_1m),
            "Confluence:     {} features".format(self.n_confluence),
            "",
            "Class distribution:",
        ]
        total = sum(self.class_distribution.values())
        for cls, cnt in sorted(self.class_distribution.items()):
            pct = cnt / total * 100 if total > 0 else 0
            lines.append("  {}: {:,} ({:.1f}%)".format(cls, cnt, pct))

        if self.nan_counts:
            lines.append("")
            lines.append("NaN counts per feature (top 10):")
            sorted_nans = sorted(self.nan_counts.items(), key=lambda x: -x[1])
            for col, cnt in sorted_nans[:10]:
                if cnt > 0:
                    lines.append("  {}: {:,}".format(col, cnt))

        if self.skipped_reasons:
            lines.append("")
            lines.append("Skipped samples:")
            for reason, cnt in self.skipped_reasons.items():
                lines.append("  {}: {:,}".format(reason, cnt))

        lines.append("=" * 60)
        return "\n".join(lines)


def build_lstm_dataset(
    tickers: list = None,
    db_path: Path = DB_PATH,
    require_outcome: bool = True,
    timeframe: str = CANONICAL_TIMEFRAME,
    min_ts_utc: Optional[float] = None,
    allowed_et_dates: Optional[set] = None,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> LSTMDataset:
    """
    Build the complete LSTM training dataset from the snapshot database.

    Process:
      1. For each ticker, extract RTH snapshots grouped by day
      2. For each day, slide a 60-bar window across the snapshots
      3. For each window:
         a. Encode 5m features for all 60 bars → X_5m sample
         b. Encode 1m features for last 20 bars → X_1m sample
         c. Compute confluence features → X_conf sample
         d. Extract target (outcome_* of last bar for the chosen ML horizon)
      4. Stack all samples into numpy arrays

    Args:
        tickers: list of tickers to include (None = all available)
        db_path: path to the database file (str or Path)
        require_outcome: if True, only include samples with the horizon label present
        ml_horizon_slug: product horizon slug (1c, 5c, …) — selects outcome_* column

    Returns:
        LSTMDataset with all arrays and diagnostics
    """
    if timeframe != CANONICAL_TIMEFRAME:
        raise ValueError(
            f"build_lstm_dataset: canonical 1m only; got timeframe={timeframe!r}"
        )
    from features.training_canonical_input import training_snapshot_for_sequence_encode

    _db = Path(db_path) if db_path else DB_PATH
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    label_col = outcome_column(hz)
    tdef = horizon_target_definition(hz)
    if tickers is None:
        try:
            from scheduler_user_tickers import load_user_scheduler_tickers_or_empty

            tickers = load_user_scheduler_tickers_or_empty()
        except Exception:
            tickers = []
        tickers = [t for t in (tickers or []) if t and not str(t).startswith("$")]
        if not tickers:
            log.warning(
                "build_lstm_dataset: logging_universe empty — no tickers "
                "(Issue 22: DISTINCT snapshot discovery disabled for enrollment authority)"
            )
        else:
            log.info(
                "build_lstm_dataset: authoritative enrolled tickers (%d): %s",
                len(tickers),
                tickers,
            )

    log.info("build_lstm_dataset: tickers=%s", tickers)

    all_X_5m = []
    all_X_1m = []
    all_X_conf = []
    all_y = []
    all_tickers = []
    all_timestamps = []
    all_days = []
    skipped = {"no_outcome": 0, "insufficient_bars": 0, "nan_target": 0}
    nan_counts = {}
    unique_days = set()

    for ticker in tickers:
        days_data = extract_rth_snapshots(
            ticker,
            timeframe=timeframe,
            db_path=_db,
            require_outcome=require_outcome,
            allowed_et_dates=allowed_et_dates,
            target_column=label_col,
        )

        for day_key, snapshots in sorted(days_data.items()):
            n_snaps = len(snapshots)
            if n_snaps < STREAM_5M_LOOKBACK:
                skipped["insufficient_bars"] += n_snaps
                continue

            unique_days.add(day_key)

            # Slide the window
            for end_idx in range(STREAM_5M_LOOKBACK, n_snaps):
                start_idx = end_idx - STREAM_5M_LOOKBACK
                window = snapshots[start_idx:end_idx]
                current = window[-1]

                if min_ts_utc is not None:
                    cts = current.get("ts_utc")
                    if cts is None or float(cts) < float(min_ts_utc):
                        continue

                # ── Target ────────────────────────────────────────────────
                target_str = current.get(label_col)
                if target_str is None or target_str not in TARGET_CLASSES:
                    skipped["no_outcome"] += 1
                    continue

                target = TARGET_CLASSES[target_str]

                # ── Reference spot (first bar in window for normalization) — no last-bar fallback
                try:
                    ref_spot = canonical_reference_spot_from_sequence_window_first_bar(window)
                except ValueError:
                    skipped["nan_target"] += 1
                    continue

                # ── 5m stream: all 60 bars ────────────────────────────────
                seq_5m = []
                for snap in window:
                    merged = training_snapshot_for_sequence_encode(snap)
                    features = encode_snapshot_5m(merged, ref_spot)
                    seq_5m.append(features)

                # ── 1m stream: last 20 bars (micro context) ──────────────
                micro_window = window[-STREAM_1M_LOOKBACK:]
                micro_ref = _safe_float(micro_window[0].get("spot"))
                if micro_ref <= 0:
                    micro_ref = ref_spot

                seq_1m = []
                for snap in micro_window:
                    merged = training_snapshot_for_sequence_encode(snap)
                    features = encode_snapshot_1m(merged, micro_ref)
                    seq_1m.append(features)

                # ── Confluence features ───────────────────────────────────
                # Compute from the full day's snapshot list for proper lookback
                day_idx = snapshots.index(current) if current in snapshots else end_idx
                conf = compute_confluence_features(snapshots, day_idx)
                conf_vec = [conf[k] for k in CONFLUENCE_FEATURES]

                # ── Track NaN counts for diagnostics (vectorized) ─────────
                arr_5m = np.array(seq_5m)  # shape: (lookback, n_features)
                for i, col in enumerate(ENCODED_FEATURES_5M):
                    if col not in nan_counts:
                        nan_counts[col] = 0
                    nan_counts[col] += int(np.isnan(arr_5m[:, i]).sum())

                # ── Append to arrays ──────────────────────────────────────
                all_X_5m.append(seq_5m)
                all_X_1m.append(seq_1m)
                all_X_conf.append(conf_vec)
                all_y.append(target)
                all_tickers.append(ticker)
                all_timestamps.append(current.get("ts_et", ""))
                all_days.append(day_key)

    # ── Convert to numpy arrays ───────────────────────────────────────────────
    if len(all_X_5m) == 0:
        log.warning("build_lstm_dataset: NO SAMPLES produced!")
        empty = np.array([])
        return LSTMDataset(
            X_5m=empty, X_1m=empty, X_conf=empty, y=empty,
            tickers=[], timestamps=[], days=[],
            target_column=label_col,
            ml_horizon_slug=hz,
            target_definition=tdef,
            skipped_reasons=skipped,
        )

    X_5m = np.array(all_X_5m, dtype=np.float32)
    X_1m = np.array(all_X_1m, dtype=np.float32)
    X_conf = np.array(all_X_conf, dtype=np.float32)
    y = np.array(all_y, dtype=np.int64)

    # Replace any NaN with 0.0 (defensive — should be rare after _safe_float)
    nan_before = int(np.isnan(X_5m).sum() + np.isnan(X_1m).sum() + np.isnan(X_conf).sum())
    X_5m = np.nan_to_num(X_5m, nan=0.0)
    X_1m = np.nan_to_num(X_1m, nan=0.0)
    X_conf = np.nan_to_num(X_conf, nan=0.0)

    if nan_before > 0:
        log.warning("build_lstm_dataset: replaced %d NaN values with 0.0", nan_before)

    # ── Class distribution ────────────────────────────────────────────────────
    class_dist = {}
    for cls_name, cls_idx in TARGET_CLASSES.items():
        class_dist[cls_name] = int((y == cls_idx).sum())

    # ── Build result ──────────────────────────────────────────────────────────
    ds = LSTMDataset(
        X_5m=X_5m,
        X_1m=X_1m,
        X_conf=X_conf,
        y=y,
        tickers=all_tickers,
        timestamps=all_timestamps,
        days=all_days,
        training_timeframe=timeframe,
        target_column=label_col,
        ml_horizon_slug=hz,
        target_definition=tdef,
        n_features_5m=X_5m.shape[2] if X_5m.ndim == 3 else 0,
        n_features_1m=X_1m.shape[2] if X_1m.ndim == 3 else 0,
        n_confluence=X_conf.shape[1] if X_conf.ndim == 2 else 0,
        n_samples=len(y),
        n_days=len(unique_days),
        n_tickers=len(set(all_tickers)),
        class_distribution=class_dist,
        nan_counts=nan_counts,
        skipped_reasons=skipped,
    )

    log.info("build_lstm_dataset: %d samples built", ds.n_samples)
    return ds


# ════════════════════════════════════════════════════════════════════════════════
# SELF-TEST — run this file directly to verify the data pipeline
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s: %(message)s",
    )

    print("=" * 70)
    print("  LSTM DATA PIPELINE — SELF-TEST")
    print("=" * 70)
    print()

    # Check DB exists
    if not DB_PATH.exists():
        print("ERROR: Database not found at " + str(DB_PATH))
        print("Make sure you are running from your EdWebConsole directory.")
        sys.exit(1)

    print("Database: " + str(DB_PATH))
    size_mb = DB_PATH.stat().st_size / 1e6
    print("Size: {:.2f} MB".format(size_mb))
    print()

    conn = _connect()
    table = _snapshot_table_for_timeframe(CANONICAL_TIMEFRAME)
    total = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE timeframe=?",
        (CANONICAL_TIMEFRAME,)
    ).fetchone()[0]
    conn.close()

    try:
        from scheduler_user_tickers import load_user_scheduler_tickers_or_empty

        tickers = [t for t in load_user_scheduler_tickers_or_empty() if t and not t.startswith("$")]
    except Exception:
        tickers = []
    if not tickers:
        print("ERROR: logging_universe has no enrolled tickers (Issue 22 — use UI/API or server sync).")
        sys.exit(1)

    print("Authoritative enrolled tickers (logging_universe): " + str(tickers))
    print("Total 1m snapshots (normalized): {:,}".format(total))
    print()

    # Build dataset
    print("Building LSTM dataset...")
    print("  5m lookback: {} bars".format(STREAM_5M_LOOKBACK))
    print("  1m lookback: {} bars".format(STREAM_1M_LOOKBACK))
    print("  Target: " + TARGET_HORIZON)
    print()

    ds = build_lstm_dataset(tickers=tickers)

    # Print summary
    print(ds.summary())
    print()

    # Detailed shape check
    print("ARRAY SHAPES:")
    print("  X_5m:   " + str(ds.X_5m.shape))
    print("  X_1m:   " + str(ds.X_1m.shape))
    print("  X_conf: " + str(ds.X_conf.shape))
    print("  y:      " + str(ds.y.shape))
    print()

    # Check for data quality issues
    print("DATA QUALITY CHECKS:")
    issues = 0

    # Check for constant features (no variance)
    if ds.n_samples > 0:
        for i, col in enumerate(FEATURES_5M):
            col_data = ds.X_5m[:, :, i].flatten()
            std = np.std(col_data)
            if std < 1e-10:
                print("  WARNING: {} has zero variance (constant)".format(col))
                issues += 1

        # Check confluence features
        for i, col in enumerate(CONFLUENCE_FEATURES):
            col_data = ds.X_conf[:, i]
            std = np.std(col_data)
            if std < 1e-10:
                print("  WARNING: {} has zero variance (constant)".format(col))
                issues += 1

        # Check for extreme values
        for i, col in enumerate(FEATURES_5M):
            col_data = ds.X_5m[:, :, i].flatten()
            max_abs = np.max(np.abs(col_data))
            if max_abs > 100:
                print("  WARNING: {} has extreme values (max |v| = {:.1f})".format(col, max_abs))
                issues += 1

    if issues == 0:
        print("  All checks passed!")
    else:
        print("  {} issues found — review above".format(issues))

    print()

    # Sample a few data points for visual inspection
    if ds.n_samples > 0:
        print("SAMPLE DATA (first 3 samples, last bar of each):")
        for i in range(min(3, ds.n_samples)):
            print("  Sample {}: ticker={} day={} ts={}".format(
                i, ds.tickers[i], ds.days[i], ds.timestamps[i]))
            print("    Target: {} ({})".format(
                ds.y[i], {v: k for k, v in TARGET_CLASSES.items()}.get(ds.y[i], "?")))
            print("    5m last bar features (first 5): {}".format(
                [round(v, 4) for v in ds.X_5m[i, -1, :5]]))
            print("    Confluence: {}".format(
                {k: round(v, 3) for k, v in zip(CONFLUENCE_FEATURES, ds.X_conf[i])}))
            print()

    print("NEXT STEP: If all checks pass, proceed to lstm_model.py")
    print("           Run: python lstm_data.py  (this script)")
    print("           Then share the output with Claude")
