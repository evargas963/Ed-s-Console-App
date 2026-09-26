"""calibration.v2_advisory_backfill's historical bulk-backfill path (schema
migration, walk-forward embargo enforcement, per-row error handling, fusion-field
inference) must reconstruct the same V2 decision shape the live logger writes --
paired with test_calibration_v2_live_logging.py's proof that both writers share
identical columns, so a backfilled row and a live row are never distinguishable by
schema alone."""
from __future__ import annotations

import json
import sqlite3


from calibration.schema import ensure_calibration_schema
from db import EdDB, configure_sqlite_connection

BASE_TS = 1_778_018_400.0


def _proof() -> dict:
    # institutional-synthetic-ok: v2 advisory-backfill test needs a controlled winner/chain_row.
    return {
        "status": "ok",
        "winner": {
            "expression": "500 CALL",
            "strike": 500.0,
            "side": "CALL",
            "chain_row": {
                "symbol": "SPY260505C00500000",
                "putCall": "CALL",
                "daysToExpiration": 0,
                "strikePrice": 500.0,
                "bid": 1.2,
                "ask": 1.28,
                "delta": 0.52,
                "gamma": 0.08,
                "theta": -0.18,
                "vega": 0.02,
                "volatility": 0.22,
                "totalVolume": 1200,
                "openInterest": 4300,
                "expirationDate": "2026-05-05",
                "quoteTimeInLong": int(BASE_TS * 1000) - 500,
                "tradeTimeInLong": int(BASE_TS * 1000) - 750,
            },
        },
    }


def _replay_context() -> str:
    return json.dumps(
        {
            "version": 1,
            "regime_primary": "trend",
            "regime_confidence": "high",
            "zone": "breakout",
            "vol_regime": "normal",
            "option_chain_selection_proof": _proof(),
        }
    )


def _seed_db(tmp_path):
    db_path = tmp_path / "v2_advisory_backfill.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    return db_path, conn


def _insert_calibration_row(conn: sqlite3.Connection, *, ts: float = BASE_TS, ticker: str = "SPY") -> None:
    conn.execute(
        """
        INSERT INTO calibration_decision_log (decision_ts_utc, ticker, canonical_timeframe, calibration_trust)
        VALUES (?, ?, '1m', 'trusted')
        """,
        (ts, ticker),
    )


def _insert_snapshot(
    conn: sqlite3.Connection,
    *,
    ts: float = BASE_TS,
    ticker: str = "SPY",
    outcome_5c: str | None = "up",
) -> None:
    conn.execute(
        """
        INSERT INTO snapshots (
            ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
            expiry, dte, hours_to_expiry, spread,
            rules_entry, rules_stop, rules_target, call_target2, rules_summary,
            fusion_dominant_direction, fusion_dominant_prob, fusion_confidence,
            fusion_prob_up, fusion_prob_down, fusion_prob_flat,
            r_units, execution_mode, replay_context_json,
            horizon_outcome_schema_version, outcome_filled,
            outcome_1c, outcome_5c, outcome_15c, outcome_60c,
            outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts
        )
        VALUES (
            ?, '1m', ?, '2026-05-05 14:00:00 ET', 14, 0, 'rth', 499.5,
            '2026-05-05', 0, 2.0, 0.08,
            500.0, 498.5, 503.0, 505.0, 'Rules favor continuation',
            'up', 0.64, 'high',
            0.64, 0.21, 0.15,
            0.25, 'STANDARD', ?,
            3, ?,
            'up', ?, 'up', 'up',
            0.1, 0.2, 0.3, 0.4
        )
        """,
        (ticker, ts, _replay_context(), 1 if outcome_5c is not None else 0, outcome_5c),
    )


def _snapshot_row(conn: sqlite3.Connection, *, ts: float = BASE_TS) -> sqlite3.Row:
    return conn.execute("SELECT * FROM snapshots WHERE ts_utc=?", (ts,)).fetchone()


def test_schema_migration_adds_nullable_v2_advisory_columns(tmp_path):
    _db_path, conn = _seed_db(tmp_path)

    cols = {row["name"] for row in conn.execute("PRAGMA table_info(calibration_decision_log)").fetchall()}
    conn.close()

    assert "advisory_v2_decision_snapshot_json" in cols
    assert "advisory_v2_snapshot_schema_version" in cols
    assert "advisory_v2_adapter_version" in cols
    assert "advisory_v2_backfill_status" in cols
































