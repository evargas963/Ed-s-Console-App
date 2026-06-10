"""m5_* additive merge must follow 1m when canonical rows exist (Issue: dead 5m stream)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_data_common import M5_ADDITIVE_SOURCE_COLS, fetch_m5_additive_dict
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME


def test_fetch_m5_additive_prefers_1m_when_both_exist(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    cols = ["ticker", "timeframe", "ts_utc"] + list(M5_ADDITIVE_SOURCE_COLS)
    conn.execute("CREATE TABLE snapshots (" + ", ".join(f"{c} REAL" for c in cols) + ")")
    ph = ",".join(["?"] * len(cols))

    def insert(*, ticker, timeframe, ts_utc, **gamma_rest):
        row = {c: 0.0 for c in M5_ADDITIVE_SOURCE_COLS}
        row.update(gamma_rest)
        vals = [ticker, timeframe, ts_utc] + [row[c] for c in M5_ADDITIVE_SOURCE_COLS]
        conn.execute(f"INSERT INTO snapshots ({','.join(cols)}) VALUES ({ph})", vals)

    insert(ticker="SPY", timeframe=DERIVED_TIMEFRAME, ts_utc=100.0, net_gamma=1.0)
    insert(ticker="SPY", timeframe=CANONICAL_TIMEFRAME, ts_utc=200.0, net_gamma=99.0)
    conn.commit()
    conn.close()

    d = fetch_m5_additive_dict("SPY", 250.0, db_path=str(db))
    assert d.get("m5_net_gamma") == pytest.approx(99.0)


def test_attach_confluence_features_for_serve_reads_sqlite_rows_as_dicts(tmp_path):
    from lstm_data import CONFLUENCE_FEATURES
    from ml_data_common import attach_confluence_features_for_serve
    from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M

    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        f"CREATE TABLE {SNAPSHOT_TABLE_1M} (ticker TEXT, timeframe TEXT, ts_utc REAL, spot REAL)"
    )
    conn.execute(
        f"INSERT INTO {SNAPSHOT_TABLE_1M} (ticker, timeframe, ts_utc, spot) VALUES (?, ?, ?, ?)",
        ("SPY", CANONICAL_TIMEFRAME, 100.0, 500.0),
    )
    conn.commit()
    conn.close()

    out = attach_confluence_features_for_serve(
        {"ticker": "SPY", "ts_utc": 100.0, "spot": 500.0},
        db_path=str(db),
    )
    for cf in CONFLUENCE_FEATURES:
        assert cf in out
