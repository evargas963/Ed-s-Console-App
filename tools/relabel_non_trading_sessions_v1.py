#!/usr/bin/env python3
"""RC-178 / RC-191: relabel non-trading-day snapshot market_session values to 'closed'.

Dry-run by default. Pass --execute to write. Never deletes rows.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from time_et import et_date_str_from_ts_utc, is_trading_day_et  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/ed_console.db")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db, timeout=120.0)
    rows = conn.execute("SELECT rowid, ts_utc, market_session FROM snapshots").fetchall()
    by_old: Counter[str] = Counter()
    victims: list[int] = []
    for rowid, ts, ms in rows:
        d = et_date_str_from_ts_utc(float(ts))
        if is_trading_day_et(d):
            continue
        if str(ms or "").lower() == "closed":
            continue
        by_old[str(ms)] += 1
        victims.append(int(rowid))

    print({
        "non_trading_mislabeled": len(victims),
        "by_old_label": dict(by_old),
        "execute": bool(args.execute),
    })
    if not args.execute or not victims:
        conn.close()
        return 0

    # Batch update via TEMP staging (same pattern as quarantine tool).
    conn.execute("CREATE TEMP TABLE _relabel_rc178 (rowid INTEGER PRIMARY KEY)")
    conn.executemany("INSERT INTO _relabel_rc178(rowid) VALUES (?)", [(r,) for r in victims])
    cur = conn.execute(
        "UPDATE snapshots SET market_session='closed' "
        "WHERE rowid IN (SELECT rowid FROM _relabel_rc178)"
    )
    conn.commit()
    print({"updated": cur.rowcount})
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
