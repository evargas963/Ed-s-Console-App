"""m5_* additive merge must follow 1m when canonical rows exist (Issue: dead 5m stream)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))





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
