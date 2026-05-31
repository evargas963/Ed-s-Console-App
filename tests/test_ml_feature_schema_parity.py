"""Issue 7: training vs inference parity for XGB tabular features."""
from __future__ import annotations

import json
import pickle

import numpy as np
import pandas as pd

from ml_train import (
    apply_xgb_imputation_matrix,
    engineer_features,
    engineer_single_snapshot,
    xgb_meta_contract_ok,
)
from model_contract import contract_metadata_dict


def _minimal_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["SPY"],
            "candle_body_pts": [1.0],
            "candle_range_pts": [2.0],
            "nearest_above_dist": [1.0],
            "nearest_below_dist": [1.0],
            "spot": [100.0],
            "outcome_1c": ["up"],
        }
    )


def test_pred_columns_do_not_create_rules_engineered_features():
    """Empirical pred_* must not become rules_* in the XGB matrix (breaks causal edge)."""
    df = _minimal_df()
    df["pred_1c_up_prob"] = np.nan
    df["pred_1c_down_prob"] = np.nan
    df["pred_1c_flat_prob"] = 0.5
    df["pred_15c_up_prob"] = 0.4
    df["pred_15c_down_prob"] = 0.3
    df["pred_15c_flat_prob"] = 0.3
    X, names, _, _ = engineer_features(df)
    assert "rules_1c_spread" not in names
    assert "rules_1c_confidence" not in names
    assert "rules_15c_up" not in names

    snap = {
        "ticker": "SPY",
        "spot": 100.0,
        "candle_body_pts": 1.0,
        "candle_range_pts": 2.0,
        "nearest_above_dist": 1.0,
        "nearest_below_dist": 1.0,
        "pred_1c_flat_prob": 0.5,
        "pred_15c_up_prob": 0.4,
        "pred_15c_down_prob": 0.3,
    }
    feats = list(X.columns)
    row = engineer_single_snapshot(snap, {}, feats, {}, "SPY")
    assert row is not None
    assert "rules_1c_spread" not in feats


def test_structural_bulk_matches_snapshot():
    """Bulk engineer_features and engineer_single_snapshot agree on shared structural columns."""
    df = _minimal_df()
    df["pred_1c_up_prob"] = 0.4
    df["pred_1c_down_prob"] = 0.3
    X, _, _, _ = engineer_features(df)
    cb = float(X["candle_body_pct"].iloc[0])
    cr = float(X["candle_range_pct"].iloc[0])

    snap = {
        "ticker": "SPY",
        "spot": 100.0,
        "candle_body_pts": 1.0,
        "candle_range_pts": 2.0,
        "nearest_above_dist": 1.0,
        "nearest_below_dist": 1.0,
        "pred_1c_up_prob": 0.4,
        "pred_1c_down_prob": 0.3,
    }
    row = engineer_single_snapshot(snap, {}, list(X.columns), {}, "SPY")
    assert abs(cb - float(row["candle_body_pct"].iloc[0])) < 1e-9
    assert abs(cr - float(row["candle_range_pct"].iloc[0])) < 1e-9


def test_apply_xgb_imputation_matrix():
    names = ["a", "b"]
    X = np.array([[np.nan, 2.0]], dtype=float)
    out = apply_xgb_imputation_matrix(X, names, {"a": 5.0, "b": 7.0})
    assert out.shape == (1, 2)
    assert out[0, 0] == 5.0
    assert out[0, 1] == 2.0


def test_xgb_meta_contract_ok():
    feats = ["a", "b"]
    good = {**contract_metadata_dict(), "features": feats, "impute_medians": {"a": 0.0, "b": 1.0}}
    assert xgb_meta_contract_ok(good)
    assert not xgb_meta_contract_ok({**good, "impute_medians": {"a": 0.0}})
    bad_miss = {**good, "missingness_contract_version": "stale"}
    assert not xgb_meta_contract_ok(bad_miss)


def test_load_xgb_rejects_stale_meta(tmp_path, monkeypatch):
    import ml_predict as mp

    mp._xgb_registry.clear()
    ticker = "ZZTEST"
    base = tmp_path / ticker
    base.mkdir(parents=True)
    with open(base / f"xgb_{ticker}_1c.pkl", "wb") as f:
        pickle.dump(None, f)
    meta = {"features": ["a"], "impute_medians": {}}
    (base / f"xgb_{ticker}_1c_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    monkeypatch.setattr(mp, "_model_dir_for_ticker", lambda _t: base)
    assert mp._load_xgb(ticker) is False
    assert mp._xgb_registry.get(mp._model_registry_key(ticker, "1c")) is None
    mp._xgb_registry.clear()


def _ordered_feature_df() -> pd.DataFrame:
    """8 chronological rows: a shared time-of-day group (idx0-5), a distinct tod tail (idx6-7),
    and a 'zone' category that appears only in the tail. Used for B3 train-only-fit tests."""
    ts = 1_700_000_000
    return pd.DataFrame(
        {
            "ticker": ["SPY"] * 8,
            "ts_utc": [ts, ts, ts, ts, ts, ts, ts + 7200, ts + 7200],
            "spot": [100.0] * 8,
            "candle_body_pts": [0.5, 0.4, 0.6, 0.5, 0.45, 0.55, 0.5, 0.5],
            "candle_range_pts": [1.0] * 8,
            "nearest_above_dist": [1.0] * 8,
            "nearest_below_dist": [1.0] * 8,
            "candle_volume": [100.0, 110.0, 90.0, 105.0, 95.0, 100.0, 200.0, 220.0],
            "zone": ["pin_neutral"] * 6 + ["breakout_up", "breakout_up"],
            "outcome_1c": ["up", "down", "flat", "up", "down", "flat", "up", "down"],
        }
    )


def test_engineer_features_fit_end_none_byte_identical():
    """B3 closeout #1 regression guard: fit_end=None (and fit_end>=len, which the <len guard treats
    as full) must reproduce the exact legacy full-df behavior — same X, names, maps, aux."""
    df = _ordered_feature_df()
    X0, n0, m0, a0 = engineer_features(df)                  # default (None)
    Xn, nn, mn, an = engineer_features(df, fit_end=None)    # explicit None
    Xf, nf, mf, af = engineer_features(df, fit_end=len(df)) # full per the 0<fit_end<len guard
    assert n0 == nn == nf
    assert m0 == mn == mf
    assert a0 == an == af
    assert X0.equals(Xn)
    assert X0.equals(Xf)
    # Legacy semantics locked numerically: zone sorted-unique mapping + a known volume_ratio.
    assert m0["zone"] == {"breakout_up": 0, "pin_neutral": 1}
    # row0 volume 100 vs full tod-group median(90,95,100,100,105,110)=100 -> ratio 1.0
    assert abs(float(X0["volume_ratio"].iloc[0]) - 1.0) < 1e-9


def test_engineer_features_train_only_category_val_only_maps_nan():
    """A category present only in the val tail is absent from the train mapping and its cat_* code
    is NaN — matching engineer_single_snapshot serving (unseen category -> NaN)."""
    df = _ordered_feature_df()
    train_end = 6  # idx0-5 train (pin_neutral), idx6-7 val (breakout_up only)
    X, names, maps, aux = engineer_features(df, fit_end=train_end)
    assert maps["zone"] == {"pin_neutral": 0}
    assert "breakout_up" not in maps["zone"]
    cat = X["cat_zone"].to_numpy()
    assert not np.isnan(cat[:train_end]).any()
    assert np.isnan(cat[train_end:]).all()
    # Contrast: the full-fit path still includes the tail-only category.
    _, _, maps_full, _ = engineer_features(df, fit_end=None)
    assert "breakout_up" in maps_full["zone"]


def test_engineer_features_train_only_volume_median_and_val_only_tod_nan():
    """volume_ratio: the persisted per-tod median is fit on the train partition only (val-tail
    inflation does not move it), and a val-only time-of-day -> volume_ratio NaN (serving parity)."""
    ts = 1_700_000_000
    df = pd.DataFrame(
        {
            "ticker": ["SPY"] * 8,
            "ts_utc": [ts, ts, ts, ts, ts, ts, ts, ts + 7200],  # idx7 = val-only tod
            "spot": [100.0] * 8,
            "candle_body_pts": [0.5] * 8,
            "candle_range_pts": [1.0] * 8,
            "nearest_above_dist": [1.0] * 8,
            "nearest_below_dist": [1.0] * 8,
            # train tod-A vols (idx0-5) all 100 -> median 100; val tod-A vol (idx6) inflated; tod-B (idx7)
            "candle_volume": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100000.0, 500.0],
            "zone": ["pin_neutral"] * 8,
            "outcome_1c": ["up", "down", "flat", "up", "down", "flat", "up", "down"],
        }
    )
    train_end = 6  # idx0-5 train, idx6-7 val
    X, names, maps, aux = engineer_features(df, fit_end=train_end)
    vol_meds = {k: v for k, v in aux.items() if k.startswith("vol_median_")}
    # Exactly one persisted median (train tod-A) == 100; the inflated val volume never enters the fit.
    assert any(abs(v - 100.0) < 1e-9 for v in vol_meds.values())
    assert all(v < 1000.0 for v in vol_meds.values())
    vr = X["volume_ratio"].to_numpy()
    assert abs(vr[0] - 1.0) < 1e-9      # train tod-A: 100/100
    assert abs(vr[6] - 10.0) < 1e-9     # val tod-A: 100000/100 clipped to 10 (uses train median)
    assert np.isnan(vr[7])              # val-only tod-B: no train median -> NaN


def test_train_impute_roundtrip_matches_inference_style():
    """One engineered row: median impute + nan_to_num must match apply_xgb_imputation_matrix."""
    df = _minimal_df()
    df = pd.concat([df, df.assign(et_hour=10, et_minute=0)], ignore_index=True)
    X, _, _, _ = engineer_features(df)
    med = X.median()
    feats = list(X.columns)
    impute = {f: float(med[f]) if pd.notna(med[f]) else 0.0 for f in feats}
    X_filled = X.iloc[[0]].fillna(pd.Series(impute))
    expected = np.nan_to_num(X_filled.values.astype(np.float64), nan=0.0)

    snap = {
        "ticker": "SPY",
        "spot": 100.0,
        "candle_body_pts": 1.0,
        "candle_range_pts": 2.0,
        "nearest_above_dist": 1.0,
        "nearest_below_dist": 1.0,
    }
    row = engineer_single_snapshot(snap, {}, feats, {}, "SPY")
    got = apply_xgb_imputation_matrix(row.values.astype(np.float64), feats, impute)
    np.testing.assert_array_almost_equal(got, expected)
