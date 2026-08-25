"""RC-478 data-truth resolution: a single-unit `mc_sigma_annualized` column.

WHAT WAS MEASURED (2026-08-25, production DB): the stored `mc_sigma_value` column mixes
three unit eras in one column — 2,315 `blend` rows (annualized), 52,556 post-2026-07-08
`garch` rows (per-1-minute-bar, convertible x sqrt(minutes/yr) ~= 313.5), and 133,528
pre-cutover `garch` rows (`legacy_unverified` — mixed intra-era cadence, ~30x spread,
NOT convertible per-row). A direct reader of the raw column gets numbers ~310x apart that
mean different things. `monte_carlo.mc_sigma_unit_for_row` already classifies each row's
era from (ts_utc, mc_vol_source), and no live path reads the historical column — the
liability is latent but real.

THE RESOLUTION (non-destructive by design). This adds ONE derived column,
`mc_sigma_annualized`, holding the value in a SINGLE unit for every row:
  * blend / annualized era -> copied unchanged,
  * per_bar_1m era         -> multiplied by the measured conversion factor,
  * legacy_unverified era  -> NULL (honest absence: the value cannot be made comparable).
The raw `mc_sigma_value` column is left UNTOUCHED as a frozen provenance archive. Because
the backfill always derives from the untouched raw column, it is IDEMPOTENT — re-running
recomputes the same values, so no migration marker is needed. It is reversible: drop the
column. Validation (measured): the per_bar_1m median 0.00100 x 313.5 = 0.3135 lands on the
already-annualized blend median 0.2856, confirming the two eras become unit-consistent.

HONEST LIMIT: `legacy_unverified` rows carry no recoverable single-unit value, so they are
NULL in the derived column — the information was lost at write time, not here.

Run (console DOWN, so there is no WAL write contention):
    python tools/mc_sigma_normalize_history_v1.py --db <path>            # dry-run report
    python tools/mc_sigma_normalize_history_v1.py --db <path> --apply    # write the column
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from monte_carlo import (  # noqa: E402
    ANNUALIZED_HOURS,
    BAR_MINUTES,
    mc_sigma_unit_for_row,
)

#: per_bar_1m sigma x this = annualized sigma. Same cadence convention as the MC/GARCH
#: blend (compute_realized_vol / annualize_at_cadence): sqrt(minutes per trading year).
CONVERSION_FACTOR = math.sqrt(ANNUALIZED_HOURS * 60.0 / BAR_MINUTES)

DERIVED_COLUMN = "mc_sigma_annualized"


def _has_column(con: sqlite3.Connection, table: str, column: str) -> bool:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def annualized_for_row(ts_utc, mc_vol_source, mc_sigma_value):
    """The single-unit value for one row, or None when it cannot be made comparable.

    One authority for the era: `mc_sigma_unit_for_row`. No SQL re-encoding of the era
    boundaries (that would be a second classifier that could drift from the first)."""
    if mc_sigma_value is None:
        return None
    era = mc_sigma_unit_for_row(ts_utc, mc_vol_source)
    if era == "annualized":
        return float(mc_sigma_value)
    if era == "per_bar_1m":
        return float(mc_sigma_value) * CONVERSION_FACTOR
    return None  # legacy_unverified: unconvertible -> honest absence


def normalize(db_path: str, *, apply: bool = False) -> dict:
    """Backfill `mc_sigma_annualized`. Returns a counts report. Never partially applies:
    the writes run in ONE transaction. Idempotent (derives from the frozen raw column)."""
    con = sqlite3.connect(db_path, timeout=60.0)
    try:
        con.execute("PRAGMA busy_timeout=60000")
        counts = {"annualized": 0, "per_bar_1m_converted": 0, "legacy_nulled": 0, "raw_null": 0}
        updates: list[tuple] = []
        cur = con.execute(
            "SELECT rowid, ts_utc, mc_vol_source, mc_sigma_value FROM snapshots "
            "WHERE mc_sigma_value IS NOT NULL"
        )
        for rowid, ts_utc, mc_vol_source, mc_sigma_value in cur:
            era = mc_sigma_unit_for_row(ts_utc, mc_vol_source)
            derived = annualized_for_row(ts_utc, mc_vol_source, mc_sigma_value)
            if era == "annualized":
                counts["annualized"] += 1
            elif era == "per_bar_1m":
                counts["per_bar_1m_converted"] += 1
            else:
                counts["legacy_nulled"] += 1
            updates.append((derived, rowid))
        counts["total_non_null_raw"] = len(updates)
        if not apply:
            counts["mode"] = "dry_run"
            return counts
        if not _has_column(con, "snapshots", DERIVED_COLUMN):
            con.execute(f"ALTER TABLE snapshots ADD COLUMN {DERIVED_COLUMN} REAL")
        con.executemany(
            f"UPDATE snapshots SET {DERIVED_COLUMN}=? WHERE rowid=?", updates
        )
        con.commit()
        counts["mode"] = "applied"
        return counts
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RC-478: backfill single-unit mc_sigma_annualized")
    ap.add_argument("--db", required=True, help="path to ed_console.db")
    ap.add_argument("--apply", action="store_true", help="write the column (default: dry-run)")
    args = ap.parse_args(argv)
    report = normalize(args.db, apply=args.apply)
    print(f"RC-478 mc_sigma_annualized ({report.get('mode')}): "
          f"factor={CONVERSION_FACTOR:.4f}")
    for k in ("total_non_null_raw", "annualized", "per_bar_1m_converted", "legacy_nulled"):
        print(f"  {k}: {report.get(k)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
