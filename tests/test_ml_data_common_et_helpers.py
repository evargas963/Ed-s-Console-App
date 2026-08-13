"""Direct unit tests for ml_data_common ET helpers (FIND-CAL-TS item-6)."""

from __future__ import annotations

import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from ml_data_common import (
    INNER_VAL_MIN_ROWS,
    filter_df_to_rth_ts_utc,
    head_rth_df_from_ts_utc,
    holdout_class_metrics,
    market_session_from_ts_utc,
    rth_where_clause,
    stamp_et_clock_columns,
    time_ordered_tail_split,
    training_base_where_clause,
)


# ── Workstream B3 — chronological inner holdout split ────────────────────────


def test_time_ordered_tail_split_holds_out_recent_tail():
    n = 1000
    train_end, n_val = time_ordered_tail_split(n, val_fraction=0.15)
    assert n_val == 150                      # last 15% (most recent) held out
    assert train_end == 850                  # earlier rows train
    assert train_end + n_val == n            # partition is exhaustive + disjoint


def test_time_ordered_tail_split_no_holdout_when_val_too_small():
    # round(80*0.15)=12 < INNER_VAL_MIN_ROWS -> no holdout (caller trains in-sample).
    train_end, n_val = time_ordered_tail_split(80, val_fraction=0.15)
    assert (train_end, n_val) == (80, 0)
    assert 12 < INNER_VAL_MIN_ROWS


def test_time_ordered_tail_split_no_holdout_when_train_too_small():
    # val passes min, but train would be < min_train -> no holdout.
    train_end, n_val = time_ordered_tail_split(120, val_fraction=0.5, min_val=20, min_train=100)
    assert (train_end, n_val) == (120, 0)


def test_time_ordered_tail_split_zero_rows():
    assert time_ordered_tail_split(0) == (0, 0)


# ── Workstream B3+ — degeneracy diagnostics (balanced_accuracy + per-class recall) ──

_TRI = ["up", "down", "flat"]


def test_holdout_class_metrics_all_flat_collapse_is_chance_balanced_acc():
    # 3-class eval where truth is balanced but the model predicts ONLY 'flat' (index 2):
    # top-line accuracy = flat base rate, but balanced_accuracy collapses to 1/3 (chance)
    # and the collapse flag fires.
    y_true = np.array([0, 1, 2, 0, 1, 2, 0, 1, 2])           # 1/3 each
    y_pred = np.full(9, 2)                                    # all 'flat'
    m = holdout_class_metrics(y_true, y_pred, 3, _TRI)
    assert m["single_class_collapse"] is True
    assert m["n_predicted_classes"] == 1
    assert m["predicted_class_names"] == ["flat"]
    assert m["per_class_recall"] == {"up": 0.0, "down": 0.0, "flat": 1.0}
    # balanced_accuracy = mean(0, 0, 1) = 0.3333 — does NOT clear a 0.40 bar even though
    # top-line accuracy (3/9 = 0.333 here) could look "above chance" on a flat-heavy tail.
    assert m["balanced_accuracy"] == pytest.approx(1 / 3, abs=1e-4)


def test_holdout_class_metrics_healthy_multiclass_no_collapse():
    y_true = np.array([0, 0, 1, 1, 2, 2])
    y_pred = np.array([0, 1, 1, 1, 2, 2])                     # up:1/2, down:1/1, flat:2/2
    m = holdout_class_metrics(y_true, y_pred, 3, _TRI)
    assert m["single_class_collapse"] is False
    assert m["n_predicted_classes"] == 3
    assert m["per_class_recall"] == {"up": 0.5, "down": 1.0, "flat": 1.0}
    assert m["balanced_accuracy"] == pytest.approx((0.5 + 1.0 + 1.0) / 3, abs=1e-4)


def test_holdout_class_metrics_recall_none_for_absent_class():
    # No 'down' (index 1) in the eval truth -> recall is None for it and excluded from
    # the balanced-accuracy mean (sklearn convention: present classes only).
    y_true = np.array([0, 0, 2, 2])
    y_pred = np.array([0, 0, 2, 2])
    m = holdout_class_metrics(y_true, y_pred, 3, _TRI)
    assert m["per_class_recall"]["down"] is None
    assert m["per_class_recall"]["up"] == 1.0
    assert m["per_class_recall"]["flat"] == 1.0
    assert m["balanced_accuracy"] == pytest.approx(1.0, abs=1e-4)
    # predicts up + flat (2 classes) -> not a single-class collapse
    assert m["single_class_collapse"] is False


def test_holdout_class_metrics_empty_truth():
    m = holdout_class_metrics(np.array([]), np.array([]), 3, _TRI)
    assert m["balanced_accuracy"] is None
    assert m["single_class_collapse"] is True  # 0 predicted classes <= 1


def test_rth_where_clause_emits_deprecation_warning():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        clause = rth_where_clause()
        assert "et_hour" in clause
        assert any(issubclass(x.category, DeprecationWarning) for x in w)


def test_filter_df_to_rth_drops_nan_ts_utc():
    df = pd.DataFrame({"ts_utc": [np.nan, None], "et_hour": [10, 10], "et_minute": [0, 0]})
    assert len(filter_df_to_rth_ts_utc(df)) == 0


def test_filter_df_to_rth_empty_frame():
    assert filter_df_to_rth_ts_utc(pd.DataFrame()).empty


def test_stamp_et_clock_columns_missing_ts_utc_column():
    df = pd.DataFrame({"et_hour": [9]})
    out = stamp_et_clock_columns(df)
    assert out.equals(df)


def test_training_base_where_clause_has_no_rth_on_stored_hour():
    w = training_base_where_clause()
    assert "et_hour" not in w
    assert "et_minute" not in w


def test_market_session_from_ts_utc_premarket():
    t = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc).timestamp()  # 8:00 ET
    assert market_session_from_ts_utc(t) == "premarket"


def test_head_rth_df_from_ts_utc_caps_after_filter():
    t_rth = datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc).timestamp()
    t_pre = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc).timestamp()
    df = pd.DataFrame({"ts_utc": [t_pre, t_rth, t_rth]})
    out = head_rth_df_from_ts_utc(df, 1)
    assert len(out) == 1
    assert float(out["ts_utc"].iloc[0]) == t_rth


def test_rc206_reader_contract_and_retry(tmp_path):
    """RC-206 negative control (re-applied after a shared-worktree rewrite dropped it): the
    ML readers run under the repo connection contract (busy_timeout from
    db.configure_sqlite_connection) and a corrupt DB degrades to None after bounded retries —
    never a traceback into the signals loop."""
    import sqlite3

    from ml_data_common import _console_read_conn, _read_one_row_with_retry

    good = tmp_path / "good.db"
    con = sqlite3.connect(str(good))
    con.execute("CREATE TABLE t (x REAL)")
    con.execute("INSERT INTO t VALUES (7.5)")
    con.commit()
    con.close()
    conn = _console_read_conn(str(good))
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000, (
            "reader connection does not carry the repo busy_timeout contract")
    finally:
        conn.close()
    row = _read_one_row_with_retry(str(good), "SELECT x FROM t", (), op="test")
    assert row is not None and float(row[0]) == 7.5

    bad = tmp_path / "bad.db"
    bad.write_bytes(b"SQLite format 3\x00" + b"\x00" * 400)  # header only: malformed image
    assert _read_one_row_with_retry(str(bad), "SELECT x FROM t", (), op="test") is None


def test_rc206_fetch_prior_net_gamma_survives_malformed_db(tmp_path):
    """The exact caller from the traceback signature: fetch_prior_net_gamma on a malformed
    file returns None instead of raising sqlite3.DatabaseError."""
    from ml_data_common import fetch_prior_net_gamma

    bad = tmp_path / "malformed.db"
    bad.write_bytes(b"SQLite format 3\x00" + b"\x00" * 400)
    assert fetch_prior_net_gamma("SPY", 1e9, db_path=str(bad)) is None


def test_rc206_confluence_serve_survives_malformed_db(tmp_path):
    """CLASS COMPLETION (operator caught this third raw caller live on the restarted
    console): attach_confluence_features_for_serve on a malformed DB degrades to cf_*
    defaults instead of raising into the signals loop."""
    from lstm_data import CONFLUENCE_FEATURES
    from ml_data_common import attach_confluence_features_for_serve

    bad = tmp_path / "malformed.db"
    bad.write_bytes(b"SQLite format 3\x00" + b"\x00" * 400)
    out = attach_confluence_features_for_serve(
        {"ticker": "SPY", "ts_utc": 1e9}, db_path=str(bad))
    for cf in CONFLUENCE_FEATURES:
        assert out.get(cf) == 0.0, f"{cf} not defaulted on malformed DB"


def test_rc207_serve_readers_use_snapshots_not_normalized():
    """RC-207 quarantine: live serve SQL must bind SERVE_SNAPSHOT_TABLE, not SNAPSHOT_TABLE_1M.

    The confluence read moved out of ``attach_confluence_features_for_serve`` and into
    ``fetch_confluence_history``, the single population authority, so the SQL this guards now
    lives one call down. The guarantee is asserted where the table is actually bound — and
    the delegating wrapper is separately required to bind NO table of its own, so the
    quarantine cannot be re-opened by a lane quietly growing its own query back.
    """
    import inspect

    import ml_data_common as m

    assert m.SERVE_SNAPSHOT_TABLE == "snapshots"
    for fn in (m.fetch_prior_net_gamma, m.fetch_confluence_history):
        src = inspect.getsource(fn)
        assert "SERVE_SNAPSHOT_TABLE" in src, f"{fn.__name__} does not bind the serve table"
        assert "SNAPSHOT_TABLE_1M" not in src
        # SQL f-strings must interpolate the serve table name, not the training mirror.
        assert "FROM {SERVE_SNAPSHOT_TABLE}" in src
        assert "FROM {SNAPSHOT_TABLE_1M}" not in src

    # The serve wrapper delegates; it must not carry a table binding of its own.
    wrapper = inspect.getsource(m.attach_confluence_features_for_serve)
    assert "SNAPSHOT_TABLE_1M" not in wrapper
    assert "FROM " not in wrapper, (
        "attach_confluence_features_for_serve grew its own query again — the population "
        "belongs to fetch_confluence_history")
    assert "confluence_features_for_bar" in wrapper


def test_rc207_fetch_prior_net_gamma_reads_snapshots_table(tmp_path):
    """Positive control: prior net_gamma is taken from snapshots rows."""
    import sqlite3

    from ml_data_common import fetch_prior_net_gamma
    from timeframe_config import CANONICAL_TIMEFRAME

    db = tmp_path / "serve.db"
    con = sqlite3.connect(str(db))
    con.execute(
        "CREATE TABLE snapshots (ticker TEXT, timeframe TEXT, ts_utc REAL, net_gamma REAL)"
    )
    con.execute(
        "CREATE TABLE snapshots_1m_normalized "
        "(ticker TEXT, timeframe TEXT, ts_utc REAL, net_gamma REAL)"
    )
    # Poison normalized with a different value — serve must ignore it.
    con.execute(
        "INSERT INTO snapshots_1m_normalized VALUES (?,?,?,?)",
        ("SPY", CANONICAL_TIMEFRAME, 1000.0, 111.0),
    )
    con.execute(
        "INSERT INTO snapshots VALUES (?,?,?,?)",
        ("SPY", CANONICAL_TIMEFRAME, 1000.0, 222.0),
    )
    con.commit()
    con.close()
    got = fetch_prior_net_gamma("SPY", 2000.0, db_path=str(db))
    assert got == 222.0


def test_rc207_rebuild_tool_measure_and_dry_defaults(tmp_path):
    """Rebuild tool measure mode writes a report and does not require --execute-clone."""
    import json
    import sqlite3
    from pathlib import Path

    from tools.rebuild_snapshots_1m_normalized_v1 import main

    db = tmp_path / "tiny.db"
    con = sqlite3.connect(str(db))
    con.execute(
        "CREATE TABLE snapshots (ticker TEXT, timeframe TEXT, ts_utc REAL, net_gamma REAL)"
    )
    con.execute(
        "INSERT INTO snapshots VALUES ('SPY','1m',1000.0,1.5)"
    )
    con.execute(
        "CREATE TABLE snapshots_1m_normalized AS SELECT * FROM snapshots WHERE 0"
    )
    con.commit()
    con.close()
    report = tmp_path / "r.json"
    rc = main(["--db", str(db), "--report", str(report)])
    assert rc == 0
    doc = json.loads(Path(report).read_text(encoding="utf-8"))
    assert doc["mode"] == "measure"
    assert doc.get("snapshots_prior_net_gamma", {}).get("ok") is True


def test_rc248_repair_tool_runs_when_invoked_BY_PATH(tmp_path):
    """RC-248: the operator ran this tool the documented way and got a traceback.

    `from db import configure_sqlite_connection` inside _connect needs the REPO root on
    sys.path; run by PATH, Python puts tools/ there instead, so the tool died with
    ModuleNotFoundError before it could measure anything — on a REPAIR tool, reached for when
    something is already broken, by someone following a written instruction.

    The test above imports main() and therefore CANNOT catch this: by the time it runs, pytest
    has already put the repo root on the path. Only executing the tool as its own process, by
    path, exercises what the operator actually typed.
    """
    import sqlite3
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    script = repo / "tools" / "rebuild_snapshots_1m_normalized_v1.py"
    db = tmp_path / "probe.db"
    sqlite3.connect(str(db)).close()
    report = tmp_path / "rc248_report.json"

    out = subprocess.run(
        [sys.executable, str(script), "--db", str(db), "--report", str(report)],
        capture_output=True, text=True, timeout=300,
        cwd=str(tmp_path),          # NOT the repo root — the path form must not depend on CWD
    )
    assert "ModuleNotFoundError" not in out.stderr, (
        f"the repair tool still cannot be run by path (RC-248): {out.stderr[-400:]}"
    )
    assert out.returncode == 0, out.stderr[-400:]
    assert report.is_file(), "path-invoked run produced no report"
