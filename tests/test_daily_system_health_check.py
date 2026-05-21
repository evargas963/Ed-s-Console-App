"""Daily system health check (verification.daily_health)."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import pytest
from zoneinfo import ZoneInfo

from time_et import ET as _ET
from verification.daily_health import (
    INTRADAY_SEVERE_GAP_SEC,
    STALE_BAR_DATA_SEC,
    run_daily_health,
    write_reports,
)


def _schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE price_bars_1m (
            ticker TEXT NOT NULL,
            bar_start_ts_utc REAL NOT NULL,
            bar_end_ts_utc REAL NOT NULL,
            close REAL NOT NULL,
            PRIMARY KEY (ticker, bar_start_ts_utc)
        );
        CREATE TABLE snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            ts_utc REAL NOT NULL,
            spot REAL NOT NULL,
            pred_1c_up_prob REAL, pred_1c_down_prob REAL, pred_1c_flat_prob REAL,
            pred_5c_up_prob REAL, pred_5c_down_prob REAL, pred_5c_flat_prob REAL,
            pred_15c_up_prob REAL, pred_15c_down_prob REAL, pred_15c_flat_prob REAL,
            pred_60c_up_prob REAL, pred_60c_down_prob REAL, pred_60c_flat_prob REAL,
            outcome_1c TEXT, outcome_5c TEXT, outcome_15c TEXT, outcome_60c TEXT
        );
        """
    )


def _seed_good(conn, *, t0: float, n: int = 120) -> None:
    for i in range(n):
        st = t0 + i * 60.0
        conn.execute(
            "INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc, close) VALUES (?,?,?,?)",
            ("SPY", st, st + 60.0, 500.0 + 0.01 * i),
        )
        conn.execute(
            """
            INSERT INTO snapshots (
              ticker, timeframe, ts_utc, spot,
              pred_1c_up_prob, pred_1c_down_prob, pred_1c_flat_prob,
              pred_5c_up_prob, pred_5c_down_prob, pred_5c_flat_prob,
              pred_15c_up_prob, pred_15c_down_prob, pred_15c_flat_prob,
              pred_60c_up_prob, pred_60c_down_prob, pred_60c_flat_prob,
              outcome_1c, outcome_5c, outcome_15c, outcome_60c
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "SPY",
                "1m",
                st,
                500.0,
                0.34,
                0.33,
                0.33,
                0.34,
                0.33,
                0.33,
                0.34,
                0.33,
                0.33,
                0.34,
                0.33,
                0.33,
                "up",
                "up",
                "flat",
                "down",
            ),
        )


def test_daily_health_passes_clean_db(tmp_path: Path) -> None:
    db = tmp_path / "h.db"
    conn = __import__("sqlite3").connect(str(db))
    _schema(conn)
    t0 = time.time() - 200 * 60.0
    _seed_good(conn, t0=t0)
    conn.commit()
    conn.close()

    rep = run_daily_health(db, ticker_filter=["SPY"])
    assert rep.overall_pass is True
    assert rep.tickers == ["SPY"]
    assert not any(c["severity"] == "FAIL" for c in rep.checks)
    assert rep.summary.get("fail_checks") == 0
    assert rep.summary.get("universe_resolution") == "explicit_ticker_filter"

    paths = write_reports(rep, root=tmp_path)
    assert paths[0].is_file()
    assert paths[1].is_file()


def test_daily_health_fails_stale_bars(tmp_path: Path) -> None:
    db = tmp_path / "s.db"
    conn = __import__("sqlite3").connect(str(db))
    _schema(conn)
    old = time.time() - float(STALE_BAR_DATA_SEC) - 86400.0
    _seed_good(conn, t0=old, n=50)
    conn.commit()
    conn.close()

    rep = run_daily_health(db, ticker_filter=["SPY"])
    assert rep.overall_pass is False
    assert any("stale" in c.get("message", "").lower() for c in rep.checks if c["severity"] == "FAIL")


def _snap_only(conn, t0: float, n: int) -> None:
    for i in range(n):
        st = t0 + i * 60.0
        conn.execute(
            """
            INSERT INTO snapshots (
              ticker, timeframe, ts_utc, spot,
              pred_1c_up_prob, pred_1c_down_prob, pred_1c_flat_prob,
              pred_5c_up_prob, pred_5c_down_prob, pred_5c_flat_prob,
              pred_15c_up_prob, pred_15c_down_prob, pred_15c_flat_prob,
              pred_60c_up_prob, pred_60c_down_prob, pred_60c_flat_prob,
              outcome_1c, outcome_5c, outcome_15c, outcome_60c
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "SPY",
                "1m",
                st,
                500.0,
                0.34,
                0.33,
                0.33,
                0.34,
                0.33,
                0.33,
                0.34,
                0.33,
                0.33,
                0.34,
                0.33,
                0.33,
                "up",
                "up",
                "flat",
                "down",
            ),
        )


def test_daily_health_weekend_rth_clock_gap_not_fail(tmp_path: Path) -> None:
    """Sat/Sun ET same-calendar RTH-clock gaps are not counted toward intraday severe FAIL."""
    db = tmp_path / "weekend_gap.db"
    conn = __import__("sqlite3").connect(str(db))
    _schema(conn)
    # 2024-06-08 is Saturday (US ET). Two bar starts in 12:00–13:00 ET window (RTH clock), same ET date, gap > 300s.
    base = datetime(2024, 6, 8, 12, 0, tzinfo=_ET).timestamp()
    conn.execute(
        "INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc, close) VALUES (?,?,?,?)",
        ("SPY", base, base + 60.0, 100.0),
    )
    st1 = base + 60.0 + float(INTRADAY_SEVERE_GAP_SEC) + 120.0
    conn.execute(
        "INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc, close) VALUES (?,?,?,?)",
        ("SPY", st1, st1 + 60.0, 101.0),
    )
    _snap_only(conn, base, 5)
    conn.commit()
    conn.close()

    rep = run_daily_health(db, ticker_filter=["SPY"])
    assert not any(c["id"] == "data_severe_intraday_gap:SPY" for c in rep.checks)
    assert any(c["id"] == "data_rth_clock_gap_weekend_et_excluded:SPY" for c in rep.checks)


def _snap_for(conn, ticker: str, t0: float, n: int) -> None:
    for i in range(n):
        st = t0 + i * 60.0
        conn.execute(
            """
            INSERT INTO snapshots (
              ticker, timeframe, ts_utc, spot,
              pred_1c_up_prob, pred_1c_down_prob, pred_1c_flat_prob,
              pred_5c_up_prob, pred_5c_down_prob, pred_5c_flat_prob,
              pred_15c_up_prob, pred_15c_down_prob, pred_15c_flat_prob,
              pred_60c_up_prob, pred_60c_down_prob, pred_60c_flat_prob,
              outcome_1c, outcome_5c, outcome_15c, outcome_60c
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ticker,
                "1m",
                st,
                20.0,
                0.34,
                0.33,
                0.33,
                0.34,
                0.33,
                0.33,
                0.34,
                0.33,
                0.33,
                0.34,
                0.33,
                0.33,
                "up",
                "up",
                "flat",
                "down",
            ),
        )


def test_vix_market_context_intraday_gap_warn_not_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """$VIX: severe RTH-clock gaps stay visible but WARN (MARKET_CONTEXT_ONLY), not equity FAIL."""
    from types import SimpleNamespace

    import verification.daily_health as dh

    db = tmp_path / "vixctx.db"
    conn = __import__("sqlite3").connect(str(db))
    _schema(conn)
    base = datetime(2024, 6, 5, 11, 0, tzinfo=_ET).timestamp()
    t0 = base
    conn.execute(
        "INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc, close) VALUES (?,?,?,?)",
        ("$VIX", t0, t0 + 60.0, 18.0),
    )
    st1 = t0 + 60.0 + float(INTRADAY_SEVERE_GAP_SEC) + 150.0
    for i in range(45):
        s = st1 + i * 60.0
        conn.execute(
            "INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc, close) VALUES (?,?,?,?)",
            ("$VIX", s, s + 60.0, 18.0 + 0.01 * i),
        )
    _snap_for(conn, "$VIX", st1, 80)
    conn.commit()
    last_bar_end = st1 + 44 * 60.0 + 60.0
    conn.close()

    # Freeze "now" so synthetic 2024 bars are not stale vs wall clock 2026.
    monkeypatch.setattr(dh, "time", SimpleNamespace(time=lambda: float(last_bar_end) + 86400.0))

    rep = run_daily_health(db, ticker_filter=["$VIX"])
    gap_checks = [c for c in rep.checks if c.get("id") == "data_severe_intraday_gap:$VIX"]
    assert gap_checks, "expected intraday gap diagnostic for $VIX"
    assert gap_checks[0]["severity"] == "WARN"
    assert "MARKET_CONTEXT_ONLY" in gap_checks[0].get("message", "")
    assert not any(c["severity"] == "FAIL" and c.get("id", "").startswith("data_severe_intraday_gap") for c in rep.checks)


def test_daily_health_fails_intraday_gap(tmp_path: Path) -> None:
    db = tmp_path / "g.db"
    conn = __import__("sqlite3").connect(str(db))
    _schema(conn)
    base = datetime(2024, 6, 5, 11, 0, tzinfo=_ET).timestamp()
    t0 = base
    conn.execute(
        "INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc, close) VALUES (?,?,?,?)",
        ("SPY", t0, t0 + 60.0, 100.0),
    )
    st1 = t0 + 60.0 + float(INTRADAY_SEVERE_GAP_SEC) + 150.0
    for i in range(45):
        s = st1 + i * 60.0
        conn.execute(
            "INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc, close) VALUES (?,?,?,?)",
            ("SPY", s, s + 60.0, 100.0 + 0.01 * i),
        )
    _snap_only(conn, st1, 80)
    conn.commit()
    conn.close()

    rep = run_daily_health(db, ticker_filter=["SPY"])
    assert rep.overall_pass is False
    assert any(
        "rth-clock" in c.get("message", "").lower() or "intraday" in c.get("message", "").lower()
        for c in rep.checks
        if c["severity"] == "FAIL"
    )


def test_daily_health_fails_missing_required_column(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    conn = __import__("sqlite3").connect(str(db))
    conn.execute(
        "CREATE TABLE snapshots (ticker TEXT, timeframe TEXT, ts_utc REAL, spot REAL);"
    )
    conn.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, bar_end_ts_utc REAL, close REAL);")
    conn.commit()
    conn.close()

    rep = run_daily_health(db, ticker_filter=["SPY"])
    assert rep.overall_pass is False
    assert any(c["id"] == "schema_required_columns" for c in rep.checks)


def test_daily_health_thin_snapshots_skip_pred_triad_gate(tmp_path: Path) -> None:
    """Below MIN_SNAPSHOTS_FOR_PRED_TRIAD_GATE, missing 1c triads must not FAIL pred coverage."""
    from verification.daily_health import MIN_SNAPSHOTS_FOR_PRED_TRIAD_GATE

    db = tmp_path / "thin.db"
    conn = __import__("sqlite3").connect(str(db))
    _schema(conn)
    t0 = time.time() - 3000.0
    n = min(80, MIN_SNAPSHOTS_FOR_PRED_TRIAD_GATE - 1)
    for i in range(n):
        st = t0 + i * 60.0
        conn.execute(
            "INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc, close) VALUES (?,?,?,?)",
            ("SPY", st, st + 60.0, 500.0),
        )
        conn.execute(
            """
            INSERT INTO snapshots (
              ticker, timeframe, ts_utc, spot,
              pred_1c_up_prob, pred_1c_down_prob, pred_1c_flat_prob,
              pred_5c_up_prob, pred_5c_down_prob, pred_5c_flat_prob,
              pred_15c_up_prob, pred_15c_down_prob, pred_15c_flat_prob,
              pred_60c_up_prob, pred_60c_down_prob, pred_60c_flat_prob,
              outcome_1c, outcome_5c, outcome_15c, outcome_60c
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "SPY",
                "1m",
                st,
                500.0,
                None,
                None,
                None,
                0.34,
                0.33,
                0.33,
                0.34,
                0.33,
                0.33,
                0.34,
                0.33,
                0.33,
                "up",
                "up",
                "flat",
                "down",
            ),
        )
    conn.commit()
    conn.close()

    rep = run_daily_health(db, ticker_filter=["SPY"])
    assert any(c["id"].startswith("universe_thin_skip_pred_gate:") for c in rep.checks)
    assert not any(c["id"].startswith("feature_pred_coverage_fail:") for c in rep.checks)


def test_cli_script_invocation_smoke(tmp_path: Path) -> None:
    import subprocess
    import sys

    db = tmp_path / "cli.db"
    conn = __import__("sqlite3").connect(str(db))
    _schema(conn)
    _seed_good(conn, t0=time.time() - 3000.0, n=80)
    conn.commit()
    conn.close()

    script = Path(__file__).resolve().parents[1] / "tools" / "daily_system_health_check.py"
    r = subprocess.run(
        [sys.executable, str(script), "--db", str(db), "SPY"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
