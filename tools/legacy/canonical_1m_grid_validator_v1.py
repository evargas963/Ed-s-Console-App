#!/usr/bin/env python3
"""
Gate: BAR_ANCHOR_V1 forward bar grid completeness for snapshots in the outcome fill window.

PASS iff:
  - missing_forward_bar_count == 0 (no required forward bar_start_ts missing from price_bars_1m)
  - off_grid_price_bars_1m == 0

Does NOT fail on missing_anchor_* (snapshots before first bar for a ticker — separate history gap class).

Usage:
  python tools/canonical_1m_grid_validator_v1.py --db data/ed_console.db
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.canonical_1m_grid_scan import result_to_dict, scan_db
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate canonical 1m forward grid completeness")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="canonical_1m_grid_validator_v1", write_capable=False)

    r = scan_db(args.db)
    d = result_to_dict(r)
    ok = d["missing_forward_bar_count"] == 0 and d["off_grid_price_bars_1m"] == 0
    d["canonical_1m_grid_gate_pass"] = ok
    d["note"] = (
        "missing_anchor_count reflects snapshots with ts_utc before any price_bars_1m bar_end for that ticker; "
        "not part of the forward-grid defect class."
    )
    print(json.dumps(d, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
