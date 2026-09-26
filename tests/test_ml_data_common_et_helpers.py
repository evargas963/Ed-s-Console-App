"""Direct unit tests for ml_data_common ET helpers (FIND-CAL-TS item-6)."""

from __future__ import annotations





# ── Workstream B3 — chronological inner holdout split ────────────────────────










# ── Workstream B3+ — degeneracy diagnostics (balanced_accuracy + per-class recall) ──

_TRI = ["up", "down", "flat"]
























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

    RC-332 moved the confluence read out of `attach_confluence_features_for_serve` and into
    `fetch_confluence_history`, the single population authority, so the SQL this guards now
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
        "belongs to fetch_confluence_history (RC-332)")
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

