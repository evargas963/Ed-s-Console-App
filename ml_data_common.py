"""
ml_data_common.py Shared RTH + Exponential Decay for ML Training
==================================================================
RULE 1 constants and helpers. Used by ml_train, lstm_model, transformer_train,
train_all, ml_scheduler.
"""

from __future__ import annotations

from db import sql_select_snapshots_columns


import sqlite3
from typing import Any

import numpy as np
import pandas as pd

# RTH: 09:30–16:00 ET weekdays
# et_hour * 60 + et_minute: 570 = 9:30, 960 = 16:00 (exclusive)
RTH_START_MINS = 570   # 09:30 ET
RTH_END_MINS   = 960   # 16:00 ET (exclusive; 959 is last valid minute)

def rth_where_clause() -> str:
    """SQL fragment: (et_hour * 60 + et_minute) >= 570 AND (et_hour * 60 + et_minute) < 960"""
    return (
        "(et_hour * 60 + et_minute) >= " + str(RTH_START_MINS) + " "
        "AND (et_hour * 60 + et_minute) < " + str(RTH_END_MINS)
    )

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

def compute_exponential_weights(n: int, decay: float = 2.0) -> list:
    """
    Exponential decay weights: most recent rows get highest weight, oldest get lowest.
    weight[i] = exp(-decay * (1 - (i+0.5)/n))
    So i=0 (oldest) gets ~exp(-decay), i=n-1 (newest) gets ~1.0.
    """
    import numpy as np
    if n <= 0:
        return []
    indices = np.arange(n, dtype=np.float64)
    frac = (indices + 0.5) / n
    w = np.exp(-decay * (1.0 - frac))
    return w.tolist()


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
    return {f"m5_{k}": d[k] for k in d}


def snapshot_with_m5_additive(snapshot: dict, db_path: str | None = None) -> dict:
    """Copy of snapshot plus m5_* keys from latest additive-source row at or before ts_utc."""
    out = dict(snapshot)
    ts = out.get("ts_utc")
    tk = out.get("ticker")
    if ts is not None and tk:
        out.update(fetch_m5_additive_dict(str(tk), float(ts), db_path))
    return out


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
    return out
