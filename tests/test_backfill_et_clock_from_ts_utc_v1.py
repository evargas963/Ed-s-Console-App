"""FIND-CAL-TS item-6: historical ET clock backfill from ts_utc."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


from calibration.backfill_et_clock_from_ts_utc_v1 import (
    backfill_table,
    derive_et_clock_from_ts_utc,
    row_differs_from_derived,
    run_backfill,
    sample_post_backfill_check,
)
from time_et import COH_I_A_ET_BACKFILL_CEILING_TS_UTC, et_clock_from_ts_utc


def _make_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            ts_utc REAL,
            ts_et TEXT,
            et_hour INTEGER,
            et_minute INTEGER,
            market_session TEXT
        )
        """
    )
    conn.commit()
    return conn


def test_derive_et_clock_matches_helpers():
    t = datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc).timestamp()
    d = derive_et_clock_from_ts_utc(t)
    h, m, _ = et_clock_from_ts_utc(t)
    assert d.et_hour == h
    assert d.et_minute == m
    assert d.market_session == "rth"
    assert d.ts_et == "2026-07-07 11:00:00 ET"


def test_row_differs_ts_et_exact_not_trimmed():
    t = datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc).timestamp()
    d = derive_et_clock_from_ts_utc(t)
    assert not row_differs_from_derived(t, d.et_hour, d.et_minute, d.market_session, d.ts_et)
    assert row_differs_from_derived(t, d.et_hour, d.et_minute, d.market_session, f" {d.ts_et} ")


def test_row_differs_detects_skewed_stored_hour():
    t = datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc).timestamp()
    assert row_differs_from_derived(t, 9, 0, "rth", "2026-07-07 09:00:00 ET")


def test_backfill_commit_and_idempotent(tmp_path: Path):
    db = tmp_path / "t.db"
    conn = _make_db(db)
    # Pre-cutover instant (still 11:00 ET on 2026-07-07 when interpreted at modern ts)
    t = COH_I_A_ET_BACKFILL_CEILING_TS_UTC - 86400.0
    ceiling = COH_I_A_ET_BACKFILL_CEILING_TS_UTC
    conn.execute(
        "INSERT INTO snapshots (ticker, ts_utc, ts_et, et_hour, et_minute, market_session) "
        "VALUES ('SPY', ?, '2026-07-07 09:00:00 ET', 9, 0, 'premarket')",
        (t,),
    )
    conn.commit()

    first = backfill_table(conn, "snapshots", ceiling_ts_utc=ceiling, apply=True)
    assert first["updated"] == 1

    row = conn.execute("SELECT et_hour, et_minute, market_session, ts_et FROM snapshots WHERE snapshot_id=1").fetchone()
    d = derive_et_clock_from_ts_utc(t)
    assert row[0] == d.et_hour
    assert row[1] == d.et_minute
    assert row[2] == d.market_session
    assert row[3] == d.ts_et

    second = backfill_table(conn, "snapshots", ceiling_ts_utc=ceiling, apply=True)
    assert second["would_update"] == 0
    assert second["updated"] == 0

    check = sample_post_backfill_check(conn, "snapshots", ceiling_ts_utc=ceiling, sample_size=5)
    assert check["ok"] is True
    conn.close()


def test_run_backfill_dry_run_counts(tmp_path: Path):
    db = tmp_path / "t2.db"
    conn = _make_db(db)
    t = datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc).timestamp()
    conn.execute(
        "INSERT INTO snapshots (ticker, ts_utc, ts_et, et_hour, et_minute, market_session) "
        "VALUES ('SPY', ?, 'skew', 1, 2, 'closed')",
        (t,),
    )
    conn.commit()
    conn.close()

    out = run_backfill(str(db), apply=False, ceiling_ts_utc=COH_I_A_ET_BACKFILL_CEILING_TS_UTC + 1e9)
    snap = next(x for x in out["tables"] if x["table"] == "snapshots")
    assert snap["would_update"] >= 1
    assert snap["updated"] == 0


def test_max_rows_limits_updates_not_just_scan(tmp_path: Path):
    db = tmp_path / "t3.db"
    conn = _make_db(db)
    ceiling = COH_I_A_ET_BACKFILL_CEILING_TS_UTC + 1e9
    for i in range(5):
        conn.execute(
            "INSERT INTO snapshots (ticker, ts_utc, ts_et, et_hour, et_minute, market_session) "
            "VALUES ('SPY', ?, 'x', 0, 0, 'closed')",
            (float(1_700_000_000 + i),),
        )
    conn.commit()
    stats = backfill_table(conn, "snapshots", ceiling_ts_utc=ceiling, apply=True, max_rows=2)
    assert stats["updated"] == 2
    assert stats["scanned"] >= 2
    remaining = conn.execute(
        "SELECT COUNT(*) FROM snapshots WHERE ts_et = 'x'"
    ).fetchone()[0]
    assert remaining == 3
    conn.close()


def test_cli_verify_sample_passes(tmp_path: Path, monkeypatch):
    from tools import backfill_et_clock_from_ts_utc_v1 as cli

    db = tmp_path / "cli.db"
    conn = _make_db(db)
    t = COH_I_A_ET_BACKFILL_CEILING_TS_UTC - 3600.0
    conn.execute(
        "INSERT INTO snapshots (ticker, ts_utc, ts_et, et_hour, et_minute, market_session) "
        "VALUES ('SPY', ?, 'bad', 0, 0, 'closed')",
        (t,),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        cli,
        "require_canonical_db_target",
        lambda *a, **k: None,
    )
    rc = cli.main(
        [
            "--db",
            str(db),
            "--commit",
            "--verify-sample",
            "5",
            "--allow-noncanonical-db",
            # RC-510: without this the CLI defaults its audit to reports/audits/ and every
            # suite run drops a timestamped JSON into the TRACKED tree, carrying the
            # operator's home path in `db_path` and `audit_path` — which the credential
            # firewall then blocks on the next commit. The tool already provides the
            # override; the test simply never used it.
            "--audit-root",
            str(tmp_path / "audits"),
        ]
    )
    assert rc == 0
    written = sorted((tmp_path / "audits").glob("*.json"))
    assert written, "the audit went somewhere other than the directory the test named"
