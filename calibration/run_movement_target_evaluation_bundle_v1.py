#!/usr/bin/env python3
"""
Run movement-target evaluation chain: Phase 5 → 6 → 6.5 → 6.5 cleanup (new heads).

Optional: refresh thresholds first:
  python tools/select_movement_thresholds_percentile_v1.py --db data/ed_console.db

  python -m calibration.run_movement_target_evaluation_bundle_v1 --db data/ed_console.db
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    ap.add_argument("--allow-noncanonical-db", action="store_true")
    args = ap.parse_args()
    py = sys.executable
    extra = []
    if args.allow_noncanonical_db:
        extra.append("--allow-noncanonical-db")
    steps = [
        [py, "-m", "calibration.movement_target_phase5_discrimination_v1", "--db", str(args.db), *extra],
        [py, "-m", "calibration.movement_target_phase6_edge_v1", "--db", str(args.db), *extra],
        [py, "-m", "calibration.movement_target_phase65_isolation_v1", "--db", str(args.db), *extra],
        [py, "-m", "calibration.movement_target_phase65_cleanup_v1"],
    ]
    for cmd in steps:
        print("RUN:", " ".join(cmd), flush=True)
        r = subprocess.run(cmd, cwd=str(ROOT))
        if r.returncode != 0:
            return int(r.returncode)
    print("OK: wrote data/movement_target_phase5_discrimination_v1.json, data/movement_target_phase6_edge_v1.json, data/phase65_movement_isolation_v1_report.json, data/phase65_movement_cleanup_v1_result.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
