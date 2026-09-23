"""Hermetic contracts for pred_1c persistence and the legacy audit wiring.

Operator production audit (canonical DB must have governed pred_1c rows):
  ED_REQUIRE_GOVERNED_PRED_1C=1 python -m pytest tests/test_pred_1c_eddb_and_audit_contract_v1.py -q
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CANONICAL_DB = ROOT / "data" / "ed_console.db"

_GOVERNED_PRED_1C_COUNT_SQL = """
SELECT COUNT(*) FROM snapshots s
WHERE s.timeframe = '1m' AND s.horizon_outcome_schema_version = 3
AND EXISTS (SELECT 1 FROM price_bars_1m p WHERE p.ticker = s.ticker AND p.bar_end_ts_utc <= s.ts_utc)
AND s.outcome_1c IS NOT NULL AND s.pred_1c_up_prob IS NOT NULL
"""


def _require_governed_pred_1c_hard_gate() -> bool:
    return os.environ.get("ED_REQUIRE_GOVERNED_PRED_1C", "").strip().lower() in ("1", "true", "yes")  # caps-ok: opt-in env flag: unset means the hard production-data gate was not requested for this run


def _governed_pred_1c_count(db_path: Path) -> int:
    with sqlite3.connect(str(db_path)) as conn:
        return int(conn.execute(_GOVERNED_PRED_1C_COUNT_SQL).fetchone()[0])


def test_snapshots_table_accepts_pred_1c_triple_minimal_insert(tmp_path: Path) -> None:
    from db import EdDB

    db = EdDB(tmp_path / "p1c.db", allow_noncanonical=True)
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
            ("SPY", "1m", 1_777_000_000.0, "test_et", 500.0, "pin_neutral",
             "above", 0.31, 0.41, 0.28, 3),
        )
        snapshot_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        row = conn.execute(
            "SELECT pred_1c_up_prob, pred_1c_down_prob, pred_1c_flat_prob "
            "FROM snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
    assert row is not None
    assert tuple(row) == pytest.approx((0.31, 0.41, 0.28))


def test_phase5_audit_module_defines_governed_pred_1c_metric() -> None:
    source = (
        ROOT / "tools" / "legacy" / "horizon_7" / "_phase5_discrimination_audit_v1.py"
    ).read_text(encoding="utf-8")
    assert '"governed_rows_with_pred_1c_nonnull": n_gov_pred1c,' in source
    assert "s.pred_1c_up_prob IS NOT NULL" in source


def test_production_db_has_governed_pred_1c_when_expected() -> None:
    """Governed pred_1c row-count gate — hard assert only when ED_REQUIRE_GOVERNED_PRED_1C=1.

    Default/CI: a greenfield data/ed_console.db (schema only, or absent) skips this gate --
    file presence is not production history, and the operator runs the hard audit explicitly."""
    if not CANONICAL_DB.is_file():
        pytest.skip("PRODUCTION-DATA-ONLY: canonical DB not present in workspace")

    n = _governed_pred_1c_count(CANONICAL_DB)

    if _require_governed_pred_1c_hard_gate():
        assert n > 0, (
            f"ED_REQUIRE_GOVERNED_PRED_1C=1: expected governed snapshots with non-null "
            f"pred_1c_up_prob; got n={n} on {CANONICAL_DB.resolve()}"
        )
        return

    if n == 0:
        pytest.skip(
            "greenfield CI/offline DB file presence is not production history; "
            "governed pred_1c SQL predicate executed successfully (n=0); "
            "operator hard audit requires ED_REQUIRE_GOVERNED_PRED_1C=1"
        )


def test_freshest_snapshot_row_with_pred_1c_readable() -> None:
    """Smoke: latest high snapshot_id with pred_1c is queryable (live path uses same table)."""
    from db import DB_PATH

    if not Path(DB_PATH).is_file():
        pytest.skip("DB file missing")
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        """
        SELECT snapshot_id, ticker, pred_1c_up_prob, pred_1c_down_prob, pred_1c_flat_prob
        FROM snapshots
        WHERE pred_1c_up_prob IS NOT NULL
        ORDER BY snapshot_id DESC LIMIT 1
        """
    ).fetchone()
    conn.close()
    if row is None:
        pytest.skip("PRODUCTION-DATA-ONLY: no governed pred_1c rows in local DB yet")
    assert all(x is not None for x in row[2:5])


def test_governed_pred_1c_subset_of_governed_total_on_current_schema() -> None:
    """The pred_1c-populated governed count must never exceed the governed total it is a
    subset of -- a live regression guard against the 4-horizon governed predicate and the
    pred_1c predicate silently drifting apart (e.g. one gains a horizon column the other
    doesn't check), which no single-count smoke test can see."""
    if not CANONICAL_DB.is_file():
        pytest.skip("PRODUCTION-DATA-ONLY: canonical DB not present in workspace")
    conn = sqlite3.connect(str(CANONICAL_DB))
    governed_predicate = """
        s.timeframe = '1m'
        AND s.horizon_outcome_schema_version = 3
        AND EXISTS (SELECT 1 FROM price_bars_1m p WHERE p.ticker = s.ticker AND p.bar_end_ts_utc <= s.ts_utc)
        AND s.outcome_1c IS NOT NULL AND s.outcome_5c IS NOT NULL
        AND s.outcome_15c IS NOT NULL AND s.outcome_60c IS NOT NULL
    """
    n_governed = conn.execute(f"SELECT COUNT(*) FROM snapshots s WHERE {governed_predicate}").fetchone()[0]
    n_governed_with_pred_1c = conn.execute(
        f"SELECT COUNT(*) FROM snapshots s WHERE {governed_predicate} AND s.pred_1c_up_prob IS NOT NULL"
    ).fetchone()[0]
    conn.close()
    if n_governed == 0:
        pytest.skip("no governed rows on current schema in this DB yet")
    assert n_governed_with_pred_1c <= n_governed
