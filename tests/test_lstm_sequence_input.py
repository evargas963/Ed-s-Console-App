"""LSTM sequence input: canonical MVP merge + InferenceSnapshotV1 live bar."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _minimal_valid_inference_v1():
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row
    from features.canonical_contract import get_mvp_feature_names

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = 400.0
    feats["price.spread_pts"] = 0.02
    feats["structure.zone"] = "pin_bull"
    feats["structure.nearest_above_dist"] = 1.0
    feats["structure.nearest_below_dist"] = -1.0
    feats["structure.net_gamma"] = 0.0
    feats["anchor.vwap_side"] = "above"
    feats["anchor.vwap_dist_pts"] = 0.1
    return build_inference_snapshot_v1_from_feature_row(
        ticker="SPY",
        expiry=None,
        as_of_ts=1_700_000_100.0,
        features=feats,
    )


def _base_db_row(ts_utc: float, spot: float = 450.0) -> dict:
    return {
        "ts_utc": ts_utc,
        "ticker": "SPY",
        "spot": spot,
        "spread": 0.02,
        "zone": "pin_neutral",
        "nearest_above_dist": 2.0,
        "nearest_below_dist": -2.0,
        "net_gamma": 1.0,
        "vwap_side": "below",
        "vwap_dist_pts": 9.99,
        "absorption_score": None,
        "continuation_score": None,
        "candle_body_pts": 0.1,
        "candle_range_pts": 0.2,
        "dist_call_gamma_wall": 1.0,
        "dist_put_gamma_wall": -1.0,
        "dist_gamma_inflection": 0.0,
        "dist_delta_inflection": 0.0,
        "dist_call_oi_wall": 0.0,
        "dist_put_oi_wall": 0.0,
        "spy_chg_pct": 0.0,
        "qqq_chg_pct": 0.0,
        "iwm_chg_pct": 0.0,
        "vix_level": 18.0,
        "iv_level": 0.2,
    }


def test_merge_strips_legacy_mvp_and_uses_canonical():
    from features.lstm_sequence_input import merge_db_row_with_canonical_mvp
    from features.canonical_contract import get_mvp_feature_names

    db = _base_db_row(1.0, spot=999.0)
    cf = {k: None for k in get_mvp_feature_names()}
    cf["price.spot"] = 450.0
    cf["price.spread_pts"] = 0.02
    cf["structure.zone"] = "pin_bull"
    cf["structure.nearest_above_dist"] = 1.0
    cf["structure.nearest_below_dist"] = -1.0
    cf["structure.net_gamma"] = 0.0
    cf["anchor.vwap_side"] = "above"
    cf["anchor.vwap_dist_pts"] = 0.1
    m = merge_db_row_with_canonical_mvp(db, cf)
    assert m["spot"] == 450.0
    assert m["zone"] == "pin_bull"
    assert m["vwap_side"] == "above"
    assert m["candle_body_pts"] == 0.1


def test_encode_snapshot_dimensions_match_features_lists():
    from lstm_data import encode_snapshot_5m, encode_snapshot_1m, FEATURES_5M, FEATURES_1M
    from features.canonical_contract import get_mvp_feature_names

    cf = {k: None for k in get_mvp_feature_names()}
    cf["price.spot"] = 450.0
    cf["price.spread_pts"] = 0.02
    cf["structure.zone"] = "pin_bull"
    cf["structure.nearest_above_dist"] = 1.0
    cf["structure.nearest_below_dist"] = -1.0
    cf["structure.net_gamma"] = 0.0
    cf["anchor.vwap_side"] = "above"
    cf["anchor.vwap_dist_pts"] = 0.1
    db = _base_db_row(1.0)
    from features.lstm_sequence_input import merge_db_row_with_canonical_mvp

    merged = merge_db_row_with_canonical_mvp(db, cf)
    v5 = encode_snapshot_5m(merged, 450.0)
    v1 = encode_snapshot_1m(merged, 450.0)
    assert len(v5) == len(FEATURES_5M)
    assert len(v1) == len(FEATURES_1M)


def test_inference_snapshot_wrong_version_fails():
    from features.lstm_sequence_input import build_lstm_merged_windows, LstmSequenceInputError

    inf = _minimal_valid_inference_v1()
    bad = copy.deepcopy(inf)
    bad["feature_contract_version"] = "wrong"
    win = [_base_db_row(1.0 + i) for i in range(3)]
    days = list(win)
    with pytest.raises(LstmSequenceInputError):
        build_lstm_merged_windows(win, days, inference_snapshot_v1=bad)


def test_inference_snapshot_wrong_timeframe_fails():
    from features.lstm_sequence_input import build_lstm_merged_windows, LstmSequenceInputError

    inf = _minimal_valid_inference_v1()
    bad = copy.deepcopy(inf)
    bad["canonical_timeframe"] = "5m"
    win = [_base_db_row(1.0 + i) for i in range(3)]
    days = list(win)
    with pytest.raises(LstmSequenceInputError):
        build_lstm_merged_windows(win, days, inference_snapshot_v1=bad)


def test_invalid_db_row_mvp_source_fails():
    from features.lstm_sequence_input import build_lstm_merged_windows, LstmSequenceInputError

    win = [_base_db_row(1.0)]
    win[0]["spot"] = "not_a_number"
    with pytest.raises(LstmSequenceInputError):
        build_lstm_merged_windows(win, list(win), inference_snapshot_v1=None)


def test_live_bar_overrides_db_mvp_with_inference_snapshot():
    from features.lstm_sequence_input import build_lstm_merged_windows

    inf = _minimal_valid_inference_v1()
    win = [_base_db_row(1.0 + i, spot=100.0) for i in range(3)]
    win[-1]["ts_utc"] = 1_700_000_100.0
    days = list(win)
    mw, md = build_lstm_merged_windows(win, days, inference_snapshot_v1=inf)
    assert mw[-1]["spot"] == 400.0
    assert mw[0]["spot"] == 100.0


def test_invalid_live_canonical_row_fails():
    from features.lstm_sequence_input import build_lstm_merged_windows, LstmSequenceInputError

    inf = _minimal_valid_inference_v1()
    bad = copy.deepcopy(inf)
    bad["features"]["price.spot"] = -1.0
    win = [_base_db_row(1.0)]
    with pytest.raises(LstmSequenceInputError, match="price.spot"):
        build_lstm_merged_windows(win, list(win), inference_snapshot_v1=bad)


def test_legacy_mvp_values_in_db_row_do_not_affect_merged_when_canonical_differs():
    """Poisoned legacy spot/zone must not survive merge — canonical wins."""
    from features.lstm_sequence_input import merge_db_row_with_canonical_mvp
    from features.canonical_contract import get_mvp_feature_names

    db = _base_db_row(1.0, spot=1.0)
    db["zone"] = "breakdown"
    cf = {k: None for k in get_mvp_feature_names()}
    cf["price.spot"] = 450.0
    cf["price.spread_pts"] = 0.02
    cf["structure.zone"] = "pin_bull"
    cf["structure.nearest_above_dist"] = 1.0
    cf["structure.nearest_below_dist"] = -1.0
    cf["structure.net_gamma"] = 0.0
    cf["anchor.vwap_side"] = "above"
    cf["anchor.vwap_dist_pts"] = 0.1
    m = merge_db_row_with_canonical_mvp(db, cf)
    assert m["spot"] == 450.0
    assert m["zone"] == "pin_bull"
