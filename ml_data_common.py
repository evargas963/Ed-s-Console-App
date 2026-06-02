"""
ml_data_common.py Shared RTH + Exponential Decay for ML Training
==================================================================
RULE 1 constants and helpers. Used by ml_train, lstm_model, transformer_train,
train_all, ml_scheduler.
"""

from __future__ import annotations

import sqlite3
import warnings
from typing import Any

from db import sql_select_snapshots_columns

import numpy as np
import pandas as pd

# RTH: 09:30–16:00 ET weekdays (re-exported from time_et for single authority)
from time_et import (
    COH_I_A_ET_AUTHORITY_TS_UTC,
    RTH_END_MINS,
    RTH_START_MINS,
    calibration_widen_min_ts_utc,
    et_clock_from_ts_utc,
    et_date_str_from_ts_utc,
    is_rth_ts_utc,
)


_RTH_WHERE_DEPRECATION_WARNED = False


def rth_where_clause() -> str:
    """
    DEPRECATED: use filter_df_to_rth_ts_utc post-fetch — this SQL clause skews EDT cohorts on
    pre-99ea0e0 rows where stored et_hour/et_minute were logged under fixed EST.

    Prefer filter_df_to_rth_ts_utc / filter_ts_utc_list_to_rth / training_base_where_clause.
    """
    global _RTH_WHERE_DEPRECATION_WARNED
    if not _RTH_WHERE_DEPRECATION_WARNED:
        warnings.warn(
            "rth_where_clause() is deprecated: filter on ts_utc via filter_df_to_rth_ts_utc "
            "after fetch — stored et_hour skews EDT cohorts on pre-COH-I-A rows.",
            DeprecationWarning,
            stacklevel=2,
        )
        _RTH_WHERE_DEPRECATION_WARNED = True
    return (
        "(et_hour * 60 + et_minute) >= " + str(RTH_START_MINS) + " "
        "AND (et_hour * 60 + et_minute) < " + str(RTH_END_MINS)
    )


def filter_ts_utc_list_to_rth(ts_values: list[float]) -> list[float]:
    out: list[float] = []
    for t in ts_values:
        try:
            if is_rth_ts_utc(float(t)):
                out.append(float(t))
        except (TypeError, ValueError):
            continue
    return out


def filter_df_to_rth_ts_utc(df: pd.DataFrame) -> pd.DataFrame:
    """Keep rows whose ts_utc is in RTH per DST-aware ET (ignores stored et_hour)."""
    if df.empty or "ts_utc" not in df.columns:
        return df
    ts = pd.to_numeric(df["ts_utc"], errors="coerce")

    def _keep(v: float) -> bool:
        try:
            return bool(is_rth_ts_utc(float(v)))
        except (TypeError, ValueError):
            return False

    mask = ts.apply(lambda v: _keep(v) if pd.notna(v) else False)
    return df.loc[mask].copy()


def head_rth_df_from_ts_utc(df: pd.DataFrame, max_rows: int | None) -> pd.DataFrame:
    """Post-fetch RTH filter via ts_utc, then cap row count (for SQL LIMIT oversample paths)."""
    out = filter_df_to_rth_ts_utc(df)
    if max_rows is not None and int(max_rows) > 0:
        out = out.head(int(max_rows))
    return out


def stamp_et_clock_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Overwrite et_hour/et_minute from ts_utc (DST-safe)."""
    if df.empty or "ts_utc" not in df.columns:
        return df
    out = df.copy()
    ts = pd.to_numeric(out["ts_utc"], errors="coerce")

    def _clock(v: float) -> tuple[int, int]:
        h, m, _ = et_clock_from_ts_utc(float(v))
        return h, m

    clocks = ts.apply(lambda v: _clock(v) if pd.notna(v) else (np.nan, np.nan))
    out["et_hour"] = [c[0] for c in clocks]
    out["et_minute"] = [c[1] for c in clocks]
    return out


def et_hour_minute_arrays_from_ts_utc(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Model time-of-day features from ts_utc only (never trust stored et_hour on old rows)."""
    n = len(df)
    hrs = np.full(n, np.nan, dtype=float)
    mns = np.full(n, np.nan, dtype=float)
    if "ts_utc" not in df.columns:
        return hrs, mns
    ts = pd.to_numeric(df["ts_utc"], errors="coerce")
    for i, v in enumerate(ts):
        if pd.isna(v):
            continue
        h, m, _ = et_clock_from_ts_utc(float(v))
        hrs[i], mns[i] = float(h), float(m)
    return hrs, mns


def market_session_from_ts_utc(ts_utc: float) -> str:
    from db import market_session

    h, m, _ = et_clock_from_ts_utc(ts_utc)
    return market_session(h, m)


def row_market_session_from_ts_utc(row: Any) -> str:
    """Session label for sqlite3.Row / dict with ts_utc."""
    try:
        return market_session_from_ts_utc(float(row["ts_utc"]))
    except (TypeError, ValueError, KeyError):
        ms = row.get("market_session") if isinstance(row, dict) else None
        if ms is None and hasattr(row, "keys") and "market_session" in row.keys():
            ms = row["market_session"]
        return str(ms or "").strip().lower() or "unknown"

def training_base_where_clause(
    label_column: str | None = None,
    *,
    include_ticker: bool = False,
) -> str:
    """SQL WHERE without RTH on stored et_hour (RTH applied post-fetch via ts_utc)."""
    from ml_horizon import DEFAULT_TRAINING_LABEL_COLUMN

    col = (label_column if label_column is not None else DEFAULT_TRAINING_LABEL_COLUMN).strip()
    parts = ["timeframe = ?"]
    if include_ticker:
        parts.append("ticker = ?")
    parts.append(training_label_where_clause(col))
    parts.append(f"({weekday_where_clause()})")
    return " AND ".join(parts)


def training_label_where_clause(label_column: str | None = None) -> str:
    """
    SQL fragment for ML training row eligibility for a single label column (Issue 14).

    Each horizon is independent: use the matching outcome_{slug} IS NOT NULL for that
    horizon's training rows. Do not require outcome_filled or other horizons — those rows
    are excluded incorrectly when longer labels are still pending.
    """
    from horizon_outcomes import (
        OUTCOME_DIR_HORIZON_MINUTES,
        OUTCOME_HORIZON_MINUTES,
        OUTCOME_MOVE_HORIZON_MINUTES,
        THRESHOLD_MOVE_HORIZON_MINUTES,
        VALID_DIR_HORIZON_MINUTES,
    )
    from ml_horizon import DEFAULT_TRAINING_LABEL_COLUMN

    col = (label_column if label_column is not None else DEFAULT_TRAINING_LABEL_COLUMN).strip()
    _allowed = (
        set(OUTCOME_HORIZON_MINUTES)
        | set(OUTCOME_DIR_HORIZON_MINUTES)
        | set(OUTCOME_MOVE_HORIZON_MINUTES)
        | set(VALID_DIR_HORIZON_MINUTES)
        | set(THRESHOLD_MOVE_HORIZON_MINUTES)
    )
    if col not in _allowed:
        raise ValueError(
            f"training_label_where_clause: unknown label {label_column!r}; "
            f"expected one of {sorted(_allowed)}"
        )
    return f"{col} IS NOT NULL"


def outcome_where_clause() -> str:
    """
    Legacy alias: canonical 1m-ahead (XGB/LSTM/Transformer) training filter.

    Issue 14: no longer couples to outcome_filled (which means “all bar-spec
    horizons backfilled” in db.fill_outcomes, not “eligible for 1c training”).
    """
    from ml_horizon import DEFAULT_TRAINING_LABEL_COLUMN

    return training_label_where_clause(DEFAULT_TRAINING_LABEL_COLUMN)

def weekday_where_clause() -> str:
    """SQL fragment: weekdays only (Mon=1 through Fri=5 in SQLite %w; 0=Sun, 6=Sat)"""
    return "CAST(strftime('%w', datetime(ts_utc, 'unixepoch')) AS INTEGER) BETWEEN 1 AND 5"

# ── Training sample weighting: EQUAL / UNIFORM ONLY — canonical, no toggle (O-55) ──
# Operator decision 2026-05-27: every training row counts equally across the full history.
# There is intentionally NO recency / time-decay weighting in training and NO runtime switch
# (env var or mode arg) to enable it. Equal weighting is the entire policy.
TRAIN_SAMPLE_WEIGHT_MODE = "equal"  # recorded in checkpoint meta for audit; not configurable


def equal_sample_weights(n: int):
    """Uniform per-row training weights (all ones) — the only training weighting (O-55)."""
    import numpy as np

    return np.ones(int(max(0, n)), dtype=np.float64)


# ------------------------------------------------------------------------------
# Workstream B3 — temporal inner holdout for each base trainer
# ------------------------------------------------------------------------------
INNER_VAL_TAIL_FRACTION: float = 0.15
INNER_VAL_MIN_ROWS: int = 20
INNER_VAL_MIN_TRAIN_ROWS: int = 100


def time_ordered_tail_split(
    n: int,
    *,
    val_fraction: float = INNER_VAL_TAIL_FRACTION,
    min_val: int = INNER_VAL_MIN_ROWS,
    min_train: int = INNER_VAL_MIN_TRAIN_ROWS,
) -> tuple[int, int]:
    """Index boundary for a chronological inner holdout (Workstream B3).

    The caller's rows MUST already be time-ordered ascending (XGB ``df`` is
    ``ORDER BY ts_utc``; LSTM/Transformer arrays are built day-by-day). Returns
    ``(train_end, n_val)`` where train rows are ``[0:train_end)`` (earlier) and the
    val tail is the LAST ``n_val`` rows (most recent) ``[train_end:n)``.

    Returns ``(n, 0)`` — NO holdout — when there aren't enough rows for a meaningful,
    honest split (``n_val < min_val`` or ``train rows < min_train``). The caller then
    trains on all rows and MUST report the metric as in-sample (not an honest val), and
    such a thin ticker is already blocked from promotion by the A1/B1 gates.
    """
    n = int(n)
    if n <= 0:
        return 0, 0
    n_val = int(round(n * float(val_fraction)))
    if n_val < int(min_val) or (n - n_val) < int(min_train):
        return n, 0
    return n - n_val, n_val


def holdout_class_metrics(
    y_true,
    y_pred,
    n_classes: int,
    class_names: list[str] | None = None,
) -> dict[str, Any]:
    """Degeneracy diagnostics for a classifier's (held-out) predictions (Workstream B3+).

    The honest top-line accuracy can hide a majority-class collapse: a model that always
    predicts ``flat`` scores the flat base rate (e.g. 0.62 on a 62%-flat tail) while having
    balanced_accuracy ~ 1/n_classes (chance) and zero recall on the minority directions.
    This helper makes that visible so the per-class signal can be reported and an all-flat
    base can be blocked from promotion regardless of top-line accuracy.

    Returns a dict with:
      - ``balanced_accuracy``: mean per-class recall over classes PRESENT in ``y_true``
        (the sklearn convention); ``None`` when ``y_true`` is empty.
      - ``per_class_recall``: ``{class_name: recall}`` for every class index 0..n_classes-1
        (recall ``None`` for a class with no support in ``y_true``).
      - ``predicted_class_names``: sorted list of distinct class names the model emitted.
      - ``n_predicted_classes``: count of distinct predicted classes.
      - ``single_class_collapse``: True when the model emitted exactly one class across all
        rows (the all-flat / majority-collapse failure mode).
    """
    import numpy as _np

    nc = int(n_classes)
    names = list(class_names) if class_names is not None else [str(i) for i in range(nc)]
    yt = _np.asarray(y_true).astype(int).ravel()
    yp = _np.asarray(y_pred).astype(int).ravel()

    per_class_recall: dict[str, float | None] = {}
    recalls_present: list[float] = []
    for c in range(nc):
        support = int((yt == c).sum())
        cname = names[c] if c < len(names) else str(c)
        if support == 0:
            per_class_recall[cname] = None
            continue
        tp = int(((yt == c) & (yp == c)).sum())
        rec = float(tp) / float(support)
        per_class_recall[cname] = round(rec, 4)
        recalls_present.append(rec)

    balanced_accuracy = (
        round(float(_np.mean(recalls_present)), 4) if recalls_present else None
    )
    pred_classes = sorted({int(v) for v in yp.tolist()})
    pred_class_names = [names[c] if c < len(names) else str(c) for c in pred_classes]
    return {
        "balanced_accuracy": balanced_accuracy,
        "per_class_recall": per_class_recall,
        "predicted_class_names": pred_class_names,
        "n_predicted_classes": len(pred_classes),
        "single_class_collapse": len(pred_classes) <= 1,
    }


# ------------------------------------------------------------------------------
# m5_* additive context (1m normalized base + as-of structure columns)
# ------------------------------------------------------------------------------
# Additive m5_* columns are merged from canonical timeframe='1m' snapshot rows only
# (as-of backward). Native timeframe='5m' snapshot rows are never used as the source.
# ------------------------------------------------------------------------------

def _db_default_path() -> str:
    """Matches db.DB_PATH (ED_CONSOLE_DB or data/ed_console.db)."""
    from db import DB_PATH

    return str(DB_PATH)


# Columns copied from canonical 1m snapshot rows only (merged as m5_*).
M5_SOURCE_TIMEFRAME_COL = "m5_source_timeframe"
M5_SOURCE_TIMEFRAME_1M_ASOF = "1m_asof"

M5_ADDITIVE_SOURCE_COLS: tuple[str, ...] = (
    "zone_since_bars_5m",
    "net_gamma",
    "net_delta",
    "charm_net",
    "iv_level",
    "put_call_oi_ratio",
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
    "candle_body_pts",
    "candle_range_pts",
    "spy_chg_pct",
    "qqq_chg_pct",
    "iwm_chg_pct",
)


def fetch_m5_additive_dict(
    ticker: str,
    ts_utc: float,
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    Latest canonical 1m snapshot row at or before ts_utc; keys are m5_<col>.
    Returns {} if no 1m row exists — never reads native timeframe='5m' snapshots.
    """
    path = db_path or _db_default_path()
    t = str(ticker or "").upper().strip()
    if not t:
        return {}

    from timeframe_config import CANONICAL_TIMEFRAME

    cols_sql = ", ".join(M5_ADDITIVE_SOURCE_COLS)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            sql_select_snapshots_columns(cols_sql)
            + "\n            WHERE ticker = ? AND timeframe = ? AND ts_utc <= ?\n            ORDER BY ts_utc DESC\n            LIMIT 1\n            ",
            (t, CANONICAL_TIMEFRAME, float(ts_utc)),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return {}
    d = dict(row)
    out = {f"m5_{k}": d[k] for k in d}
    out[M5_SOURCE_TIMEFRAME_COL] = M5_SOURCE_TIMEFRAME_1M_ASOF
    return out


def fetch_prior_net_gamma(
    ticker: str,
    ts_utc: float,
    db_path: str | None = None,
) -> float | None:
    """
    net_gamma from the immediately prior normalized training row (same ticker, ts_utc strictly less).
    Matches training ``groupby(ticker).diff()`` on chronologically ordered snapshots_1m_normalized rows.
    """
    path = db_path or _db_default_path()
    t = str(ticker or "").upper().strip()
    if not t:
        return None

    from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M

    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            f"SELECT net_gamma FROM {SNAPSHOT_TABLE_1M} "
            "WHERE ticker = ? AND timeframe = ? AND ts_utc < ? "
            "ORDER BY ts_utc DESC LIMIT 1",
            (t, CANONICAL_TIMEFRAME, float(ts_utc)),
        ).fetchone()
    finally:
        conn.close()
    if not row or row[0] is None:
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def attach_net_gamma_prev_column(df: pd.DataFrame) -> pd.DataFrame:
    """Add net_gamma_prev per (ticker, ts_utc) for ΔGEX train/serve formula parity."""
    if df is None or len(df) == 0 or "net_gamma" not in df.columns:
        return df
    if "ticker" not in df.columns or "ts_utc" not in df.columns:
        return df
    out = df.copy()
    order = out.sort_values(["ticker", "ts_utc"]).index
    ng = pd.to_numeric(out["net_gamma"], errors="coerce")
    prev = ng.loc[order].groupby(out.loc[order, "ticker"]).shift(1)
    out["net_gamma_prev"] = prev.reindex(out.index).to_numpy(dtype=float)
    return out


def attach_net_gamma_prev_for_dgex(
    snapshot: dict,
    db_path: str | None = None,
) -> dict:
    """Attach net_gamma_prev for ΔGEX (1-bar diff parity with training load_data path)."""
    out = dict(snapshot)
    ts = out.get("ts_utc")
    tk = out.get("ticker")
    if ts is not None and tk:
        prev_ng = fetch_prior_net_gamma(str(tk), float(ts), db_path)
        if prev_ng is not None:
            out["net_gamma_prev"] = prev_ng
    return out


def snapshot_with_m5_additive(snapshot: dict, db_path: str | None = None) -> dict:
    """Deprecated alias — m5_* strip (v7). Only attaches net_gamma_prev for ΔGEX parity."""
    return attach_net_gamma_prev_for_dgex(dict(snapshot), db_path)


def attach_5m_additive_context(
    df: pd.DataFrame,
    db_path: str | None = None,
) -> pd.DataFrame:
    """
    For each training row (1m normalized), merge as-of backward from canonical 1m
    `snapshots` rows only. If a ticker has no 1m history, m5_* stay NaN — no 5m fallback.
    """
    if df is None or len(df) == 0:
        return df
    if "ticker" not in df.columns or "ts_utc" not in df.columns:
        return df

    path = db_path or _db_default_path()
    tickers = sorted({str(x).upper().strip() for x in df["ticker"].dropna().unique()})
    if not tickers:
        return df

    from timeframe_config import CANONICAL_TIMEFRAME

    sel = ", ".join(["ticker", "ts_utc"] + list(M5_ADDITIVE_SOURCE_COLS))
    conn = sqlite3.connect(path)
    try:
        frames: list[pd.DataFrame] = []
        for t in tickers:
            chunk = pd.read_sql_query(
                sql_select_snapshots_columns(sel)
                + " WHERE ticker = ? AND timeframe = ? ORDER BY ts_utc ASC",
                conn,
                params=[t, CANONICAL_TIMEFRAME],
            )
            if not chunk.empty:
                frames.append(chunk)
        m5 = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    finally:
        conn.close()
    if m5.empty:
        return df

    rename = {c: f"m5_{c}" for c in M5_ADDITIVE_SOURCE_COLS}
    m5 = m5.rename(columns=rename)
    m5 = m5.drop_duplicates(subset=["ticker", "ts_utc"], keep="last")

    # pandas merge_asof validates the *on* column alone with Index(ts_utc).is_monotonic_increasing
    # on the *entire* frame *before* applying `by=` grouping (see _AsOfMerge._get_join_indexers).
    # Sorting by (ticker, ts_utc) breaks global ts monotonicity when multiple tickers exist
    # (common for `right` built from per-ticker SQL chunks). Required order: ts_utc ascending
    # globally, then ticker for deterministic ties; preserve original row order via _asof_row_order.
    work = df.copy()
    work["_asof_row_order"] = np.arange(len(work), dtype=np.int64)
    work["ticker"] = work["ticker"].map(
        lambda x: str(x).upper().strip() if pd.notna(x) and str(x).strip() else x
    )
    work["ts_utc"] = pd.to_numeric(work["ts_utc"], errors="coerce").astype("float64")
    if work["ts_utc"].isna().any():
        n_bad = int(work["ts_utc"].isna().sum())
        raise ValueError(
            f"attach_5m_additive_context: {n_bad} training row(s) have null ts_utc after coercion; "
            "merge_asof cannot proceed"
        )

    m5_keys = m5.copy()
    m5_keys["ticker"] = m5_keys["ticker"].map(
        lambda x: str(x).upper().strip() if pd.notna(x) and str(x).strip() else x
    )
    m5_keys["ts_utc"] = pd.to_numeric(m5_keys["ts_utc"], errors="coerce").astype("float64")
    m5_keys = m5_keys.loc[m5_keys["ts_utc"].notna()].copy()
    if m5_keys.empty:
        return df

    asof_sort = ["ts_utc", "ticker"]
    left_s = work.sort_values(
        [*asof_sort, "_asof_row_order"], kind="mergesort"
    ).reset_index(drop=True)
    m5_keys = m5_keys.sort_values(asof_sort, kind="mergesort").reset_index(drop=True)

    for side, frame in ("left", left_s), ("right", m5_keys):
        ts = frame["ts_utc"]
        if not pd.api.types.is_numeric_dtype(ts):
            raise ValueError(
                f"attach_5m_additive_context: {side} ts_utc must be numeric, got {ts.dtype}"
            )
        if ts.isna().any():
            raise ValueError(f"attach_5m_additive_context: {side} has null ts_utc after merge prep")
        if not bool(pd.Index(ts).is_monotonic_increasing):
            raise ValueError(
                f"attach_5m_additive_context: {side} ts_utc is not globally monotonic_increasing "
                f"after sort {asof_sort!r} (required by pandas merge_asof before `by=` grouping)"
            )

    m5_keys[M5_SOURCE_TIMEFRAME_COL] = M5_SOURCE_TIMEFRAME_1M_ASOF

    out = pd.merge_asof(
        left_s,
        m5_keys,
        on="ts_utc",
        by="ticker",
        direction="backward",
    )
    out = (
        out.sort_values("_asof_row_order", kind="mergesort")
        .drop(columns=["_asof_row_order"])
        .reset_index(drop=True)
    )
    # Rows without a matching 1m as-of snapshot keep NaN m5_*; do not stamp proxy timeframe.
    if M5_SOURCE_TIMEFRAME_COL in out.columns:
        m5_proxy_cols = [f"m5_{c}" for c in M5_ADDITIVE_SOURCE_COLS]
        has_proxy = out[m5_proxy_cols].notna().any(axis=1) if m5_proxy_cols else False
        out.loc[~has_proxy, M5_SOURCE_TIMEFRAME_COL] = None
    return out
