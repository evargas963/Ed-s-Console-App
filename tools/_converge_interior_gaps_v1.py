#!/usr/bin/env python3
"""Run repair_canonical_1m_interior_gaps_v1 until dry-run inserts == 0 (max iterations)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.repair_canonical_1m_interior_gaps_v1 import run_repair  # noqa: E402
from calibration.paths import DEFAULT_DB  # noqa: E402
from db import EdDB  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--max-iter", type=int, default=60)
    ap.add_argument("--no-refresh", action="store_true")
    args = ap.parse_args()
    dbp = args.db.resolve()
    total = 0
    for i in range(args.max_iter):
        dry = run_repair(dbp, dry_run=True)
        n = int(dry.get("bars_to_insert") or 0)
        print(json.dumps({"iter": i, "dry_run": True, "bars_to_insert": n}))
        if n == 0:
            if not args.no_refresh:
                edb = EdDB(dbp)
                ref = edb.refresh_all_governed_bar_anchor_outcomes_v1()
                print(json.dumps({"refresh_all_governed_bar_anchor_outcomes_v1": ref}))
            print(json.dumps({"converged": True, "total_rows_upserted_session": total}))
            return 0
        w = run_repair(dbp, dry_run=False)
        u = int(w.get("rows_upserted") or 0)
        total += u
        print(json.dumps({"iter": i, "rows_upserted": u}))
    print(json.dumps({"converged": False, "total_rows_upserted_session": total}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
