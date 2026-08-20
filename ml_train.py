"""
Ed Console - ML Training Pipeline (Phase 4)
============================================
Per-ticker XGBoost training with normalized features.

All dollar-denominated features are converted to % of spot before training.
Each ticker gets its own model file - adding a ticker never affects other models.

RULE 1: RTH data only (09:30-16:00 ET weekdays), TARGET label IS NOT NULL (per-horizon; not outcome_filled).
        Exponential decay weighting — most recent rows get highest weight.
RULE 2: No gates — train if data exists, save always.
"""

import sys, json, time, sqlite3, pickle, warnings, argparse, logging
from pathlib import Path
from typing import Any, Optional, Set
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

# -- Config ----------------------------------------------------------------------
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import DB_PATH as _DB_PATH_OBJ

DB_PATH = str(_DB_PATH_OBJ)  # same file as EdDB; honors ED_CONSOLE_DB via db.py
MODEL_DIR = Path("models")
from canonical_distances import canonicalize_distance_read
from ml_horizon import (
    DEFAULT_ML_HORIZON_SLUG,
    DEFAULT_TRAINING_LABEL_COLUMN,
    directional_label_column,
    move_label_column,
    normalize_ml_horizon_slug,
    outcome_column,
)
from time_et import RTH_OPEN_MINS, RTH_SESSION_MINUTES
# RC-345/F25 (train-write faucet): the model/meta WRITERS must emit the identical artifact
# identity the readers/verifier/predictor expect — one canonical authority, no local .upper().
from instrument_identity import ticker_storage_key

TARGET_COL = DEFAULT_TRAINING_LABEL_COLUMN  # Default tabular label; training uses outcome_column(ml_horizon_slug).

# movement-target v1 binary heads (parallel to legacy triclass)
TARGET_MODE_TRICLASS = "triclass"
TARGET_MODE_DIR = "dir"
TARGET_MODE_MOVE = "move"
# Empirical pred_{hz}_* may exist on DB training rows (fusion / histogram outputs). They must not be
# copied into engineered XGB columns — that created same-tick circular dependence (stack → overlay → XGB).
N_SPLITS    = 5
CLASS_MAP   = {"up": 0, "down": 1, "flat": 2}
CLASS_NAMES = ["up", "down", "flat"]
DIR_CLASS_MAP = {"up": 0, "down": 1}
DIR_CLASS_NAMES = ["up", "down"]
MOVE_CLASS_MAP = {"move": 0, "no_move": 1}
MOVE_CLASS_NAMES = ["move", "no_move"]

def xgb_meta_contract_ok(meta: dict) -> bool:
    """True if XGB meta satisfies system contract + tabular impute_medians."""
    from model_contract import validate_artifact_contract

    ok, _ = validate_artifact_contract(meta, "xgb")
    return ok


def apply_xgb_imputation_matrix(
    x_mat: np.ndarray,
    feature_names: list,
    impute_medians: dict,
) -> np.ndarray:
    """Match train_ticker: per-column training median fill, then nan_to_num(nan=0).

    Training may impute historical MAR gaps. Live serve must call
    ``engineered_features_missing_withheld_wall_distances`` (RC-435) *before*
    this helper so structurally withheld OI/vanna distances are not fabricated.
    """
    out = np.asarray(x_mat, dtype=np.float64, order="C")
    out = out.copy()
    if impute_medians and feature_names:
        for j, name in enumerate(feature_names):
            med = impute_medians.get(name)
            if med is None:
                continue
            col = out[..., j]
            out[..., j] = np.where(np.isnan(col), float(med), col)
    return np.nan_to_num(out, nan=0.0)


# RC-422 withheld CONSENSUS OI/vanna walls live; RC-435: serve must abstain when these
# distances (base or *_pct) are in the model vector and non-finite — not median/zero-fill.
STRUCTURALLY_WITHHELD_WALL_DISTANCE_COLS: tuple[str, ...] = (
    "dist_call_oi_wall",
    "dist_put_oi_wall",
    "dist_call_vanna_wall",
    "dist_put_vanna_wall",
)


def structurally_withheld_wall_distance_feature_names() -> frozenset[str]:
    names: set[str] = set()
    for col in STRUCTURALLY_WITHHELD_WALL_DISTANCE_COLS:
        names.add(col)
        names.add(f"{col}_pct")
    return frozenset(names)


def _finite_number(v) -> bool:
    if v is None:
        return False
    try:
        return bool(np.isfinite(float(v)))
    except (TypeError, ValueError):
        return False


def snapshot_missing_structurally_withheld_wall_distances(
    snap: dict,
    feature_names: list | None = None,
) -> bool:
    """True when a model-required withheld wall-distance feature is absent on ``snap``.

    For ``*_pct`` features, a finite base ``dist_*`` also counts as present (pct is
    derived). Feature lists that omit every withheld name never trip this gate.
    """
    withheld = structurally_withheld_wall_distance_feature_names()
    names = list(feature_names) if feature_names is not None else list(withheld)
    for name in names:
        if name not in withheld:
            continue
        if name.endswith("_pct"):
            base = name[: -len("_pct")]
            if _finite_number(snap.get(name)) or _finite_number(snap.get(base)):
                continue
            return True
        if not _finite_number(snap.get(name)):
            return True
    return False


def engineered_features_missing_withheld_wall_distances(
    x_row: np.ndarray,
    feature_names: list,
) -> bool:
    """True when any withheld wall-distance column in ``feature_names`` is non-finite."""
    withheld = structurally_withheld_wall_distance_feature_names()
    arr = np.asarray(x_row, dtype=np.float64).reshape(-1)
    for j, name in enumerate(feature_names):
        if name not in withheld:
            continue
        if j >= arr.size or not np.isfinite(arr[j]):
            return True
    return False

# -- Model path helpers ----------------------------------------------------------
def model_path(
    ticker: str,
    model_dir: Path = None,
    *,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
    target_mode: str = TARGET_MODE_TRICLASS,
) -> Path:
    base = model_dir or MODEL_DIR
    base.mkdir(parents=True, exist_ok=True)
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    t = ticker_storage_key(ticker)
    if target_mode == TARGET_MODE_TRICLASS:
        return base / f"xgb_{t}_{hz}.pkl"
    if target_mode == TARGET_MODE_DIR:
        return base / f"xgb_{t}_{hz}_dir.pkl"
    if target_mode == TARGET_MODE_MOVE:
        return base / f"xgb_{t}_{hz}_move.pkl"
    raise ValueError(f"model_path: unknown target_mode {target_mode!r}")

def meta_path(
    ticker: str,
    model_dir: Path = None,
    *,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
    target_mode: str = TARGET_MODE_TRICLASS,
) -> Path:
    base = model_dir or MODEL_DIR
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    t = ticker_storage_key(ticker)
    if target_mode == TARGET_MODE_TRICLASS:
        return base / f"xgb_{t}_{hz}_meta.json"
    if target_mode == TARGET_MODE_DIR:
        return base / f"xgb_{t}_{hz}_dir_meta.json"
    if target_mode == TARGET_MODE_MOVE:
        return base / f"xgb_{t}_{hz}_move_meta.json"
    raise ValueError(f"meta_path: unknown target_mode {target_mode!r}")


# =============================================================================
# FEATURE COLUMN DEFINITIONS
# =============================================================================

DOLLAR_COLS = [
    "candle_body_pts",     "candle_range_pts",
    "nearest_above_dist",   "nearest_below_dist",
]

WALL_DISTANCE_COLS = [
    "dist_call_gamma_wall", "dist_put_gamma_wall",
    "dist_call_delta_wall", "dist_put_delta_wall",
    # RC-422/F4: CONSENSUS OI/vanna walls are withheld live. These four columns stay
    # in the train/serve vector so FEATURE_SCHEMA_VERSION / artifact widths do not
    # break. Live persist writes NULL. RC-435: serve abstains before median/zero fill
    # (STRUCTURALLY_WITHHELD_WALL_DISTANCE_COLS) — do not fabricate proximity.
    "dist_call_oi_wall",    "dist_put_oi_wall",
    "dist_call_vanna_wall", "dist_put_vanna_wall",
    "dist_gamma_inflection","dist_delta_inflection",
    "pin_width_pts",
]

SCALE_INVARIANT_COLS = [
    "net_gamma", "net_delta", "charm_net", "put_call_oi_ratio",
    "spy_chg_pct", "qqq_chg_pct", "iwm_chg_pct",
    "vix_level", "vix_vs_prev", "vwap_dist_pts", "iv_level",
    "spy_weighted_push", "qqq_weighted_push", "iwm_weighted_push",
    "nvda_chg_pct", "aapl_chg_pct", "msft_chg_pct", "amzn_chg_pct",
    "googl_chg_pct", "avgo_chg_pct", "meta_chg_pct", "tsla_chg_pct",
    "kre_chg_pct", "xbi_chg_pct", "psci_chg_pct", "xrt_chg_pct",
    # Feature epic Slice A (2026-06-01): persisted on snapshot ~100%, previously unregistered.
    "tnx_yield", "tnx_chg", "qqq_vs_spy", "spy_iwm_divergence",
    "zone_since_bars",  # DB column: 1m execution-layer (alias for zone_since_bars_1m)
    "candle_volume", "bid_ask_imbalance",
    "spread", "atr", "iv_rank", "smart_money_score",
    "breakout_score", "pin_score",
    # Context layer (snapshots after rollout — NaN for legacy rows until backfilled).
    # SENTIMENT/NEWS FEATURE RETIRE (2026-05-31, Schwab-first): 6 non-Schwab news/sentiment
    # features de-registered — sentiment_composite/_buzz/_finnhub/_av, breaking_news_flag,
    # pre_market_sentiment — all Finnhub/AlphaVantage-sourced (NO_SCHWAB_EQUIVALENT), XGB-only
    # (absent from CATEGORICALS + LSTM FEATURES_5M/1M). The news_sentiment producer and the
    # /api/state news headline display stay as display-only (not model features); the DB column
    # DROP is post-retrain hygiene. FEATURE_SCHEMA_VERSION bumped so this fail-closes serving.
    "absorption_score", "continuation_score",
]

# Price-action cone (operator 2026-06-11): the 27 pa_* columns persisted by
# features/signal_layer_v1.compute_price_action_snapshot_columns are DELIBERATELY
# NOT registered here yet. Registering them widens the tabular/sequence encodes
# (94→121 / 88→115) and bumps FEATURE_SCHEMA_VERSION, which fail-closes every
# v7-trained bundle — the 2026-06-11 live-stack outage. The serving-cone flip
# (registration + v8 version bump + width-lock test updates) lands in the SAME
# commit as the retrained artifacts. [REAL-GATE: training-skew] — OPEN_ITEMS
# row PA-CONE-V8-RETRAIN. Until then pa_* are ablation/discovery candidates only.

TIME_COLS   = ["et_hour", "et_minute"]
ALL_DB_COLS = TIME_COLS + DOLLAR_COLS + WALL_DISTANCE_COLS + SCALE_INVARIANT_COLS

CATEGORICALS = [
    "zone", "prev_zone", "vwap_side", "candle_direction",
    "session_bucket", "vix_bucket",
    "charm_direction", "charm_magnitude", "iv_direction",
    "combined_signal", "combined_conviction",
    "pressure_label", "pressure_trend",
    "liquidity_behavior_label",
]

NUMERIC_FEATURES     = ALL_DB_COLS
CATEGORICAL_FEATURES = CATEGORICALS


# =============================================================================
# DATA LOADING — RTH 09:30-16:00 ET, TARGET_COL IS NOT NULL (Issue 14: no outcome_filled coupling)
# =============================================================================

def load_data(
    db_path: str = DB_PATH,
    ticker: str = None,
    model_dir: Path = None,
    timeframe: str = None,
    min_ts_utc: Optional[float] = None,
    allowed_et_dates: Optional[Set[str]] = None,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
    label_column: Optional[str] = None,
) -> pd.DataFrame:
    """
    Load 1m RTH training data from snapshots_1m_normalized.
    Uses normalized 1m sampled rows (resampled from sub-minute snapshots).
    Attaches net_gamma_prev for ΔGEX train/serve parity (no m5_* lag block — feature epic DROP).
    min_ts_utc: if set, only rows with ts_utc >= this value (rolling RTH session window).
    allowed_et_dates: if set, only rows whose ts_et date (YYYY-MM-DD) is in this set.
    """
    # RC-345/F25: the DB-facing function itself consumes the canonical storage identity —
    # SPX and $SPX bind the same stored key ("$SPX"). Do NOT push this up to callers only.
    ticker = ticker_storage_key(ticker) if ticker else ticker
    from ml_data_common import (
        filter_df_to_rth_ts_utc,
        stamp_et_clock_columns,
        training_label_where_clause,
        weekday_where_clause,
    )
    from timeframe_config import CANONICAL_TIMEFRAME
    _tf = timeframe or CANONICAL_TIMEFRAME
    assert _tf == CANONICAL_TIMEFRAME, f"Training requires canonical timeframe {CANONICAL_TIMEFRAME}, got {_tf}"
    label_col = (
        str(label_column).strip()
        if label_column is not None
        else outcome_column(normalize_ml_horizon_slug(ml_horizon_slug))
    )
    _hz_norm = normalize_ml_horizon_slug(ml_horizon_slug)
    try:
        from normalized_training_sync import (
            ensure_normalized_training_table,
            inline_normsync_enabled,
        )

        if inline_normsync_enabled():
            _ns = ensure_normalized_training_table(
                db_path, force=False, logger=logging.getLogger("ml_train.normsync")
            )
            if not _ns.get("ok"):
                logging.getLogger("ml_train.normsync").warning(
                    "normalized_training_sync failed: %s", _ns.get("errors")
                )
    except Exception as _e:
        logging.getLogger("ml_train.normsync").warning("normalized_training_sync: %s", _e)

    conn = sqlite3.connect(db_path)
    _extra_dir = ""
    if label_col == directional_label_column(_hz_norm):
        _extra_dir = f" AND CAST(valid_dir_{_hz_norm} AS INTEGER) = 1"
    where = (
        f"timeframe = ? AND {training_label_where_clause(label_col)}{_extra_dir} "
        f"AND ({weekday_where_clause()})"
    )
    params: list = [_tf]
    if ticker:
        where += " AND ticker = ?"
        params.append(ticker)
    if min_ts_utc is not None:
        where += " AND ts_utc >= ?"
        params.append(float(min_ts_utc))
    if allowed_et_dates:
        ds = sorted(allowed_et_dates)
        ph = ",".join(["?"] * len(ds))
        where += f" AND substr(ts_et, 1, 10) IN ({ph})"
        params.extend(ds)
    df = pd.read_sql_query(
        f"SELECT * FROM snapshots_1m_normalized WHERE {where} ORDER BY ts_utc ASC",
        conn,
        params=params,
    )
    conn.close()
    if len(df) == 0:
        print("  Loaded 0 RTH rows (run: python snapshot_normalizer.py to materialize)")
        return df
    df = filter_df_to_rth_ts_utc(df)
    df = stamp_et_clock_columns(df)
    if len(df) == 0:
        print("  Loaded 0 RTH rows after ts_utc-derived RTH filter")
        return df
    from ml_data_common import attach_net_gamma_prev_column

    df = attach_net_gamma_prev_column(df, db_path)  # RC-342: raw-prior authority, DB-scoped
    print(f"  Loaded {len(df):,} RTH rows  "
          f"[{df['ts_et'].iloc[0]} -> {df['ts_et'].iloc[-1]}]")
    if not ticker:
        print(f"  Tickers: {df['ticker'].nunique()} "
              f"({', '.join(df['ticker'].unique()[:8])}...)")
    print(f"  Zones:    {dict(df['zone'].value_counts())}")
    if label_col in df.columns:
        print(f"  Outcomes ({label_col}): {dict(df[label_col].value_counts())}")
    from arch_competition.stack_bundle_eval_v1 import (
        ablated_drop_group_ids_for_model_horizon,
        ablation_survivors_training_enabled,
        apply_ablation_survivor_nulls_to_dataframe_for_model,
    )

    if ablation_survivors_training_enabled():
        # O-56: XGB trains on ITS OWN survivor set for THIS horizon (the ablated data). Fail LOUD if
        # the matrix can't be applied — never silently train full-feature on an ablated retrain
        # (AGENTS §Ablation contract: full-feature is not a valid retrain target).
        drop_groups = ablated_drop_group_ids_for_model_horizon("xgb", _hz_norm)
        df = apply_ablation_survivor_nulls_to_dataframe_for_model(
            df, model_family="xgb", horizon_slug=_hz_norm
        )
        print(
            f"  Ablation survivor mask (xgb/{_hz_norm}) ON — dropped {len(drop_groups)} feature groups "
            f"({', '.join(drop_groups[:4])}{'…' if len(drop_groups) > 4 else ''})"
        )
    return df


# =============================================================================
# FEATURE ENGINEERING
# =============================================================================

def probe_training_feature_row() -> dict[str, Any]:
    """Minimal single-row probe for tabular feature-name enumeration (XGB + sequence parity)."""
    row: dict[str, Any] = {
        "ticker": "SPY",
        "ts_utc": 1.0,
        "spot": 100.0,
        "outcome_1c": "up",
        "et_hour": 10,
        "et_minute": 0,
        "candle_body_pts": 0.5,
        "candle_range_pts": 1.0,
        "nearest_above_dist": 1.0,
        "nearest_below_dist": 1.0,
        "net_gamma": 1.0,
        "zone": "pin_neutral",
        "vwap_side": "above",
        "flow_imbalance": 0.5,
    }
    for c in list(WALL_DISTANCE_COLS) + list(SCALE_INVARIANT_COLS):
        row.setdefault(c, 1.0)
    for c in CATEGORICALS:
        row.setdefault(c, "neutral")
    return row


_TABULAR_TRAINING_FEATURE_NAMES: list[str] | None = None


def refresh_tabular_training_feature_names_cache() -> list[str]:
    """Bust cached tabular column order (after engineer_features layout change)."""
    global _TABULAR_TRAINING_FEATURE_NAMES
    _TABULAR_TRAINING_FEATURE_NAMES = None
    return tabular_training_feature_names()


def tabular_training_feature_names() -> list[str]:
    """Stable XGB ``engineer_features`` column order (cached). Sequence encoders + ablation cone."""
    global _TABULAR_TRAINING_FEATURE_NAMES
    if _TABULAR_TRAINING_FEATURE_NAMES is None:
        df = pd.DataFrame(
            [
                probe_training_feature_row(),
                {**probe_training_feature_row(), "ts_utc": 2.0, "net_gamma": 2.0},
            ]
        )
        _, names, _, _ = engineer_features(df)
        _TABULAR_TRAINING_FEATURE_NAMES = list(names)
    return list(_TABULAR_TRAINING_FEATURE_NAMES)


def encode_tabular_feature_vector(
    snapshot: dict,
    feature_names: list[str] | None = None,
    *,
    category_maps: dict | None = None,
    vol_medians: dict | None = None,
    ticker: str | None = None,
) -> list[float]:
    """One snapshot → XGB-tabular vector (LSTM/Transformer structure + micro streams, Stage 2)."""
    import math

    names = feature_names or tabular_training_feature_names()
    row_df = engineer_single_snapshot(
        snapshot,
        category_maps or {},
        names,
        vol_medians or {},
        ticker=ticker or snapshot.get("ticker"),
    )
    if row_df is None:
        return [0.0] * len(names)
    out: list[float] = []
    for fn in names:
        v = row_df[fn].iloc[0]
        try:
            fv = float(v)
        except (TypeError, ValueError):
            out.append(0.0)
            continue
        out.append(0.0 if (not math.isfinite(fv)) else fv)
    return out


def _mutable_float_ndarray(values) -> np.ndarray:
    """Return a writable float ndarray (pandas/NumPy map outputs may be read-only)."""
    out = np.asarray(values, dtype=float)
    return out.copy() if not out.flags.writeable else out


# ═══════════════════════════════════════════════════════════════════════════════════════
# RC-339 — ONE COMPUTATION AUTHORITY PER SHARED TRAIN/SERVE FEATURE SEMANTIC
# ═══════════════════════════════════════════════════════════════════════════════════════
# Until 2026-08-10, `engineer_features` (batch/train) and `engineer_single_snapshot`
# (scalar/serve) each carried a full private encoding of the same feature formulas — the
# pct-of-spot conversion, session-time trig, body/range ratio, ΔGEX, NaN-preserving sign
# flags, cross-market products and stats, volume log/ratio, imbalance pressure thresholds
# and categorical coding. RC-335 proved the cost: three of those twin encodings had
# silently diverged (8 of 94 features) and only executing both sides exposed it. Parity
# tests catch divergence AFTER it ships; this removes the second author. Each kernel below
# is dtype-polymorphic — numpy broadcasting lets ONE body serve the vectorised training
# frame and the scalar serve row — so the two builders own SHAPE ONLY: column extraction,
# index alignment, fit mechanics and row packaging. Fitted semantics (the volume-median
# FIT, the category-map FIT) remain train-only concepts; only their APPLICATION is shared.
import warnings

IMBALANCE_BUY_PRESSURE_MIN: float = 0.65
IMBALANCE_SELL_PRESSURE_MAX: float = 0.35
VOLUME_RATIO_CAP: float = 10.0


def fk_pct_of_spot(points, spot):
    """Points expressed as percent of spot — THE pct formula for every *_pct feature."""
    return np.asarray(points, dtype=float) / spot * 100.0


def fk_body_range_ratio(body_pct, range_pct):
    """|body| / range; a non-positive range is not a range — absent, never a sign flip."""
    rng = np.asarray(range_pct, dtype=float)
    rng = np.where(rng > 0, rng, np.nan)
    return np.abs(np.asarray(body_pct, dtype=float)) / rng


def fk_session_time_features(minutes_of_day):
    """(time_sin, time_cos, time_progress, minutes_since_open) from ET minutes-of-day.

    NaN in -> NaN out for all four: no canonical clock means no session position.
    """
    mod = np.asarray(minutes_of_day, dtype=float)
    prog = np.clip((mod - RTH_OPEN_MINS) / float(RTH_SESSION_MINUTES), 0, 1)
    mins_open = np.clip(mod - RTH_OPEN_MINS, 0, float(RTH_SESSION_MINUTES))
    return np.sin(2 * np.pi * prog), np.cos(2 * np.pi * prog), prog, mins_open


def fk_dgex(net_gamma, net_gamma_prev):
    """ΔGEX = current minus previous same-ticker net_gamma; NaN propagates."""
    return np.asarray(net_gamma, dtype=float) - np.asarray(net_gamma_prev, dtype=float)


def fk_sign_positive(values):
    """1.0 if value > 0, 0.0 if not, NaN if ABSENT — missing is never 'not positive'."""
    arr = np.asarray(values, dtype=float)
    return np.where(np.isfinite(arr), (arr > 0).astype(float), np.nan)


def fk_agreement_positive(a, b):
    """1.0 when both sides share a sign, 0.0 when not; either side absent -> NaN."""
    aa = np.asarray(a, dtype=float)
    bb = np.asarray(b, dtype=float)
    return np.where(np.isfinite(aa) & np.isfinite(bb),
                    ((aa > 0) == (bb > 0)).astype(float), np.nan)


def fk_alignment(a, b):
    """Signed co-movement product; NaN propagates from either leg."""
    return np.asarray(a, dtype=float) * np.asarray(b, dtype=float)


def fk_cross_change_stats(*changes):
    """(mean, population std) across market change legs; a 'cross' needs >= 2 real legs.

    Rows with fewer than two finite legs yield NaN — one market's move is not a
    cross-market statistic. (The serve side always encoded this; the train side let a
    single surviving leg masquerade as the cross mean. The stricter contract is the one
    that matches the feature's name, so it is now the only one.)
    """
    stack = np.array(np.broadcast_arrays(*[np.asarray(c, dtype=float) for c in changes]))
    n_ok = np.sum(np.isfinite(stack), axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mean = np.nanmean(stack, axis=0)
        std = np.nanstd(stack, axis=0)
    return (np.where(n_ok >= 2, mean, np.nan), np.where(n_ok >= 2, std, np.nan))


def fk_volume_log(volume):
    """log1p(volume) with non-positive/absent volume contributing log1p(0) = 0.0."""
    v = np.asarray(volume, dtype=float)
    v = np.where(v > 0, v, np.nan)
    return np.log1p(np.nan_to_num(v, nan=0.0))


def fk_volume_ratio(volume, median):
    """volume / fitted time-of-day median, capped; unusable inputs -> NaN, never a fake 1."""
    v = np.asarray(volume, dtype=float)
    m = np.asarray(median, dtype=float)
    ok = np.isfinite(v) & (v > 0) & np.isfinite(m) & (m > 0)
    return np.where(ok, np.clip(v / np.where(ok, m, 1.0), 0, VOLUME_RATIO_CAP), np.nan)


def fk_imbalance_pressures(imbalance):
    """(buy_pressure, sell_pressure) flags; absent imbalance -> NaN flags (0.0 is a reading)."""
    arr = np.asarray(imbalance, dtype=float)
    fin = np.isfinite(arr)
    buy = np.where(fin, (arr > IMBALANCE_BUY_PRESSURE_MIN).astype(float), np.nan)
    sell = np.where(fin, (arr < IMBALANCE_SELL_PRESSURE_MAX).astype(float), np.nan)
    return buy, sell


def fk_category_code(value, mapping: dict):
    """Fitted category -> float code APPLICATION (the fit itself is a train-only concept)."""
    if value is None:
        return np.nan
    if value in mapping:
        return float(mapping[value])
    s = str(value)
    return float(mapping[s]) if s in mapping else np.nan


def engineer_features(
    df: pd.DataFrame,
    fit_end: Optional[int] = None,
    db_path: Optional[str] = None,
) -> tuple:
    """Build normalized feature matrix. Returns (X, feature_names, category_maps, aux_stats).

    ``fit_end`` (B3 closeout #1): when set, the two stateful transforms — the per-(ticker,hr,min)
    volume median behind ``volume_ratio`` and the categorical -> integer code maps — are FIT on the
    train partition ``df.iloc[:fit_end]`` only, then APPLIED to the full frame. Val-only time-of-day
    keys / categories therefore map to NaN, exactly matching ``engineer_single_snapshot`` serving (no
    persisted median / mapping for an unseen key). ``fit_end=None`` preserves the exact legacy full-df
    behavior byte-for-byte (used by tests, the feature_contracts parity audit, eval-only, and the
    no-holdout / thin-ticker training paths).
    """
    from ml_data_common import attach_confluence_feature_columns, et_hour_minute_arrays_from_ts_utc
    from lstm_data import CONFLUENCE_FEATURES

    # RC-335: `db_path` is threaded so the cf_* population can be STATED. Training could
    # previously only take the process default while serving was handed an explicit path,
    # which meant the two lanes' population was the same only as long as nobody pointed
    # either somewhere else — and it is what makes a train/serve parity control possible
    # against a fixture database. Default None preserves the existing behaviour exactly.
    df_cf = attach_confluence_feature_columns(df, db_path)

    spot  = pd.to_numeric(df["spot"], errors="coerce").values
    feats = {}
    aux_stats = {}

    with np.errstate(divide="ignore", invalid="ignore"):
        name_map = {
            "candle_body_pts": "candle_body_pct",
            "candle_range_pts": "candle_range_pct",
            "nearest_above_dist": "nearest_above_pct",
            "nearest_below_dist": "nearest_below_pct",
        }
        for raw, pct in name_map.items():
            if raw in df.columns:
                v = pd.to_numeric(df[raw], errors="coerce").values
                if raw in ("nearest_above_dist", "nearest_below_dist"):
                    v = np.abs(v)
                feats[pct] = fk_pct_of_spot(v, spot)

        for col in WALL_DISTANCE_COLS:
            if col in df.columns:
                v = pd.to_numeric(df[col], errors="coerce").values
                pct_name = "pin_width_pct" if col == "pin_width_pts" else f"{col}_pct"
                feats[pct_name] = fk_pct_of_spot(v, spot)

        if "vwap_dist_pts" in df.columns:
            v = pd.to_numeric(df["vwap_dist_pts"], errors="coerce").values
            feats["vwap_dist_pts"] = v
            feats["vwap_dist_pct"] = fk_pct_of_spot(v, spot)

    skip = {"candle_volume", "bid_ask_imbalance", "vwap_dist_pts"}
    for col in SCALE_INVARIANT_COLS:
        if col not in skip and col in df.columns:
            feats[col] = pd.to_numeric(df[col], errors="coerce").values

    hrs, mns = et_hour_minute_arrays_from_ts_utc(df)
    if np.any(np.isfinite(hrs)) and np.any(np.isfinite(mns)):
        _tsin, _tcos, _tprog, _mopen = fk_session_time_features(hrs * 60 + mns)
        feats["time_sin"] = _tsin
        feats["time_cos"] = _tcos
        feats["time_progress"] = _tprog
        feats["minutes_since_open"] = _mopen.astype(float)

    if "candle_body_pct" in feats and "candle_range_pct" in feats:
        feats["body_range_ratio"] = fk_body_range_ratio(
            feats["candle_body_pct"], feats["candle_range_pct"])

    if "net_gamma" in df.columns:
        # Adapter mechanics: locate the PREVIOUS same-ticker net_gamma (alignment only);
        # the ΔGEX semantic itself is fk_dgex, shared with the serve row.
        # RC-342: net_gamma_prev has ONE authority (attach_net_gamma_prev_column, raw prior
        # 1m bar). engineer_features must CONSUME that column, never reconstruct it — the
        # old inline groupby-shift fallback was a third producer of the same semantic and
        # gap-jumped differently than the serve path. Absent column -> dgex NaN (RC-335).
        ng_s = pd.to_numeric(df["net_gamma"], errors="coerce")
        if "net_gamma_prev" in df.columns:
            prev_s = pd.to_numeric(df["net_gamma_prev"], errors="coerce")
        else:
            prev_s = pd.Series(np.nan, index=df.index)
        feats["dgex"] = fk_dgex(ng_s.to_numpy(dtype=float), prev_s.to_numpy(dtype=float))
        feats["dgex_positive"] = fk_sign_positive(feats["dgex"])

    # RC-335: preserve MISSING as missing, exactly as `dgex_positive` does two lines above
    # and exactly as the serve builder does at `engineer_single_snapshot` (ml_train.py:655-
    # 657, `float(ng>0) if not np.isnan(ng) else np.nan`).
    #
    # `(series > 0).astype(float)` evaluates NaN > 0 as False and writes 0.0, so an ABSENT
    # net_gamma became a positive assertion that gamma is not positive — while serving, on
    # the identical bar, emitted NaN. XGBoost routes NaN down its learned default branch and
    # 0.0 down a real split, so the two lanes sent the same bar down different trees.
    # MEASURED over 60 bars across SPY, QQQ and IWM: all three flags disagreed on 40 of them.
    if "net_gamma" in feats:
        feats["gamma_positive"] = fk_sign_positive(feats["net_gamma"])
    if "net_delta" in feats:
        feats["delta_positive"] = fk_sign_positive(feats["net_delta"])
    if "net_delta" in feats and "charm_net" in feats:
        feats["charm_delta_agree"] = fk_agreement_positive(
            feats["net_delta"], feats["charm_net"])

    for c1, c2, nm in [("spy_chg_pct","qqq_chg_pct","spy_qqq_align"),
                        ("spy_chg_pct","iwm_chg_pct","spy_iwm_align")]:
        if c1 in feats and c2 in feats:
            feats[nm] = fk_alignment(feats[c1], feats[c2])

    cross = [c for c in ["spy_chg_pct","qqq_chg_pct","iwm_chg_pct"] if c in feats]
    if len(cross) >= 2:          # column presence gates the SCHEMA (adapter decision);
        feats["cross_avg_chg"], feats["cross_std_chg"] = fk_cross_change_stats(
            *[feats[c] for c in cross])          # the row semantic is the kernel's

    if "candle_volume" in df.columns:
        vol = pd.to_numeric(df["candle_volume"], errors="coerce").values.copy()
        vol[vol <= 0] = np.nan               # fit-series hygiene (train-only mechanics)
        feats["candle_volume_log"] = fk_volume_log(vol)
        hrs_s, mns_s = et_hour_minute_arrays_from_ts_utc(df)
        _valid_clock = np.isfinite(hrs_s) & np.isfinite(mns_s)
        if np.any(_valid_clock):
            # RC-336: a row with NO canonical clock gets NO time-of-day bucket. This was
            # `np.nan_to_num(hrs_s, nan=0)`, which filed every clockless row under hour 0
            # minute 0 — so it joined a midnight bucket, frequently became its own median,
            # and emitted volume_ratio = 1.0, i.e. "exactly average volume for this minute",
            # from a minute that was never observed. Serving, which cannot look up a median
            # without a clock, emitted NaN for the same row: MEASURED as 3 divergences in
            # the adversarial matrix. It also polluted the median of genuine 00:00 rows.
            # Setting the key to NaN both excludes these rows from the fit (groupby drops
            # NaN keys) and makes the later .map() yield NaN, which is the honest answer.
            hrs_i = np.nan_to_num(hrs_s, nan=0).astype(int)
            mns_i = np.nan_to_num(mns_s, nan=0).astype(int)
            tkr_s = df["ticker"].astype(str) if "ticker" in df.columns else pd.Series(["?"]*len(df))
            tod   = tkr_s + "_" + hrs_i.astype(str) + "_" + mns_i.astype(str)
            vseries    = pd.Series(vol, index=df.index)
            tod_series = pd.Series(np.asarray(tod), index=df.index)
            tod_series = tod_series.where(pd.Series(_valid_clock, index=df.index), other=np.nan)
            # B3 train-only fit: per-(ticker,hr,min) median fit on the TRAIN partition only,
            # applied to all rows. fit_end=None => full-df (legacy / serving-equiv / eval-only).
            # tod_series.map(full_median) is numerically identical to the old transform("median")
            # for the fit_end=None path, so the default is a no-op regression-wise.
            if fit_end is not None and 0 < fit_end < len(df):
                fit_med = vseries.iloc[:fit_end].groupby(tod_series.iloc[:fit_end]).median()
            else:
                fit_med = vseries.groupby(tod_series).median()
            avg_vol = _mutable_float_ndarray(tod_series.map(fit_med))
            feats["volume_ratio"] = fk_volume_ratio(vol, avg_vol)
            for key, med in fit_med.items():
                if not np.isnan(med):
                    aux_stats[f"vol_median_{key}"] = float(med)

    imb_col = "bid_ask_imbalance" if "bid_ask_imbalance" in df.columns else "flow_imbalance" if "flow_imbalance" in df.columns else None
    if imb_col:
        imb = pd.to_numeric(df[imb_col], errors="coerce").values
        feats["bid_ask_imbalance"] = imb
        feats["imbalance_buy_pressure"], feats["imbalance_sell_pressure"] = (
            fk_imbalance_pressures(imb))

    category_maps = {}
    for col in CATEGORICALS:
        if col in df.columns:
            col_full = df[col]
            # B3 train-only fit: category codes learned from the TRAIN partition only; a val-only
            # category (absent from the train mapping) -> NaN, matching engineer_single_snapshot
            # serving. fit_end=None => full-df (same sorted-unique categories + codes as legacy).
            fit_col = (col_full.iloc[:fit_end]
                       if (fit_end is not None and 0 < fit_end < len(df)) else col_full)
            mapping = {v: i for i, v in enumerate(pd.Categorical(fit_col).categories)}
            category_maps[col] = mapping
            # FIT is a train-only concept (above); APPLICATION is the shared kernel.
            feats[f"cat_{col}"] = col_full.map(
                lambda v, _m=mapping: fk_category_code(v, _m)).to_numpy(dtype=float)

    for cf in CONFLUENCE_FEATURES:
        if cf in df_cf.columns:
            feats[cf] = pd.to_numeric(df_cf[cf], errors="coerce").values

    X = pd.DataFrame(feats, index=df.index)
    dupes = X.columns[X.columns.duplicated()].tolist()
    if dupes:
        print(f"  BUG: duplicate columns: {dupes}")
        X = X.loc[:, ~X.columns.duplicated()]

    return X, list(X.columns), category_maps, aux_stats


def engineer_single_snapshot(snapshot: dict, category_maps: dict,
                              feature_names: list, vol_medians: dict = None,
                              ticker: str = None) -> Optional[pd.DataFrame]:
    """Convert one snapshot dict into a feature row."""
    raw_spot = snapshot.get("spot")
    try:
        spot = float(raw_spot) if raw_spot is not None else None
    except (TypeError, ValueError):
        spot = None
    if spot is None or spot <= 0:
        return None

    tkr = ticker or snapshot.get("ticker", "?")
    row = {}

    def _f(key):
        v = snapshot.get(key)
        if v is None:
            return np.nan
        try:
            return float(v)
        except (TypeError, ValueError):
            # Parity with engineer_features(): training uses pd.to_numeric(errors="coerce"),
            # so a non-numeric snapshot value (e.g. qqq_vs_spy='lagging' from market_state)
            # must become NaN at serve too — not crash the whole XGB prediction.
            return np.nan

    def _pct(key):
        # Scalar adapter over THE pct authority (RC-339) — no second encoding here.
        return float(fk_pct_of_spot(_f(key), spot))

    row["candle_body_pct"]   = _pct("candle_body_pts")
    row["candle_range_pct"]  = _pct("candle_range_pts")
    _nad0, _nbd0 = canonicalize_distance_read(
        snapshot.get("nearest_above_dist"), snapshot.get("nearest_below_dist")
    )
    row["nearest_above_pct"] = float(
        fk_pct_of_spot(_nad0 if _nad0 is not None else np.nan, spot))
    row["nearest_below_pct"] = float(
        fk_pct_of_spot(_nbd0 if _nbd0 is not None else np.nan, spot))

    for col in WALL_DISTANCE_COLS:
        pct_name = "pin_width_pct" if col == "pin_width_pts" else f"{col}_pct"
        row[pct_name] = _pct(col)

    vd = _f("vwap_dist_pts")
    row["vwap_dist_pts"] = vd
    row["vwap_dist_pct"] = float(fk_pct_of_spot(vd, spot))

    skip = {"candle_volume", "bid_ask_imbalance", "vwap_dist_pts"}
    for col in SCALE_INVARIANT_COLS:
        if col not in skip:
            row[col] = _f(col)

    if np.isnan(row.get("qqq_vs_spy", np.nan)):
        # Producer split: live SignalInput carries the 'leading'/'lagging'/'inline' label under
        # qqq_vs_spy and the numeric spread under qqq_vs_spy_delta; the DB/training column holds
        # the numeric spread (server snapshot writer). Use the numeric twin for serve parity.
        row["qqq_vs_spy"] = _f("qqq_vs_spy_delta")

    # RC-335: derive the ET clock from ts_utc, the same authority training uses
    # (`et_hour_minute_arrays_from_ts_utc` at ml_train.py:448 and :521). Reading the STORED
    # et_hour/et_minute here made this the only lane trusting a column the repo has already
    # ruled untrustworthy — `ml_data_common.et_hour_minute_arrays_from_ts_utc` says "never
    # trust stored et_hour on old rows" and `rth_where_clause` is deprecated because those
    # columns "were logged under fixed EST" and skew EDT cohorts. MEASURED over 60 bars on
    # SPY/QQQ/IWM: time_sin, time_cos, time_progress and minutes_since_open each disagreed
    # with training on 6 bars, minutes_since_open by exactly one minute — and volume_ratio
    # broke with them on 4, because its median key `vol_median_{tkr}_{eh}_{em}` is built
    # from this clock while the medians were FIT under the derived one, so the lookup missed
    # and the feature went absent. The stored columns remain the fallback for rows that
    # carry no usable ts_utc, which is the only case training cannot cover either.
    # RC-336: ts_utc is the ONLY clock authority here, with NO fallback to the stored
    # et_hour/et_minute columns. RC-335 derived from ts_utc but kept the stored columns as a
    # fallback, and that fallback fires exactly when the canonical clock is absent — the one
    # case real market rows almost never exercise and the one case training cannot match,
    # because `et_hour_minute_arrays_from_ts_utc` yields NaN there. MEASURED over an
    # adversarial matrix: 15 divergences. With ts_utc missing, training emitted NaN for
    # time_sin/time_cos/time_progress/minutes_since_open while serving emitted 0.4647 /
    # 0.8855 / 0.0769 / 30.0 from the stored clock; with the stored clock ALSO stale at
    # 03:17, serving emitted minutes_since_open = 0.0 — a confident "the session just
    # opened" manufactured from a column this repo already documents as untrustworthy.
    # Absent canonical time is ABSENT: the clock features go NaN, exactly as training does.
    eh = em = None
    _ts_for_clock = snapshot.get("ts_utc")
    if _ts_for_clock is not None:
        try:
            _ts_f = float(_ts_for_clock)
        except (TypeError, ValueError):
            _ts_f = float("nan")
        if np.isfinite(_ts_f):
            from time_et import et_clock_from_ts_utc

            eh, em, _ = et_clock_from_ts_utc(_ts_f)
    # Scalar adapter: compose minutes-of-day from the canonical clock; the session-time
    # semantic itself is fk_session_time_features, shared with training (RC-339).
    _mod = (float(eh) * 60 + float(em)) if (eh is not None and em is not None) else np.nan
    _tsin, _tcos, _tprog, _mopen = fk_session_time_features(_mod)
    row["time_sin"] = float(_tsin)
    row["time_cos"] = float(_tcos)
    row["time_progress"] = float(_tprog)
    row["minutes_since_open"] = float(_mopen)

    row["body_range_ratio"] = float(fk_body_range_ratio(
        row.get("candle_body_pct", np.nan), row.get("candle_range_pct", np.nan)))

    ng = row.get("net_gamma", np.nan)
    row["dgex"] = float(fk_dgex(ng, _f("net_gamma_prev")))
    row["dgex_positive"] = float(fk_sign_positive(row["dgex"]))
    nd = row.get("net_delta", np.nan)
    cn = row.get("charm_net", np.nan)
    row["gamma_positive"] = float(fk_sign_positive(ng))
    row["delta_positive"] = float(fk_sign_positive(nd))
    row["charm_delta_agree"] = float(fk_agreement_positive(nd, cn))

    sc = row.get("spy_chg_pct", np.nan)
    qc = row.get("qqq_chg_pct", np.nan)
    ic = row.get("iwm_chg_pct", np.nan)
    row["spy_qqq_align"] = float(fk_alignment(sc, qc))
    row["spy_iwm_align"] = float(fk_alignment(sc, ic))
    _cavg, _cstd = fk_cross_change_stats(sc, qc, ic)
    row["cross_avg_chg"] = float(_cavg)
    row["cross_std_chg"] = float(_cstd)

    _vf = _f("candle_volume")
    row["candle_volume_log"] = float(fk_volume_log(_vf))
    if vol_medians and eh is not None and em is not None:
        # Artifact SELECTION is adapter work; the ratio semantic is the kernel's.
        med = vol_medians.get(f"vol_median_{tkr}_{int(eh)}_{int(em)}")
        _vr = float(fk_volume_ratio(_vf, med if med is not None else np.nan))
        if not np.isnan(_vr):
            row["volume_ratio"] = _vr

    # RC-333: choose the source column by PRESENCE, exactly as the training lane does at
    # `engineer_features` (ml_train.py:523). This was `snapshot.get("bid_ask_imbalance") or
    # snapshot.get("flow_imbalance")`, which selects by TRUTHINESS — so a legitimate 0.0 in
    # the first key silently switches the feature to a different source, while training,
    # selecting on column presence, would have kept it. 0.0 is a real imbalance reading and
    # the extreme one: the thresholds below are 0.65 and 0.35, so 0.0 is maximal sell-side
    # pressure, the single most informative value the expression could discard. It is latent
    # rather than firing today only because `bid_ask_imbalance` exists in neither `snapshots`
    # nor `snapshots_1m_normalized` (measured), so the first key is always absent — and
    # `flow_imbalance` is exactly 0.0 in 15.5% of SPY rows, so the hazard is real the moment
    # the column lands. Absence, not falsiness, is what "no reading" means.
    imb = (snapshot.get("bid_ask_imbalance")
           if snapshot.get("bid_ask_imbalance") is not None
           else snapshot.get("flow_imbalance"))
    if imb is not None:
        imb_f = float(imb)
        row["bid_ask_imbalance"] = imb_f
        _buy, _sell = fk_imbalance_pressures(imb_f)
        row["imbalance_buy_pressure"] = float(_buy)
        row["imbalance_sell_pressure"] = float(_sell)

    for col in CATEGORICALS:
        row[f"cat_{col}"] = fk_category_code(snapshot.get(col), category_maps.get(col, {}))

    from lstm_data import CONFLUENCE_FEATURES

    for cf in CONFLUENCE_FEATURES:
        v = snapshot.get(cf)
        try:
            row[cf] = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            row[cf] = 0.0

    return pd.DataFrame([{fn: row.get(fn, np.nan) for fn in feature_names}])


# =============================================================================
# MODEL
# =============================================================================

XGB_EARLY_STOPPING_ROUNDS: int = 10


def get_model(n_classes=3, early_stopping_rounds=None):
    try:
        import xgboost as xgb
        print("  Using XGBoost")
        es = {} if early_stopping_rounds is None else {"early_stopping_rounds": int(early_stopping_rounds)}
        if n_classes == 2:
            return xgb.XGBClassifier(
                n_estimators=50, max_depth=3, learning_rate=0.05,
                subsample=0.7, colsample_bytree=0.7, min_child_weight=30,
                gamma=1.0, reg_alpha=1.0, reg_lambda=5.0,
                tree_method="hist", enable_categorical=False,
                n_jobs=-1, random_state=42,
                objective="binary:logistic", eval_metric="logloss",
                **es,
            )
        return xgb.XGBClassifier(
            n_estimators=50, max_depth=3, learning_rate=0.05,
            subsample=0.7, colsample_bytree=0.7, min_child_weight=30,
            gamma=1.0, reg_alpha=1.0, reg_lambda=5.0,
            tree_method="hist", enable_categorical=False,
            n_jobs=-1, random_state=42,
            objective="multi:softprob", num_class=n_classes, eval_metric="mlogloss",
            **es,
        )
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingClassifier
        print("  Using sklearn HistGradientBoosting")
        return HistGradientBoostingClassifier(
            max_iter=50, max_depth=3, learning_rate=0.05,
            min_samples_leaf=30, l2_regularization=5.0, random_state=42)


def encode_target(df, target_column: str):
    return df[target_column].map(CLASS_MAP).values


def _xgb_append_only_ok(prev_fp: dict, curr_fp: dict) -> bool:
    """Require same min_ts_utc, non-shrinking max_ts_utc and row_count (append-only growth)."""
    from training_cache import _normalize_data_fp

    a, b = _normalize_data_fp(prev_fp), _normalize_data_fp(curr_fp)
    if ticker_storage_key(str(a.get("ticker", ""))) != ticker_storage_key(str(b.get("ticker", ""))):
        return False
    if a.get("min_ts_utc") is None or b.get("min_ts_utc") is None:
        return False
    if abs(float(a["min_ts_utc"]) - float(b["min_ts_utc"])) > 1e-6:
        return False
    if float(b.get("max_ts_utc") or 0) + 1e-9 < float(a.get("max_ts_utc") or 0):
        return False
    if int(b.get("row_count", 0)) < int(a.get("row_count", 0)):
        return False
    return True


# =============================================================================
# TRAIN + SAVE ONE TICKER — No gates, always save
# =============================================================================

def train_ticker(
    ticker: str,
    df: pd.DataFrame,
    model_dir: Path = None,
    nan_threshold: float = 0.30,
    skip_sanity: bool = False,
    show_importance: bool = False,
    compare: bool = False,
    evaluate_only: bool = False,
    prior_data_fingerprint: Optional[dict] = None,
    current_data_fingerprint: Optional[dict] = None,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
    target_mode: str = TARGET_MODE_TRICLASS,
    db_path: Optional[str] = None,
) -> dict:
    base_dir = model_dir or MODEL_DIR
    base_dir.mkdir(parents=True, exist_ok=True)
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    tm = (target_mode or TARGET_MODE_TRICLASS).strip().lower()
    if tm == TARGET_MODE_DIR:
        target_col = directional_label_column(hz)
        nc = 2
        class_names = DIR_CLASS_NAMES
        class_map = DIR_CLASS_MAP
    elif tm == TARGET_MODE_MOVE:
        target_col = move_label_column(hz)
        nc = 2
        class_names = MOVE_CLASS_NAMES
        class_map = MOVE_CLASS_MAP
    else:
        tm = TARGET_MODE_TRICLASS
        target_col = outcome_column(hz)
        nc = 3
        class_names = CLASS_NAMES
        class_map = CLASS_MAP

    print(f"\n{'='*60}")
    print(f"XGBoost: {ticker}  ({len(df):,} rows)  horizon={hz} target={target_col} mode={tm}")
    print(f"{'='*60}")

    from features.training_canonical_input import validate_tabular_training_dataframe_canonical

    validate_tabular_training_dataframe_canonical(df)

    if tm == TARGET_MODE_DIR:
        df = df[df[target_col].notna()].reset_index(drop=True)
        if len(df) == 0:
            raise ValueError(f"{ticker}: no rows with non-null {target_col} for dir training")
    if tm != TARGET_MODE_TRICLASS and target_col not in df.columns:
        raise ValueError(f"{ticker}: column {target_col} missing from training frame")

    # B3 closeout #1 — compute the chronological inner split BEFORE feature engineering so the
    # stateful transforms (per-(tkr,hr,min) volume median, category->code maps) AND the NaN column
    # filter below are fit on the TRAIN partition only; the val tail never influences feature
    # computation or selection. len(df) == len(y) here (the dir-mode row filter above already ran;
    # no row drops after). fit_end=None on eval-only / no-holdout / thin-ticker paths preserves the
    # exact legacy full-df behavior.
    from ml_data_common import time_ordered_tail_split

    train_end, n_val = (len(df), 0) if evaluate_only else time_ordered_tail_split(len(df))
    _fit_end = train_end if (n_val > 0 and not evaluate_only) else None
    # RC-340 (DEFECT B): forward the caller's DB so the confluence authority queries the
    # SAME source the training rows came from. This call previously dropped it, so a
    # custom/scratch training DB silently sourced cf_* from the process-default DB —
    # a different population under the same feature names. Default None preserves the
    # default-DB path exactly.
    X, feat_names, cat_maps, aux_stats = engineer_features(
        df, fit_end=_fit_end, db_path=db_path)
    y = df[target_col].map(class_map).values
    if np.any(pd.isna(y)):
        bad = int(np.sum(pd.isna(y)))
        raise ValueError(f"{ticker}: {bad} rows have label outside {class_names} for {target_col}")
    y = y.astype(np.int64)
    print(f"  Engineered {len(X.columns)} features, shape {X.shape}")
    print(f"  NaN density: {X.isna().mean().mean():.1%}")
    print(f"  Class balance: {dict(zip(class_names, np.bincount(y, minlength=nc)))}")

    # B3 closeout #1: decide the surviving feature set on the TRAIN partition only (full-df on the
    # eval-only / no-holdout paths) so the val tail — including the val-region NaNs that the
    # train-only category/volume fit now produces — never influences which features the model sees.
    _nan_basis = X.iloc[:train_end] if (n_val > 0 and not evaluate_only) else X
    nan_pct = _nan_basis.isna().mean().sort_values(ascending=False)
    good    = nan_pct[nan_pct < nan_threshold].index.tolist()
    dropped = nan_pct[nan_pct >= nan_threshold].index.tolist()
    print(f"\n  NaN filter ({nan_threshold:.0%}): kept {len(good)}, dropped {len(dropped)}")
    for f in dropped[:6]:
        print(f"    dropped: {f:40s} {nan_pct[f]:.1%}")
    if len(dropped) > 6:
        print(f"    ... and {len(dropped)-6} more")

    X = X[good]
    feat_names = good

    from arch_competition.stack_bundle_eval_v1 import (
        ablation_survivors_training_enabled,
        drop_ablated_xgb_engineered_columns,
    )

    if ablation_survivors_training_enabled():
        X, feat_names, _n_abl = drop_ablated_xgb_engineered_columns(X, feat_names, hz)
        if _n_abl:
            print(f"  Ablation XGB post-engineer drop: {_n_abl} engineered columns removed")

    # Workstream B3 — chronological inner holdout (df is ORDER BY ts_utc ASC). The split (train_end,
    # n_val) is computed above, BEFORE engineer_features, so the imputation medians, the per-
    # (tkr,hr,min) volume median, the category code maps, AND the NaN column filter are all fit on
    # the TRAIN partition only; the XGB best boosting round is early-stopped on the strictly-later
    # val tail (not training loss) and the reported val_accuracy is out-of-sample. Thin tickers get
    # no holdout (in-sample, disclosed; blocked from promotion by A1/B1); evaluate_only keeps the
    # legacy full-data path. CORRECTNESS-CLOSEOUT #1 (2026-05-31): the prior
    # [REAL-GATE: training-skew] full-df category/volume fit is now closed — feature VALUES change,
    # so PREPROCESSING_VERSION is bumped to force the one clean refit.
    _impute_basis = X.iloc[:train_end] if n_val > 0 else X
    med_series = _impute_basis.median()
    impute_medians = {}
    for f in feat_names:
        v = med_series[f] if f in med_series.index else np.nan
        impute_medians[f] = float(v) if pd.notna(v) else 0.0
    X = X.fillna(pd.Series(impute_medians))
    X_np = np.nan_to_num(X.values.astype(np.float64), nan=0.0)

    # O-55: equal/uniform sample weights only — every row counts the same. No recency
    # decay, no class re-weighting, no toggle.
    from ml_data_common import equal_sample_weights
    sample_w = equal_sample_weights(len(y))

    if not skip_sanity:
        maj_pct = np.bincount(y, minlength=nc).max() / len(y)
        print(f"\n  Majority: {class_names[np.bincount(y, minlength=nc).argmax()]} ({maj_pct:.1%})")

    from sklearn.metrics import accuracy_score as _acc

    # B3 holdout fit: early-stopped on the strictly-later val tail. When a holdout exists the
    # incremental warm-continuation is bypassed so the best-round selection is governed purely
    # by the held-out tail (disclosed: warm-start perf opt is off for healthy tickers).
    val_accuracy = None
    val_basis = "in_sample_no_holdout"
    xgb_best_iteration = None
    holdout_done = False
    _tr_acc = None
    mdl_final = None
    if n_val > 0 and not evaluate_only:
        X_tr, y_tr, w_tr = X_np[:train_end], y[:train_end], sample_w[:train_end]
        X_val, y_val = X_np[train_end:], y[train_end:]
        _m = get_model(nc, early_stopping_rounds=XGB_EARLY_STOPPING_ROUNDS)
        try:
            _m.fit(X_tr, y_tr, sample_weight=w_tr, eval_set=[(X_val, y_val)], verbose=False)
            mdl_final = _m
            xgb_best_iteration = getattr(_m, "best_iteration", None)
            val_accuracy = float(_acc(y_val, _m.predict(X_val)))
            _tr_acc = float(_acc(y_tr, _m.predict(X_tr)))
            val_basis = "time_ordered_tail"
            holdout_done = True
            print(
                f"  B3 holdout: val_acc={val_accuracy:.1%} "
                f"(n_val={n_val}, best_iter={xgb_best_iteration}); train_acc={_tr_acc:.1%}"
            )
        except TypeError as _es_ex:
            # eval_set / early stopping unsupported (sklearn fallback) -> in-sample path below.
            print(f"  B3 holdout unavailable ({_es_ex}); in-sample fit")
            mdl_final = None

    print(f"\n  Training on {len(y):,} rows (equal sample weights — O-55)...")
    from training_cache_policy import XGBOOST_INCREMENTAL_TRAIN_ALLOWED

    if mdl_final is None:
        mdl_final = get_model(nc)
    incremental_done = False
    if (
        XGBOOST_INCREMENTAL_TRAIN_ALLOWED
        and not holdout_done
        and prior_data_fingerprint
        and current_data_fingerprint
        and not evaluate_only
    ):
        mp_ex = model_path(ticker, base_dir, ml_horizon_slug=hz, target_mode=tm)
        prev_meta = None
        prev_clf = None
        if mp_ex.is_file():
            try:
                with open(meta_path(ticker, base_dir, ml_horizon_slug=hz, target_mode=tm), encoding="utf-8") as fm:
                    prev_meta = json.load(fm)
                with open(mp_ex, "rb") as f:
                    prev_clf = pickle.load(f)
            except (OSError, json.JSONDecodeError, pickle.UnpicklingError, EOFError) as _inc_ex:
                logging.getLogger("ml_train").debug(
                    "XGB incremental load failed for %s: %s", ticker, _inc_ex
                )
                prev_meta, prev_clf = None, None
        from training_provenance import PREPROCESSING_VERSION as _PREPROC_V

        if (
            prev_clf is not None
            and prev_meta is not None
            and str(prev_meta.get("preprocessing_version", "")) == str(_PREPROC_V)
            and _xgb_append_only_ok(prior_data_fingerprint, current_data_fingerprint)
            and prev_meta.get("features") == feat_names
            and prev_meta.get("target") == target_col
            and str(prev_meta.get("target_mode", TARGET_MODE_TRICLASS)).lower() == tm
            and xgb_meta_contract_ok(prev_meta)
            and hasattr(prev_clf, "get_booster")
        ):
            try:
                mdl_final.fit(
                    X_np,
                    y,
                    sample_weight=sample_w,
                    xgb_model=prev_clf.get_booster(),
                    verbose=False,
                )
                incremental_done = True
                print("  XGBoost: incremental continuation (ED_XGB_INCREMENTAL=1, append-only + schema match)")
            except Exception as ex:
                print(f"  XGBoost incremental failed ({ex}); full refit")
                mdl_final = get_model(nc)
    if not incremental_done and not holdout_done:
        mdl_final.fit(X_np, y, sample_weight=sample_w, verbose=False)

    from ml_data_common import holdout_class_metrics
    if holdout_done:
        # train_accuracy stays in-sample-by-name (train partition); val_accuracy is the honest
        # out-of-sample headline metric, and the degeneracy diagnostics below are measured on the
        # same held-out tail (not in-sample) so a majority-class collapse is visible.
        fa = float(_tr_acc)
        _y_eval = y[train_end:]
        _yhat_eval = mdl_final.predict(X_np[train_end:])
        pd_d = {class_names[i]: int((_yhat_eval == i).sum()) for i in range(nc)}
        print(f"  Holdout val pred dist: {pd_d}")
    else:
        _y_eval = y
        _yhat_eval = mdl_final.predict(X_np)
        fa = _acc(y, _yhat_eval)
        pd_d = {class_names[i]: int((_yhat_eval == i).sum()) for i in range(nc)}
        print(f"  Full-data accuracy: {fa:.1%}  Pred dist: {pd_d}")
    # Workstream B3+ degeneracy diagnostics: balanced_accuracy + per-class recall on the eval set
    # (held-out tail when a holdout exists, else in-sample full data). single_class_collapse marks
    # an all-flat base whose top-line accuracy is just the majority base rate — blocked from
    # promotion regardless of accuracy by the validate_for_promotion collapse guard.
    deg = holdout_class_metrics(_y_eval, _yhat_eval, nc, class_names)
    print(
        f"  Degeneracy: balanced_acc={deg['balanced_accuracy']}, "
        f"recall={deg['per_class_recall']}"
        + ("  [SINGLE-CLASS COLLAPSE]" if deg["single_class_collapse"] else "")
    )

    _base = 1.0 / float(nc)
    if evaluate_only:
        return dict(ticker=ticker, cv={"avg_accuracy": fa}, edge=fa - _base,
                   feat_names=feat_names, cat_maps=cat_maps, aux_stats=aux_stats,
                   X_np=X_np, y=y)

    mp = model_path(ticker, base_dir, ml_horizon_slug=hz, target_mode=tm)
    with open(mp, "wb") as f:
        pickle.dump(mdl_final, f)

    meta = dict(
        ticker=ticker, model_type=type(mdl_final).__name__,
        model_version="ml_v4_per_ticker",
        trained_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        samples=len(y), features=feat_names, n_features=len(feat_names),
        target=target_col, ml_horizon_slug=hz, target_mode=tm,
        class_map={n: i for i, n in enumerate(class_names)},
        class_names=class_names, train_accuracy=round(fa, 4),
        val_accuracy=(round(val_accuracy, 4) if val_accuracy is not None else None),
        val_basis=val_basis,
        balanced_accuracy=deg["balanced_accuracy"],
        val_per_class_recall=deg["per_class_recall"],
        val_single_class_collapse=bool(deg["single_class_collapse"]),
        val_predicted_class_names=deg["predicted_class_names"],
        xgb_best_iteration=(int(xgb_best_iteration) if xgb_best_iteration is not None else None),
        weight_mode="equal",
        sample_weight_mode="equal",
        nan_threshold=nan_threshold, features_dropped=dropped,
        category_maps={k: {str(ck): int(cv_v) for ck, cv_v in v.items()}
                      for k, v in cat_maps.items()},
        vol_medians=aux_stats,
        impute_medians=impute_medians,
    )
    # Persist full training provenance (required for promotion gating)
    from training_provenance import build_xgb_provenance
    from model_contract import contract_metadata_dict

    prov = build_xgb_provenance(ticker, df, meta, horizon_slug=hz)
    meta.update(prov.to_dict())
    meta.update(contract_metadata_dict())
    mtp = meta_path(ticker, base_dir, ml_horizon_slug=hz, target_mode=tm)
    with open(mtp, "w") as f:
        json.dump(meta, f, indent=2,
                  default=lambda o: float(o) if hasattr(o, "item") else str(o))

    print(f"  Saved: {mp}")

    return dict(ticker=ticker, cv={"avg_accuracy": fa}, edge=fa - _base,
                meta=meta, feat_names=feat_names, cat_maps=cat_maps,
                aux_stats=aux_stats, model=mdl_final, X_np=X_np, y=y)


# =============================================================================
# MAIN
# =============================================================================

def main():
    ap = argparse.ArgumentParser(description="Train per-ticker XGBoost models")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--ticker", type=str, default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--evaluate-only", action="store_true")
    ap.add_argument("--feature-importance", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--nan-threshold", type=float, default=0.30)
    ap.add_argument("--skip-sanity", action="store_true")
    ap.add_argument("--model-dir", type=str, default=None,
                    help="Output directory (default: models)")
    ap.add_argument(
        "--horizon",
        type=str,
        default=DEFAULT_ML_HORIZON_SLUG,
        help="ML horizon slug (1c, 5c, 15c, 60c). Selects outcome_* label and artifact names.",
    )
    ap.add_argument(
        "--target-mode",
        type=str,
        default=TARGET_MODE_TRICLASS,
        choices=[TARGET_MODE_TRICLASS, TARGET_MODE_DIR, TARGET_MODE_MOVE],
        help="triclass=legacy outcome_*; dir=outcome_dir_* (filtered); move=outcome_move_* (full sample).",
    )
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="ml_train", write_capable=False)

    print("=" * 60)
    print("ED CONSOLE - ML TRAINING PIPELINE (Phase 4 - Per-Ticker)")
    print("=" * 60)

    if not args.ticker and not args.all:
        print("\nERROR: specify --ticker TICKER or --all")
        sys.exit(1)

    model_dir = Path(args.model_dir) if args.model_dir else MODEL_DIR

    print("\n1. LOADING DATA")
    hz_arg = normalize_ml_horizon_slug(args.horizon)
    tm_arg = str(args.target_mode).strip().lower()
    if tm_arg == TARGET_MODE_DIR:
        _lc = directional_label_column(hz_arg)
    elif tm_arg == TARGET_MODE_MOVE:
        _lc = move_label_column(hz_arg)
    else:
        _lc = outcome_column(hz_arg)
    from scheduler_user_tickers import require_ml_training_ticker_allowed, resolve_ml_training_roster

    if args.ticker:
        tkr = require_ml_training_ticker_allowed(args.ticker)
        df_all = load_data(
            args.db, ticker=tkr, ml_horizon_slug=hz_arg, label_column=_lc
        )
        tickers = [tkr]
    else:
        df_all = load_data(args.db, ml_horizon_slug=hz_arg, label_column=_lc)
        raw = df_all["ticker"].unique().tolist() if len(df_all) > 0 else []
        tickers = resolve_ml_training_roster(raw, args.db)
        if not tickers:
            print("\nERROR: no training-roster tickers in data (anchors: SPY/QQQ/IWM)")
            sys.exit(1)
        print(f"\n  Tickers (training roster): {tickers}")

    results = {}
    for tkr in tickers:
        if args.ticker:
            df = df_all
        else:
            df = df_all[df_all["ticker"] == tkr].reset_index(drop=True)
        if len(df) == 0:
            print(f"\n  Skipping {tkr}: no data")
            continue
        try:
            r = train_ticker(
                ticker=tkr, df=df,
                model_dir=model_dir,
                nan_threshold=args.nan_threshold,
                skip_sanity=args.skip_sanity,
                show_importance=args.feature_importance,
                compare=args.compare,
                evaluate_only=args.evaluate_only,
                ml_horizon_slug=hz_arg,
                target_mode=tm_arg,
                db_path=args.db,  # RC-344/F35: same DB as load_data(args.db) above
            )
            results[tkr] = r
        except Exception as e:
            print(f"\n  ERROR training {tkr}: {e}")
            import traceback
            traceback.print_exc()

    if len(tickers) > 1:
        print(f"\n{'='*60}\nSUMMARY\n{'='*60}")
        for tkr, r in results.items():
            edge = r.get("edge", 0) * 100
            acc = r.get("cv", {}).get("avg_accuracy", 0)
            print(f"  {tkr:8s}  acc={acc:.1%}  edge={edge:+.1f}pp")


if __name__ == "__main__":
    main()
