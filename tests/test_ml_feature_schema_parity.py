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


def test_sentiment_news_features_deregistered():
    """SENTIMENT/NEWS FEATURE RETIRE: the 6 non-Schwab news/sentiment cols are not XGB features,
    even when present and populated in the source df (train + serve, since both emit from
    SCALE_INVARIANT_COLS)."""
    retired = (
        "sentiment_composite", "sentiment_buzz", "sentiment_finnhub",
        "sentiment_av", "breaking_news_flag", "pre_market_sentiment",
    )
    df = _minimal_df()
    for c in retired:
        df[c] = 0.5
    X, names, _, _ = engineer_features(df)
    for c in retired:
        assert c not in names, f"{c} still a training feature"
        assert c not in X.columns, f"{c} still in engineered matrix"
    # serving side emits from the same list → also absent
    snap = {"ticker": "SPY", "spot": 100.0, "candle_body_pts": 1.0, "candle_range_pts": 2.0,
            "nearest_above_dist": 1.0, "nearest_below_dist": 1.0,
            **{c: 0.5 for c in retired}}
    row = engineer_single_snapshot(snap, {}, list(X.columns), {}, "SPY")
    assert row is not None
    for c in retired:
        assert c not in row


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


def test_slice_a_cross_asset_cols_registered_in_scale_invariant():
    from ml_train import SCALE_INVARIANT_COLS

    for col in ("tnx_yield", "tnx_chg", "qqq_vs_spy", "spy_iwm_divergence"):
        assert col in SCALE_INVARIANT_COLS


def test_dgex_first_diff_engineered_train_and_serve():
    df = pd.DataFrame(
        {
            "ticker": ["SPY", "SPY", "SPY"],
            "ts_utc": [100.0, 160.0, 220.0],
            "spot": [100.0, 100.0, 100.0],
            "net_gamma": [1.0, 4.0, 2.0],
            "outcome_1c": ["up", "down", "flat"],
        }
    )
    from ml_data_common import attach_net_gamma_prev_column

    df = attach_net_gamma_prev_column(df)
    X, names, _, _ = engineer_features(df)
    assert "dgex" in names
    assert "dgex_positive" in names
    assert np.isnan(float(X.loc[0, "dgex"]))
    assert abs(float(X.loc[1, "dgex"]) - 3.0) < 1e-9
    assert float(X.loc[1, "dgex_positive"]) == 1.0

    snap = {"ticker": "SPY", "spot": 100.0, "net_gamma": 2.0, "net_gamma_prev": 4.0}
    row = engineer_single_snapshot(snap, {}, names, {}, "SPY")
    assert row is not None
    assert abs(float(row.iloc[0]["dgex"]) - (-2.0)) < 1e-9


def test_dgex_train_serve_parity_via_prior_db_row(tmp_path):
    """Serve path: attach_net_gamma_prev_for_dgex attaches net_gamma_prev from prior normalized row."""
    import sqlite3

    from ml_data_common import attach_net_gamma_prev_column, attach_net_gamma_prev_for_dgex
    from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M

    db = tmp_path / "dgex_parity.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        f"CREATE TABLE {SNAPSHOT_TABLE_1M} ("
        "ticker TEXT NOT NULL, timeframe TEXT NOT NULL, ts_utc REAL NOT NULL, net_gamma REAL)"
    )
    for ts, ng in ((100.0, 1.0), (160.0, 4.0), (220.0, 2.0)):
        conn.execute(
            f"INSERT INTO {SNAPSHOT_TABLE_1M} (ticker, timeframe, ts_utc, net_gamma) VALUES (?, ?, ?, ?)",
            ("SPY", CANONICAL_TIMEFRAME, ts, ng),
        )
    conn.commit()
    conn.close()

    df = pd.DataFrame(
        {
            "ticker": ["SPY", "SPY", "SPY"],
            "ts_utc": [100.0, 160.0, 220.0],
            "spot": [100.0, 100.0, 100.0],
            "net_gamma": [1.0, 4.0, 2.0],
            "outcome_1c": ["up", "down", "flat"],
        }
    )
    df = attach_net_gamma_prev_column(df)
    X_train, names, _, _ = engineer_features(df)

    snap = {
        "ticker": "SPY",
        "ts_utc": 220.0,
        "spot": 100.0,
        "net_gamma": 2.0,
    }
    enriched = attach_net_gamma_prev_for_dgex(snap, str(db))
    assert enriched.get("net_gamma_prev") == 4.0
    row = engineer_single_snapshot(enriched, {}, names, {}, "SPY")
    assert row is not None
    train_dgex = float(X_train.loc[2, "dgex"])
    serve_dgex = float(row.iloc[0]["dgex"])
    assert abs(train_dgex - serve_dgex) < 1e-9
    assert abs(serve_dgex - (-2.0)) < 1e-9


def test_m5_stripped_symmetric_train_and_serve():
    """m5_* lag block DROP: engineer_features and engineer_single_snapshot ignore m5_* inputs."""
    df = _minimal_df()
    df["m5_net_gamma"] = 99.0
    df["m5_candle_body_pts"] = 50.0
    X, names, _, _ = engineer_features(df)
    assert not any(str(n).startswith("m5_") for n in names)

    snap = {
        "ticker": "SPY",
        "spot": 100.0,
        "candle_body_pts": 1.0,
        "candle_range_pts": 2.0,
        "nearest_above_dist": 1.0,
        "nearest_below_dist": 1.0,
        "m5_net_gamma": 99.0,
        "m5_candle_body_pts": 50.0,
    }
    row = engineer_single_snapshot(snap, {}, names, {}, "SPY")
    assert row is not None
    assert not any(str(c).startswith("m5_") for c in row.columns)


def test_feature_schema_version_bumped_for_m5_strip():
    from training_provenance import FEATURE_SCHEMA_VERSION, PREPROCESSING_VERSION

    assert FEATURE_SCHEMA_VERSION == "v7_m5_strip"
    assert PREPROCESSING_VERSION == "v5_no_m5_lag"


def test_feature_ablation_manifest_matches_engineer_features():
    from tools.build_feature_assignment_matrix_v2 import resolve_ablation_universe

    payload = resolve_ablation_universe()
    assert payload["totals"]["xgb_engineered_columns"] == 88
    assert payload["totals"]["lstm_5m_channels"] == 23
    assert payload["totals"]["lstm_1m_channels"] == 12
    assert payload["unassigned_xgb"] == []
    by_id = {g["group_id"]: g for g in payload["groups"]}
    assert by_id["m5_block"]["disposition"] == "DROP"
    assert by_id["m5_block"]["member_counts"]["xgb"] == 0
    assert by_id["combined_leakage"]["disposition"] == "EXCLUDE"
    assert by_id["time"]["member_counts"]["xgb"] == 4
    assert by_id["iv"]["member_counts"]["xgb"] == 4  # iv_level, iv_rank, cat_iv_direction, atr
    assert by_id["microstructure"]["member_counts"]["xgb"] == 4


def test_ablation_harness_manifest_only_grid():
    from tools.feature_curation_gate import (
        ablation_grid_cell_specs,
        ablation_groups,
        build_ablation_report,
        load_ablation_manifest,
    )

    manifest = load_ablation_manifest()
    groups = ablation_groups(manifest)
    method = manifest["ablation_method"]
    expected_cells = (
        len(method["anchors"]) * len(method["models"]) * len(method["horizons"]) * len(groups)
    )
    specs = ablation_grid_cell_specs(manifest)
    assert len(specs) == expected_cells
    assert set(method["grid"]) == {"anchor_ticker", "model_family", "horizon_slug"}
    assert all(g["disposition"] == "ABLATE" for g in manifest["groups"] if g["group_id"] in {s["group_id"] for s in specs})

    report = build_ablation_report(dry_run=True)
    assert report["dry_run"] is True
    assert report["grid_cell_count"] == expected_cells
    assert report["cells"][0]["anchor_ticker"] in method["anchors"]
    assert report["cells"][0]["model_family"] in method["models"]
    assert report["cells"][0]["horizon_slug"] in method["horizons"]


def test_curation_gate_keeps_override_protected_index_family():
    from tools.feature_curation_gate import _protected_db_columns

    protected = _protected_db_columns()
    assert "tnx_yield" in protected
    assert "qqq_vs_spy" in protected
    assert "spy_chg_pct" in protected
    assert "qqq_chg_pct" in protected
