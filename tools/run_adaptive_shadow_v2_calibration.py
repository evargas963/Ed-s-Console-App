#!/usr/bin/env python3
"""
CLI: run Adaptive Shadow v2 weight calibration (shadow only) and write JSON report.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adaptive_shadow_v2_calibration import DEFAULT_ANCHORS_JSON, emit_calibration_json

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import DB_PATH, EdDB


def main() -> None:
    ap = argparse.ArgumentParser(description="Adaptive Shadow v2 calibration bundle (no production changes).")
    ap.add_argument("--db", type=Path, default=DB_PATH, help="Path to ed_console.sqlite")
    ap.add_argument(
        "--anchors-json",
        type=Path,
        default=DEFAULT_ANCHORS_JSON,
        help="survivorship_multi_anchor_20.json (or compatible)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "verification" / "adaptive_shadow_v2_calibration.json",
    )
    ap.add_argument("--n-similar", type=int, default=500)
    ap.add_argument("--pool-cap", type=int, default=8000)
    ap.add_argument("--no-ablation", action="store_true", help="Skip Tier 3 zero-one-out ablation (faster).")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="tools.run_adaptive_shadow_v2_calibration", write_capable=False)
    if not args.db.is_file():
        print("DB not found:", args.db, file=sys.stderr)
        sys.exit(1)
    if not args.anchors_json.is_file():
        print("Anchors JSON not found:", args.anchors_json, file=sys.stderr)
        sys.exit(1)
    db = EdDB(
        args.db,
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
    )
    emit_calibration_json(
        db,
        args.out,
        anchors_path=args.anchors_json,
        n_similar=args.n_similar,
        structural_pool_cap=args.pool_cap,
        include_feature_ablation=not args.no_ablation,
    )
    print("Wrote", args.out)


if __name__ == "__main__":
    main()
