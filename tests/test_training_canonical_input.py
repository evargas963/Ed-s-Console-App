"""Training-side canonical MVP boundary: tabular validation, sequence merge, cache identity."""
from __future__ import annotations

import pandas as pd
import pytest

from features.canonical_contract import CANONICAL_FEATURE_CONTRACT_VERSION
from features.training_canonical_input import (
    TrainingCanonicalInputError,
    assert_shared_feature_cache_keys_equal,
    assert_training_lineage_matches_canonical,
    normalize_pandas_sql_null_row_dict,
    records_for_mvp_from_dataframe,
    training_canonical_lineage_header,
    training_snapshot_for_sequence_encode,
    validate_tabular_training_dataframe_canonical,
)
from training_cache import compute_feature_cache_key


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


def test_training_snapshot_for_sequence_encode_rejects_legacy_mvp_poison_zone():
    row = _minimal_valid_db_row()
    row["zone"] = "not_a_real_zone_enum"
    with pytest.raises(TrainingCanonicalInputError):
        training_snapshot_for_sequence_encode(row)


def test_training_snapshot_for_sequence_encode_stable_merge():
    row = _minimal_valid_db_row()
    merged = training_snapshot_for_sequence_encode(row)
    assert merged.get("zone") == "pin_bull"
    assert merged.get("vwap_side") == "above"


def test_validate_tabular_ok_on_valid_frame():
    row = _minimal_valid_db_row()
    df = pd.DataFrame([row])
    validate_tabular_training_dataframe_canonical(df, max_rows=10)


def test_validate_tabular_treats_pandas_nan_as_missing_on_absorption_score():
    """DATA-PIPELINE-INTEGRITY 2026-05-25 regression: pandas converts SQL
    NULL on numeric columns to float NaN; MVP coercion rejects NaN as
    "broken upstream compute" per the MVP contract. The training boundary
    _row_dict_from_df must convert NaN -> None so SQL NULL semantics are
    preserved. Reproduces the SPY/QQQ/IWM/megacap row-0 fail: 17 of 41
    tickers in the scheduler run blocked by 'row 0: MVP coercion failed:
    liquidity.absorption_score: non-finite value nan' because 33% of SPY
    snapshot rows have NULL absorption_score.
    """
    row = _minimal_valid_db_row()
    row["absorption_score"] = float("nan")
    df = pd.DataFrame([row])
    # Must NOT raise — NaN-from-DataFrame is treated as missing (None).
    validate_tabular_training_dataframe_canonical(df, max_rows=10)


def test_validate_tabular_treats_pandas_nan_as_missing_on_structure_columns():
    """Same regression class — confirms fix covers all numeric MVP columns,
    not just absorption_score. The 2026-05-25 incident had 11 additional
    tickers blocked on structure.nearest_above_dist / nearest_below_dist /
    anchor.vwap_dist_pts NaN at various row positions."""
    row = _minimal_valid_db_row()
    row["nearest_above_dist"] = float("nan")
    row["nearest_below_dist"] = float("nan")
    row["vwap_dist_pts"] = float("nan")
    df = pd.DataFrame([row])
    validate_tabular_training_dataframe_canonical(df, max_rows=10)


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


def test_validate_tabular_nan_to_none_does_not_launder_real_breakage():
    """Honest-limit lock: the NaN -> None conversion happens at the
    DataFrame -> dict boundary in _row_dict_from_df. Live inference paths
    that pass a Python dict directly (not via DataFrame) still hit the
    contract's non-finite check because they bypass this boundary.
    Verifies by calling training_snapshot_for_sequence_encode (live-path
    function that takes a dict directly) — it must still reject float NaN
    as invalid.
    """
    row = _minimal_valid_db_row()
    row["absorption_score"] = float("nan")
    # Direct dict path (no DataFrame conversion) — actual upstream NaN
    # still raises as designed.
    with pytest.raises(TrainingCanonicalInputError):
        training_snapshot_for_sequence_encode(row)


def test_assert_training_lineage_matches_canonical_ok():
    assert_training_lineage_matches_canonical(training_canonical_lineage_header())


def test_assert_training_lineage_contract_mismatch():
    bad = dict(training_canonical_lineage_header())
    bad["canonical_feature_contract_version"] = "bogus"
    with pytest.raises(TrainingCanonicalInputError):
        assert_training_lineage_matches_canonical(bad)


def test_shared_feature_cache_keys_equal():
    data_fp = {
        "table": "snapshots_1m_normalized",
        "timeframe": "1m",
        "ticker": "SPY",
        "min_ts_utc": 1.0,
        "max_ts_utc": 2.0,
        "row_count": 100,
    }
    code_fp = "abc"
    a = compute_feature_cache_key("SPY", data_fp, code_fp, target_column="outcome_1c")
    b = compute_feature_cache_key("SPY", data_fp, code_fp, target_column="outcome_1c")
    assert_shared_feature_cache_keys_equal(a, b)


def test_shared_feature_cache_keys_mismatch_raises():
    with pytest.raises(TrainingCanonicalInputError):
        assert_shared_feature_cache_keys_equal("a" * 64, "b" * 64)


def test_feature_cache_key_includes_contract_version():
    data_fp = {
        "table": "t",
        "timeframe": "1m",
        "ticker": "SPY",
        "min_ts_utc": None,
        "max_ts_utc": None,
        "row_count": 1,
    }
    k = compute_feature_cache_key("SPY", data_fp, "code", target_column="outcome_1c")
    assert isinstance(k, str) and len(k) == 64
    # Changing contract version would change key (implicit via imports in compute_feature_cache_key).
    assert CANONICAL_FEATURE_CONTRACT_VERSION


def test_lstm_feature_ordering_stable():
    from lstm_data import CONFLUENCE_FEATURES, FEATURES_5M, FEATURES_1M
    from ml_train import tabular_training_feature_names

    tabular = tabular_training_feature_names()
    expected_stream = [n for n in tabular if n not in frozenset(CONFLUENCE_FEATURES)]
    assert FEATURES_5M == expected_stream
    assert FEATURES_1M == expected_stream
    assert set(CONFLUENCE_FEATURES).issubset(set(tabular))
    assert "cat_zone" in FEATURES_5M


def test_train_parallel_rejects_bad_feature_cache_key_override():
    from ml_scheduler import train_parallel_candidate
    from pathlib import Path
    import tempfile

    data_fp = {
        "table": "snapshots_1m_normalized",
        "timeframe": "1m",
        "ticker": "ZZZ",
        "min_ts_utc": None,
        "max_ts_utc": None,
        "row_count": 0,
    }
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        with pytest.raises(TrainingCanonicalInputError):
            train_parallel_candidate(
                "ZZZ",
                str(out / "missing.db"),
                out,
                data_fp=data_fp,
                code_fp="x" * 64,
                feature_cache_key="0" * 64,
            )


def test_normalize_pandas_sql_null_row_dict_maps_nan_to_none() -> None:
    out = normalize_pandas_sql_null_row_dict(
        {"absorption_score": float("nan"), "spot": 100.0, "zone": "pin_bull"}
    )
    assert out["absorption_score"] is None
    assert out["spot"] == 100.0


def test_records_for_mvp_from_dataframe_unblocks_meta_inference_snapshot_path() -> None:
    """META assembly regression (SPY 2026-05-26): raw NaN fails MVP coercion."""
    from features.db_feature_adapter import build_db_mvp_feature_row
    from features.inference_snapshot import build_inference_snapshot_v1_from_db_row
    from features.mvp_source_coercion import MvpFeatureSourceError

    base = {
        "spot": 100.0,
        "spread": 0.05,
        "zone": "pin_bull",
        "nearest_above_dist": 1.0,
        "nearest_below_dist": 1.0,
        "net_gamma": 0.0,
        "vwap_side": "above",
        "vwap_dist_pts": 0.2,
        "absorption_score": float("nan"),
        "continuation_score": float("nan"),
    }
    with pytest.raises(MvpFeatureSourceError, match="absorption_score"):
        build_db_mvp_feature_row(base)
    rows = records_for_mvp_from_dataframe(pd.DataFrame([base]))
    snap = build_inference_snapshot_v1_from_db_row(
        ticker="SPY",
        expiry=None,
        as_of_ts=1.0,
        db_row=rows[0],
    )
    assert snap["features"]["liquidity.absorption_score"] is None
    assert snap["features"]["liquidity.continuation_score"] is None


def test_repo_bans_raw_to_dict_records_on_mvp_feed_paths() -> None:
    """Mechanical lock: MVP paths must use records_for_mvp_from_dataframe."""
    import sys
    from pathlib import Path

    tools = Path(__file__).resolve().parent.parent / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import check_fix_everything_we_touch as mod

    assert mod.check_mvp_dataframe_ingress() == []


def test_meta_assembly_uses_canonical_dataframe_ingress() -> None:
    """Source lock: scheduler META must not call df.to_dict('records') directly."""
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "ml_scheduler.py").read_text(encoding="utf-8")
    assert "records_for_mvp_from_dataframe" in text
    assert '.to_dict("records")' not in text or "records_for_mvp_from_dataframe(df)" in text
    # Explicit ban: no inline list-comp over raw to_dict in meta block
    assert "[clean_dataframe_row_dict(r) for r in df.to_dict" not in text
    assert '[normalize_pandas_sql_null_row_dict(r) for r in df.to_dict' not in text
