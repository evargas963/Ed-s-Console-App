"""RC-478: the mc_sigma_annualized backfill produces a single-unit series, non-destructively.

WHAT IS PROVEN: the derived column converts the per_bar_1m era by the measured factor,
copies the annualized/blend era unchanged, NULLs the unconvertible legacy_unverified era,
leaves the raw mc_sigma_value column untouched, and is idempotent (it always derives from
the frozen raw column, so re-running recomputes identical values).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from monte_carlo import MC_SIGMA_BAR_CADENCE_CUTOVER_TS, MC_SIGMA_LEGACY_LAST_WRITE_TS
from tools.mc_sigma_normalize_history_v1 import CONVERSION_FACTOR, normalize

CUTOVER = MC_SIGMA_BAR_CADENCE_CUTOVER_TS
LEGACY_LAST = MC_SIGMA_LEGACY_LAST_WRITE_TS


def _db(tmp_path: Path) -> str:
    p = tmp_path / "snap.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE snapshots (ts_utc REAL, mc_vol_source TEXT, mc_sigma_value REAL)")
    rows = [
        (CUTOVER - 1000.0, "blend", 0.30),           # annualized (blend) -> copied
        (LEGACY_LAST + 1000.0, "garch", 0.28),       # annualized (post-legacy garch) -> copied
        ((CUTOVER + LEGACY_LAST) / 2, "garch", 0.001),  # per_bar_1m -> x factor
        (CUTOVER - 1000.0, "garch", 0.072),          # legacy_unverified -> NULL
        (LEGACY_LAST + 1000.0, "garch", None),       # raw NULL -> stays NULL
    ]
    con.executemany("INSERT INTO snapshots (ts_utc, mc_vol_source, mc_sigma_value) VALUES (?,?,?)", rows)
    con.commit()
    con.close()
    return str(p)


def _annualized(db_path: str) -> list:
    con = sqlite3.connect(db_path)
    try:
        return [r[0] for r in con.execute(
            "SELECT mc_sigma_annualized FROM snapshots ORDER BY rowid").fetchall()]
    finally:
        con.close()


def test_backfill_makes_one_unit_and_preserves_raw(tmp_path):
    db = _db(tmp_path)
    report = normalize(db, apply=True)
    assert report["annualized"] == 2
    assert report["per_bar_1m_converted"] == 1
    assert report["legacy_nulled"] == 1
    got = _annualized(db)
    assert abs(got[0] - 0.30) < 1e-9            # blend copied
    assert abs(got[1] - 0.28) < 1e-9            # post-legacy garch copied
    assert abs(got[2] - 0.001 * CONVERSION_FACTOR) < 1e-9  # per_bar_1m converted
    assert got[3] is None                        # legacy nulled
    assert got[4] is None                        # raw-null stays null
    # raw column is untouched (frozen archive)
    con = sqlite3.connect(db)
    raw = [r[0] for r in con.execute("SELECT mc_sigma_value FROM snapshots ORDER BY rowid").fetchall()]
    con.close()
    assert raw[3] == 0.072 and raw[2] == 0.001, "raw mc_sigma_value must be preserved"


def test_idempotent_second_run_is_stable(tmp_path):
    db = _db(tmp_path)
    normalize(db, apply=True)
    first = _annualized(db)
    normalize(db, apply=True)      # derives from the frozen raw column again
    assert _annualized(db) == first


def test_dry_run_writes_nothing(tmp_path):
    db = _db(tmp_path)
    report = normalize(db, apply=False)
    assert report["mode"] == "dry_run"
    con = sqlite3.connect(db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(snapshots)").fetchall()]
    con.close()
    assert "mc_sigma_annualized" not in cols, "dry run must not add the column"
