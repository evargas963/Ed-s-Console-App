"""Training-side canonical MVP boundary: tabular validation, sequence merge, cache identity."""
from __future__ import annotations




def _minimal_valid_db_row() -> dict:
    """Enough for canonical MVP + lstm encode (legacy-shaped merge)."""
    return {
        "spot": 100.0,
        "spread": 0.05,
        "zone": "pin_bull",
        "nearest_above_dist": 1.0,
        "nearest_below_dist": 1.0,
        "net_gamma": 0.01,
        "vwap_side": "above",
        "vwap_dist_pts": 0.2,
        "absorption_score": 0.0,
        "continuation_score": 0.0,
        "candle_body_pts": 0.1,
        "candle_range_pts": 0.2,
        "dist_call_gamma_wall": 1.0,
        "dist_put_gamma_wall": 1.0,
        "dist_gamma_inflection": 1.0,
        "dist_delta_inflection": 1.0,
        "dist_call_oi_wall": 1.0,
        "dist_put_oi_wall": 1.0,
        "net_delta": 0.0,
        "charm_net": 0.0,
        "spy_chg_pct": 0.0,
        "qqq_chg_pct": 0.0,
        "iwm_chg_pct": 0.0,
        "spy_weighted_push": 0.0,
        "qqq_weighted_push": 0.0,
        "iwm_weighted_push": 0.0,
        "vix_level": 15.0,
        "iv_level": 0.3,
    }












def _make_snapshots_db(tmp_path, rows_per_ticker: dict) -> str:
    """Build a minimal snapshots_1m_normalized fixture DB for preflight tests."""
    import sqlite3
    db = tmp_path / "preflight.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE snapshots_1m_normalized ("
        "snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "ticker TEXT NOT NULL, timeframe TEXT NOT NULL, ts_utc REAL NOT NULL, "
        "spot REAL, spread REAL, zone TEXT, "
        "nearest_above_dist REAL, nearest_below_dist REAL, net_gamma REAL, "
        "vwap_side TEXT, vwap_dist_pts REAL, "
        "absorption_score REAL, continuation_score REAL)"
    )
    for ticker, rows in rows_per_ticker.items():
        for ts, row_overrides in enumerate(rows, start=1):
            base = {
                "ticker": ticker, "timeframe": "1m", "ts_utc": float(ts),
                "spot": 100.0, "spread": 0.05, "zone": "pin_neutral",
                "nearest_above_dist": 1.0, "nearest_below_dist": -1.0,
                "net_gamma": 0.0, "vwap_side": "above", "vwap_dist_pts": 0.2,
                "absorption_score": None, "continuation_score": None,
            }
            base.update(row_overrides)
            cols = ", ".join(base.keys())
            ph = ", ".join("?" for _ in base)
            conn.execute(
                f"INSERT INTO snapshots_1m_normalized ({cols}) VALUES ({ph})",
                list(base.values()),
            )
    conn.commit()
    conn.close()
    return str(db)


def test_preflight_passes_when_all_tickers_valid(tmp_path):
    """DATA-PIPELINE-INTEGRITY Pass 2 — preflight gate happy path."""
    from features.training_canonical_input import preflight_tickers_for_training

    db_path = _make_snapshots_db(tmp_path, {"SPY": [{}] * 10, "QQQ": [{}] * 10})
    result = preflight_tickers_for_training(db_path, ["SPY", "QQQ"], sample_rows=10)
    assert result["ok"] is True
    assert sorted(result["tickers_ok"]) == ["QQQ", "SPY"]
    assert result["tickers_failed"] == {}
    assert result["tickers_no_data"] == []
    assert result["sample_rows_per_ticker"] == 10


def test_preflight_excludes_failing_ticker_but_keeps_run_alive(tmp_path):
    """Pass 2 — one ticker with a contract violation must be excluded but
    not abort the whole run; the others stay eligible."""
    from features.training_canonical_input import preflight_tickers_for_training

    # SPY first row has an INVALID zone (vocabulary violation; not a missing
    # value, so it can't be laundered to None by the NaN fix). QQQ is clean.
    db_path = _make_snapshots_db(
        tmp_path,
        {"SPY": [{"zone": "not_a_real_zone"}] + [{}] * 9, "QQQ": [{}] * 10},
    )
    result = preflight_tickers_for_training(db_path, ["SPY", "QQQ"], sample_rows=10)
    assert result["ok"] is False
    assert result["tickers_ok"] == ["QQQ"]
    assert "SPY" in result["tickers_failed"]
    assert "not_a_real_zone" in result["tickers_failed"]["SPY"]


def test_preflight_treats_pandas_nan_as_missing_end_to_end(tmp_path):
    """Pass 1 (fd0accd) NaN -> None fix verified end-to-end through preflight:
    a ticker with NULL absorption_score in every row must pass preflight (was
    the SPY/QQQ/IWM/megacap row-0 fail class on 2026-05-25)."""
    from features.training_canonical_input import preflight_tickers_for_training

    db_path = _make_snapshots_db(
        tmp_path,
        {"SPY": [{"absorption_score": None}] * 50},  # all NULL — pandas loads as NaN
    )
    result = preflight_tickers_for_training(db_path, ["SPY"], sample_rows=50)
    assert result["ok"] is True
    assert result["tickers_ok"] == ["SPY"]


def test_preflight_buckets_tickers_with_no_rows_separately(tmp_path):
    """Preflight must distinguish "schema-incompatible / contract-violating"
    (blocking) from "no rows yet" (not blocking; training skips naturally)."""
    from features.training_canonical_input import preflight_tickers_for_training

    db_path = _make_snapshots_db(tmp_path, {"SPY": [{}] * 5})  # only SPY has rows
    result = preflight_tickers_for_training(db_path, ["SPY", "BRAND_NEW_TICKER"], sample_rows=10)
    assert result["ok"] is True  # no failures
    assert result["tickers_ok"] == ["SPY"]
    assert result["tickers_no_data"] == ["BRAND_NEW_TICKER"]
    assert result["tickers_failed"] == {}


def test_db_training_fingerprint_fail_closed_when_table_missing(tmp_path):
    """Empty console DB files are in-scope: governed empty fingerprint, not OperationalError."""
    from training_cache import db_training_fingerprint

    db = tmp_path / "touch.db"
    db.write_bytes(b"")
    fp = db_training_fingerprint(str(db), "SPY")
    assert fp["row_count"] == 0
    assert fp["schema_absent"] is True
    assert fp["table"] == "snapshots_1m_normalized"


def test_preflight_returns_structured_error_when_table_missing(tmp_path):
    """If snapshots_1m_normalized doesn't exist, preflight should mark every
    ticker as sql_error (so wire-in caller can decide whether to abort)."""
    import sqlite3
    from features.training_canonical_input import preflight_tickers_for_training

    db = tmp_path / "no_table.db"
    sqlite3.connect(str(db)).close()
    result = preflight_tickers_for_training(str(db), ["SPY", "QQQ"], sample_rows=10)
    assert result["ok"] is False
    assert "SPY" in result["tickers_failed"]
    assert "QQQ" in result["tickers_failed"]
    assert "sql_error" in result["tickers_failed"]["SPY"]














def test_lstm_feature_ordering_stable():
    from lstm_data import CONFLUENCE_FEATURES, FEATURES_5M, FEATURES_1M
    from ml_train import tabular_training_feature_names

    tabular = tabular_training_feature_names()
    expected_stream = [n for n in tabular if n not in frozenset(CONFLUENCE_FEATURES)]
    assert FEATURES_5M == expected_stream
    assert FEATURES_1M == expected_stream
    assert set(CONFLUENCE_FEATURES).issubset(set(tabular))
    assert "cat_zone" in FEATURES_5M








def test_meta_assembly_uses_canonical_dataframe_ingress() -> None:
    """Source lock: scheduler META must not call df.to_dict('records') directly."""
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "ml_scheduler.py").read_text(encoding="utf-8")
    assert "records_for_mvp_from_dataframe" in text
    # TEST_SYSTEM_REHAB_V2: was `'.to_dict("records")' not in text or
    # "records_for_mvp_from_dataframe(df)" in text` -- a whole-file OR, so a
    # reintroduced raw `df.to_dict("records")` in the META block would pass as long
    # as records_for_mvp_from_dataframe(df) is STILL called anywhere else in the
    # file, exactly the direct-call regression this line claims to ban. Made an
    # unconditional ban, matching the two explicit bans immediately below it.
    assert '.to_dict("records")' not in text, (
        "ml_scheduler.py calls df.to_dict('records') directly -- must go through "
        "records_for_mvp_from_dataframe(df) instead")
    # Explicit ban: no inline list-comp over raw to_dict in meta block
    assert "[clean_dataframe_row_dict(r) for r in df.to_dict" not in text
    assert '[normalize_pandas_sql_null_row_dict(r) for r in df.to_dict' not in text
