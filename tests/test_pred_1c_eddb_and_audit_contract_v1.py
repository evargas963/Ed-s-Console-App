"""Contracts: EdDB persists pred_1c_*; phase5 audit exposes governed pred_1c count."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_snapshots_table_accepts_pred_1c_triple_minimal_insert(tmp_path):
    """DB schema accepts pred_1c_* on insert (same columns as live tier-1 writes)."""
    from db import EdDB

    dbp = tmp_path / "p1c.db"
    db = EdDB(dbp, allow_noncanonical=True)
    ts = 1_777_000_000.0
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
              ticker, timeframe, ts_utc, ts_et, spot, zone, vwap_side,
              pred_1c_up_prob, pred_1c_down_prob, pred_1c_flat_prob,
              horizon_outcome_schema_version
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "SPY",
                "1m",
                ts,
                "test_et",
                500.0,
                "pin_neutral",
                "above",
                0.31,
                0.41,
                0.28,
                3,
            ),
        )
        conn.commit()
        sid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        r = conn.execute(
            "SELECT pred_1c_up_prob, pred_1c_down_prob, pred_1c_flat_prob FROM snapshots WHERE snapshot_id = ?",
            (sid,),
        ).fetchone()
    assert r is not None
    assert pytest.approx(r[0], rel=1e-6) == 0.31
    assert pytest.approx(r[1], rel=1e-6) == 0.41
    assert pytest.approx(r[2], rel=1e-6) == 0.28


def test_phase5_audit_module_defines_governed_pred_1c_metric():
    p = ROOT / "tools" / "_phase5_discrimination_audit_v1.py"
    src = p.read_text(encoding="utf-8")
    assert "governed_rows_with_pred_1c_nonnull" in src
    assert "n_gov_pred1c" in src or "governed_rows_with_pred_1c_nonnull" in src


@pytest.mark.skipif(
    not (ROOT / "data" / "ed_console.db").is_file(),
    reason="canonical DB not present in workspace",
)
def test_production_db_has_governed_pred_1c_when_expected():
    """Hard check: if DB exists, governed pred_1c count must be > 0 post-remediation."""
    c = sqlite3.connect(str(ROOT / "data" / "ed_console.db"))
    n = c.execute(
        """
        SELECT COUNT(*) FROM snapshots s
        WHERE s.timeframe = '1m' AND s.horizon_outcome_schema_version = 3
        AND EXISTS (SELECT 1 FROM price_bars_1m p WHERE p.ticker = s.ticker AND p.bar_end_ts_utc <= s.ts_utc)
        AND s.outcome_1c IS NOT NULL AND s.pred_1c_up_prob IS NOT NULL
        """
    ).fetchone()[0]
    assert n > 0


def test_freshest_snapshot_row_with_pred_1c_readable():
    """Smoke: latest high snapshot_id with pred_1c is queryable (live path uses same table)."""
    from db import DB_PATH

    if not Path(DB_PATH).is_file():
        pytest.skip("DB file missing")
    c = sqlite3.connect(str(DB_PATH))
    r = c.execute(
        """
        SELECT snapshot_id, ticker, pred_1c_up_prob, pred_1c_down_prob, pred_1c_flat_prob
        FROM snapshots
        WHERE pred_1c_up_prob IS NOT NULL
        ORDER BY snapshot_id DESC LIMIT 1
        """
    ).fetchone()
    assert r is not None
    assert all(x is not None for x in r[2:5])


def test_subprocess_phase5_json_includes_governed_pred_1c_key():
    if not (ROOT / "data" / "ed_console.db").is_file():
        pytest.skip("no DB")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "_phase5_discrimination_audit_v1.py"), "--db", str(ROOT / "data" / "ed_console.db")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    d = json.loads(proc.stdout)
    assert "governed_rows_with_pred_1c_nonnull" in d
    assert d["governed_rows_with_pred_1c_nonnull"] >= 0
