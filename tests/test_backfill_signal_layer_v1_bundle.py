"""backfill_signal_layer_v1_bundle — trusted-only, skip only when bars present."""

from __future__ import annotations

import json
import sqlite3

from calibration.backfill_signal_layer_v1_bundle import backfill
from calibration.schema import ensure_calibration_schema
from db import EdDB, configure_sqlite_connection

BASE_TS = 1_910_000_000.0


def _seed_db(tmp_path):
    db_path = tmp_path / "slvb.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    return db_path, conn


def test_backfill_recomputes_empty_signal_layer_when_bars_exist(tmp_path) -> None:
    db_path, conn = _seed_db(tmp_path)
    be = BASE_TS
    bs = be - 60.0
    conn.execute(
        """
        INSERT INTO price_bars_1m (
            ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume, source
        ) VALUES ('SPY', ?, ?, 100, 101, 99, 100.5, 1e6, 'test')
        """,
        (bs, be),
    )
    bundle = {
        "signal_layer_v1": {
            "meta.decision_ts_utc": BASE_TS,
            "meta.n_bars": 0,
        }
    }
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
            decision_ts_utc, ticker, canonical_timeframe, calibration_trust, raw_bundle_json
        ) VALUES (?, 'SPY', '1m', 'trusted', ?)
        """,
        (BASE_TS, json.dumps(bundle)),
    )
    conn.commit()
    conn.close()

    out = backfill(db_path, dry_run=False, force=False, allow_noncanonical=True)
    assert out["updated"] == 1
    assert out["skipped_nonempty"] == 0

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT raw_bundle_json FROM calibration_decision_log").fetchone()
    conn.close()
    payload = json.loads(row[0])
    assert int(payload["signal_layer_v1"].get("meta.n_bars") or 0) > 0


def test_backfill_skips_nonempty_layer_without_force(tmp_path) -> None:
    db_path, conn = _seed_db(tmp_path)
    bundle = {
        "signal_layer_v1": {
            "meta.decision_ts_utc": BASE_TS,
            "meta.n_bars": 42,
            "meta.bar_end_last": BASE_TS,
        }
    }
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
            decision_ts_utc, ticker, canonical_timeframe, calibration_trust, raw_bundle_json
        ) VALUES (?, 'SPY', '1m', 'trusted', ?)
        """,
        (BASE_TS, json.dumps(bundle)),
    )
    conn.commit()
    conn.close()

    out = backfill(db_path, dry_run=True, force=False, allow_noncanonical=True)
    assert out["updated"] == 0
    assert out["skipped_nonempty"] == 1


def test_backfill_ignores_legacy_rows(tmp_path) -> None:
    db_path, conn = _seed_db(tmp_path)
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
            decision_ts_utc, ticker, canonical_timeframe, calibration_trust, raw_bundle_json
        ) VALUES (?, 'SPY', '1m', 'legacy', '{}')
        """,
        (BASE_TS,),
    )
    conn.commit()
    conn.close()

    out = backfill(db_path, dry_run=True, allow_noncanonical=True)
    assert out["rows_total"] == 0
    assert out["updated"] == 0
