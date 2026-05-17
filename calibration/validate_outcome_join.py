#!/usr/bin/env python3
"""
Analyze outcome join safety: ambiguity, verification of attached outcomes vs snapshots.

  python -m calibration.validate_outcome_join --db data/ed_console.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from calibration.backfill_outcomes import resolve_snapshot_for_backfill
from calibration.canonical_enforcement import (
    CalibrationCanonicalViolationError,
    enforce_calibration_decision_log_only_1m,
)
from calibration.paths import DEFAULT_DB
from calibration.schema import ensure_calibration_schema
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.trust import CALIBRATION_TRUST_LEGACY, CALIBRATION_TRUST_TRUSTED

try:
    from db import configure_sqlite_connection
except Exception:

    def configure_sqlite_connection(conn, **kwargs):
        pass

from db import get_snapshot_sql

_OUTCOME_COLS = (
    "outcome_1c",
    "outcome_5c",
    "outcome_15c",
    "outcome_60c",
    "outcome_1c_pts",
    "outcome_5c_pts",
    "outcome_15c_pts",
    "outcome_60c_pts",
)


def _fclose(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    try:
        if a is None or b is None:
            return False
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return str(a) == str(b)


def _outcome_field_equal(calib_val: Any, snap_val: Any, *, numeric: bool) -> bool:
    """Strict None vs empty-string — do not conflate missing with recorded empty label."""
    if numeric:
        return _fclose(calib_val, snap_val)
    if calib_val is None and snap_val is None:
        return True
    if calib_val is None or snap_val is None:
        return False
    return str(calib_val) == str(snap_val)


def analyze(db_path: Path, *, trusted_only: bool = True) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    enforce_calibration_decision_log_only_1m(conn)

    out: dict[str, Any] = {
        "study_trusted_only": trusted_only,
        "calibration_row_count": 0,
        "calibration_trusted_row_count": 0,
        "calibration_legacy_row_count": 0,
        "rows_with_outcomes": 0,
        "rows_pending_outcomes": 0,
        "ambiguous_exact_ts_duplicate_snapshots": 0,
        "ambiguous_examples": [],
        "verification_pass": 0,
        "verification_fail": 0,
        "verification_fail_examples": [],
        "manual_sample": [],
    }

    out["calibration_row_count"] = int(
        conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    )
    out["calibration_trusted_row_count"] = int(
        conn.execute(
            "SELECT COUNT(*) FROM calibration_decision_log WHERE calibration_trust = ?",
            (CALIBRATION_TRUST_TRUSTED,),
        ).fetchone()[0]
    )
    out["calibration_legacy_row_count"] = int(
        conn.execute(
            "SELECT COUNT(*) FROM calibration_decision_log WHERE calibration_trust = ?",
            (CALIBRATION_TRUST_LEGACY,),
        ).fetchone()[0]
    )
    tc = "calibration_trust = 'trusted'" if trusted_only else "1=1"
    cc = "c.calibration_trust = 'trusted'" if trusted_only else "1=1"
    out["rows_with_outcomes"] = int(
        conn.execute(
            f"SELECT COUNT(*) FROM calibration_decision_log WHERE outcome_5c IS NOT NULL AND ({tc})"
        ).fetchone()[0]
    )
    out["rows_pending_outcomes"] = int(
        conn.execute(
            f"SELECT COUNT(*) FROM calibration_decision_log WHERE outcome_5c IS NULL AND ({tc})"
        ).fetchone()[0]
    )

    # A) More than one snapshots row at same (ticker, ts_utc) for trusted calibration keys
    dup_key = (
        "calibration/validate_outcome_join.py:89"
        if trusted_only
        else "calibration/validate_outcome_join.py:89_include_legacy"
    )
    dup_rows = conn.execute(get_snapshot_sql(dup_key)).fetchall()
    amb = [dict(r) for r in dup_rows if int(r["n"]) > 1]
    out["ambiguous_exact_ts_duplicate_snapshots"] = len(amb)
    out["ambiguous_examples"] = amb[:20]

    # B) Verify attached rows: outcome columns match snapshot at join key (trusted-only by default)
    joined = conn.execute(
        f"""
        SELECT c.id, c.ticker, c.decision_ts_utc, c.matched_snapshot_ts_utc, c.outcome_join_method,
               c.outcome_1c, c.outcome_5c, c.outcome_15c, c.outcome_60c,
               c.outcome_1c_pts, c.outcome_5c_pts, c.outcome_15c_pts, c.outcome_60c_pts
        FROM calibration_decision_log c
        WHERE c.outcome_5c IS NOT NULL AND ({cc})
        ORDER BY c.id
        """
    ).fetchall()

    for r in joined:
        key_ts = r["matched_snapshot_ts_utc"]
        if key_ts is None:
            key_ts = r["decision_ts_utc"]
        key_ts = float(key_ts)
        snap = conn.execute(
            get_snapshot_sql("calibration/validate_outcome_join.py:118"),
            (r["ticker"], key_ts),
        ).fetchall()
        if len(snap) != 1:
            out["verification_fail"] += 1
            out["verification_fail_examples"].append(
                {
                    "id": r["id"],
                    "reason": "snapshot_missing_or_duplicate",
                    "ticker": r["ticker"],
                    "key_ts_utc": key_ts,
                    "n_snap_rows": len(snap),
                }
            )
            continue
        s0 = snap[0]
        ok = True
        for col in _OUTCOME_COLS:
            cv = r[col]
            sv = s0[col]
            if not _outcome_field_equal(cv, sv, numeric=col.endswith("_pts")):
                ok = False
                break
        if ok:
            out["verification_pass"] += 1
        else:
            out["verification_fail"] += 1
            out["verification_fail_examples"].append(
                {
                    "id": r["id"],
                    "reason": "outcome_mismatch_vs_snapshot",
                    "ticker": r["ticker"],
                    "key_ts_utc": key_ts,
                }
            )

    # C) Manual sample: random 20 rows with outcomes that passed verification (or first 20)
    sample_src = conn.execute(
        f"""
        SELECT c.id, c.ticker, c.decision_ts_utc, c.matched_snapshot_ts_utc,
               c.outcome_1c, c.outcome_5c, c.outcome_15c, c.outcome_60c,
               c.outcome_join_method
        FROM calibration_decision_log c
        WHERE c.outcome_5c IS NOT NULL AND ({cc})
        ORDER BY RANDOM() LIMIT 20
        """
    ).fetchall()
    for r in sample_src:
        kt = r["matched_snapshot_ts_utc"]
        if kt is None:
            kt = r["decision_ts_utc"]
        s = conn.execute(
            get_snapshot_sql("calibration/validate_outcome_join.py:181"),
            (r["ticker"], float(kt)),
        ).fetchone()
        horizons_ok = True
        if s:
            for hc in ("outcome_1c", "outcome_5c", "outcome_15c", "outcome_60c"):
                cv, sv = r[hc], s[hc]
                if not _outcome_field_equal(cv, sv, numeric=False):
                    horizons_ok = False
                    break
        else:
            horizons_ok = False
        out["manual_sample"].append(
            {
                "calib_id": r["id"],
                "ticker": r["ticker"],
                "decision_ts_utc": r["decision_ts_utc"],
                "matched_snapshot_ts_utc": r["matched_snapshot_ts_utc"],
                "join_method": r["outcome_join_method"],
                "snapshot_ts_utc": float(s["ts_utc"]) if s else None,
                "outcome_1c_calib": r["outcome_1c"],
                "outcome_1c_snap": s["outcome_1c"] if s else None,
                "outcome_5c_calib": r["outcome_5c"],
                "outcome_5c_snap": s["outcome_5c"] if s else None,
                "outcome_15c_calib": r["outcome_15c"],
                "outcome_15c_snap": s["outcome_15c"] if s else None,
                "outcome_60c_calib": r["outcome_60c"],
                "outcome_60c_snap": s["outcome_60c"] if s else None,
                "snapshot_row_found": s is not None,
                "all_horizons_match_snapshot_row": horizons_ok,
            }
        )

    # D) Pending rows: classify why still unmatched (exact + optional tol=5 preview)
    pending_rows = conn.execute(
        f"""
        SELECT id, ticker, decision_ts_utc FROM calibration_decision_log
        WHERE outcome_5c IS NULL AND ({tc}) ORDER BY id
        """
    ).fetchall()
    exact_pending: dict[str, int] = {}
    tol5_preview: dict[str, int] = {}
    for pr in pending_rows:
        _, reason, _ = resolve_snapshot_for_backfill(
            conn, pr["ticker"], float(pr["decision_ts_utc"]), 0.0
        )
        exact_pending[reason] = exact_pending.get(reason, 0) + 1
        _, reason5, _ = resolve_snapshot_for_backfill(
            conn, pr["ticker"], float(pr["decision_ts_utc"]), 5.0
        )
        tol5_preview[reason5] = tol5_preview.get(reason5, 0) + 1

    conn.close()

    out["pending_count"] = len(pending_rows)
    out["pending_reasons_exact_tol0"] = exact_pending
    out["pending_reasons_if_tol5_hypothetical"] = tol5_preview

    out["binary_pass"] = (
        out["ambiguous_exact_ts_duplicate_snapshots"] == 0
        and out["verification_fail"] == 0
        and out["rows_with_outcomes"] == out["verification_pass"]
    )
    # Production-scope gate: trusted rows must have outcomes attached (no vacuous pass on 0 rows).
    out["binary_pass_strict_production"] = bool(
        out["binary_pass"]
        and (not trusted_only or int(out.get("rows_pending_outcomes") or 0) == 0)
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--include-legacy",
        action="store_true",
        help="Verify/count legacy rows too (default: trusted-only study scope).",
    )
    ap.add_argument(
        "--strict-production",
        action="store_true",
        help="Exit non-zero unless trusted rows have no pending outcomes (full join proof).",
    )
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    if not args.db.is_file():
        print(json.dumps({"error": "db not found"}))
        return 1
    require_canonical_db_target(
        args,
        tool_name="calibration.validate_outcome_join",
        write_capable=False,
    )
    try:
        data = analyze(args.db, trusted_only=not args.include_legacy)
    except CalibrationCanonicalViolationError as e:
        print(json.dumps({"error": str(e), "binary_pass": False}))
        return 2
    print(json.dumps(data, indent=2))
    if args.strict_production:
        return 0 if data.get("binary_pass_strict_production") else 3
    return 0 if data.get("binary_pass") else 2


if __name__ == "__main__":
    sys.exit(main())
