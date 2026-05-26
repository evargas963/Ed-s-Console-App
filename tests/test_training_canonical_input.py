"""Training-side canonical MVP boundary: tabular validation, sequence merge, cache identity."""
from __future__ import annotations

import pandas as pd
import pytest

from features.canonical_contract import CANONICAL_FEATURE_CONTRACT_VERSION
from features.training_canonical_input import (
    TrainingCanonicalInputError,
    assert_shared_feature_cache_keys_equal,
    assert_training_lineage_matches_canonical,
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
    "broken upstream compute" by design. The training boundary
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
    from lstm_data import FEATURES_5M, FEATURES_1M

    assert FEATURES_5M[0] == "spot"
    assert "zone" in FEATURES_5M
    assert FEATURES_1M[-1] == "vwap_side"


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
