"""Layer 5 lstm_sequence_input chunk-1: contract locks not covered by existing LSTM/TR tests."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _minimal_valid_inference_v1():
    from features.canonical_contract import get_mvp_feature_names
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row

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


def test_envelope_rejects_non_dict_inference_snapshot():
    from features.lstm_sequence_input import LstmSequenceInputError, build_lstm_merged_windows

    win = [_base_db_row(1.0)]
    with pytest.raises(LstmSequenceInputError, match="must be a dict"):
        build_lstm_merged_windows(win, list(win), inference_snapshot_v1="not-a-dict")  # type: ignore[arg-type]


def test_envelope_rejects_wrong_snapshot_type():
    from features.lstm_sequence_input import LstmSequenceInputError, build_lstm_merged_windows

    inf = _minimal_valid_inference_v1()
    bad = copy.deepcopy(inf)
    bad["snapshot_type"] = "WrongType"
    win = [_base_db_row(1.0 + i) for i in range(2)]
    with pytest.raises(LstmSequenceInputError, match="snapshot_type"):
        build_lstm_merged_windows(win, list(win), inference_snapshot_v1=bad)


def test_canonical_missing_masks_partial_presence():
    from features.canonical_contract import get_mvp_feature_names
    from features.lstm_sequence_input import _canonical_missing_masks

    cf = {k: None for k in get_mvp_feature_names()}
    cf["structure.net_gamma"] = 100.0
    assert _canonical_missing_masks(cf) == [1.0, 0.0]


def test_encode_vwap_side_none_uses_unknown_encoded():
    from features.canonical_contract import get_mvp_feature_names
    from features.lstm_sequence_input import (
        VWAP_SIDE_UNKNOWN_ENCODED,
        encode_lstm_structure_bar_with_masks,
    )
    from lstm_data import ENCODED_FEATURES_5M

    cf = {k: None for k in get_mvp_feature_names()}
    cf["price.spot"] = 450.0
    cf["anchor.vwap_side"] = None
    merged = _base_db_row(1.0)
    enc = encode_lstm_structure_bar_with_masks(merged, cf, 450.0)
    vi = ENCODED_FEATURES_5M.index("vwap_side")
    assert enc["features"][vi] == VWAP_SIDE_UNKNOWN_ENCODED


def test_encode_known_zone_maps_to_zone_code():
    from features.canonical_contract import get_mvp_feature_names
    from features.lstm_sequence_input import encode_lstm_structure_bar_with_masks
    from lstm_data import ENCODED_FEATURES_5M, ZONE_MAP

    cf = {k: None for k in get_mvp_feature_names()}
    cf["price.spot"] = 450.0
    cf["structure.zone"] = "pin_bull"
    enc = encode_lstm_structure_bar_with_masks(_base_db_row(1.0), cf, 450.0)
    zi = ENCODED_FEATURES_5M.index("zone")
    assert enc["features"][zi] == float(ZONE_MAP["pin_bull"])


def test_encode_unknown_zone_string_defaults_pin_neutral_code_lsi1():
    """FIND-LSI1: locks current ZONE_MAP.get(..., 2) behavior (pin_neutral code)."""
    from features.canonical_contract import get_mvp_feature_names
    from features.lstm_sequence_input import encode_lstm_structure_bar_with_masks
    from lstm_data import ENCODED_FEATURES_5M, ZONE_MAP

    cf = {k: None for k in get_mvp_feature_names()}
    cf["price.spot"] = 450.0
    cf["structure.zone"] = "not_a_real_zone"
    enc = encode_lstm_structure_bar_with_masks(_base_db_row(1.0), cf, 450.0)
    zi = ENCODED_FEATURES_5M.index("zone")
    assert enc["features"][zi] == float(ZONE_MAP["pin_neutral"])


def test_day_snaps_ts_close_override_applies_live_features():
    from features.lstm_sequence_input import build_lstm_merged_windows

    inf = _minimal_valid_inference_v1()
    last_ts = 1_700_000_100.0
    win = [_base_db_row(1.0, spot=100.0), _base_db_row(2.0, spot=100.0), _base_db_row(last_ts, spot=100.0)]
    days = [
        _base_db_row(1.0, spot=100.0),
        _base_db_row(last_ts, spot=100.0),
    ]
    _mw, md = build_lstm_merged_windows(win, days, inference_snapshot_v1=inf)
    assert md[0]["spot"] == 100.0
    assert md[1]["spot"] == 400.0


def test_day_snaps_ts_mismatch_keeps_db_mvp():
    from features.lstm_sequence_input import build_lstm_merged_windows

    inf = _minimal_valid_inference_v1()
    last_ts = 1_700_000_100.0
    win = [_base_db_row(1.0, spot=100.0), _base_db_row(last_ts, spot=100.0)]
    days = [_base_db_row(last_ts + 1.0, spot=222.0)]
    _mw, md = build_lstm_merged_windows(win, days, inference_snapshot_v1=inf)
    assert md[0]["spot"] == 222.0


def test_transformer_reraises_lstm_error_as_transformer_type():
    from features.lstm_sequence_input import (
        LstmSequenceInputError,
        TransformerSequenceInputError,
        build_transformer_merged_window,
    )

    inf = _minimal_valid_inference_v1()
    bad = copy.deepcopy(inf)
    bad["snapshot_type"] = "WrongType"
    win = [_base_db_row(1.0)]
    with pytest.raises(TransformerSequenceInputError):
        build_transformer_merged_window(win, inference_snapshot_v1=bad)


def test_merge_strips_all_mvp_legacy_keys():
    from features.canonical_contract import get_mvp_feature_names
    from features.lstm_sequence_input import merge_db_row_with_canonical_mvp
    from features.xgb_model_input import MVP_LEGACY_KEYS

    db = _base_db_row(1.0, spot=999.0)
    cf = {k: None for k in get_mvp_feature_names()}
    cf["price.spot"] = 450.0
    cf["structure.zone"] = "pin_bull"
    m = merge_db_row_with_canonical_mvp(db, cf)
    for leg in MVP_LEGACY_KEYS:
        if leg in ("absorption_score", "continuation_score"):
            continue
        assert m[leg] != 999.0 or leg not in db


def test_ts_close_docstring_documents_epsilon():
    from features import lstm_sequence_input as lsi

    doc = (lsi._ts_close.__doc__ or "").lower()
    assert "epsilon" in doc or "eps" in doc
    assert "1e-3" in doc
    assert "1 ms" in doc
    merged_doc = (lsi.build_lstm_merged_windows.__doc__ or "").lower()
    assert "_ts_close" in merged_doc
    assert "1e-3" in merged_doc or "1 ms" in merged_doc
