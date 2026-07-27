"""RC-6 Phase A: after the option_chain_json / replay_context_json blobs are DROPPED from
snapshots_1m_normalized, the two readers must still find them by JOIN to `snapshots`.

The fixtures build the exact POST-DROP shape — snapshots carries the blobs, the normalized
table does NOT have the columns at all — so a reader that still named the normalized columns
would raise 'no such column'. These tests fail if the RC-6 repoint regresses.
"""
import sqlite3
from pathlib import Path

import pytest

from live_vs_replay_validation import run_live_vs_replay_validation
from replay_bundle_coverage import _coverage_for_table
from timeframe_config import CANONICAL_TIMEFRAME

_OC = '{"contracts":[{"k":450,"g":0.05}]}'   # >10 chars -> passes REPLAY_BUNDLE_MIN_JSON_LENGTH
_RC = '{"replay_max_hold_bars":5,"note":"bundle"}'
_N = 6


def _build_postdrop_db(p: Path) -> None:
    c = sqlite3.connect(str(p))
    # snapshots KEEPS the blobs
    c.execute(
        "CREATE TABLE snapshots (snapshot_id INTEGER PRIMARY KEY, ticker TEXT, timeframe TEXT, "
        "ts_utc INTEGER, ts_et TEXT, expiry TEXT, spot REAL, combined_signal TEXT, "
        "option_chain_json TEXT, replay_context_json TEXT, rules_entry REAL, rules_stop REAL, "
        "rules_target REAL)"
    )
    # normalized is the POST-DROP shape: NO option_chain_json / replay_context_json columns
    c.execute(
        "CREATE TABLE snapshots_1m_normalized (snapshot_id INTEGER PRIMARY KEY, ticker TEXT, "
        "timeframe TEXT, ts_utc INTEGER, ts_et TEXT, expiry TEXT, spot REAL, combined_signal TEXT, "
        "rules_entry REAL, rules_stop REAL, rules_target REAL)"
    )
    for i in range(_N):
        tkr, tf, ts = "SPY", CANONICAL_TIMEFRAME, 1000 + i
        # snapshots: 13 cols (id, ticker, timeframe, ts_utc, ts_et, expiry, spot,
        # combined_signal, option_chain_json, replay_context_json, rules_entry/stop/target)
        c.execute(
            "INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (i + 1, tkr, tf, ts, f"et{i}", f"2026-07-2{i}", 450.0 + i, "no_trade",
             _OC, _RC, None, None, None),
        )
        # normalized post-drop: 11 cols (same, MINUS the two blob columns)
        c.execute(
            "INSERT INTO snapshots_1m_normalized VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (i + 1, tkr, tf, ts, f"et{i}", f"2026-07-2{i}", 450.0 + i, "no_trade",
             None, None, None),
        )
    c.commit()
    c.close()


def test_normalized_table_truly_lacks_the_blobs(tmp_path):
    """Guards the fixtures: the normalized table must NOT have the columns, else the JOIN
    tests below would pass trivially against the old copy."""
    p = tmp_path / "d.db"
    _build_postdrop_db(p)
    c = sqlite3.connect(str(p))
    try:
        with pytest.raises(sqlite3.OperationalError):
            c.execute("SELECT option_chain_json FROM snapshots_1m_normalized").fetchone()
    finally:
        c.close()


def test_replay_bundle_coverage_reads_blobs_via_join_after_drop(tmp_path):
    p = tmp_path / "d.db"
    _build_postdrop_db(p)
    c = sqlite3.connect(str(p))
    c.row_factory = sqlite3.Row
    try:
        norm = _coverage_for_table(c, "snapshots_1m_normalized", timeframe=CANONICAL_TIMEFRAME)
        assert norm["rows_total"] == _N
        assert norm["rows_with_full_bundle"] == _N   # full bundle found via JOIN to snapshots
        assert norm["by_ticker"][0]["rows_with_full_bundle"] == _N
        base = _coverage_for_table(c, "snapshots", timeframe=CANONICAL_TIMEFRAME)
        assert base["rows_with_full_bundle"] == _N   # self-join path also correct
    finally:
        c.close()


def test_live_vs_replay_counts_bundles_via_join_after_drop(tmp_path):
    p = tmp_path / "d.db"
    _build_postdrop_db(p)
    # table defaults to snapshots_1m_normalized; a non-repointed reader would raise
    # 'no such column: option_chain_json' here.
    report = run_live_vs_replay_validation(str(p), n=_N, min_required=1)
    assert isinstance(report, dict)
    assert report["rows_available_full_bundle"] == _N
