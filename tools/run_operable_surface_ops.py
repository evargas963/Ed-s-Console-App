#!/usr/bin/env python3
"""Recurring Collect ops: production backfill (tol=29) + operable-surface gate.

Optional one-shot historical repair (tol=59) and quarantine of remaining old
unattached operable rows. Production BACKFILL_JOIN_TOL_SEC stays 29.

Usage:
  python -m tools.run_operable_surface_ops --db data/ed_console.db
  python -m tools.run_operable_surface_ops --db data/ed_console.db --repair59 --quarantine
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.backfill_outcomes import backfill
from calibration.daily_scoreboard import BACKFILL_JOIN_TOL_SEC
from runtime_layout import data_dir, reports_dir  # RC-523: runtime/artifacts roots
from tools.operable_surface_gate import (
    evaluate_operable_surface,
    quarantine_old_unattached,
)

REPORT = reports_dir() / "operable_surface_ops_latest.json"
HISTORICAL_ONE_SHOT_TOL = 59.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Operable surface recurring ops")
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument(
        "--refresh-outcomes",
        action="store_true",
        help="Run refresh_all_governed_bar_anchor_outcomes_v1 before backfill",
    )
    ap.add_argument(
        "--repair59",
        action="store_true",
        help="One-shot historical nearest join at tol=59 after production tol=29",
    )
    ap.add_argument(
        "--quarantine",
        action="store_true",
        help="Quarantine remaining old (>70m) operable unattached rows",
    )
    ap.add_argument("--write-report", action="store_true", default=True)
    args = ap.parse_args(argv)

    try:
        from db import DB_PATH
    except Exception:
        DB_PATH = None  # type: ignore[misc, assignment]
    db_path = args.db or (Path(DB_PATH) if DB_PATH else data_dir() / "ed_console.db")
    if not Path(db_path).is_file():
        print(f"run_operable_surface_ops: missing db {db_path}", file=sys.stderr)
        return 2

    out: dict = {
        "schema": "operable_surface_ops_v1",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "db_path": str(db_path),
        "production_tol_sec": BACKFILL_JOIN_TOL_SEC,
    }

    if args.refresh_outcomes:
        from db import EdDB

        db = EdDB(Path(db_path))
        out["refresh_outcomes"] = db.refresh_all_governed_bar_anchor_outcomes_v1()

    before = evaluate_operable_surface(Path(db_path))
    out["before"] = {
        "verdict": before["verdict"],
        "old_missing_all_ticker": before["counts"]["old_missing_all_ticker"],
        "old_missing_sentinel": before["counts"]["old_missing_sentinel"],
    }

    t0 = time.perf_counter()
    out["backfill_29"] = backfill(Path(db_path), tol_sec=float(BACKFILL_JOIN_TOL_SEC))
    out["backfill_29"]["elapsed_sec"] = round(time.perf_counter() - t0, 3)

    if args.repair59:
        t1 = time.perf_counter()
        out["backfill_59_oneshot"] = backfill(
            Path(db_path), tol_sec=HISTORICAL_ONE_SHOT_TOL
        )
        out["backfill_59_oneshot"]["elapsed_sec"] = round(time.perf_counter() - t1, 3)
        out["backfill_59_oneshot"]["note"] = (
            "one-shot historical repair; production tol remains 29"
        )

    if args.quarantine:
        out["quarantine"] = quarantine_old_unattached(Path(db_path))

    after = evaluate_operable_surface(Path(db_path))
    out["after"] = after
    out["verdict"] = after["verdict"]

    text = json.dumps(out, indent=2, sort_keys=True, default=str)
    print(text)
    if args.write_report:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(text + "\n", encoding="utf-8")
        # Refresh durable gate proof.
        from tools.operable_surface_gate import main as gate_main

        gate_main(["--db", str(db_path), "--write-report"])

    return 0 if after["verdict"] == "OPERABLE_SURFACE_CLEAN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
