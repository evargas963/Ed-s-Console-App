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

import os, sys, json, time, sqlite3, pickle, warnings, argparse, logging
from pathlib import Path
from typing import Optional, Set
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
    """Match train_ticker: per-column training median fill, then nan_to_num(nan=0)."""
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
    t = str(ticker).strip().upper()
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
    t = str(ticker).strip().upper()
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
    "dist_call_oi_wall",    "dist_put_oi_wall",
    "dist_call_vanna_wall", "dist_put_vanna_wall",
    "dist_gamma_inflection","dist_delta_inflection",
    "pin_width_pts",
]

# m5_* additive columns merged as-of from canonical 1m snapshot rows only (attach_5m_additive_context)
M5_WALL_DISTANCE_COLS = tuple(f"m5_{c}" for c in WALL_DISTANCE_COLS)
M5_SCALE_INVARIANT_EXTRA = (
    "m5_zone_since_bars_5m",
    "m5_net_gamma",
    "m5_net_delta",
    "m5_charm_net",
    "m5_iv_level",
    "m5_put_call_oi_ratio",
    "m5_spy_chg_pct",
    "m5_qqq_chg_pct",
    "m5_iwm_chg_pct",
)

SCALE_INVARIANT_COLS = [
    "net_gamma", "net_delta", "charm_net", "put_call_oi_ratio",
    "spy_chg_pct", "qqq_chg_pct", "iwm_chg_pct",
    "vix_level", "vix_vs_prev", "vwap_dist_pts", "iv_level",
    "spy_weighted_push", "qqq_weighted_push", "iwm_weighted_push",
    "nvda_chg_pct", "aapl_chg_pct", "msft_chg_pct", "amzn_chg_pct",
    "googl_chg_pct", "avgo_chg_pct", "meta_chg_pct", "tsla_chg_pct",
    "kre_chg_pct", "xbi_chg_pct", "psci_chg_pct", "xrt_chg_pct",
    "zone_since_bars",  # DB column: 1m execution-layer (alias for zone_since_bars_1m)
    "candle_volume", "bid_ask_imbalance",
    "spread", "atr", "iv_rank", "smart_money_score",
    "breakout_score", "pin_score",
    # Context layer (snapshots after rollout — NaN for legacy rows until backfilled)
    "sentiment_composite", "sentiment_buzz", "sentiment_finnhub", "sentiment_av",
    "breaking_news_flag", "pre_market_sentiment",
    "absorption_score", "continuation_score",
]

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
    Merges additive m5_* columns via as-of backward join from canonical timeframe='1m'
    snapshots only (see ml_data_common.attach_5m_additive_context).
    min_ts_utc: if set, only rows with ts_utc >= this value (rolling RTH session window).
    allowed_et_dates: if set, only rows whose ts_et date (YYYY-MM-DD) is in this set.
    """
    from ml_data_common import (
        attach_5m_additive_context,
        et_hour_minute_arrays_from_ts_utc,
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
        from normalized_training_sync import ensure_normalized_training_table

        _ns = ensure_normalized_training_table(db_path, force=False, logger=logging.getLogger("ml_train.normsync"))
        if not _ns.get("ok"):
            logging.getLogger("ml_train.normsync").warning(
                "normalized_training_sync failed: %s", _ns.get("errors")
            )
    except (sqlite3.Error, OSError, ValueError, TypeError) as _e:
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
    df = attach_5m_additive_context(df, db_path)
    extra_m5 = sum(1 for c in df.columns if str(c).startswith("m5_"))
    print(f"  m5 additive context: {extra_m5} m5_* columns (as-of merge; 1m snapshots preferred, else 5m)")
    print(f"  Loaded {len(df):,} RTH rows  "
          f"[{df['ts_et'].iloc[0]} -> {df['ts_et'].iloc[-1]}]")
    if not ticker:
        print(f"  Tickers: {df['ticker'].nunique()} "
              f"({', '.join(df['ticker'].unique()[:8])}...)")
    print(f"  Zones:    {dict(df['zone'].value_counts())}")
    if label_col in df.columns:
        print(f"  Outcomes ({label_col}): {dict(df[label_col].value_counts())}")
    return df


# =============================================================================
# FEATURE ENGINEERING
# =============================================================================

def engineer_features(df: pd.DataFrame) -> tuple:
    """Build normalized feature matrix. Returns (X, feature_names, category_maps, aux_stats)."""
    from ml_data_common import et_hour_minute_arrays_from_ts_utc

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
                feats[pct] = v / spot * 100.0

        for col in WALL_DISTANCE_COLS:
            if col in df.columns:
                v = pd.to_numeric(df[col], errors="coerce").values
                pct_name = "pin_width_pct" if col == "pin_width_pts" else f"{col}_pct"
                feats[pct_name] = v / spot * 100.0

        if "vwap_dist_pts" in df.columns:
            v = pd.to_numeric(df["vwap_dist_pts"], errors="coerce").values
            feats["vwap_dist_pts"] = v
            feats["vwap_dist_pct"] = v / spot * 100.0

        m5_candle_map = {
            "m5_candle_body_pts": "m5_candle_body_pct",
            "m5_candle_range_pts": "m5_candle_range_pct",
        }
        for raw, pct in m5_candle_map.items():
            if raw in df.columns:
                v = pd.to_numeric(df[raw], errors="coerce").values
                feats[pct] = v / spot * 100.0

        for col in M5_WALL_DISTANCE_COLS:
            if col in df.columns:
                v = pd.to_numeric(df[col], errors="coerce").values
                pct_name = "m5_pin_width_pct" if col == "m5_pin_width_pts" else f"{col}_pct"
                feats[pct_name] = v / spot * 100.0

        for col in M5_SCALE_INVARIANT_EXTRA:
            if col in df.columns:
                feats[col] = pd.to_numeric(df[col], errors="coerce").values

    skip = {"candle_volume", "bid_ask_imbalance", "vwap_dist_pts"}
    for col in SCALE_INVARIANT_COLS:
        if col not in skip and col in df.columns:
            feats[col] = pd.to_numeric(df[col], errors="coerce").values

    hrs, mns = et_hour_minute_arrays_from_ts_utc(df)
    if np.any(np.isfinite(hrs)) and np.any(np.isfinite(mns)):
        prog = np.clip((hrs * 60 + mns - RTH_OPEN_MINS) / float(RTH_SESSION_MINUTES), 0, 1)
        feats["time_sin"]      = np.sin(2 * np.pi * prog)
        feats["time_cos"]      = np.cos(2 * np.pi * prog)
        feats["time_progress"] = prog
        feats["minutes_since_open"] = np.clip(
            hrs * 60 + mns - RTH_OPEN_MINS, 0, RTH_SESSION_MINUTES
        ).astype(float)

    if "candle_body_pct" in feats and "candle_range_pct" in feats:
        rng = feats["candle_range_pct"].copy()
        rng[rng == 0] = np.nan
        feats["body_range_ratio"] = np.abs(feats["candle_body_pct"]) / rng

    if "net_gamma" in feats:
        feats["gamma_positive"] = (feats["net_gamma"] > 0).astype(float)
    if "net_delta" in feats:
        feats["delta_positive"] = (feats["net_delta"] > 0).astype(float)
    if "net_delta" in feats and "charm_net" in feats:
        feats["charm_delta_agree"] = (
            (feats["net_delta"] > 0) == (feats["charm_net"] > 0)).astype(float)

    for c1, c2, nm in [("spy_chg_pct","qqq_chg_pct","spy_qqq_align"),
                        ("spy_chg_pct","iwm_chg_pct","spy_iwm_align")]:
        if c1 in feats and c2 in feats:
            feats[nm] = feats[c1] * feats[c2]

    cross = [c for c in ["spy_chg_pct","qqq_chg_pct","iwm_chg_pct"] if c in feats]
    if len(cross) >= 2:
        arr = np.column_stack([feats[c] for c in cross])
        feats["cross_avg_chg"] = np.nanmean(arr, axis=1)
        feats["cross_std_chg"] = np.nanstd(arr, axis=1)

    if "candle_volume" in df.columns:
        vol = pd.to_numeric(df["candle_volume"], errors="coerce").values.copy()
        vol[vol <= 0] = np.nan
        feats["candle_volume_log"] = np.log1p(np.nan_to_num(vol, nan=0.0))
        hrs_s, mns_s = et_hour_minute_arrays_from_ts_utc(df)
        if np.any(np.isfinite(hrs_s)) and np.any(np.isfinite(mns_s)):
            hrs_i = np.nan_to_num(hrs_s, nan=0).astype(int)
            mns_i = np.nan_to_num(mns_s, nan=0).astype(int)
            tkr_s = df["ticker"].astype(str) if "ticker" in df.columns else pd.Series(["?"]*len(df))
            tod   = tkr_s + "_" + hrs_i.astype(str) + "_" + mns_i.astype(str)
            vseries    = pd.Series(vol, index=df.index)
            med_by_tod = vseries.groupby(tod).transform("median")
            avg_vol    = med_by_tod.values
            avg_vol[avg_vol <= 0] = np.nan
            feats["volume_ratio"] = np.clip(vol / avg_vol, 0, 10)
            for key, med in vseries.groupby(tod).median().items():
                if not np.isnan(med):
                    aux_stats[f"vol_median_{key}"] = float(med)

    imb_col = "bid_ask_imbalance" if "bid_ask_imbalance" in df.columns else "flow_imbalance" if "flow_imbalance" in df.columns else None
    if imb_col:
        imb = pd.to_numeric(df[imb_col], errors="coerce").values
        nm  = np.isnan(imb)
        feats["bid_ask_imbalance"] = imb
        for k, fn in [("imbalance_buy_pressure",  lambda x: x > 0.65),
                      ("imbalance_sell_pressure", lambda x: x < 0.35)]:
            arr = fn(imb).astype(float); arr[nm] = np.nan; feats[k] = arr

    category_maps = {}
    for col in CATEGORICALS:
        if col in df.columns:
            cat     = df[col].astype("category")
            mapping = {v: i for i, v in enumerate(cat.cat.categories)}
            category_maps[col] = mapping
            codes   = cat.cat.codes.values.astype(float)
            codes[codes < 0] = np.nan
            feats[f"cat_{col}"] = codes

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
        return float(v) if v is not None else np.nan

    def _pct(key):
        v = _f(key)
        return (v / spot * 100.0) if not np.isnan(v) else np.nan

    row["candle_body_pct"]   = _pct("candle_body_pts")
    row["candle_range_pct"]  = _pct("candle_range_pts")
    _nad0, _nbd0 = canonicalize_distance_read(
        snapshot.get("nearest_above_dist"), snapshot.get("nearest_below_dist")
    )
    row["nearest_above_pct"] = (
        (_nad0 / spot * 100.0) if _nad0 is not None else np.nan
    )
    row["nearest_below_pct"] = (
        (_nbd0 / spot * 100.0) if _nbd0 is not None else np.nan
    )

    for col in WALL_DISTANCE_COLS:
        pct_name = "pin_width_pct" if col == "pin_width_pts" else f"{col}_pct"
        row[pct_name] = _pct(col)

    vd = _f("vwap_dist_pts")
    row["vwap_dist_pts"] = vd
    row["vwap_dist_pct"] = (vd / spot * 100.0) if not np.isnan(vd) else np.nan

    skip = {"candle_volume", "bid_ask_imbalance", "vwap_dist_pts"}
    for col in SCALE_INVARIANT_COLS:
        if col not in skip:
            row[col] = _f(col)

    eh = snapshot.get("et_hour")
    em = snapshot.get("et_minute")
    if eh is not None and em is not None:
        prog = max(
            0.0,
            min(1.0, (float(eh) * 60 + float(em) - RTH_OPEN_MINS) / float(RTH_SESSION_MINUTES)),
        )
        row["time_sin"]      = np.sin(2 * np.pi * prog)
        row["time_cos"]      = np.cos(2 * np.pi * prog)
        row["time_progress"] = prog
        mins_open = max(
            0.0,
            min(float(RTH_SESSION_MINUTES), float(eh) * 60 + float(em) - RTH_OPEN_MINS),
        )
        row["minutes_since_open"] = mins_open
    else:
        row["time_sin"] = row["time_cos"] = row["time_progress"] = np.nan
        row["minutes_since_open"] = np.nan

    cb = row.get("candle_body_pct", np.nan)
    cr = row.get("candle_range_pct", np.nan)
    row["body_range_ratio"] = (abs(cb)/cr) if (not np.isnan(cb) and cr and cr>0) else np.nan

    ng = row.get("net_gamma", np.nan)
    nd = row.get("net_delta", np.nan)
    cn = row.get("charm_net", np.nan)
    row["gamma_positive"]    = float(ng>0) if not np.isnan(ng) else np.nan
    row["delta_positive"]    = float(nd>0) if not np.isnan(nd) else np.nan
    row["charm_delta_agree"] = float((nd>0)==(cn>0)) if not(np.isnan(nd) or np.isnan(cn)) else np.nan

    sc = row.get("spy_chg_pct", np.nan)
    qc = row.get("qqq_chg_pct", np.nan)
    ic = row.get("iwm_chg_pct", np.nan)
    row["spy_qqq_align"] = (sc*qc) if not(np.isnan(sc) or np.isnan(qc)) else np.nan
    row["spy_iwm_align"] = (sc*ic) if not(np.isnan(sc) or np.isnan(ic)) else np.nan
    cv = [v for v in [sc,qc,ic] if not np.isnan(v)]
    row["cross_avg_chg"] = float(np.mean(cv)) if len(cv)>=2 else np.nan
    row["cross_std_chg"] = float(np.std(cv))  if len(cv)>=2 else np.nan

    vol = snapshot.get("candle_volume")
    if vol is not None and float(vol) > 0:
        vf = float(vol)
        row["candle_volume_log"] = float(np.log1p(vf))
        if vol_medians and eh is not None and em is not None:
            med = vol_medians.get(f"vol_median_{tkr}_{int(eh)}_{int(em)}")
            if med and med > 0:
                row["volume_ratio"] = min(10.0, vf/med)
    else:
        row["candle_volume_log"] = 0.0

    imb = snapshot.get("bid_ask_imbalance") or snapshot.get("flow_imbalance")
    if imb is not None:
        imb_f = float(imb)
        row["bid_ask_imbalance"]       = imb_f
        row["imbalance_buy_pressure"]  = float(imb_f > 0.65)
        row["imbalance_sell_pressure"] = float(imb_f < 0.35)

    for raw, pct in [
        ("m5_candle_body_pts", "m5_candle_body_pct"),
        ("m5_candle_range_pts", "m5_candle_range_pct"),
    ]:
        v = _f(raw)
        row[pct] = (v / spot * 100.0) if not np.isnan(v) else np.nan

    for col in M5_WALL_DISTANCE_COLS:
        pct_name = "m5_pin_width_pct" if col == "m5_pin_width_pts" else f"{col}_pct"
        v = _f(col)
        row[pct_name] = (v / spot * 100.0) if not np.isnan(v) else np.nan

    for col in M5_SCALE_INVARIANT_EXTRA:
        row[col] = _f(col)

    for col in CATEGORICALS:
        val     = snapshot.get(col)
        mapping = category_maps.get(col, {})
        row[f"cat_{col}"] = float(mapping[str(val)]) if (
            val is not None and str(val) in mapping) else np.nan

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
    if str(a.get("ticker", "")).upper() != str(b.get("ticker", "")).upper():
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

    X, feat_names, cat_maps, aux_stats = engineer_features(df)
    y = df[target_col].map(class_map).values
    if np.any(pd.isna(y)):
        bad = int(np.sum(pd.isna(y)))
        raise ValueError(f"{ticker}: {bad} rows have label outside {class_names} for {target_col}")
    y = y.astype(np.int64)
    print(f"  Engineered {len(X.columns)} features, shape {X.shape}")
    print(f"  NaN density: {X.isna().mean().mean():.1%}")
    print(f"  Class balance: {dict(zip(class_names, np.bincount(y, minlength=nc)))}")

    nan_pct = X.isna().mean().sort_values(ascending=False)
    good    = nan_pct[nan_pct < nan_threshold].index.tolist()
    dropped = nan_pct[nan_pct >= nan_threshold].index.tolist()
    print(f"\n  NaN filter ({nan_threshold:.0%}): kept {len(good)}, dropped {len(dropped)}")
    for f in dropped[:6]:
        print(f"    dropped: {f:40s} {nan_pct[f]:.1%}")
    if len(dropped) > 6:
        print(f"    ... and {len(dropped)-6} more")

    X = X[good]
    feat_names = good

    # Workstream B3 — chronological inner holdout (df is ORDER BY ts_utc ASC). Imputation
    # medians are fit on the TRAIN partition only; the XGB best boosting round is selected by
    # early stopping on the strictly-later val tail (not training loss); reported val_accuracy
    # is out-of-sample. Thin tickers get no holdout (in-sample, disclosed) and are blocked from
    # promotion by A1/B1. evaluate_only keeps the legacy full-data path.
    # [REAL-GATE: training-skew] engineer_features' category maps + aux vol medians are still
    # fit on the full df (only fillna imputation is train-partition-only here). Fixing this
    # alters feature computation → requires the one clean retrain, so it lands with the
    # CORRECTNESS-CLOSEOUT (item #1) per OPEN_ITEMS "OPERATOR GATE 2026-05-31" — not standalone.
    from ml_data_common import time_ordered_tail_split

    train_end, n_val = (len(y), 0) if evaluate_only else time_ordered_tail_split(len(y))
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
        from sklearn.metrics import accuracy_score
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
    if args.ticker:
        df_all  = load_data(
            args.db, ticker=args.ticker.upper(), ml_horizon_slug=hz_arg, label_column=_lc
        )
        tickers = [args.ticker.upper()]
    else:
        df_all  = load_data(args.db, ml_horizon_slug=hz_arg, label_column=_lc)
        tickers = df_all["ticker"].unique().tolist() if len(df_all) > 0 else []
        print(f"\n  Tickers: {tickers}")

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
