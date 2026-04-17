"""m5_* additive merge must follow 1m when canonical rows exist (Issue: dead 5m stream)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_data_common import M5_ADDITIVE_SOURCE_COLS, attach_5m_additive_context, fetch_m5_additive_dict
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


def test_attach_5m_uses_per_ticker_timeframe(tmp_path):
    db = tmp_path / "t2.db"
    conn = sqlite3.connect(str(db))
    snap_cols = (
        "ticker TEXT, timeframe TEXT, ts_utc REAL, "
        + ", ".join(f"{c} REAL" for c in M5_ADDITIVE_SOURCE_COLS)
    )
    conn.execute("CREATE TABLE snapshots (" + snap_cols + ")")
    icols = "ticker, timeframe, ts_utc, " + ", ".join(M5_ADDITIVE_SOURCE_COLS)
    ph_feat = ",".join(["?"] * len(M5_ADDITIVE_SOURCE_COLS))

    def ins(tkr, tf, ts, net_gamma):
        z = [0.0] * len(M5_ADDITIVE_SOURCE_COLS)
        ix = list(M5_ADDITIVE_SOURCE_COLS).index("net_gamma")
        z[ix] = float(net_gamma)
        conn.execute(
            f"INSERT INTO snapshots ({icols}) VALUES (?,?,?,{ph_feat})",
            [tkr, tf, ts] + z,
        )

    ins("QQQ", DERIVED_TIMEFRAME, 10.0, 11.0)
    ins("SPY", DERIVED_TIMEFRAME, 10.0, 1.0)
    ins("SPY", CANONICAL_TIMEFRAME, 20.0, 42.0)
    conn.commit()
    conn.close()

    df = pd.DataFrame(
        {
            "ticker": ["SPY", "QQQ"],
            "ts_utc": [25.0, 15.0],
            "spot": [1.0, 1.0],
        }
    )
    out = attach_5m_additive_context(df, db_path=str(db))
    spy = out.loc[out["ticker"] == "SPY"].iloc[0]
    qqq = out.loc[out["ticker"] == "QQQ"].iloc[0]
    assert spy["m5_net_gamma"] == pytest.approx(42.0)
    assert qqq["m5_net_gamma"] == pytest.approx(11.0)
