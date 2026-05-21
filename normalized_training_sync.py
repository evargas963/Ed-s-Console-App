"""
Issue 16 — coordinated refresh of snapshots_1m_normalized after snapshots/outcomes change.

Training reads snapshots_1m_normalized; live and backfill write outcomes and other columns on
snapshots. This module:

- Computes a cheap aggregate fingerprint over snapshots (1m + legacy 5m rows).
- Persists the last fingerprint successfully materialized in ed_schema_flags.
- Runs materialize_normalized_table only when fingerprint moved (or force=True).
- Serializes materialization with a process-wide lock; debounces live server triggers.

See ensure_normalized_training_table, schedule_debounced_normalized_refresh, and
persist_training_fingerprint_after_materialize.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from db import sql_snapshots_training_fingerprint_select
from horizon_outcomes import OUTCOME_BAR_SPECS, OUTCOME_MOVEMENT_V1_SPECS
from snapshot_normalizer import SUBMINUTE_SOURCE_TIMEFRAME, materialize_normalized_table
from timeframe_config import CANONICAL_TIMEFRAME

_log = logging.getLogger(__name__)

FP_FLAG_KEY = "normalized_training_snapshot_fp_v1"

_materialize_lock = threading.Lock()
_debounce_timer: Optional[threading.Timer] = None
_debounce_lock = threading.Lock()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    r = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return r is not None


def _aggregate_select_exprs(cols: set[str]) -> list[str]:
    parts = ["COUNT(*)", "COALESCE(MAX(snapshot_id), 0)"]
    for odir, opt, _ in OUTCOME_BAR_SPECS:
        if odir in cols:
            parts.append(f"SUM(CASE WHEN {odir} IS NOT NULL THEN 1 ELSE 0 END)")
        if opt in cols:
            parts.append(f"COALESCE(SUM(CAST({opt} AS REAL)), 0.0)")
    for dcol, mcol, vdcol, tmcol, legtcol, _, _slug in OUTCOME_MOVEMENT_V1_SPECS:
        if dcol in cols:
            parts.append(f"SUM(CASE WHEN {dcol} IS NOT NULL THEN 1 ELSE 0 END)")
        if mcol in cols:
            parts.append(f"SUM(CASE WHEN {mcol} IS NOT NULL THEN 1 ELSE 0 END)")
        if vdcol in cols:
            parts.append(f"SUM(CASE WHEN {vdcol} IS NOT NULL THEN 1 ELSE 0 END)")
        if tmcol in cols:
            parts.append(f"COALESCE(SUM(CAST({tmcol} AS REAL)), 0.0)")
        if legtcol in cols:
            parts.append(f"COALESCE(SUM(CAST({legtcol} AS REAL)), 0.0)")
    for c in ("vwap", "spot", "flow_imbalance", "smart_money_score"):
        if c in cols:
            parts.append(f"COALESCE(SUM(CAST({c} AS REAL)), 0.0)")
    if "horizon_outcome_schema_version" in cols:
        parts.append("COALESCE(MAX(CAST(horizon_outcome_schema_version AS INTEGER)), 0)")
    if "outcome_filled" in cols:
        parts.append(
            "SUM(CASE WHEN outcome_filled IS NOT NULL AND CAST(outcome_filled AS INTEGER) != 0 "
            "THEN 1 ELSE 0 END)"
        )
    return parts


def compute_snapshots_training_fingerprint(conn: sqlite3.Connection) -> str:
    """
    Cheap aggregate over raw snapshots that should change when outcomes or training-relevant
    columns change. Covers canonical 1m and legacy 5m sub-minute rows (same inputs as the normalizer).
    """
    if not _table_exists(conn, "snapshots"):
        return "no_snapshots_table"
    cur = conn.execute("PRAGMA table_info(snapshots)")
    cols = {row[1] for row in cur.fetchall()}
    aggs = _aggregate_select_exprs(cols)
    sql = sql_snapshots_training_fingerprint_select(", ".join(aggs))
    rows = conn.execute(
        sql,
        (CANONICAL_TIMEFRAME, SUBMINUTE_SOURCE_TIMEFRAME),
    ).fetchall()
    by_tf = {r[0]: r for r in rows}
    chunks: list[str] = []
    for tf in (CANONICAL_TIMEFRAME, SUBMINUTE_SOURCE_TIMEFRAME):
        r = by_tf.get(tf)
        if r is None:
            chunks.append(tf + ":" + "|".join("0" for _ in aggs))
        else:
            vals = [r[i] for i in range(1, len(r))]
            chunks.append(tf + ":" + "|".join(str(v) for v in vals))
    return "::".join(chunks)


def _get_stored_fp(conn: sqlite3.Connection) -> Optional[str]:
    if not _table_exists(conn, "ed_schema_flags"):
        return None
    row = conn.execute(
        "SELECT flag_value FROM ed_schema_flags WHERE flag_key = ?",
        (FP_FLAG_KEY,),
    ).fetchone()
    return str(row[0]) if row and row[0] is not None else None


def _set_stored_fp(conn: sqlite3.Connection, fp: str) -> None:
    conn.execute(
        """
        INSERT INTO ed_schema_flags (flag_key, flag_value, set_ts_utc)
        VALUES (?, ?, ?)
        ON CONFLICT(flag_key) DO UPDATE SET
            flag_value = excluded.flag_value,
            set_ts_utc = excluded.set_ts_utc
        """,
        (FP_FLAG_KEY, fp, time.time()),
    )


def persist_training_fingerprint_after_materialize(db_path: str | Path) -> dict[str, Any]:
    """Record current snapshots fingerprint after an external successful full materialize (e.g. CLI)."""
    db_path = Path(db_path)
    out: dict[str, Any] = {"ok": False, "fingerprint": None, "error": None}
    if not db_path.exists():
        out["error"] = "db missing"
        return out
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        conn.row_factory = sqlite3.Row
        from db import configure_sqlite_connection

        configure_sqlite_connection(conn)
        if not _table_exists(conn, "ed_schema_flags"):
            out["error"] = "ed_schema_flags missing"
            return out
        fp = compute_snapshots_training_fingerprint(conn)
        _set_stored_fp(conn, fp)
        conn.commit()
        out["ok"] = True
        out["fingerprint"] = fp
        return out
    finally:
        conn.close()


def verify_normalized_freshness(db_path: str | Path) -> dict[str, Any]:
    """Diagnostic: True if stored fingerprint matches current snapshots (normalized assumed in sync)."""
    db_path = Path(db_path)
    out: dict[str, Any] = {"fresh": False, "current_fp": None, "stored_fp": None}
    if not db_path.exists():
        return out
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        conn.row_factory = sqlite3.Row
        from db import configure_sqlite_connection

        configure_sqlite_connection(conn)
        cur = compute_snapshots_training_fingerprint(conn)
        st = _get_stored_fp(conn)
        out["current_fp"] = cur
        out["stored_fp"] = st
        out["fresh"] = st is not None and st == cur
        return out
    finally:
        conn.close()


def ensure_normalized_training_table(
    db_path: str | Path,
    *,
    force: bool = False,
    logger: Optional[logging.Logger] = None,
) -> dict[str, Any]:
    """
    If snapshots fingerprint differs from last successful materialization (or force), rebuild
    snapshots_1m_normalized and persist the new fingerprint. On materialize failure, fingerprint
    is not advanced (retry on next call).
    """
    lg = logger or _log
    db_path = Path(db_path)
    out: dict[str, Any] = {
        "ok": True,
        "skipped": False,
        "materialized": False,
        "fingerprint": None,
        "stored_fingerprint": None,
        "materialize": None,
        "errors": [],
    }
    if not db_path.exists():
        out["ok"] = False
        out["errors"].append("db missing")
        return out

    with _materialize_lock:
        conn = sqlite3.connect(str(db_path), timeout=120.0)
        try:
            conn.row_factory = sqlite3.Row
            from db import configure_sqlite_connection

            configure_sqlite_connection(conn)
            if not _table_exists(conn, "snapshots_1m_normalized"):
                out["ok"] = False
                out["errors"].append("snapshots_1m_normalized missing")
                return out
            cur_fp = compute_snapshots_training_fingerprint(conn)
            stored = _get_stored_fp(conn)
            out["fingerprint"] = cur_fp
            out["stored_fingerprint"] = stored
        finally:
            conn.close()

        if not force and stored is not None and stored == cur_fp:
            out["skipped"] = True
            lg.debug("normalized_training_sync: skip (fingerprint unchanged)")
            return out

        lg.info(
            "normalized_training_sync: materializing snapshots_1m_normalized (force=%s, had_stored=%s)",
            force,
            stored is not None,
        )
        mat = materialize_normalized_table(db_path, tickers=None, clear_first=True)
        out["materialize"] = mat
        if mat.get("errors"):
            out["ok"] = False
            out["errors"].extend(str(e) for e in mat["errors"])
            lg.error("normalized_training_sync: materialize failed: %s", mat["errors"])
            return out

        conn = sqlite3.connect(str(db_path), timeout=120.0)
        try:
            conn.row_factory = sqlite3.Row
            from db import configure_sqlite_connection

            configure_sqlite_connection(conn)
            new_fp = compute_snapshots_training_fingerprint(conn)
            _set_stored_fp(conn, new_fp)
            conn.commit()
            out["fingerprint"] = new_fp
            out["materialized"] = True
        finally:
            conn.close()

        lg.info(
            "normalized_training_sync: done normalized_rows=%s",
            (mat or {}).get("normalized_rows"),
        )
    return out


def schedule_debounced_normalized_refresh(
    db_path: str | Path,
    *,
    delay_s: Optional[float] = None,
    logger: Optional[logging.Logger] = None,
) -> None:
    """
    Coalesce live-path snapshot/outcome writes: after delay since the last schedule, run
    ensure_normalized_training_table(force=False). Training and scheduler call ensure at entry
    so data is fresh even if the timer has not fired yet.
    """
    global _debounce_timer
    lg = logger or _log
    db_path = Path(db_path)
    if delay_s is None:
        delay_s = float(os.environ.get("ED_NORMALIZED_REFRESH_DEBOUNCE_SEC", "120"))

    def _fire() -> None:
        global _debounce_timer
        try:
            ensure_normalized_training_table(db_path, force=False, logger=lg)
        except Exception as e:
            lg.warning("normalized_training_sync: debounced refresh failed: %s", e)
        finally:
            with _debounce_lock:
                _debounce_timer = None

    t = threading.Timer(float(delay_s), _fire)
    t.daemon = True
    with _debounce_lock:
        if _debounce_timer is not None:
            try:
                _debounce_timer.cancel()
            except Exception as e:
                _log.debug("debounce timer cancel: %s", e, exc_info=True)
        _debounce_timer = t
    t.start()
