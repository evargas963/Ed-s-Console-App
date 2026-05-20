#!/usr/bin/env python3
"""
Recompute signal_layer_v1 at each calibration row's decision_ts from price_bars_1m
(bar_end_ts_utc <= decision_ts) and merge into raw_bundle_json.

Same contract as live compute_signals (features.signal_layer_v1.compute_signal_layer_v1_for_calibration).

Usage:
  python -m calibration.backfill_signal_layer_v1_bundle --db data/ed_console.db
  python -m calibration.backfill_signal_layer_v1_bundle --db data/ed_console.db --dry-run
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from calibration.canonical_enforcement import (
    CalibrationCanonicalViolationError,
    enforce_calibration_decision_log_only_1m,
)
from calibration.json_utils import dumps_compact
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from calibration.schema import ensure_calibration_schema
from calibration.trust import TRUSTED_PREDICATE_SQL

try:
    from db import EdDB, configure_sqlite_connection
except Exception:

    def configure_sqlite_connection(conn, **kwargs):
        pass


def backfill(
    db_path: Path,
    *,
    dry_run: bool = False,
    force: bool = False,
    allow_noncanonical: bool = False,
) -> dict[str, Any]:
    from features.signal_layer_v1 import compute_signal_layer_v1_for_calibration, meta_n_bars_int

    if not db_path.is_file():
        return {"error": "db_not_found", "path": str(db_path)}

    db = EdDB(db_path, allow_noncanonical=allow_noncanonical)
    conn = sqlite3.connect(str(db_path), timeout=120.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    enforce_calibration_decision_log_only_1m(conn)

    rows = conn.execute(
        f"""
        SELECT id, ticker, decision_ts_utc, raw_bundle_json
        FROM calibration_decision_log
        WHERE ({TRUSTED_PREDICATE_SQL})
        ORDER BY id
        """
    ).fetchall()

    updated = 0
    skipped_nonempty = 0
    errors: list[dict[str, Any]] = []

    for r in rows:
        rid = int(r["id"])
        raw = r["raw_bundle_json"]
        bundle: dict[str, Any] = {}
        if raw:
            try:
                bundle = json.loads(raw)
            except json.JSONDecodeError as e:
                errors.append({"id": rid, "error": f"json_decode:{e}"})
                continue

        if not force and bundle.get("signal_layer_v1") and isinstance(bundle["signal_layer_v1"], dict):
            nb = meta_n_bars_int(bundle["signal_layer_v1"])
            if nb > 0:
                skipped_nonempty += 1
                continue

        try:
            layer = compute_signal_layer_v1_for_calibration(
                db, str(r["ticker"]), float(r["decision_ts_utc"]), None
            )
        except Exception as e:
            errors.append({"id": rid, "error": str(e)})
            continue

        bundle["signal_layer_v1"] = layer
        new_json = dumps_compact(bundle)
        if not dry_run:
            conn.execute(
                "UPDATE calibration_decision_log SET raw_bundle_json = ? WHERE id = ?",
                (new_json, rid),
            )
        updated += 1

    if not dry_run:
        conn.commit()
    conn.close()

    return {
        "db": str(db_path),
        "dry_run": dry_run,
        "force": force,
        "rows_total": len(rows),
        "updated": updated,
        "skipped_nonempty": skipped_nonempty,
        "errors": errors,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing non-empty signal_layer_v1 entries.",
    )
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(
        args,
        tool_name="calibration.backfill_signal_layer_v1_bundle",
        write_capable=True,
    )
    try:
        out = backfill(
            args.db,
            dry_run=args.dry_run,
            force=args.force,
            allow_noncanonical=args.allow_noncanonical_db,
        )
    except CalibrationCanonicalViolationError as e:
        print(f"CANONICAL_ENFORCEMENT_FAIL: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 1 if out.get("errors") else 0


if __name__ == "__main__":
    sys.exit(main())
