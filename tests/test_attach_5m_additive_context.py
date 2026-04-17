"""merge_asof sorting contract for attach_5m_additive_context (ml_data_common)."""
from __future__ import annotations

import sqlite3

import pandas as pd

import ml_data_common as mdc


def test_attach_5m_additive_context_unsorted_left_merge_succeeds(monkeypatch, tmp_path):
    """
    Left frame intentionally not sorted by (ticker, ts_utc) — as when SQL uses ORDER BY ts_utc
    only across multiple tickers. merge_asof must not raise; row order must match input.
    """
    db_path = str(tmp_path / "empty.db")
    sqlite3.connect(db_path).close()

    def fake_read_sql_query(query, con, params=None):
        assert params is not None and len(params) == 2
        t, _tf = params
        assert t == "SPY"
        rows = []
        for ts in (100.0, 200.0, 300.0, 400.0):
            row: dict = {"ticker": "SPY", "ts_utc": ts}
            for c in mdc.M5_ADDITIVE_SOURCE_COLS:
                row[c] = float(ts)
            rows.append(row)
        return pd.DataFrame(rows)

    monkeypatch.setattr(pd, "read_sql_query", fake_read_sql_query)

    left = pd.DataFrame(
        {
            "ticker": ["SPY", "SPY", "SPY", "SPY"],
            "ts_utc": [350.0, 150.0, 400.0, 120.0],
            "spot": [1, 2, 3, 4],
        }
    )
    out = mdc.attach_5m_additive_context(left, db_path=db_path)
    assert len(out) == 4
    assert list(out["spot"]) == [1, 2, 3, 4]
    first_m5 = f"m5_{mdc.M5_ADDITIVE_SOURCE_COLS[0]}"
    assert float(out.iloc[0][first_m5]) == 300.0
    assert float(out.iloc[1][first_m5]) == 100.0
    assert float(out.iloc[2][first_m5]) == 400.0
    assert float(out.iloc[3][first_m5]) == 100.0


def test_attach_5m_object_ts_utc_sorted_numerically_not_lexically(monkeypatch, tmp_path):
    """
    ts_utc as strings that sort differently lexicographically vs numerically would break
    merge_asof without pd.to_numeric (e.g. '900' before '1000' lex, but 1000 > 900 numerically).
    """
    db_path = str(tmp_path / "empty2.db")
    sqlite3.connect(db_path).close()

    def fake_read_sql_query(query, con, params=None):
        rows = []
        for ts in (100.0, 900.0, 1000.0):
            row: dict = {"ticker": "SPY", "ts_utc": ts}
            for c in mdc.M5_ADDITIVE_SOURCE_COLS:
                row[c] = float(ts)
            rows.append(row)
        return pd.DataFrame(rows)

    monkeypatch.setattr(pd, "read_sql_query", fake_read_sql_query)

    left = pd.DataFrame(
        {
            "ticker": ["SPY", "SPY"],
            "ts_utc": ["1000", "900"],
            "spot": [1, 2],
        }
    )
    out = mdc.attach_5m_additive_context(left, db_path=db_path)
    assert len(out) == 2
    assert list(out["spot"]) == [1, 2]
    assert float(out["ts_utc"].iloc[0]) == 1000.0
    first_m5 = f"m5_{mdc.M5_ADDITIVE_SOURCE_COLS[0]}"
    assert float(out.iloc[0][first_m5]) == 1000.0
    assert float(out.iloc[1][first_m5]) == 900.0


def test_multi_ticker_concat_breaks_global_ts_without_ts_ticker_sort(monkeypatch, tmp_path):
    """
    Production path: tickers are iterated in sorted() order (SPY then QQQ). Each SQL chunk is
    ts-asc per ticker, but concat(SPY afternoon, QQQ morning) yields ts_utc non-monotonic globally.
    pandas merge_asof validates global ts_utc monotonicity before `by=` grouping — this must merge.
    """
    db_path = str(tmp_path / "multi.db")
    sqlite3.connect(db_path).close()

    def fake_read_sql_query(query, con, params=None):
        t = params[0]
        if t == "SPY":
            tss = (1000.0, 1001.0)
        elif t == "QQQ":
            tss = (50.0, 51.0)
        else:
            raise AssertionError(t)
        rows = []
        for ts in tss:
            row: dict = {"ticker": t, "ts_utc": ts}
            for c in mdc.M5_ADDITIVE_SOURCE_COLS:
                row[c] = float(ts)
            rows.append(row)
        return pd.DataFrame(rows)

    monkeypatch.setattr(pd, "read_sql_query", fake_read_sql_query)

    left = pd.DataFrame(
        {
            "ticker": ["SPY", "QQQ", "SPY"],
            "ts_utc": [1001.0, 51.0, 1002.0],
            "spot": [10, 20, 30],
        }
    )
    out = mdc.attach_5m_additive_context(left, db_path=db_path)
    assert len(out) == 3
    assert list(out["spot"]) == [10, 20, 30]
    first_m5 = f"m5_{mdc.M5_ADDITIVE_SOURCE_COLS[0]}"
    assert float(out.iloc[0][first_m5]) == 1001.0
    assert float(out.iloc[1][first_m5]) == 51.0
    assert float(out.iloc[2][first_m5]) == 1001.0
