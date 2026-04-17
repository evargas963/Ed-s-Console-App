#!/usr/bin/env python3
"""
Issue 22 — read-only dump of EdDB.logging_universe (audit v2 shape + inspection).

Requires the same DB path as the running server (default: data/ed_console.db).
Does not mutate enrollment.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import DB_PATH, EdDB  # noqa: E402


def main() -> int:
    dbp = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH
    db = EdDB(dbp)
    rows = db.logging_universe_list_rows_audit()
    payload = {
        "db_path": str(dbp.resolve()),
        "schema": "logging_universe_audit_v2",
        "count": len(rows),
        "protected_symbols": db.logging_universe_protected_tickers(),
        "eviction_candidates_fifo_user_persisted": db.logging_universe_eviction_candidates_fifo(),
        "recent_evictions": db.logging_universe_recent_evictions(limit=50),
        "logging_universe_rows": rows,
    }
    json.dump(payload, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
