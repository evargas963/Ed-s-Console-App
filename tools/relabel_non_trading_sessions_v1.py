#!/usr/bin/env python3
"""RC-178 / RC-191 / RC-283: repair non-trading-day contamination wherever it landed.

Dry-run by default. Pass --execute to write. NEVER deletes a row.

TWO SURFACES, because the class outgrew the incident that named this file:

  snapshots               mislabelled `market_session` -> relabelled 'closed' (RC-178)
  option_chain_accrual    whole rows banked on a closed day -> moved to
  option_chain_morning_full   <table>_quarantine, evidence intact (RC-283)

WHY THE SECOND SURFACE WAS MISSING. This tool was written for RC-178, whose contamination
was in `snapshots`. RC-278 later found the two option-chain WRITERS gating on the clock and
never the calendar, so they banked weekend rows into different tables — and nobody
re-checked this tool against the new location. Cursor's audit measured
`option_chain references: 0` while `option_chain_accrual` held a Sunday row (QQQ,
2026-08-02, minute 919, 212 strikes). A repair tool records the shape of the incident that
prompted it, not the shape of the defect class.

WHY QUARANTINE AND NOT DELETE. The surviving rows are the only evidence of the RC-278
window — how long the writers ran without a calendar and what they banked. Deleting them
destroys the proof and leaves a gap indistinguishable from "we were not collecting".
Relabelling is not available either: an accrual row is not mislabelled, it should not exist
at all. So it moves, whole, with the reason and the sweep timestamp attached.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.time_et import et_date_str_from_ts_utc, is_trading_day_et  # noqa: E402


#: RC-283: tables whose ROWS must not exist on a closed day at all. `snapshots` is not here
#: — a snapshot taken while the market is shut is a real observation wearing the wrong
#: label, so it is relabelled. An accrual row is a banked wide chain for a session that
#: never happened; there is no correct label for it.
OPTION_TABLES: tuple[str, ...] = ("option_chain_accrual", "option_chain_morning_full")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def quarantine_non_trading_option_rows(
    conn: sqlite3.Connection, *, execute: bool, now_utc: float,
) -> dict[str, dict[str, int]]:
    """Move rows banked on a non-trading et_date into `<table>_quarantine`.

    Idempotent: the second run finds nothing because the rows are no longer in the live
    table, and re-running must never duplicate a quarantine record.
    """
    report: dict[str, dict[str, int]] = {}
    for table in OPTION_TABLES:
        if not _table_exists(conn, table):
            report[table] = {"scanned": 0, "non_trading": 0, "moved": 0, "missing_table": 1}
            continue
        rows = conn.execute(f"SELECT rowid, et_date FROM {table}").fetchall()
        victims = [int(r[0]) for r in rows
                   if r[1] and not is_trading_day_et(str(r[1]))]
        report[table] = {"scanned": len(rows), "non_trading": len(victims), "moved": 0}
        if not victims or not execute:
            continue

        q = f"{table}_quarantine"
        # The quarantine mirrors the live schema exactly, plus WHY and WHEN. Building it
        # from the live table means a schema change cannot silently drop a column on the
        # way out — the evidence keeps the same shape as the thing it evidences.
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {q} AS SELECT * FROM {table} WHERE 0")
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({q})").fetchall()}
        if "quarantine_reason" not in cols:
            conn.execute(f"ALTER TABLE {q} ADD COLUMN quarantine_reason TEXT")
        if "quarantined_at_utc" not in cols:
            conn.execute(f"ALTER TABLE {q} ADD COLUMN quarantined_at_utc REAL")

        live_cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        col_list = ", ".join(live_cols)
        marks = ",".join("?" * len(victims))
        conn.execute(
            f"INSERT INTO {q} ({col_list}, quarantine_reason, quarantined_at_utc) "
            f"SELECT {col_list}, 'RC-283 non_trading_day', ? FROM {table} "
            f"WHERE rowid IN ({marks})",
            (now_utc, *victims))
        cur = conn.execute(f"DELETE FROM {table} WHERE rowid IN ({marks})", victims)
        report[table]["moved"] = int(cur.rowcount)
    return report


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

    # RC-283: the option tables are swept in the SAME run, so a leak cannot be repaired on
    # one surface and left standing on the other.
    option_report = quarantine_non_trading_option_rows(
        conn, execute=bool(args.execute), now_utc=time.time())
    print({
        "non_trading_mislabeled": len(victims),
        "by_old_label": dict(by_old),
        "option_tables": option_report,
        "execute": bool(args.execute),
    })
    if args.execute:
        conn.commit()
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
