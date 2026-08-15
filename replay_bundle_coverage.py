"""
Replay bundle coverage — how many snapshot rows can run live-vs-replay validation.

Reports, per SQLite table and ticker:
  rows_total, rows_with_replay_context_json, rows_with_option_chain_json,
  rows_with_full_bundle, replay_coverage_rate, rows_added_since_last_run
  (vs models/replay_bundle_coverage_state.json), estimated_rows_needed_to_reach_minimum,
  first/latest ts for full-bundle rows.

Whitelisted tables: snapshots, snapshots_1m_normalized
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from timeframe_config import CANONICAL_TIMEFRAME

APP_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = APP_DIR / "models" / "replay_bundle_coverage.json"
STATE_PATH = APP_DIR / "models" / "replay_bundle_coverage_state.json"

DEFAULT_MIN_REQUIRED_ROWS = 20

ALLOWED_TABLES = frozenset({"snapshots", "snapshots_1m_normalized"})

# STACK-WIRE-6b FIND-WIRE6-5: single-authority minimum-non-trivial JSON length.
# Used in SQL ``length(<column>) > REPLAY_BUNDLE_MIN_JSON_LENGTH`` predicates that
# distinguish empty/trivial bundles from real captures. Imported by
# realized_contract_eval, live_vs_replay_validation, tools/measure_post_fix_theta_v1.
REPLAY_BUNDLE_MIN_JSON_LENGTH: int = 10

_RC_OK = f"replay_context_json IS NOT NULL AND length(replay_context_json) > {REPLAY_BUNDLE_MIN_JSON_LENGTH}"
_OC_OK = f"option_chain_json IS NOT NULL AND length(option_chain_json) > {REPLAY_BUNDLE_MIN_JSON_LENGTH}"
_FULL = f"({_RC_OK}) AND ({_OC_OK})"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _coverage_for_table(
    conn: sqlite3.Connection,
    table: str,
    *,
    timeframe: Optional[str],
) -> dict[str, Any]:
    if table not in ALLOWED_TABLES:
        raise ValueError(f"table must be one of {sorted(ALLOWED_TABLES)}")
    if not _table_exists(conn, table):
        return {"table": table, "error": "table_missing"}

    tf_clause = "n.timeframe = ?" if timeframe else "1=1"
    base_params: tuple[Any, ...] = (timeframe,) if timeframe else ()

    # RC-6: the bundle blobs live ONLY in `snapshots` now (the byte-identical duplicate in
    # snapshots_1m_normalized was dropped). LEFT JOIN snapshots on the aligned key so coverage
    # is computed against where the bundle actually is; LEFT (not INNER) preserves rows_total =
    # COUNT(*) of the base table so a row with no matching snapshots row reads as bundle-absent
    # rather than being silently excluded. When {table} IS snapshots this is a 1:1 self-join
    # (no duplicate keys). s-qualified predicates are local so the shared _RC_OK/_OC_OK constants
    # (used by base-table readers) stay unchanged.
    _rc_s = f"s.replay_context_json IS NOT NULL AND length(s.replay_context_json) > {REPLAY_BUNDLE_MIN_JSON_LENGTH}"
    _oc_s = f"s.option_chain_json IS NOT NULL AND length(s.option_chain_json) > {REPLAY_BUNDLE_MIN_JSON_LENGTH}"
    _full_s = f"({_rc_s}) AND ({_oc_s})"
    _join = (f"{table} n LEFT JOIN snapshots s "
             "ON s.ticker = n.ticker AND s.timeframe = n.timeframe AND s.ts_utc = n.ts_utc")

    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS rows_total,
            SUM(CASE WHEN {_rc_s} THEN 1 ELSE 0 END) AS n_rc,
            SUM(CASE WHEN {_oc_s} THEN 1 ELSE 0 END) AS n_oc,
            SUM(CASE WHEN {_full_s} THEN 1 ELSE 0 END) AS n_full,
            MIN(CASE WHEN {_full_s} THEN n.ts_utc END) AS first_ts_utc,
            MAX(CASE WHEN {_full_s} THEN n.ts_utc END) AS latest_ts_utc,
            MIN(CASE WHEN {_full_s} THEN n.ts_et END) AS first_ts_et,
            MAX(CASE WHEN {_full_s} THEN n.ts_et END) AS latest_ts_et
        FROM {_join}
        WHERE {tf_clause}
        """,
        base_params,
    ).fetchone()
    assert row is not None

    by_ticker: list[dict[str, Any]] = []
    cur = conn.execute(
        f"""
        SELECT
            n.ticker AS ticker,
            COUNT(*) AS rows_total,
            SUM(CASE WHEN {_rc_s} THEN 1 ELSE 0 END) AS rows_with_replay_context_json,
            SUM(CASE WHEN {_oc_s} THEN 1 ELSE 0 END) AS rows_with_option_chain_json,
            SUM(CASE WHEN {_full_s} THEN 1 ELSE 0 END) AS rows_with_full_bundle,
            MIN(CASE WHEN {_full_s} THEN n.ts_utc END) AS first_ts_utc,
            MAX(CASE WHEN {_full_s} THEN n.ts_utc END) AS latest_ts_utc,
            MIN(CASE WHEN {_full_s} THEN n.ts_et END) AS first_ts_et,
            MAX(CASE WHEN {_full_s} THEN n.ts_et END) AS latest_ts_et
        FROM {_join}
        WHERE {tf_clause}
        GROUP BY n.ticker
        ORDER BY n.ticker
        """,
        base_params,
    )
    for r in cur:
        by_ticker.append(
            {
                "ticker": r["ticker"],
                "rows_total": int(r["rows_total"] or 0),
                "rows_with_replay_context_json": int(r["rows_with_replay_context_json"] or 0),
                "rows_with_option_chain_json": int(r["rows_with_option_chain_json"] or 0),
                "rows_with_full_bundle": int(r["rows_with_full_bundle"] or 0),
                "first_ts_with_full_bundle_utc": r["first_ts_utc"],
                "latest_ts_with_full_bundle_utc": r["latest_ts_utc"],
                "first_ts_with_full_bundle_et": r["first_ts_et"],
                "latest_ts_with_full_bundle_et": r["latest_ts_et"],
            }
        )

    return {
        "table": table,
        "timeframe_filter": timeframe,
        "rows_total": int(row["rows_total"] or 0),
        "rows_with_replay_context_json": int(row["n_rc"] or 0),
        "rows_with_option_chain_json": int(row["n_oc"] or 0),
        "rows_with_full_bundle": int(row["n_full"] or 0),
        "first_ts_with_full_bundle_utc": row["first_ts_utc"],
        "latest_ts_with_full_bundle_utc": row["latest_ts_utc"],
        "first_ts_with_full_bundle_et": row["first_ts_et"],
        "latest_ts_with_full_bundle_et": row["latest_ts_et"],
        "by_ticker": by_ticker,
    }


def _load_coverage_state(state_path: Path) -> dict[str, Any]:
    if not state_path.is_file():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_coverage_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _enrich_with_expansion(
    table_stats: dict[str, Any],
    *,
    min_required_rows: int,
    prev_table: dict[str, Any],
) -> None:
    """Mutate table_stats with replay_coverage_rate, deltas, and shortage estimate."""
    total = int(table_stats.get("rows_total") or 0)
    n_full = int(table_stats.get("rows_with_full_bundle") or 0)
    table_stats["replay_coverage_rate"] = (
        round(n_full / total, 6) if total > 0 else None
    )
    table_stats["estimated_rows_needed_to_reach_minimum"] = max(
        0, min_required_rows - n_full
    )
    prev_full = prev_table.get("rows_with_full_bundle")
    if prev_full is None:
        table_stats["rows_added_since_last_run"] = None
        table_stats["rows_added_since_last_run_note"] = "no_prior_saved_state"
    else:
        table_stats["rows_added_since_last_run"] = n_full - int(prev_full)
        table_stats.pop("rows_added_since_last_run_note", None)

    prev_by_t = prev_table.get("by_ticker") or {}
    for row in table_stats.get("by_ticker") or []:
        tk = row["ticker"]
        rt = int(row.get("rows_total") or 0)
        rf = int(row.get("rows_with_full_bundle") or 0)
        row["replay_coverage_rate"] = round(rf / rt, 6) if rt > 0 else None
        row["estimated_rows_needed_to_reach_minimum"] = max(
            0, min_required_rows - rf
        )
        pt = prev_by_t.get(tk)
        if pt is None:
            row["rows_added_since_last_run"] = None
            row["rows_added_since_last_run_note"] = (
                "first_observation_of_ticker_in_saved_state"
            )
        else:
            row["rows_added_since_last_run"] = rf - int(pt)
            row.pop("rows_added_since_last_run_note", None)


def build_replay_bundle_coverage(
    db_path: str | Path,
    *,
    tables: Optional[list[str]] = None,
    min_required_rows: int = DEFAULT_MIN_REQUIRED_ROWS,
    persist_state: bool = True,
    state_path: Path = STATE_PATH,
) -> dict[str, Any]:
    """
    Overall + per-ticker bundle stats for `snapshots` (canonical 1m only) and
    `snapshots_1m_normalized` (training / validation table).

    When ``persist_state`` is True, saves counts after the run so the next invocation
    can report ``rows_added_since_last_run``. The first run has no prior baseline.
    """
    path = Path(db_path).resolve()
    want = list(tables or ["snapshots", "snapshots_1m_normalized"])

    prev_blob = _load_coverage_state(state_path)
    prev_for_db = prev_blob if prev_blob.get("db_path") == str(path) else {}
    prev_tables = prev_for_db.get("tables") or {}

    out: dict[str, Any] = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "db_path": str(path),
        "min_required_rows": min_required_rows,
        "tables": {},
        "note": (
            "full_bundle = replay_context_json and option_chain_json both present and non-trivial. "
            "If snapshots shows full_bundle > 0 but snapshots_1m_normalized is 0, run "
            "python snapshot_normalizer.py to materialize 1m rows from snapshots."
        ),
        "historical_backfill": {
            "automatic_sql_backfill_available": False,
            "summary": (
                "Rows captured without option_chain_json and replay_context_json cannot be "
                "reconstructed from SQLite alone; those fields are produced at server refresh. "
                "Coverage and live-vs-replay validation therefore accumulate forward (and via "
                "snapshot_normalizer for the training table). No SQL backfill path is implemented here."
            ),
        },
    }
    new_state: dict[str, Any] = {
        "updated_at_utc": out["updated_at_utc"],
        "db_path": str(path),
        "min_required_rows": min_required_rows,
        "tables": {},
    }

    with _connect(path) as conn:
        for tbl in want:
            if tbl not in ALLOWED_TABLES:
                out["tables"][tbl] = {"error": "table_not_allowed"}
                continue
            stats = _coverage_for_table(conn, tbl, timeframe=CANONICAL_TIMEFRAME)
            _enrich_with_expansion(
                stats,
                min_required_rows=min_required_rows,
                prev_table=prev_tables.get(tbl) or {},
            )
            out["tables"][tbl] = stats
            new_state["tables"][tbl] = {
                "rows_with_full_bundle": stats["rows_with_full_bundle"],
                "rows_total": stats["rows_total"],
                "by_ticker": {
                    r["ticker"]: r["rows_with_full_bundle"]
                    for r in stats.get("by_ticker") or []
                },
            }

    if persist_state:
        _save_coverage_state(state_path, new_state)

    return out


def main() -> None:
    from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
    from db import DB_PATH

    ap = argparse.ArgumentParser(description="Replay bundle coverage report")
    ap.add_argument("--db", type=str, default=str(DB_PATH))
    ap.add_argument("--out", type=str, default=str(DEFAULT_OUTPUT))
    ap.add_argument(
        "--min",
        type=int,
        dest="min_required_rows",
        default=DEFAULT_MIN_REQUIRED_ROWS,
        help="Minimum full-bundle rows target (for shortage / coverage estimates)",
    )
    ap.add_argument(
        "--no-persist-state",
        action="store_true",
        help="Do not read or write replay_bundle_coverage_state.json",
    )
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="replay_bundle_coverage", write_capable=False)
    report = build_replay_bundle_coverage(
        args.db,
        min_required_rows=args.min_required_rows,
        persist_state=not args.no_persist_state,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("db_path", "tables")}, indent=2, default=str))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
