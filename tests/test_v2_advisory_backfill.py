from __future__ import annotations

import json
import sqlite3

import pytest

from calibration.json_utils import parse_json_mapping
from calibration.schema import ensure_calibration_schema
from calibration.v2_advisory_backfill import (
    ADVISORY_V2_ADAPTER_VERSION,
    ADVISORY_V2_SNAPSHOT_SCHEMA_VERSION,
    RECONSTRUCTED_LIVE_MS_SOURCE,
    _direction_from_triplet,
    backfill_v2_advisory_decisions,
    build_v2_advisory_snapshot,
    build_walk_forward_splits,
    ms_dict_from_snapshot_row,
    validate_purged_embargo_splits,
)
from db import EdDB, configure_sqlite_connection
from v2_decision import build_module_a_a1_decision, validate_v2_decision

BASE_TS = 1_778_018_400.0


def _proof() -> dict:
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


def test_reconstructed_ms_dict_validates_through_v2_adapter(tmp_path):
    _db_path, conn = _seed_db(tmp_path)
    _insert_snapshot(conn)
    conn.commit()

    ms = ms_dict_from_snapshot_row(_snapshot_row(conn))
    decision = build_module_a_a1_decision(ms)
    conn.close()

    validate_v2_decision(decision)
    assert decision["decision"]["action"]["value"] == "TRADE"
    assert decision["decision"]["probability"]["value"] == 0.64
    assert decision["expression_profiles"]["A2"]["option_expression"]["option_action"]["value"] == "TRADE"


def test_snapshot_alias_mapping_matches_equivalent_ms_dict(tmp_path):
    _db_path, conn = _seed_db(tmp_path)
    _insert_snapshot(conn)
    conn.commit()

    ms = ms_dict_from_snapshot_row(_snapshot_row(conn))
    equivalent = {
        "ticker": "SPY",
        "fusion_available": True,
        "fusion_dominant_direction": "up",
        "fusion_dominant_prob": 0.64,
        "fusion_confidence": "high",
        "rules_headline": "Rules favor continuation",
        "entry": 500.0,
        "stop": 498.5,
        "target": 503.0,
        "target2": 505.0,
        "execution_mode": "STANDARD",
        "r_units": 0.25,
        "spread": 0.08,
    }
    conn.close()

    reconstructed = build_module_a_a1_decision(ms)
    expected = build_module_a_a1_decision(equivalent)
    assert reconstructed["decision"]["action"] == expected["decision"]["action"]
    assert reconstructed["decision"]["direction"] == expected["decision"]["direction"]
    assert reconstructed["decision"]["probability"] == expected["decision"]["probability"]


def test_replay_context_proof_extraction_populates_a2_selection(tmp_path):
    _db_path, conn = _seed_db(tmp_path)
    _insert_snapshot(conn)
    conn.commit()

    payload = build_v2_advisory_snapshot(_snapshot_row(conn))
    conn.close()

    a2 = payload["v2_decision"]["expression_profiles"]["A2"]
    assert a2["option_expression"]["option_right"]["value"] == "CALL"
    assert a2["option_expression"]["strike"]["value"] == 500.0
    assert a2["execution"]["quote_staleness_ms"]["value"] == 500


def test_v2_advisory_backfill_persists_snapshot_with_adapter_version(tmp_path):
    db_path, conn = _seed_db(tmp_path)
    _insert_calibration_row(conn)
    _insert_snapshot(conn)
    conn.commit()
    conn.close()

    stats = backfill_v2_advisory_decisions(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM calibration_decision_log").fetchone()
    payload = json.loads(row["advisory_v2_decision_snapshot_json"])
    conn.close()

    assert stats["updated"] == 1
    assert row["advisory_v2_backfill_status"] == "ok"
    assert row["advisory_v2_snapshot_schema_version"] == ADVISORY_V2_SNAPSHOT_SCHEMA_VERSION
    assert row["advisory_v2_adapter_version"] == ADVISORY_V2_ADAPTER_VERSION
    assert payload["adapter_version"] == ADVISORY_V2_ADAPTER_VERSION
    assert payload["v2_decision"]["authority"]["mode"] == "advisory_non_authoritative"


def test_unlabeled_snapshot_is_skipped_not_neutralized(tmp_path):
    db_path, conn = _seed_db(tmp_path)
    _insert_calibration_row(conn)
    _insert_snapshot(conn, outcome_5c=None)
    conn.commit()
    conn.close()

    stats = backfill_v2_advisory_decisions(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM calibration_decision_log").fetchone()
    conn.close()

    assert stats["updated"] == 0
    assert stats["skipped"] == 1
    assert row["advisory_v2_decision_snapshot_json"] is None
    assert row["advisory_v2_backfill_status"] == "skipped"
    assert row["advisory_v2_backfill_reason"] == "snapshot_outcomes_not_filled"


def test_walk_forward_splits_do_not_overlap_and_enforce_embargo():
    splits = build_walk_forward_splits(
        start_ts=0.0,
        end_ts=100.0,
        train_span=20.0,
        calibration_span=10.0,
        holdout_span=10.0,
        step_span=20.0,
        embargo_span=5.0,
    )

    validate_purged_embargo_splits(splits, embargo_span=5.0)
    assert splits
    for split in splits:
        assert split.train_end == split.calibration_start
        assert split.holdout_start >= split.calibration_end + 5.0


def test_walk_forward_validation_rejects_embargo_violation():
    splits = build_walk_forward_splits(
        start_ts=0.0,
        end_ts=60.0,
        train_span=20.0,
        calibration_span=10.0,
        holdout_span=10.0,
        step_span=20.0,
        embargo_span=0.0,
    )

    with pytest.raises(ValueError, match="embargo"):
        validate_purged_embargo_splits(splits, embargo_span=5.0)


def test_infer_fusion_fields_partial_triplet_does_not_mark_available() -> None:
    ms: dict = {"fusion_prob_up": 0.9}
    from calibration.v2_advisory_backfill import _infer_fusion_fields

    _infer_fusion_fields(ms)
    assert ms["fusion_available"] is False
    assert ms.get("fusion_dominant_direction") is None
    assert ms.get("fusion_dominant_prob") is None


def test_infer_fusion_fields_complete_triplet_infers_direction_and_prob() -> None:
    ms: dict = {
        "fusion_prob_up": 0.2,
        "fusion_prob_down": 0.25,
        "fusion_prob_flat": 0.55,
    }
    from calibration.v2_advisory_backfill import _infer_fusion_fields

    _infer_fusion_fields(ms)
    assert ms["fusion_available"] is True
    assert ms["fusion_dominant_direction"] == "flat"
    assert ms["fusion_dominant_prob"] == pytest.approx(0.55)


def test_build_snapshot_decision_ts_from_decision_ts_utc_alias() -> None:
    row = {
        "ticker": "SPY",
        "decision_ts_utc": BASE_TS,
        "fusion_available": True,
        "fusion_dominant_direction": "up",
        "fusion_dominant_prob": 0.6,
        "execution_mode": "STANDARD",
    }
    payload = build_v2_advisory_snapshot(row)
    assert payload["decision_ts_utc"] == BASE_TS


def test_direction_from_triplet_flat_matches_bayesian_fusion_canonical() -> None:
    """Backfill must emit 'flat' (not 'neutral') when flat prob wins argmax."""
    assert _direction_from_triplet(0.2, 0.25, 0.55) == "flat"
    assert _direction_from_triplet(0.5, 0.3, 0.2) == "up"
    assert _direction_from_triplet(None, None, None) is None


def test_json_obj_logs_on_corrupt_replay_context(caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        out = parse_json_mapping(
            "{not valid json",
            context="v2_advisory_backfill: replay_context_json",
        )
    assert out == {}
    assert any("replay_context_json unparseable" in r.message for r in caplog.records)


def test_ms_dict_does_not_stamp_live_stack_blocks():
    row = {
        "ticker": "SPY",
        "ts_utc": BASE_TS,
        "stack_runtime": {"fusion_active": True, "source": "live_parallel_stack"},
        "stack_governance": {"policy": "ok", "source": "live_parallel_stack"},
        "signal_chain": {"chain_id": "abc", "source": "live_parallel_stack"},
    }
    ms = ms_dict_from_snapshot_row(row)
    assert "stack_runtime" not in ms["live_ms_field_sources"]
    assert "stack_governance" not in ms["live_ms_field_sources"]
    assert "signal_chain" not in ms["live_ms_field_sources"]
    assert ms["stack_runtime"]["source"] == "live_parallel_stack"


def test_ms_dict_stamps_missing_stack_blocks():
    ms = ms_dict_from_snapshot_row({"ticker": "SPY", "ts_utc": BASE_TS})
    for block in ("stack_runtime", "stack_governance", "signal_chain"):
        assert ms[block]["source"] == RECONSTRUCTED_LIVE_MS_SOURCE
        assert ms["live_ms_field_sources"][block] == RECONSTRUCTED_LIVE_MS_SOURCE


def test_backfill_marks_row_error_and_continues(tmp_path, monkeypatch):
    db_path, conn = _seed_db(tmp_path)
    _insert_calibration_row(conn, ts=BASE_TS, ticker="SPY")
    _insert_calibration_row(conn, ts=BASE_TS + 60.0, ticker="QQQ")
    _insert_snapshot(conn, ts=BASE_TS, ticker="SPY")
    _insert_snapshot(conn, ts=BASE_TS + 60.0, ticker="QQQ")
    conn.commit()
    conn.close()

    def _fake_build(snap):
        if float(snap["ts_utc"]) == BASE_TS:
            raise ValueError("malformed snapshot row")
        return build_v2_advisory_snapshot(snap)

    monkeypatch.setattr(
        "calibration.v2_advisory_backfill.build_v2_advisory_snapshot",
        _fake_build,
    )

    stats = backfill_v2_advisory_decisions(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = {r["ticker"]: r for r in conn.execute("SELECT * FROM calibration_decision_log").fetchall()}
    conn.close()

    assert stats["updated"] == 1
    assert stats["errored"] == 1
    assert rows["SPY"]["advisory_v2_backfill_status"] == "error"
    assert rows["SPY"]["advisory_v2_backfill_reason"].startswith("build_failed:ValueError:")
    assert rows["QQQ"]["advisory_v2_backfill_status"] == "ok"
    assert rows["QQQ"]["advisory_v2_decision_snapshot_json"] is not None
