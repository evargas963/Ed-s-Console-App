#!/usr/bin/env python3
"""Earnings calendar collector -> world_earnings (free Nasdaq endpoint).

Unblocks: card #1 single-name scrub, card #4 single-name arm (external audit
requirement 2026-07-22: earnings days masquerade as exhaustion but reprice on
fundamentals). World-data lock: gap named -> source found -> ingested.

Source (fetch-verified at first run): https://api.nasdaq.com/api/calendar/earnings
?date=YYYY-MM-DD -> {"data":{"rows":[{"symbol":...}]}} — browser UA required.
Idempotent per date: on a successful fetch, DELETE that date's rows then INSERT
the current payload (so retracted symbols do not linger). Fetch errors leave
the prior day untouched.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "ed_console.db"
URL = "https://api.nasdaq.com/api/calendar/earnings?date={d}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      " (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
SCHEMA = """
CREATE TABLE IF NOT EXISTS world_earnings (
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    time_hint TEXT,
    fetched_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (date, symbol)
);
"""


def fetch_day(d: str) -> list[tuple[str, str, str]]:
    req = urllib.request.Request(URL.format(d=d), headers={"User-Agent": UA,
                                                           "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    rows = ((payload.get("data") or {}).get("rows")) or []
    out = []
    for r in rows:
        sym = str(r.get("symbol") or "").strip().upper()
        if sym:
            out.append((d, sym, str(r.get("time") or "")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2026-03-01")
    ap.add_argument("--end", default=date.today().isoformat())
    a = ap.parse_args()
    con = sqlite3.connect(str(DB), timeout=60)
    con.executescript(SCHEMA)
    d0, d1 = date.fromisoformat(a.start), date.fromisoformat(a.end)
    total, days_ok, days_err = 0, 0, []
    d = d0
    while d <= d1:
        if d.weekday() < 5:
            try:
                day_s = d.isoformat()
                rows = fetch_day(day_s)
                con.execute("DELETE FROM world_earnings WHERE date=?", (day_s,))
                con.executemany(
                    "INSERT INTO world_earnings(date, symbol, time_hint)"
                    " VALUES (?,?,?)", rows)
                con.commit()
                total += len(rows)
                days_ok += 1
            except Exception as exc:  # noqa: BLE001 — per-day isolation; summarized below
                days_err.append(f"{d}:{type(exc).__name__}")
            time.sleep(0.4)          # polite pacing on a free endpoint
        d += timedelta(days=1)
    n = con.execute("SELECT COUNT(*) FROM world_earnings").fetchone()[0]
    con.close()
    print(json.dumps({"days_ok": days_ok, "rows_ingested": total,
                      "table_total": n, "errors": days_err[:10],
                      "n_errors": len(days_err)}, indent=2))
    return 1 if days_err and not days_ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
