"""repair_canonical_1m_edge_carry_v1 fail-closed contracts."""

from __future__ import annotations

import sqlite3
from pathlib import Path


from calibration.repair_canonical_1m_edge_carry_v1 import run_repair
from horizon_outcomes import AUTHORITATIVE_1M_SOURCE, SYNTHETIC_EDGE_CARRY_V1


def _seed_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE price_bars_1m (
            ticker TEXT NOT NULL,
            bar_start_ts_utc REAL NOT NULL,
            bar_end_ts_utc REAL NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            source TEXT,
            PRIMARY KEY (ticker, bar_start_ts_utc)
        );
        """
    )
    conn.execute(
        """
        INSERT INTO price_bars_1m
          (ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("SPY", 1000.0, 1060.0, 10.0, 10.0, 10.0, 10.0, 1.0, AUTHORITATIVE_1M_SOURCE),
    )
    conn.commit()
    conn.close()


def test_run_repair_empty_db_errors(tmp_path: Path):
    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE price_bars_1m (
            ticker TEXT NOT NULL,
            bar_start_ts_utc REAL NOT NULL,
            bar_end_ts_utc REAL NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            source TEXT,
            PRIMARY KEY (ticker, bar_start_ts_utc)
        );
        """
    )
    conn.close()
    rep = run_repair(db_path, dry_run=True)
    assert rep.get("error") == "no_bars_in_price_bars_1m"


def test_carry_basis_excludes_prior_synthetic_close(tmp_path: Path, monkeypatch):
    """Carry price must come from Schwab bar, not an earlier synthetic repair bar."""
    from calibration import repair_canonical_1m_edge_carry_v1 as edge

    db_path = tmp_path / "carry.db"
    _seed_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO price_bars_1m
          (ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("SPY", 5000.0, 5060.0, 99.0, 99.0, 99.0, 99.0, 0.0, SYNTHETIC_EDGE_CARRY_V1),
    )
    conn.commit()
    conn.close()

    class _Rec:
        def __init__(self, ticker: str, required: float):
            self._d = {"ticker": ticker, "required_bar_start_ts_utc": required}

        def __getitem__(self, k):
            return self._d[k]

    monkeypatch.setattr(
        edge,
        "scan_db",
        lambda _db, tz_now_utc: type(
            "R",
            (),
            {"missing_forward": [_Rec("SPY", 4000.0)]},
        )(),
    )

    planned = edge._planned_edge_carries(db_path, tz_now=6000.0)
    assert planned
    _tkr, _g, close = planned[0]
    assert close == 10.0


def test_run_repair_failure_reports_none_not_zero_counts(tmp_path: Path, monkeypatch):
    """
    No-fallback lock repair (FB-00129/FB-00130): apply_repair_1m_bar_batch_writes rolls
    back its single transaction on any exception, so rows_upserted/tickers_touched/
    governed_outcome_refresh_tickers ARE durably zero on failure -- but a bare 0 there is
    indistinguishable from "ran fine, nothing to touch." None marks the report fields as
    not-reported-due-to-failure, distinct from either outcome.
    """
    from calibration import repair_canonical_1m_edge_carry_v1 as edge

    db_path = tmp_path / "fail.db"
    _seed_db(db_path)

    monkeypatch.setattr(
        edge, "_planned_edge_carries", lambda _db, _tz: [("SPY", 4000.0, 10.0)]
    )

    def _boom(*_a, **_k):
        raise RuntimeError("simulated batch-write failure")

    monkeypatch.setattr(edge, "apply_repair_1m_bar_batch_writes", _boom)

    rep = edge.run_repair(db_path, dry_run=False)
    assert rep["error"].startswith("repair_failed_rollback:")
    assert rep["rows_upserted"] is None
    assert rep["tickers_touched"] is None
    assert rep["governed_outcome_refresh_tickers"] is None
