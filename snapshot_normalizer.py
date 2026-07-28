"""
snapshot_normalizer.py — Production Normalization of Sub-Minute Snapshots to 1m Sampled Rows
=============================================================================================

Semantics (DO NOT call these native exchange 1m candles unless proven):
- Input: `snapshots` rows — prefer timeframe='1m' (current live path); if none exist for
  a ticker, fall back to legacy timeframe='5m' sub-minute rows.
- Output: `snapshots_1m_normalized` — one row per ticker per minute; derived by bucketing
  `int(ts_utc // 60)` and taking last row in bucket (carries option_chain_json / replay_context_json).

What is REAL vs DERIVED:
- REAL: Price OHLC from actual snapshots; timestamps; state fields copied from last snapshot.
- DERIVED: The 1m bar construct itself — open/high/low/close are computed by aggregation
  over sub-minute snapshots. NOT native exchange 1m candles.

Transformation rules:
- Group by: (ticker, minute_bucket) where minute_bucket = int(ts_utc // 60)
- open: first snapshot's candle_open (or spot if missing)
- high: max(candle_high) over bucket; fallback max(spot) if all null
- low: min(candle_low) over bucket; fallback min(spot) if all null
- close: last snapshot's candle_close or spot
- volume: last snapshot's candle_volume (accumulated bar volume)
- timestamp: last snapshot's ts_utc, ts_et (bar close)
- All state-derived fields (zone, net_gamma, vwap_side, etc.): from last snapshot
- Outcomes (outcome_1c, outcome_5c, outcome_15c, outcome_60c): from last snapshot
  in the minute bucket (Issue 16: snapshots_1m_normalized columns must stay aligned with
  `snapshots` so INSERT succeeds; after `fill_outcomes` backfill, run materialize to refresh).

Usage:
  python snapshot_normalizer.py              # materialize + validate
  python snapshot_normalizer.py --validate   # validate only
  from snapshot_normalizer import materialize_normalized_table, load_normalized_rows
"""

from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from db import DB_PATH, get_snapshot_sql
from timeframe_config import CANONICAL_TIMEFRAME
from math_snapshot_derive import derive_vwap_side
import logging

log = logging.getLogger(__name__)


# Legacy label for raw sub-minute rows (historical DBs only; live now writes CANONICAL_TIMEFRAME)
SUBMINUTE_SOURCE_TIMEFRAME = "5m"

# Canonical output timeframe
NORMALIZED_TIMEFRAME = "1m"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        from db import configure_sqlite_connection

        configure_sqlite_connection(conn)
    except ImportError:
        conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _minute_bucket(ts_utc: float) -> int:
    """Unix minute bucket for grouping: int(ts_utc // 60)."""
    return int(ts_utc // 60)


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def resample_to_1m(
    rows: list[dict[str, Any]],
    ticker: str,
    *,
    normalized_from_subminute: int = 1,
) -> list[dict[str, Any]]:
    """
    Resample sub-minute snapshot rows into one normalized 1m row per minute bucket.

    Args:
        rows: List of row dicts (from sqlite3.Row or similar), ordered by ts_utc ASC.
        ticker: Ticker symbol (must match rows).

    Returns:
        List of normalized row dicts, one per (ticker, minute_bucket), ordered by ts_utc ASC.
    """
    if not rows:
        return []

    # Group by minute bucket
    buckets: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        tb = _safe_float(r.get("ts_utc"))
        if tb is None:
            continue
        bucket = _minute_bucket(tb)
        buckets[bucket].append(dict(r))

    # Sort each bucket by ts_utc (input should already be ordered)
    for bucket_rows in buckets.values():
        bucket_rows.sort(
            key=lambda x: (
                _safe_float(x.get("ts_utc"))
                if _safe_float(x.get("ts_utc")) is not None
                else float("inf")
            )
        )

    out: list[dict] = []
    for bucket in sorted(buckets.keys()):
        group = buckets[bucket]
        first = group[0]
        last = group[-1]

        # OHLC rules — fail closed when no usable open (no silent o=0.0 spot fallback).
        missing_fields: list[str] = []
        o = _safe_float(first.get("candle_open"))
        if o is None:
            missing_fields.append("candle_open")
            o = _safe_float(first.get("spot"))
            if o is not None:
                missing_fields.append("candle_open_spot_proxy")
        if o is None or o == 0:
            continue

        highs = [_safe_float(r.get("candle_high")) for r in group]
        lows = [_safe_float(r.get("candle_low")) for r in group]
        highs_clean = [x for x in highs if x is not None]
        lows_clean = [x for x in lows if x is not None]
        if not highs_clean or not lows_clean:
            continue
        h = max(highs_clean)
        l = min(lows_clean)
        if h == 0 or l == 0:
            continue

        c = _safe_float(last.get("candle_close"))
        if c is None:
            missing_fields.append("candle_close")
            c = _safe_float(last.get("spot"))
            if c is not None:
                missing_fields.append("candle_close_spot_proxy")
        if c is None:
            continue
        if c == 0:
            continue

        vol = _safe_float(last.get("candle_volume"))
        if vol is None:
            missing_fields.append("candle_volume")

        # Build normalized row: base on last snapshot, overwrite OHLC and timeframe
        norm = dict(last)
        norm["candle_open"] = o
        norm["candle_high"] = h
        norm["candle_low"] = l
        norm["candle_close"] = c
        norm["candle_volume"] = vol
        norm["timeframe"] = NORMALIZED_TIMEFRAME
        norm["normalized_from_subminute"] = normalized_from_subminute
        norm["source"] = "snapshot_synthetic"
        norm["synthetic"] = True
        norm["missing_fields"] = missing_fields
        spot_val = _safe_float(last.get("spot"))
        if spot_val is None:
            spot_val = c
            missing_fields.append("spot_close_proxy")
        norm["spot"] = spot_val
        # Recompute OHLC-derived fields from normalized OHLC
        norm["candle_body_pts"] = abs(c - o) if (c is not None and o is not None) else None
        norm["candle_range_pts"] = (h - l) if (h is not None and l is not None) else None
        norm["candle_direction"] = (
            "up" if c > o else ("down" if c < o else "flat")
        ) if (c is not None and o is not None) else None
        vs = derive_vwap_side(norm.get("spot"), norm.get("vwap"))
        if vs:
            norm["vwap_side"] = vs
        out.append(norm)

    return out


def fetch_raw_subminute_rows(
    conn: sqlite3.Connection, ticker: str
) -> list[dict[str, Any]]:
    """Fetch legacy sub-minute snapshot rows for a ticker (timeframe='5m')."""
    rows = conn.execute(
        get_snapshot_sql("snapshot_normalizer.py:176"),
        (ticker, SUBMINUTE_SOURCE_TIMEFRAME),
    ).fetchall()
    return [dict(r) for r in rows]


def resolve_source_timeframe(conn: sqlite3.Connection, ticker: str) -> str:
    """
    Prefer native canonical 1m rows when present (current live path).
    Fall back to legacy '5m' sub-minute rows for older databases.
    """
    row = conn.execute(
        get_snapshot_sql("snapshot_normalizer.py:192"),
        (ticker, CANONICAL_TIMEFRAME),
    ).fetchone()
    n = int(row[0] if row is not None else 0)
    if n > 0:
        return CANONICAL_TIMEFRAME
    return SUBMINUTE_SOURCE_TIMEFRAME


def fetch_rows_for_normalization(
    conn: sqlite3.Connection, ticker: str, since_ts_utc: Optional[float] = None
) -> tuple[list[dict[str, Any]], str]:
    """Load source rows and the timeframe they came from.

    since_ts_utc: when set, only rows with ts_utc >= since_ts_utc are read
    (index-served via idx_snap_ticker_tf_ts) — the incremental live path must not
    re-read the full multi-GB snapshots history every cycle.
    """
    tf = resolve_source_timeframe(conn, ticker)
    if since_ts_utc is not None:
        rows = conn.execute(
            get_snapshot_sql("snapshot_normalizer.py:fetch_window"),
            (ticker, tf, float(since_ts_utc)),
        ).fetchall()
    else:
        rows = conn.execute(
            get_snapshot_sql("snapshot_normalizer.py:210"),
            (ticker, tf),
        ).fetchall()
    return [dict(r) for r in rows], tf


def normalize_ticker(db_path: Path, ticker: str) -> list[dict[str, Any]]:
    """Fetch source rows for ticker and resample to 1m. Returns list of normalized dicts."""
    conn = _connect(db_path)
    try:
        raw, source_tf = fetch_rows_for_normalization(conn, ticker)
        norm_flag = 1 if source_tf == SUBMINUTE_SOURCE_TIMEFRAME else 0
        return resample_to_1m(raw, ticker, normalized_from_subminute=norm_flag)
    finally:
        conn.close()


def _normalized_table_exists(conn: sqlite3.Connection) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='snapshots_1m_normalized'"
    )
    return cur.fetchone() is not None


def _get_snapshots_columns(conn: sqlite3.Connection) -> list[str]:
    """Return snapshots column names excluding snapshot_id (let DB assign)."""
    cur = conn.execute("PRAGMA table_info(snapshots)")
    return [row[1] for row in cur.fetchall() if row[1] != "snapshot_id"]


def _table_column_set(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _normalized_insert_columns(conn: sqlite3.Connection) -> list[str]:
    """
    INSERT column list: snapshot_id plus every snapshots column that exists on
    snapshots_1m_normalized (same names), preserving snapshots column order, then
    normalized_from_subminute if the table has it and it was not already listed.
    Prevents drift when snapshots gains a column before normalized is migrated.
    """
    snap_cols = _get_snapshots_columns(conn)
    norm = _table_column_set(conn, "snapshots_1m_normalized")
    # RC-6 (v17 measured the bleed: 1,097 -> 1,373 rows / 239MB in one day): the culled blob
    # columns still EXIST on the normalized table until the supervised 2026-08-09 drop, and
    # this intersection kept refilling them on every pass. They are excluded by NAME so the
    # bleed stops NOW; the raw `snapshots` table keeps the one authoritative chain copy, and
    # the 08-09 migration removes the lingering columns + rows.
    _RC6_CULLED = ("option_chain_json", "replay_context_json")
    body = [c for c in snap_cols if c in norm and c not in _RC6_CULLED]
    if "normalized_from_subminute" in norm and "normalized_from_subminute" not in body:
        body.append("normalized_from_subminute")
    return ["snapshot_id"] + body


def materialize_normalized_table(
    db_path: Path = DB_PATH,
    tickers: Optional[list[str]] = None,
    clear_first: bool = True,
    incremental_lookback_sec: Optional[float] = None,
) -> dict[str, Any]:
    """
    Resample sub-minute snapshots into snapshots_1m_normalized table.
    Idempotent: per-ticker atomic replace by default (not a global table wipe).

    Args:
        db_path: Path to the database.
        tickers: List of tickers to process. None = all tickers with 1m or legacy 5m rows.
        clear_first: If True, delete existing rows before insert (default).
        incremental_lookback_sec: When set, a ticker that already has normalized rows is
            refreshed INCREMENTALLY: only raw rows newer than
            (MAX(normalized ts_utc) - lookback) are re-read, and only that window's
            normalized rows are replaced, in one bounded transaction. The lookback must
            cover the outcome backfill horizon (60c ≈ 60 minutes) so fill_outcomes
            updates land in normalized rows exactly as under a full rebuild; rows older
            than the window have final outcomes and never change on the live path.
            The full clear+rebuild against the multi-GB snapshots table held the SQLite
            write lock for 5-22s EVERY cycle (2026-07-03 live incident) — the live
            observability path must never do that. Training's full-history rebuild
            (ensure_normalized_training_table) is unchanged. A ticker with no
            normalized rows falls back to the full path automatically.

    Returns:
        Dict with counts: raw_rows, normalized_rows, by_ticker, errors.
    """
    conn = _connect(db_path)
    result: dict[str, Any] = {
        "raw_rows": 0,
        "normalized_rows": 0,
        "by_ticker": {},
        "errors": [],
    }

    try:
        if not _normalized_table_exists(conn):
            result["errors"].append(
                "Table snapshots_1m_normalized does not exist. Run db schema init first."
            )
            return result

        # Per-ticker ATOMIC replace (2026-06-03): the prior "DELETE all + commit up front" left
        # EVERY ticker empty during the multi-ticker repopulate. A concurrent reader (the pre-train
        # gate) or the live server's ongoing ingestion during that window saw the live ticker (SPY)
        # as 0 rows -> sequence gate NO-GO -> retrain aborted, even though SPY normalizes fine. We
        # no longer wipe the whole table; instead each ticker's rows are replaced inside one
        # transaction per ticker (DELETE ticker + INSERT ticker + single commit, below), so no
        # ticker is ever globally absent. clear_first now means "replace each processed ticker".

        if tickers is None:
            rows = conn.execute(
                get_snapshot_sql("snapshot_normalizer.py:301"),
                (CANONICAL_TIMEFRAME, SUBMINUTE_SOURCE_TIMEFRAME),
            ).fetchall()
            tickers = [r[0] for r in rows]

        # Column list: intersection of snapshots vs normalized (by name, snapshots order).
        insert_cols = _normalized_insert_columns(conn)

        placeholders = ", ".join("?" for _ in insert_cols)
        col_str = ", ".join(insert_cols)
        insert_sql = f"INSERT INTO snapshots_1m_normalized ({col_str}) VALUES ({placeholders})"

        # Table is never globally wiped now, so snapshot_id always continues from the current max
        # (ids stay unique across per-ticker replaces; contiguity is not required for this derived table).
        for ticker in tickers:
            row_mx = conn.execute(
                "SELECT COALESCE(MAX(snapshot_id), 0) FROM snapshots_1m_normalized"
            ).fetchone()
            next_sid = int(row_mx[0] if row_mx and row_mx[0] is not None else 0)

            # Incremental window: replace only [cutoff, now) when the ticker already has
            # normalized rows; a ticker with none takes the full path (first materialize).
            window_cutoff: Optional[float] = None
            if incremental_lookback_sec is not None:
                row_ts = conn.execute(
                    "SELECT MAX(ts_utc) FROM snapshots_1m_normalized WHERE ticker = ?",
                    (ticker,),
                ).fetchone()
                last_norm_ts = _safe_float(row_ts[0] if row_ts else None)
                if last_norm_ts is not None:
                    # Align to a minute boundary so the boundary bucket is replaced whole.
                    window_cutoff = float(
                        _minute_bucket(last_norm_ts - float(incremental_lookback_sec)) * 60
                    )

            raw, source_tf = fetch_rows_for_normalization(
                conn, ticker, since_ts_utc=window_cutoff
            )
            result["raw_rows"] += len(raw)
            if not raw:
                continue
            norm_flag = 1 if source_tf == SUBMINUTE_SOURCE_TIMEFRAME else 0
            normalized = resample_to_1m(
                raw, ticker, normalized_from_subminute=norm_flag
            )
            result["by_ticker"][ticker] = {
                "raw": len(raw),
                "normalized": len(normalized),
                "source_timeframe": source_tf,
                "mode": "incremental" if window_cutoff is not None else "full",
            }
            result["normalized_rows"] += len(normalized)
            batch = []
            for nr in normalized:
                nr.pop("snapshot_id", None)
                next_sid += 1
                nr["snapshot_id"] = next_sid
                batch.append([nr.get(c) for c in insert_cols])
            if batch:
                # Atomic per-ticker replace: DELETE this ticker's old rows + INSERT the new ones in
                # ONE transaction (single commit), so a concurrent reader sees either the old SPY
                # rows or the new ones — never an empty SPY. Per-ticker commit still bounds WAL
                # growth and releases the write lock between tickers (DB-WRITE-PATH-FIXES intent).
                # Incremental mode deletes only the refresh window — the bounded transaction that
                # keeps the live write lock hold in milliseconds instead of seconds.
                if window_cutoff is not None:
                    conn.execute(
                        "DELETE FROM snapshots_1m_normalized WHERE ticker = ? AND ts_utc >= ?",
                        (ticker, window_cutoff),
                    )
                elif clear_first:
                    conn.execute("DELETE FROM snapshots_1m_normalized WHERE ticker = ?", (ticker,))
                conn.executemany(insert_sql, batch)
                conn.commit()
    except Exception as e:
        result["errors"].append(str(e))
        conn.rollback()
    finally:
        conn.close()

    return result


def clear_normalized_table(db_path: Path = DB_PATH) -> int:
    """Clear snapshots_1m_normalized. Returns number of rows deleted."""
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM snapshots_1m_normalized")
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def validate_normalization(db_path: Path = DB_PATH) -> dict[str, Any]:
    """
    Run validation checks on normalized data.

    Returns:
        Dict with: ok, row_count, tickers, checks (one_per_minute, ordering, no_duplicates),
        per_ticker_counts, errors.
    """
    conn = _connect(db_path)
    out: dict[str, Any] = {
        "ok": True,
        "row_count": 0,
        "tickers": [],
        "checks": {},
        "per_ticker_counts": {},
        "errors": [],
    }

    try:
        if not _normalized_table_exists(conn):
            out["ok"] = False
            out["errors"].append("Table snapshots_1m_normalized does not exist")
            return out

        cnt = conn.execute("SELECT COUNT(*) FROM snapshots_1m_normalized").fetchone()[0]
        out["row_count"] = cnt

        tickers = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT ticker FROM snapshots_1m_normalized ORDER BY ticker"
            ).fetchall()
        ]
        out["tickers"] = tickers

        # Per-ticker counts
        for ticker in tickers:
            c = conn.execute(
                "SELECT COUNT(*) FROM snapshots_1m_normalized WHERE ticker = ?",
                (ticker,),
            ).fetchone()[0]
            out["per_ticker_counts"][ticker] = c

        # Check 1: one row per ticker per minute (no duplicate minute buckets)
        dup = conn.execute(
            """
            SELECT ticker, minute_bucket, cnt
            FROM (
                SELECT ticker, CAST(ts_utc/60 AS INTEGER) AS minute_bucket, COUNT(*) as cnt
                FROM snapshots_1m_normalized
                GROUP BY ticker, minute_bucket
                HAVING cnt > 1
            )
            """
        ).fetchall()
        out["checks"]["one_per_minute"] = len(dup) == 0
        if dup:
            out["errors"].append(f"Duplicate minute buckets: {len(dup)}")
            out["ok"] = False

        # Check 2: timestamp ordering per ticker
        ordering_ok = True
        for ticker in tickers:
            rows = conn.execute(
                """
                SELECT ts_utc FROM snapshots_1m_normalized
                WHERE ticker = ?
                ORDER BY ts_utc ASC
                """,
                (ticker,),
            ).fetchall()
            prev = -1.0
            for r in rows:
                t = r[0]
                if t < prev:
                    ordering_ok = False
                    break
                prev = t
        out["checks"]["ordering"] = ordering_ok
        if not ordering_ok:
            out["errors"].append("Timestamp ordering violated for at least one ticker")
            out["ok"] = False

        # Check 3: no duplicate outputs (already covered by one_per_minute)
        out["checks"]["no_duplicates"] = out["checks"]["one_per_minute"]

    except Exception as e:
        out["ok"] = False
        out["errors"].append(str(e))
    finally:
        conn.close()

    return out


def load_normalized_rows(
    db_path: Path = DB_PATH,
    ticker: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Load normalized rows for training/analysis. Same interface as reading from snapshots.

    Returns rows with timeframe='1m' from snapshots_1m_normalized.
    """
    conn = _connect(db_path)
    try:
        if ticker:
            rows = conn.execute(
                "SELECT * FROM snapshots_1m_normalized WHERE ticker = ? ORDER BY ts_utc ASC",
                (ticker,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM snapshots_1m_normalized ORDER BY ticker, ts_utc ASC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def run_full_materialization(db_path: Path = DB_PATH) -> dict[str, Any]:
    """Materialize (clears first) and validate. Returns combined result dict."""
    mat = materialize_normalized_table(db_path, clear_first=True)
    if not mat.get("errors"):
        try:
            from normalized_training_sync import persist_training_fingerprint_after_materialize

            persist_training_fingerprint_after_materialize(db_path)
        except Exception as e:
            print(
                "WARNING: could not persist normalized_training fingerprint after materialize:",
                e,
                file=sys.stderr,
            )
    val = validate_normalization(db_path)
    return {
        "materialize": mat,
        "validate": val,
        "success": mat.get("errors") == [] and val.get("ok", False),
    }


def backfill_price_action_columns(
    db_path: Path = DB_PATH,
    tickers: Optional[list[str]] = None,
    *,
    max_bars: int = 80,
    only_null: bool = True,
) -> dict[str, Any]:
    """
    Backfill the persisted price-action cone (pa_* columns) on historical
    snapshots from price_bars_1m, leak-free (bars with bar_end <= ts_utc only).

    Updates BOTH snapshots and snapshots_1m_normalized in place so retraining
    can use the new columns without waiting for live accumulation. max_bars=80
    covers the longest window (60m return lookback + ATR seeding).
    """
    import bisect
    from types import SimpleNamespace

    from features.signal_layer_v1 import (
        SNAPSHOT_PRICE_ACTION_COLUMNS,
        compute_price_action_snapshot_columns,
    )

    pa_cols = [c for c, _ in SNAPSHOT_PRICE_ACTION_COLUMNS]
    set_sql = ", ".join(f"{c} = ?" for c in pa_cols)
    out: dict[str, Any] = {"by_ticker": {}, "rows_updated": 0, "rows_skipped_no_bars": 0}
    conn = _connect(db_path)
    try:
        if tickers is None:
            tickers = [
                str(r[0])
                for r in conn.execute("SELECT DISTINCT ticker FROM snapshots ORDER BY ticker")
            ]
        for tkr in tickers:
            bars = [
                {
                    "bar_start_ts_utc": float(r[0]),
                    "bar_end_ts_utc": float(r[1]),
                    "open": r[2], "high": r[3], "low": r[4], "close": r[5], "volume": r[6],
                }
                for r in conn.execute(
                    "SELECT bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume"
                    " FROM price_bars_1m WHERE ticker = ? ORDER BY bar_end_ts_utc ASC",
                    (tkr,),
                )
            ]
            bar_ends = [b["bar_end_ts_utc"] for b in bars]
            null_filter = f" AND {pa_cols[0]} IS NULL" if only_null else ""
            snaps = conn.execute(
                f"SELECT snapshot_id, ts_utc, vwap FROM snapshots WHERE ticker = ?{null_filter}"
                " ORDER BY ts_utc ASC",
                (tkr,),
            ).fetchall()
            updated = skipped = 0
            for snap_id, ts_utc, vwap in snaps:
                hi = bisect.bisect_right(bar_ends, float(ts_utc))
                window = bars[max(0, hi - max_bars) : hi]
                if not window:
                    skipped += 1
                    continue
                vals = compute_price_action_snapshot_columns(
                    window,
                    decision_ts_utc=float(ts_utc),
                    inp=SimpleNamespace(vwap=vwap),
                )
                params = [vals[c] for c in pa_cols]
                conn.execute(
                    f"UPDATE snapshots SET {set_sql} WHERE snapshot_id = ?", [*params, snap_id]
                )
                conn.execute(
                    f"UPDATE snapshots_1m_normalized SET {set_sql}"
                    " WHERE ticker = ? AND ts_utc = ?",
                    [*params, tkr, float(ts_utc)],
                )
                updated += 1
            conn.commit()
            out["by_ticker"][tkr] = {"updated": updated, "skipped_no_bars": skipped}
            out["rows_updated"] += updated
            out["rows_skipped_no_bars"] += skipped
    finally:
        conn.close()
    return out


def _print_ingestion_context(db_path: Path, raw_rows: int, normalized_rows: int) -> None:
    """Clarify why raw_rows is far below snapshot row counts (1m-vs-5m selection)."""
    conn = _connect(db_path)
    try:
        tf_rows = conn.execute(
            get_snapshot_sql("snapshot_normalizer.py:513")
        ).fetchall()
    finally:
        conn.close()
    by_tf = {str(r[0]): int(r[1]) for r in tf_rows}
    total = sum(by_tf.values())
    print("\nContext (expected if this looks 'too small' vs total DB rows):")
    print(f"  Total in snapshots (sum of GROUP BY timeframe, no unscoped COUNT): {total}  by timeframe: {by_tf}")
    print(f"  Fed into normalizer: raw_rows={raw_rows}  →  normalized (1 row/min/ticker)={normalized_rows}")
    print(
        "  Rule: per ticker, if ANY 1m rows exist, ONLY those are used; that ticker's 5m history is skipped."
    )


if __name__ == "__main__":
    # Reconfigure stdout for Windows
    if sys.stdout.encoding and "cp1252" in (sys.stdout.encoding or "").lower():
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception as e:
            log.debug("stdout reconfigure: %s", e, exc_info=True)
    db = Path(DB_PATH)
    if not db.exists():
        print(f"ERROR: Database not found: {db}")
        sys.exit(1)

    validate_only = "--validate" in sys.argv

    if "--backfill-price-action" in sys.argv:
        res = backfill_price_action_columns(db)
        print("Price-action backfill:")
        print("  rows_updated:", res["rows_updated"])
        print("  rows_skipped_no_bars:", res["rows_skipped_no_bars"])
        for t, st in res["by_ticker"].items():
            print(f"  {t}: {st}")
        sys.exit(0)

    if validate_only:
        v = validate_normalization(db)
        print("Validation result:")
        print("  ok:", v["ok"])
        print("  row_count:", v["row_count"])
        print("  tickers:", v["tickers"])
        print("  per_ticker_counts:", v["per_ticker_counts"])
        print("  checks:", v["checks"])
        if v["errors"]:
            print("  errors:", v["errors"])
        sys.exit(0 if v["ok"] else 1)

    r = run_full_materialization(db)
    print("Materialization:")
    print("  raw_rows:", r["materialize"].get("raw_rows"))
    print("  normalized_rows:", r["materialize"].get("normalized_rows"))
    print("  by_ticker:", r["materialize"].get("by_ticker"))
    if r["materialize"].get("errors"):
        print("  errors:", r["materialize"]["errors"])
    _print_ingestion_context(
        db,
        int(r["materialize"].get("raw_rows") or 0),
        int(r["materialize"].get("normalized_rows") or 0),
    )

    print("\nValidation:")
    v = r["validate"]
    print("  ok:", v["ok"])
    print("  checks:", v["checks"])
    if v["errors"]:
        print("  errors:", v["errors"])
    print("\nPer-ticker 1m row counts:", v.get("per_ticker_counts", {}))

    sys.exit(0 if r["success"] else 1)
