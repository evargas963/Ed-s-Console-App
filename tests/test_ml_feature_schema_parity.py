"""Issue 7: training vs inference parity for XGB tabular features."""
from __future__ import annotations

import inspect
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

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


def test_non_numeric_scale_invariant_value_coerces_nan_train_and_serve():
    """qqq_vs_spy live regression (2026-06-09): market_state emits 'leading'/'lagging'/'inline'
    strings for a column registered in SCALE_INVARIANT_COLS. Training coerces via
    pd.to_numeric(errors='coerce') -> NaN; serve must mirror that (NaN), never raise and kill
    the whole XGB prediction ('could not convert string to float: lagging')."""
    df = _minimal_df()
    df["qqq_vs_spy"] = ["lagging"]
    X, names, _, _ = engineer_features(df)
    assert "qqq_vs_spy" in names
    assert np.isnan(float(X["qqq_vs_spy"].iloc[0]))

    snap = {
        "ticker": "SPY",
        "spot": 100.0,
        "candle_body_pts": 1.0,
        "candle_range_pts": 2.0,
        "nearest_above_dist": 1.0,
        "nearest_below_dist": 1.0,
        "qqq_vs_spy": "lagging",
    }
    row = engineer_single_snapshot(snap, {}, list(X.columns), {}, "SPY")
    assert row is not None, "serve must not fail-closed the entire XGB row on a string value"
    assert np.isnan(float(row["qqq_vs_spy"].iloc[0]))

    # Numeric twin present (live serve path): use the qqq_vs_spy_delta spread — the same
    # quantity the DB/training column stores — instead of NaN.
    snap_with_delta = dict(snap, qqq_vs_spy_delta=-0.9368)
    row2 = engineer_single_snapshot(snap_with_delta, {}, list(X.columns), {}, "SPY")
    assert abs(float(row2["qqq_vs_spy"].iloc[0]) - (-0.9368)) < 1e-9


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
    """Expanded Schwab atomic universe includes registered ML cone + cf_* on lstm_5m."""
    from tools.build_feature_assignment_matrix_v2 import (
        MIN_ABLATION_EXPANSION_FACTOR,
        resolve_ablation_universe,
    )

    payload = resolve_ablation_universe()
    reg_n = int(payload["totals"]["registered_ml_cone_columns"])
    ablate_n = int(payload["totals"]["ablation_group_count"])
    assert ablate_n >= reg_n * MIN_ABLATION_EXPANSION_FACTOR
    banned = ("members", "member_counts", "members_note", "horizon_disposition")
    for g in payload.get("groups") or []:
        assert not any(k in g for k in banned), g.get("group_id")
        assert g.get("atomic_column"), g.get("group_id")
    gids = {g["group_id"] for g in payload["groups"] if g.get("disposition") == "ABLATE"}
    for cf in (
        "cf_alignment_score",
        "cf_greek_support",
        "cf_momentum_5m",
        "cf_structure_15m",
        "cf_trend_1h",
        "cf_vwap_distance_pct",
    ):
        assert f"reg__atomic__{cf}" in gids



def test_ablation_manifest_generator_has_no_model_stamp_builder():
    """Generator source must not retain legacy compound model-stamp builders."""
    from tools.check_fix_everything_we_touch import check_ablation_manifest_generator_no_model_preassignment

    assert check_ablation_manifest_generator_no_model_preassignment() == []


def test_ablation_harness_manifest_only_grid():
    from tools.feature_curation_gate import (
        FULL_STACK_LAYERS,
        REQUIRED_ABLATION_HORIZONS,
        ablation_stack_authority_cell_specs,
        build_ablation_report,
        load_ablation_manifest,
    )

    from tools.feature_curation_gate import ablation_per_model_feature_cell_specs

    manifest = load_ablation_manifest()
    method = manifest["ablation_method"]
    ablate_groups = [g for g in manifest["groups"] if g.get("disposition") == "ABLATE"]
    feat_specs = ablation_per_model_feature_cell_specs(manifest)
    expected = (
        len(method["anchors"]) * len(method["models"])
        * len(method["horizons"]) * len(ablate_groups)
    )
    assert len(feat_specs) == expected
    assert manifest["totals"]["per_model_feature_cell_count"] == expected

    assert method["primary_pass"] == "per_model_per_horizon_atomic_permutation_importance"
    assert method["decision_mode"] == "per_model_holdout"
    assert method["decision_metric"] == "mcc_delta"
    assert set(method["models"]) == {"xgb", "lstm", "transformer"}
    assert set(method["horizons"]) == set(REQUIRED_ABLATION_HORIZONS)
    assert set(method["full_stack_layers"]) == set(FULL_STACK_LAYERS)

    assert {c["model_family"] for c in feat_specs} == {"xgb", "lstm", "transformer"}
    assert {c["horizon_slug"] for c in feat_specs} == set(REQUIRED_ABLATION_HORIZONS)

    report = build_ablation_report(dry_run=True)
    assert report["dry_run"] is True
    assert report["per_model_feature_cell_count"] == expected
    if manifest.get("schema_version") == "4_schwab_expanded":
        from tools.feature_curation_gate import ablation_whole_stack_feature_cell_specs

        whole = ablation_whole_stack_feature_cell_specs(manifest)
        assert len(whole) == report.get("whole_stack_feature_cell_count", len(whole))
        assert whole[0]["model_family"] in set(FULL_STACK_LAYERS)
    else:
        stack_specs = ablation_stack_authority_cell_specs(manifest)
        assert len(stack_specs) == manifest["totals"]["stack_authority_cell_count"]
        assert manifest["totals"]["grid_cell_count"] == expected + len(stack_specs)
        assert report["stack_authority_cell_count"] == len(stack_specs)
        assert report["grid_cell_count"] == expected + len(stack_specs)
        assert report["stack_authority_cells"][0]["ablation_kind"] == "stack_authority"
        stack_auth = method.get("stack_authority_pass") or method.get("stack_eval") or {}
        assert "meta_stack" in stack_auth["modes"]
        assert "full_fusion" in stack_auth["modes"]
        assert report["per_model_feature_cells"][0]["model_family"] in {"xgb", "lstm", "transformer"}


def test_ablation_harness_wires_per_model_and_stack_authority():
    """O-56 primary + stack authority wiring — production manifest + module constants."""
    from tools.build_feature_assignment_matrix_v2 import (
        BASE_MODEL_COMPARISONS,
        FULL_STACK_ABLATION_MODES,
    )
    from tools.feature_curation_gate import (
        _permute_eval_lstm_group,
        _permute_eval_transformer_group,
        _permute_eval_xgb_group,
        _prepare_lstm_holdout,
        _prepare_transformer_holdout,
        _prepare_xgb_holdout,
        ablation_per_model_feature_cell_specs,
        build_per_model_feature_ablation_section,
        load_ablation_manifest,
        run_stack_layer_ablation_cell,
    )

    manifest = load_ablation_manifest()
    method = manifest["ablation_method"]
    assert method["primary_pass"] == "per_model_per_horizon_atomic_permutation_importance"
    assert set(method["full_stack_layers"]) == {
        "xgb", "lstm", "transformer", "meta", "monte_carlo", "regime", "fusion",
    }
    assert set(BASE_MODEL_COMPARISONS) == {
        "lstm_over_xgb", "transformer_over_xgb", "transformer_over_pair",
    }
    assert "meta_stack" in FULL_STACK_ABLATION_MODES
    assert "full_fusion" in FULL_STACK_ABLATION_MODES
    assert len(ablation_per_model_feature_cell_specs(manifest)) == manifest["totals"][
        "per_model_feature_cell_count"
    ]
    for fn in (
        _prepare_xgb_holdout, _prepare_lstm_holdout, _prepare_transformer_holdout,
        _permute_eval_xgb_group, _permute_eval_lstm_group, _permute_eval_transformer_group,
        build_per_model_feature_ablation_section, run_stack_layer_ablation_cell,
    ):
        assert callable(fn)


def test_stack_layer_meta_degenerate_when_meta_artifact_missing(tmp_path):
    """Meta lift must flag degenerate when meta_*.pkl is absent — not silent ~0."""
    from tools.feature_curation_gate import _stack_layer_lifts

    metrics = {
        "xgb_plus_lstm_plus_transformer": {"multiclass_log_loss": 1.0},
        "meta_stack": {"multiclass_log_loss": 1.0},
    }
    lifts = _stack_layer_lifts(
        metrics,
        {
            "meta": {
                "baseline": "xgb_plus_lstm_plus_transformer",
                "treatment": "meta_stack",
                "metric": "multiclass_log_loss",
            }
        },
    )
    lifts["meta"]["degenerate"] = True
    lifts["meta"]["degenerate_reason"] = "meta_artifact_missing__meta_stack_falls_back_to_weighted_average"
    lifts["meta"]["treatment_helps"] = None
    assert lifts["meta"]["degenerate"] is True
    assert lifts["meta"]["treatment_helps"] is None


def test_group_snapshot_columns_maps_xgb_engineered_to_raw_db_keys():
    """XGB manifest members are engineered names; permutation must target raw DB snapshot keys."""
    from arch_competition.stack_bundle_eval_v1 import group_snapshot_columns
    from tools.feature_curation_gate import load_ablation_manifest

    manifest = load_ablation_manifest()
    vwap = next(g for g in manifest["groups"] if g["group_id"] == "reg__atomic__vwap_dist_pts")
    cols = group_snapshot_columns(vwap)
    assert "vwap_dist_pts" in cols
    assert "vwap_side" not in cols
    assert "cat_vwap_side" not in cols
    assert "vwap_dist_pct" not in cols


def test_permute_snapshot_columns_across_rows_isolates_group():
    import numpy as np
    from arch_competition.stack_bundle_eval_v1 import permute_snapshot_columns_across_rows

    rows = [{"a": i, "b": i * 10} for i in range(6)]
    out = permute_snapshot_columns_across_rows(rows, ["a"], np.random.default_rng(0))
    assert [r["b"] for r in out] == [r["b"] for r in rows]
    assert sorted(r["a"] for r in out) == sorted(r["a"] for r in rows)
    assert [r["a"] for r in out] != [r["a"] for r in rows]


def test_curation_gate_keeps_override_protected_index_family():
    from tools.feature_curation_gate import _protected_db_columns

    protected = _protected_db_columns()
    assert "tnx_yield" in protected
    assert "qqq_vs_spy" in protected
    assert "spy_chg_pct" in protected
    assert "qqq_chg_pct" in protected


def test_ablation_channel_mapping_pre_and_post_mask():
    """Test-lock the sequence channel mapping (the 'reads as zero' risk surface)."""
    import numpy as np
    from lstm_data import ENCODED_FEATURES_5M, FEATURES_5M
    from tools.feature_curation_gate import (
        _post_mask_channel_indices,
        _pre_mask_encoded_indices,
    )

    # Stage 2: flat tabular channels (no __present mask expansion)
    pre_iv = _pre_mask_encoded_indices(["iv_level"], FEATURES_5M, ENCODED_FEATURES_5M)
    assert [ENCODED_FEATURES_5M[i] for i in pre_iv] == ["iv_level"]
    pre_ng = _pre_mask_encoded_indices(["net_gamma"], FEATURES_5M, ENCODED_FEATURES_5M)
    assert [ENCODED_FEATURES_5M[i] for i in pre_ng] == ["net_gamma"]
    assert _pre_mask_encoded_indices(["kre_chg_pct"], FEATURES_5M, ENCODED_FEATURES_5M) == [
        FEATURES_5M.index("kre_chg_pct")
    ]
    # post-mask reindex: drop channel 0 -> surviving indices shift down by 1, stay in range
    mask = np.ones(len(ENCODED_FEATURES_5M), dtype=bool)
    mask[0] = False
    post = _post_mask_channel_indices(pre_iv, mask)
    assert post == [i - 1 for i in pre_iv]
    assert all(0 <= c < int(mask.sum()) for c in post)
    # member whose only channel is mask-dropped -> empty (observable count 0, not silent)
    drop_mask = np.ones(len(ENCODED_FEATURES_5M), dtype=bool)
    for i in pre_ng:
        drop_mask[i] = False
    assert _post_mask_channel_indices(pre_ng, drop_mask) == []


def test_ablation_permute_sequence_isolates_target_channels():
    import numpy as np
    from tools.feature_curation_gate import _permute_sequence_channels

    X = np.arange(8 * 3 * 4, dtype=np.float32).reshape(8, 3, 4)
    out = _permute_sequence_channels(X, [1], np.random.default_rng(0))
    assert not np.array_equal(out[:, :, 1], X[:, :, 1])  # targeted channel shuffled
    assert sorted(out[:, 0, 1].tolist()) == sorted(X[:, 0, 1].tolist())  # same multiset
    for c in (0, 2, 3):
        assert np.array_equal(out[:, :, c], X[:, :, c])  # untargeted channels intact
    # empty target = no-op
    assert np.array_equal(
        _permute_sequence_channels(X, [], np.random.default_rng(0)), X
    )


def test_cf_drop_routes_to_conf_and_zeroes_x_conf_prediction():
    """cf_* ablation drops must zero X_conf (not X_5m) and change LSTM holdout predictions."""
    import torch
    import numpy as np
    from lstm_data import CONFLUENCE_FEATURES
    from lstm_model import build_model
    from tools.feature_curation_gate import (
        _drop_members_for_model,
        _lstm_predict_numpy,
        _zero_conf_channels,
    )

    manifest = {
        "groups": [
            {
                "group_id": "reg__atomic__cf_momentum_5m",
                "atomic_column": "cf_momentum_5m",
            }
        ]
    }
    xgb, m5, m1, conf = _drop_members_for_model(manifest, ["reg__atomic__cf_momentum_5m"])
    assert conf == ["cf_momentum_5m"]
    assert m5 == []
    assert m1 == []

    n_val = 24
    t5, t1 = 4, 3
    n_conf = len(CONFLUENCE_FEATURES)
    rng = np.random.default_rng(0)
    val_5m = rng.standard_normal((n_val, 5, t5)).astype(np.float32)
    val_1m = rng.standard_normal((n_val, 3, t1)).astype(np.float32)
    val_conf = rng.standard_normal((n_val, n_conf)).astype(np.float32)
    val_conf[:, 0] = 0.85

    device = torch.device("cpu")
    model = build_model(t5, t1, n_conf).to(device)
    y_val = np.clip((val_conf[:, 0] * 2 + val_conf[:, 2] * 3).astype(int), 0, 2)
    train_end = 16
    criterion = torch.nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.05)
    train_loader = torch.utils.data.DataLoader(
        torch.utils.data.TensorDataset(
            torch.tensor(val_5m[:train_end]),
            torch.tensor(val_1m[:train_end]),
            torch.tensor(val_conf[:train_end]),
            torch.tensor(y_val[:train_end]),
        ),
        batch_size=8,
        shuffle=True,
    )
    for _ in range(20):
        model.train()
        for b5, b1, bc, by in train_loader:
            optimizer.zero_grad()
            loss = criterion(model(b1, b5, bc), by)
            loss.backward()
            optimizer.step()
    model.eval()

    base_pred = _lstm_predict_numpy(model, val_5m[train_end:], val_1m[train_end:], val_conf[train_end:], device)
    dropped_conf = np.array(val_conf[train_end:], copy=True)
    _zero_conf_channels(dropped_conf, ["cf_momentum_5m"])
    cf_idx = CONFLUENCE_FEATURES.index("cf_momentum_5m")
    assert dropped_conf[:, cf_idx].max() == 0.0
    assert dropped_conf[:, cf_idx].min() == 0.0

    with torch.no_grad():
        b5 = torch.tensor(val_5m[train_end:], dtype=torch.float32)
        b1 = torch.tensor(val_1m[train_end:], dtype=torch.float32)
        bc_base = torch.tensor(val_conf[train_end:], dtype=torch.float32)
        bc_drop = torch.tensor(dropped_conf, dtype=torch.float32)
        logits_base = model(b1, b5, bc_base).numpy()
        logits_drop = model(b1, b5, bc_drop).numpy()
    assert not np.allclose(logits_base, logits_drop, atol=1e-6)
    drop_pred = _lstm_predict_numpy(model, val_5m[train_end:], val_1m[train_end:], dropped_conf, device)
    assert drop_pred.shape == base_pred.shape


def test_survivor_edge_probe_cf_drop_members_not_silently_discarded(monkeypatch, tmp_path):
    """Edge probe must 4-unpack cf_* into conf — stale 3-unpack silently discarded drops."""
    import arch_competition.stack_bundle_eval_v1 as sbe
    from arch_competition.stack_bundle_eval_v1 import ABLATION_CONFIRM_PATH_VERSION
    from tools.feature_curation_gate import run_survivor_edge_probe

    cf_gid = "reg__atomic__cf_momentum_5m"
    report = {
        "survivor_summary": {
            "scored_cell_count": 100,
            "confirm_pass": {
                "cells": [
                    {
                        "anchor_ticker": "SPY",
                        "model_family": "lstm",
                        "horizon_slug": "1c",
                        "status": "ok",
                        "safe_to_drop": True,
                        "dropped_groups": [cf_gid],
                        "mcc_change": 0.012,
                    }
                ],
                "anchors_required": 1,
                "confirm_path_version": ABLATION_CONFIRM_PATH_VERSION,
            },
        },
    }
    manifest = {
        "ablation_method": {"feature_grain": "schwab_expanded_atomic"},
        "groups": [
            {
                "group_id": cf_gid,
                "atomic_column": "cf_momentum_5m",
            }
        ],
    }
    rp = tmp_path / "feature_ablation_report_leaf.json"
    mp = tmp_path / "feature_ablation_manifest_leaf.json"
    rp.write_text(json.dumps(report), encoding="utf-8")
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(sbe, "_authoritative_ablation_report_path", lambda: rp)
    monkeypatch.setattr(sbe, "_authoritative_ablation_manifest_path", lambda: mp)
    monkeypatch.setattr(sbe, "compound_survivors_voided", lambda: False)
    monkeypatch.setattr(sbe, "ablation_full_matrix_cell_target", lambda: 100)
    monkeypatch.setenv("ED_APPLY_ABLATION_SURVIVORS", "1")
    monkeypatch.setattr(
        "tools.feature_curation_gate.SURVIVOR_EDGE_PROBE_PATH",
        tmp_path / "edge_probe.json",
    )
    for fn in (
        sbe.ablated_drop_group_ids_for_model_horizon,
        sbe.ablated_drop_members_for_model_horizon,
    ):
        fn.cache_clear()
    try:
        out = run_survivor_edge_probe(tickers=["SPY"], min_mcc_edge=0.001)
        issues = " ".join(out.get("issues") or [])
        assert "drop_resolve_failed" not in issues
        lstm_1c = next(
            c for c in out["cells"]
            if c["model_family"] == "lstm" and c["horizon_slug"] == "1c"
        )
        assert lstm_1c["drop_group_count"] == 1
        assert lstm_1c["lstm_conf_members"] == 1
        assert lstm_1c["lstm_5m_members"] == 0
        assert lstm_1c["verdict"] == "EDGE"
    finally:
        for fn in (
            sbe.ablated_drop_group_ids_for_model_horizon,
            sbe.ablated_drop_members_for_model_horizon,
        ):
            fn.cache_clear()


def test_survivor_validation_run_passes_drop_conf_to_lstm_holdout(monkeypatch, tmp_path):
    """Validation-run report path must wire cf_* members into LSTM holdout drop_conf."""
    import arch_competition.stack_bundle_eval_v1 as sbe
    from tools import feature_curation_gate as fcg

    cf_gid = "reg__lstm_5m__cf_momentum_5m"
    manifest = {
        "ablation_method": {"feature_grain": "schwab_expanded_atomic"},
        "groups": [
            {
                "group_id": cf_gid,
                "atomic_column": "cf_momentum_5m",
            }
        ],
    }
    report = {
        "survivor_summary": {
            "scored_cell_count": 100,
            "confirm_pass": {
                "cells": [
                    {
                        "anchor_ticker": "SPY",
                        "model_family": "lstm",
                        "horizon_slug": "1c",
                        "status": "ok",
                        "safe_to_drop": True,
                        "dropped_groups": [cf_gid],
                    }
                ],
                "anchors_required": 1,
                "confirm_path_version": "2",
            },
        },
    }
    rp = tmp_path / "feature_ablation_report_leaf.json"
    mp = tmp_path / "feature_ablation_manifest_leaf.json"
    rp.write_text(json.dumps(report), encoding="utf-8")
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(sbe, "_authoritative_ablation_report_path", lambda: rp)
    monkeypatch.setattr(sbe, "_authoritative_ablation_manifest_path", lambda: mp)
    monkeypatch.setattr(sbe, "compound_survivors_voided", lambda: False)
    monkeypatch.setattr(sbe, "ablation_full_matrix_cell_target", lambda: 100)
    monkeypatch.setenv("ED_APPLY_ABLATION_SURVIVORS", "1")
    monkeypatch.setattr(fcg, "SURVIVOR_VALIDATION_RUN_PATH", tmp_path / "validation.json")
    monkeypatch.setattr(
        fcg,
        "run_survivor_edge_probe",
        lambda **kwargs: {"ready_for_full_retrain": True, "issues": [], "summary": {}},
    )
    monkeypatch.setattr(fcg, "load_ablation_manifest", lambda: manifest)

    lstm_calls: list[dict] = []

    def _fake_lstm_holdout(**kwargs):
        lstm_calls.append(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(fcg, "_prepare_lstm_holdout", _fake_lstm_holdout)
    monkeypatch.setattr(fcg, "_prepare_xgb_holdout", lambda **kwargs: {"status": "skipped"})
    monkeypatch.setattr(fcg, "_prepare_transformer_holdout", lambda **kwargs: {"status": "skipped"})

    for fn in (
        sbe.ablated_drop_group_ids_for_model_horizon,
        sbe.ablated_drop_members_for_model_horizon,
    ):
        fn.cache_clear()
    try:
        out = fcg.run_survivor_validation_run(tickers=["SPY"], db_path=":memory:")
        assert lstm_calls, "LSTM holdout must run for lstm/1c with confirm-verified drops"
        assert lstm_calls[0]["drop_conf"] == ["cf_momentum_5m"]
        assert lstm_calls[0]["drop_5m"] == []
        assert lstm_calls[0]["drop_1m"] == []
        lstm_cell = next(
            c for c in out["cells"]
            if c["model_family"] == "lstm" and c["horizon_slug"] == "1c"
        )
        assert lstm_cell["parity_ok"] is True
    finally:
        for fn in (
            sbe.ablated_drop_group_ids_for_model_horizon,
            sbe.ablated_drop_members_for_model_horizon,
        ):
            fn.cache_clear()


def test_stage2_sequence_encoder_width_matches_xgb_tabular_universe():
    """Stage 2: LSTM streams = tabular minus cf_*; cf_* on X_conf only (no double representation)."""
    from lstm_data import CONFLUENCE_FEATURES, LSTM_ENCODER_SCHEMA_VERSION, encoded_width_5m, encoded_width_1m
    from ml_train import tabular_training_feature_names

    tabular = tabular_training_feature_names()
    assert len(tabular) == 94
    assert set(CONFLUENCE_FEATURES).issubset(set(tabular))
    assert LSTM_ENCODER_SCHEMA_VERSION == 3
    assert encoded_width_5m() == len(tabular) - len(CONFLUENCE_FEATURES)
    assert encoded_width_1m() == len(tabular) - len(CONFLUENCE_FEATURES)
    assert encoded_width_5m() == 88


def test_xgb_cf_member_in_tabular_universe_and_permute_perturbs():
    """cf_* are engineered XGB columns — grouped permute must change holdout matrix values."""
    import numpy as np
    import pandas as pd

    from ml_train import engineer_features, probe_training_feature_row
    from tools.feature_curation_gate import permute_group_columns_together

    rows = []
    base = probe_training_feature_row()
    for i in range(20):
        r = dict(base)
        r["ts_utc"] = float(1000 + i * 300)
        r["spot"] = 100.0 + i * 0.15
        r["vwap"] = 99.5 + i * 0.1
        rows.append(r)
    df = pd.DataFrame(rows)
    X, names, _, _ = engineer_features(df)
    assert "cf_momentum_5m" in names
    tail = X.iloc[-5:].copy()
    assert tail["cf_momentum_5m"].nunique(dropna=False) > 1
    rng = np.random.default_rng(42)
    permuted = permute_group_columns_together(tail, ["cf_momentum_5m"], rng)
    assert not np.allclose(
        permuted["cf_momentum_5m"].to_numpy(),
        tail["cf_momentum_5m"].to_numpy(),
    )


def test_ablation_manifest_signs_base_models_and_confirm_pass():
    """Production manifest + module constants declare confirm pass and base-model comparisons."""
    from tools.build_feature_assignment_matrix_v2 import BASE_MODEL_COMPARISONS, FULL_STACK_ABLATION_MODES
    from tools.feature_curation_gate import load_ablation_manifest

    method = load_ablation_manifest()["ablation_method"]
    assert method["primary_pass"] == "per_model_per_horizon_atomic_permutation_importance"
    assert method["confirm_pass"] == "per_model_per_horizon_atomic_drop_column_refit_on_survivors"
    assert set(BASE_MODEL_COMPARISONS) == {
        "lstm_over_xgb",
        "transformer_over_xgb",
        "transformer_over_pair",
    }
    for cmp in BASE_MODEL_COMPARISONS.values():
        assert cmp["baseline"] in FULL_STACK_ABLATION_MODES
        assert cmp["treatment"] in FULL_STACK_ABLATION_MODES
    assert "xgb_plus_lstm" in FULL_STACK_ABLATION_MODES
    assert "xgb_plus_transformer" in FULL_STACK_ABLATION_MODES


def test_drop_snapshot_columns_nulls_numeric_and_neutralizes_categorical():
    from arch_competition.stack_bundle_eval_v1 import drop_snapshot_columns_across_rows

    rows = [{"vwap_dist_pts": 1.5, "vwap_side": "above",
             "candle_direction": "up", "net_gamma": 2.0}]
    out = drop_snapshot_columns_across_rows(
        rows, ["vwap_dist_pts", "vwap_side", "candle_direction"]
    )
    assert out[0]["vwap_dist_pts"] is None           # numeric -> None
    assert out[0]["vwap_side"] is None               # MVP-locked categorical (zone/vwap_side/prev_zone) -> None
    assert out[0]["candle_direction"] == "neutral"   # non-locked categorical -> neutral
    assert out[0]["net_gamma"] == 2.0                # untouched


def test_ablation_confirm_drop_group_ids_from_survivor_summary():
    from tools.feature_curation_gate import ablation_confirm_drop_group_ids

    summary = {
        "groups": [
            {"group_id": "a", "recommendation": "DROP_CANDIDATE"},
            {"group_id": "b", "recommendation": "KEEP_CANDIDATE"},
        ]
    }
    assert ablation_confirm_drop_group_ids(summary) == ["a"]


def test_ablation_survivor_summary_rollup():
    from tools.feature_curation_gate import build_ablation_survivor_summary

    cells = [
        {"ablation_kind": "whole_stack_feature_group", "model_family": "xgb",
         "horizon_slug": "5c", "group_id": "vix", "status": "ok", "runnable": True,
         "log_loss_delta": 0.05, "group_matters": True},
        {"ablation_kind": "whole_stack_feature_group", "model_family": "xgb",
         "horizon_slug": "5c", "group_id": "vix", "status": "ok", "runnable": True,
         "log_loss_delta": 0.01, "group_matters": False},
        {"ablation_kind": "whole_stack_feature_group", "model_family": "lstm",
         "horizon_slug": "5c", "group_id": "charm", "status": "skipped", "runnable": True,
         "reason": "no_model_interface", "grid_skip_reason": "no_model_interface"},
    ]
    summary = build_ablation_survivor_summary(cells)
    assert summary["ok_cell_count"] == 2
    assert summary["metric"] == "multiclass_log_loss_delta"
    assert summary["by_model_horizon"]["xgb"]["5c"][0]["group_id"] == "vix"
    assert summary["by_model_horizon"]["xgb"]["5c"][0]["recommendation"] == "KEEP_CANDIDATE"
    flat = {(g["model_family"], g["group_id"]): g for g in summary["groups"]}
    assert flat[("xgb", "vix")]["recommendation"] == "KEEP_CANDIDATE"
    assert flat[("lstm", "charm")]["recommendation"] == "SKIPPED"


def test_ablation_survivor_training_mask_defaults(monkeypatch):
    """O-56 fail-closed contract (money path): the SHARED-snapshot survivor mask never auto-applies
    an unverified or fabricated drop set. It is empty (train/serve on the full feature set) unless an
    explicit operator override OR a confirm-verified globally-safe intersection exists."""
    from arch_competition import stack_bundle_eval_v1 as sbe
    from arch_competition.stack_bundle_eval_v1 import (
        ablation_drop_snapshot_columns,
        apply_ablation_survivor_nulls_to_snapshot,
        resolve_ablation_drop_group_ids,
    )

    # 1) survivors OFF -> empty (full feature set).
    monkeypatch.delenv("ED_ABLATION_DROP_GROUPS", raising=False)
    monkeypatch.delenv("ED_APPLY_ABLATION_SURVIVORS", raising=False)
    monkeypatch.delenv("ED_ABLATION_SCORING_PASS", raising=False)
    monkeypatch.delenv("ED_LIVE_ABLATION_EXPERIMENT", raising=False)
    monkeypatch.delenv("ED_ABLATION_PRIMARY_AUTHORITY", raising=False)
    monkeypatch.setattr(sbe, "live_ablation_experiment_active", lambda: False)
    assert resolve_ablation_drop_group_ids() == []

    # 2) survivors ON, no override, no confirm pass on the live report -> FAIL-CLOSED to empty.
    monkeypatch.setenv("ED_APPLY_ABLATION_SURVIVORS", "1")
    monkeypatch.delenv("ED_ABLATION_SCORING_PASS", raising=False)
    monkeypatch.setattr(sbe, "globally_safe_drop_group_ids", lambda _ss: [])
    monkeypatch.setattr(sbe, "ablation_primary_pass_authority_active", lambda *a, **k: False)
    sbe._ablation_drop_snapshot_columns_cached.cache_clear()
    assert resolve_ablation_drop_group_ids() == []

    # 3) explicit operator override drives the mask machinery deterministically.
    # Fidelity-first knockouts only null in_cone manifest groups (not_wired → no columns).
    monkeypatch.setenv(
        "ED_ABLATION_DROP_GROUPS",
        "reg__atomic__vwap_dist_pts,reg__atomic__atr",
    )
    sbe._ablation_drop_snapshot_columns_cached.cache_clear()
    assert resolve_ablation_drop_group_ids() == [
        "reg__atomic__atr",
        "reg__atomic__vwap_dist_pts",
    ]
    cols = ablation_drop_snapshot_columns()
    assert "vwap_dist_pts" in cols
    assert "atr" in cols

    snap = {"vwap_dist_pts": 1.25, "atr": 2.0, "spot": 100.0, "ticker": "SPY"}
    masked = apply_ablation_survivor_nulls_to_snapshot(snap)
    assert masked["vwap_dist_pts"] is None
    assert masked["atr"] is None
    assert masked["spot"] == 100.0
    sbe._ablation_drop_snapshot_columns_cached.cache_clear()


def test_globally_safe_drop_is_confirm_verified_intersection():
    """A group is safe to null in the SHARED snapshot only if EVERY (model, horizon) cell confirmed
    it safe_to_drop — the intersection. If any cell still needs it, it survives the global mask."""
    from arch_competition.stack_bundle_eval_v1 import (
        confirmed_drop_group_ids_by_model_horizon,
        globally_safe_drop_group_ids,
    )

    ss = {
        "confirm_pass": {
            "anchors_required": 2,
            "cells": [
                {
                    "model_family": "xgb",
                    "horizon_slug": "1c",
                    "status": "ok",
                    "safe_to_drop": True,
                    "dropped_groups": ["breadth_etf", "charm"],
                },
                {
                    "model_family": "xgb",
                    "horizon_slug": "1c",
                    "status": "ok",
                    "safe_to_drop": True,
                    "dropped_groups": ["breadth_etf", "charm"],
                },
                {
                    "model_family": "lstm",
                    "horizon_slug": "1c",
                    "status": "ok",
                    "safe_to_drop": True,
                    "dropped_groups": ["breadth_etf"],
                },
                {
                    "model_family": "lstm",
                    "horizon_slug": "1c",
                    "status": "ok",
                    "safe_to_drop": True,
                    "dropped_groups": ["breadth_etf"],
                },
            ],
        }
    }
    by_cell = confirmed_drop_group_ids_by_model_horizon(ss)
    assert by_cell[("xgb", "1c")] == {"breadth_etf", "charm"}
    assert by_cell[("lstm", "1c")] == {"breadth_etf"}
    assert globally_safe_drop_group_ids(ss) == ["breadth_etf"]


def test_confirmed_drops_require_all_anchors_safe():
    from arch_competition.stack_bundle_eval_v1 import confirmed_drop_group_ids_by_model_horizon

    ss = {
        "confirm_pass": {
            "anchors_required": 3,
            "cells": [
                {"model_family": "xgb", "horizon_slug": "5c", "status": "ok", "safe_to_drop": True, "dropped_groups": ["vix"]},
                {"model_family": "xgb", "horizon_slug": "5c", "status": "ok", "safe_to_drop": True, "dropped_groups": ["vix"]},
                {"model_family": "xgb", "horizon_slug": "5c", "status": "ok", "safe_to_drop": False, "dropped_groups": ["vix"]},
            ],
        }
    }
    assert confirmed_drop_group_ids_by_model_horizon(ss) == {}


def test_ablation_confirm_resume_skips_completed_cells():
    from tools.feature_curation_gate import (
        _confirm_cell_key,
        build_per_model_confirm_pass_section,
        load_ablation_manifest,
    )

    manifest = load_ablation_manifest()
    done_cell = {
        "anchor_ticker": "SPY",
        "model_family": "lstm",
        "horizon_slug": "15c",
        "status": "ok",
        "ablation_kind": "per_model_confirm_drop",
        "dropped_groups": ["charm"],
        "safe_to_drop": True,
    }
    resume = {_confirm_cell_key("SPY", "lstm", "15c"): done_cell}
    calls: list[tuple] = []

    def _prep(**kwargs):
        calls.append(kwargs)
        return {"status": "skipped", "reason": "must_not_run"}

    out: list[dict] = []
    section = build_per_model_confirm_pass_section(
        manifest,
        db_path=":memory:",
        drops_by_mh={("lstm", "15c"): ["charm"]},
        full_baseline={("SPY", "lstm", "15c"): 0.1},
        tickers=["SPY"],
        cells_out=out,
        resume_cells=resume,
    )
    assert section["confirm_drop_cell_count"] == 1
    assert out == [done_cell]
    assert calls == []


def test_stack_authority_cells_complete_gate():
    from tools.feature_curation_gate import stack_authority_cells_complete

    ok_cell = {
        "anchor_ticker": "SPY",
        "horizon_slug": "1c",
        "status": "ok",
        "paired_rows": 0,
        "layer_lifts": {
            "meta": {"baseline_log_loss": 1.0, "treatment_log_loss": 0.9},
            "monte_carlo": {"baseline_log_loss": 1.0, "treatment_log_loss": 0.95},
            "fusion": {"baseline_log_loss": 0.95, "treatment_log_loss": 0.9},
        },
        "base_model_lifts": {
            "lstm_over_xgb": {"baseline_log_loss": 1.1, "treatment_log_loss": 1.0},
            "transformer_over_xgb": {"baseline_log_loss": 1.1, "treatment_log_loss": 1.05},
            "transformer_over_pair": {"baseline_log_loss": 1.0, "treatment_log_loss": 0.98},
        },
    }
    ready, issues = stack_authority_cells_complete([ok_cell])
    assert ready and not issues
    bad = dict(ok_cell)
    bad["status"] = "failed"
    bad["base_model_lifts"]["lstm_over_xgb"] = {"baseline_log_loss": None, "treatment_log_loss": 1.0}
    ready2, issues2 = stack_authority_cells_complete([bad])
    assert not ready2 and issues2


def test_ablation_scoring_pass_disables_survivor_mask(monkeypatch):
    from arch_competition.stack_bundle_eval_v1 import (
        ABLATION_SCORING_PASS_ENV,
        ablation_survivors_training_enabled,
    )

    monkeypatch.delenv(ABLATION_SCORING_PASS_ENV, raising=False)
    monkeypatch.setenv("ED_APPLY_ABLATION_SURVIVORS", "1")
    assert ablation_survivors_training_enabled() is True
    monkeypatch.setenv(ABLATION_SCORING_PASS_ENV, "1")
    assert ablation_survivors_training_enabled() is False


def test_sequence_encoder_lineage_fail_closed_without_feature_names():
    from arch_competition.stack_bundle_eval_v1 import sequence_encoder_lineage_admissible
    from lstm_data import LSTM_ENCODER_SCHEMA_VERSION

    meta = {"n_features_5m": 27, "feature_schema_version": "v7_m5_strip"}
    ckpt = {"encoder_schema_version": LSTM_ENCODER_SCHEMA_VERSION, "encoder_width_5m_pre_mask": 88}
    ok, reason = sequence_encoder_lineage_admissible(meta, ckpt)
    assert not ok
    assert "encoder_feature_names_5m" in reason


def test_sequence_encoder_lineage_v2_pinned_registry_admissible():
    from arch_competition.stack_bundle_eval_v1 import sequence_encoder_lineage_admissible

    meta = {"n_features_5m": 27}
    ckpt = {
        "encoder_schema_version": 2,
        "encoder_width_5m_pre_mask": 31,
        "mask_5m": [True] * 31,
        "mask_1m": [True] * 16,
    }
    ok, reason = sequence_encoder_lineage_admissible(meta, ckpt)
    assert ok, reason


def test_ablation_preflight_ready_requires_whole_stack_only():
    from tools.feature_curation_gate import run_ablation_preflight

    manifest = {
        "ablation_method": {
            "horizons": ["1c", "5c", "15c", "60c"],
            "pool_tickers": ["SPY", "QQQ", "IWM"],
            "feature_grain": "schwab_expanded_atomic",
        }
    }
    pf = run_ablation_preflight(manifest, db_path="nonexistent.db", tickers=["SPY"])
    assert pf["ready"] is False
    assert pf["ready_for_whole_stack"] is False
    assert pf["ready"] == pf["ready_for_whole_stack"]


def test_xgb_post_engineer_drop_matches_confirm_path(monkeypatch, tmp_path):
    """Production XGB must drop engineered manifest members after engineer_features."""
    import arch_competition.stack_bundle_eval_v1 as sbe
    from arch_competition.stack_bundle_eval_v1 import drop_ablated_xgb_engineered_columns

    report = {
        "ablation_method": {"feature_grain": "schwab_expanded_atomic"},
        "survivor_summary": {
            "scored_cell_count": 100,
            "confirm_pass": {
                "cells": [
                    {
                        "anchor_ticker": "SPY",
                        "model_family": "xgb",
                        "horizon_slug": "5c",
                        "status": "ok",
                        "safe_to_drop": True,
                        "dropped_groups": ["reg__atomic__iv_level"],
                    }
                ],
                "anchors_required": 1,
                "confirm_path_version": "2",
            },
        },
    }
    manifest = {
        "ablation_method": {"feature_grain": "schwab_expanded_atomic"},
        "groups": [
            {
                "group_id": "reg__atomic__iv_level",
                "atomic_column": "iv_level",
            }
        ],
    }
    rp = tmp_path / "feature_ablation_report_leaf.json"
    mp = tmp_path / "feature_ablation_manifest_leaf.json"
    rp.write_text(json.dumps(report), encoding="utf-8")
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(sbe, "_authoritative_ablation_report_path", lambda: rp)
    monkeypatch.setattr(sbe, "_authoritative_ablation_manifest_path", lambda: mp)
    monkeypatch.setattr(sbe, "compound_survivors_voided", lambda: False)
    monkeypatch.setattr(sbe, "ablation_full_matrix_cell_target", lambda: 100)
    monkeypatch.setenv("ED_APPLY_ABLATION_SURVIVORS", "1")
    for fn in (
        sbe.ablated_drop_group_ids_for_model_horizon,
        sbe.ablated_drop_members_for_model_horizon,
    ):
        fn.cache_clear()
    df = _minimal_df()
    df["iv_level"] = 0.2
    X, names, _, _ = engineer_features(df)
    assert "body_range_ratio" in names
    X2, names2, n = drop_ablated_xgb_engineered_columns(X, names, "5c")
    assert n == 1
    assert "iv_level" not in names2
    for fn in (
        sbe.ablated_drop_group_ids_for_model_horizon,
        sbe.ablated_drop_members_for_model_horizon,
    ):
        fn.cache_clear()


def test_ablated_drop_requires_confirm_not_primary(monkeypatch, tmp_path):
    """Primary-pass DROP_CANDIDATE must never reach training when survivors env is on."""
    from arch_competition import stack_bundle_eval_v1 as sbe
    from arch_competition.stack_bundle_eval_v1 import AblatedTrainingUnavailable

    report = {
        "ablation_method": {"feature_grain": "schwab_expanded_atomic"},
        "survivor_summary": {
            "scored_cell_count": 828,
            "confirm_pass": "run_with_--ablation-confirm",
            "by_model_horizon": {
                "xgb": {
                    "1c": [{"group_id": "charm", "recommendation": "DROP_CANDIDATE"}],
                }
            },
        },
    }
    rp = tmp_path / "feature_ablation_report_leaf.json"
    mp = tmp_path / "feature_ablation_manifest_leaf.json"
    rp.write_text(json.dumps(report), encoding="utf-8")
    mp.write_text(json.dumps({"ablation_method": {"feature_grain": "atomic_leaf_or_derived_column"}, "groups": []}), encoding="utf-8")
    monkeypatch.setattr(sbe, "_authoritative_ablation_report_path", lambda: rp)
    monkeypatch.setattr(sbe, "_authoritative_ablation_manifest_path", lambda: mp)
    monkeypatch.setattr(sbe, "compound_survivors_voided", lambda: False)
    monkeypatch.setattr(sbe, "ablation_full_matrix_cell_target", lambda: 828)
    monkeypatch.setenv("ED_APPLY_ABLATION_SURVIVORS", "1")
    monkeypatch.delenv("ED_LIVE_ABLATION_EXPERIMENT", raising=False)
    monkeypatch.delenv("ED_ABLATION_PRIMARY_AUTHORITY", raising=False)
    monkeypatch.setattr(sbe, "live_ablation_experiment_active", lambda: False)
    sbe.ablated_drop_group_ids_for_model_horizon.cache_clear()
    try:
        with pytest.raises(AblatedTrainingUnavailable, match="ablation-confirm"):
            sbe.ablated_drop_group_ids_for_model_horizon("xgb", "1c")
    finally:
        sbe.ablated_drop_group_ids_for_model_horizon.cache_clear()


def test_primary_pass_recommendation_alone_is_not_a_verified_drop():
    """DROP_CANDIDATE in the primary rollup WITHOUT a confirm pass yields zero verified drops."""
    from arch_competition.stack_bundle_eval_v1 import (
        confirmed_drop_group_ids_by_model_horizon,
        globally_safe_drop_group_ids,
    )

    ss = {"by_model_horizon": {"xgb": {"1c": [{"group_id": "charm", "recommendation": "DROP_CANDIDATE"}]}}}
    assert confirmed_drop_group_ids_by_model_horizon(ss) == {}
    assert globally_safe_drop_group_ids(ss) == []


def test_primary_authority_applies_primary_drops_when_stamped(monkeypatch, tmp_path):
    from arch_competition import stack_bundle_eval_v1 as sbe

    report = {
        "run_meta": {"status": "complete"},
        "ablation_method": {"feature_grain": "schwab_expanded_atomic"},
        "survivor_summary": {
            "scored_cell_count": 828,
            "primary_pass_authority": True,
            "by_model_horizon": {
                "xgb": {
                    "1c": [{"group_id": "charm", "recommendation": "DROP_CANDIDATE"}],
                }
            },
        },
        "confirm_drop_summary": {"primary_authority": True, "authority": "primary_pass"},
    }
    rp = tmp_path / "feature_ablation_report_leaf.json"
    mp = tmp_path / "feature_ablation_manifest_leaf.json"
    rp.write_text(json.dumps(report), encoding="utf-8")
    mp.write_text(
        json.dumps(
            {
                "ablation_method": {"feature_grain": "atomic_leaf_or_derived_column"},
                "groups": [{"group_id": "charm", "atomic_column": "charm", "disposition": "ABLATE"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sbe, "_authoritative_ablation_report_path", lambda: rp)
    monkeypatch.setattr(sbe, "_authoritative_ablation_manifest_path", lambda: mp)
    monkeypatch.setattr(sbe, "compound_survivors_voided", lambda: False)
    monkeypatch.setattr(sbe, "ablation_full_matrix_cell_target", lambda: 828)
    monkeypatch.setenv("ED_APPLY_ABLATION_SURVIVORS", "1")
    sbe.ablated_drop_group_ids_for_model_horizon.cache_clear()
    try:
        assert sbe.ablated_drop_group_ids_for_model_horizon("xgb", "1c") == ["charm"]
    finally:
        sbe.ablated_drop_group_ids_for_model_horizon.cache_clear()


def test_stamp_primary_ablation_authority_writes_confirm_drop_summary(tmp_path, monkeypatch):
    from tools.feature_curation_gate import stamp_primary_ablation_authority

    report = {
        "run_meta": {"status": "complete"},
        "whole_stack_feature_cells": [{"status": "ok"}] * 828,
        "survivor_summary": {
            "scored_cell_count": 828,
            "primary_pass_only": True,
            "by_model_horizon": {
                "xgb": {
                    "1c": [{"group_id": "charm", "recommendation": "DROP_CANDIDATE"}],
                }
            },
        },
    }
    rp = tmp_path / "feature_ablation_report_leaf.json"
    rp.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(
        "arch_competition.stack_bundle_eval_v1.ablation_full_matrix_cell_target",
        lambda: 828,
    )
    stamped = stamp_primary_ablation_authority(rp)
    summary = stamped.get("confirm_drop_summary") or {}
    assert summary.get("primary_authority") is True
    assert summary.get("authority") == "primary_pass"
    assert summary.get("drops_by_model_horizon", {}).get("xgb/1c") == ["charm"]


def test_survivor_retrain_gate_env_contract():
    from tools.feature_curation_gate import validate_survivor_retrain_gate_env

    bad = validate_survivor_retrain_gate_env({})
    assert not bad["ok"]
    assert any("ED_APPLY_ABLATION_SURVIVORS" in i for i in bad["issues"])

    ok_env = {
        "ED_APPLY_ABLATION_SURVIVORS": "1",
        "ED_ML_SCHEDULER_TICKERS": "SPY,QQQ,IWM",
        "ED_SCHEDULER_AUTO_PROMOTE": "1",
        "ED_SCHEDULER_AUTO_PROMOTE_CORE_ONLY": "1",
    }
    good = validate_survivor_retrain_gate_env(ok_env)
    assert good["ok"], good["issues"]

    polluted = dict(ok_env)
    polluted["ED_TRAIN_ROLLING_RTH_SESSIONS_TABULAR"] = "20"
    bad2 = validate_survivor_retrain_gate_env(polluted)
    assert not bad2["ok"]


def test_guard_ablation_fresh_start_blocks_complete_report(tmp_path, monkeypatch):
    from tools.feature_curation_gate import guard_ablation_fresh_start

    monkeypatch.setattr(
        "tools.feature_curation_gate.whole_stack_cell_target",
        lambda manifest=None: 100,
    )
    report_path = tmp_path / "feature_ablation_report.json"
    runnable_cells = [{"runnable": True, "status": "ok"}] * 100
    report_path.write_text(
        json.dumps(
            {
                "whole_stack_feature_cells": runnable_cells,
                "whole_stack_runnable_cell_target": 100,
                "run_meta": {"status": "complete"},
            }
        ),
        encoding="utf-8",
    )
    import pytest

    with pytest.raises(SystemExit):
        guard_ablation_fresh_start(report_path, resume=False, force_restart=False)
    guard_ablation_fresh_start(report_path, resume=True, force_restart=False)
    guard_ablation_fresh_start(report_path, resume=False, force_restart=True)


def test_ablation_grid_is_per_model_horizon():
    """O-56 anti-drift LOCK: ablation MUST be per-model × per-horizon, never model-agnostic.

    If anyone reframes the feature ablation back to a single model-agnostic grid (whole-stack /
    full_fusion as the feature pass), this fails — forcing the contract to hold.
    """
    from tools.feature_curation_gate import (
        ablation_per_model_feature_cell_specs,
        build_ablation_report,
        load_ablation_manifest,
    )

    method = load_ablation_manifest()["ablation_method"]
    assert set(method["models"]) == {"xgb", "lstm", "transformer"}
    assert method["decision_metric"] == "mcc_delta"
    manifest = load_ablation_manifest()
    specs = ablation_per_model_feature_cell_specs(manifest)
    if "grid" in method:
        assert "model_family" in method["grid"]
    assert {s["model_family"] for s in specs} == {"xgb", "lstm", "transformer"}
    # a single (anchor, horizon, group) appears once PER MODEL (no collapse to one global list)
    by_amg: dict = {}
    for s in specs:
        by_amg.setdefault(
            (s["anchor_ticker"], s["horizon_slug"], s["group_id"]), set()
        ).add(s["model_family"])
    assert all(models == {"xgb", "lstm", "transformer"} for models in by_amg.values())
    # the live dry-run report emits per-model cells, not model-agnostic ones
    report = build_ablation_report(dry_run=True)
    assert "per_model_feature_cells" in report
    assert all("model_family" in c for c in report["per_model_feature_cells"])


def test_ablation_report_status_counts(tmp_path):
    from tools.feature_curation_gate import ablation_report_status

    missing = ablation_report_status(tmp_path / "nope.json")
    assert missing["run_status"] == "missing"
    assert not missing["complete"]


def test_snap_dict_does_not_apply_global_ablation(monkeypatch):
    """O-56 serve: _snap_dict is row-normalization only; masks live in each predictor."""
    monkeypatch.setenv("ED_APPLY_ABLATION_SURVIVORS", "1")
    from ml_predict import _snap_dict

    snap = {"ticker": "SPY", "spot": 100.0, "iv": 0.2}
    out = _snap_dict(snap)
    assert out is not None
    assert out.get("iv") == 0.2


def test_serve_ablation_mask_differs_by_model_family(monkeypatch):
    """Per-model serve masks must not collapse to one global intersection (O-56)."""
    from arch_competition.stack_bundle_eval_v1 import (
        ABLATION_LEAF_REPORT_PATH,
        ablation_confirm_pass_complete,
        ablation_primary_pass_authority_active,
        compound_survivors_voided,
    )

    if compound_survivors_voided():
        pytest.skip("compound ablation survivors void — re-ablate on leaf manifest")
    report_path = ABLATION_LEAF_REPORT_PATH
    if not report_path.is_file():
        pytest.skip("leaf ablation report missing")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    ss = report.get("survivor_summary") or {}
    if not ablation_confirm_pass_complete(ss) and not ablation_primary_pass_authority_active(
        ss, report=report
    ):
        pytest.skip("live ablation report lacks confirm or primary-pass authority")
    monkeypatch.setenv("ED_LIVE_ABLATION_EXPERIMENT", "1")
    monkeypatch.delenv("ED_APPLY_ABLATION_SURVIVORS", raising=False)
    from arch_competition.stack_bundle_eval_v1 import (
        ablation_drop_snapshot_columns_for_model_horizon,
    )
    from ml_predict import _apply_serve_ablation_snapshot, set_ml_infer_horizon_slug

    xcols = set(ablation_drop_snapshot_columns_for_model_horizon("xgb", "1c"))
    lcols = set(ablation_drop_snapshot_columns_for_model_horizon("lstm", "1c"))
    only_lstm = sorted(lcols - xcols)
    if not only_lstm:
        return
    probe_col = only_lstm[0]
    tok = set_ml_infer_horizon_slug("1c")
    try:
        base = {
            "ticker": "SPY",
            "spot": 100.0,
            "timeframe": "1m",
            probe_col: 0.25,
        }
        xgb = _apply_serve_ablation_snapshot(dict(base), "xgb")
        lstm = _apply_serve_ablation_snapshot(dict(base), "lstm")
        assert xgb.get(probe_col) == 0.25
        assert lstm.get(probe_col) is None
    finally:
        from ml_predict import reset_ml_infer_horizon_slug

        reset_ml_infer_horizon_slug(tok)


def test_cascade_tensor_builder_uses_split_xgb_lstm_extracts():
    """Cascade in-sample tensor: XGB probs from xgb-masked rows, LSTM from lstm-masked."""
    from ml_scheduler import _build_in_sample_cascade_xgb_lstm_tensor

    src = inspect.getsource(_build_in_sample_cascade_xgb_lstm_tensor)
    assert "days_xgb" in src and 'model_family="xgb"' in src
    assert "days_lstm" in src and 'model_family="lstm"' in src
    assert "current_xgb" in src and "snapshots_xgb" in src


def test_write_ablation_report_backs_up_completed_report(tmp_path):
    """HARDENING LOCK (incident 2026-06-03): a COMPLETE scored report must never be silently
    destroyed — write_ablation_report snapshots it to .complete.bak.json before any overwrite."""
    import json

    from tools.feature_curation_gate import write_ablation_report

    p = tmp_path / "feature_ablation_report.json"
    bak = p.with_name(p.stem + ".complete.bak" + p.suffix)

    # First write of a COMPLETE report: nothing prior to back up.
    write_ablation_report(
        {"run_meta": {"status": "complete"}, "per_model_feature_cells": [{"group_id": "iv"}]}, p
    )
    assert p.is_file() and not bak.is_file()

    # Overwriting the complete report (e.g., a dry-run or fresh run) MUST snapshot the prior first.
    write_ablation_report({"run_meta": {"status": "partial"}, "dry_run": True}, p)
    assert bak.is_file(), "completed report was overwritten without a backup"
    preserved = json.loads(bak.read_text(encoding="utf-8"))
    assert preserved["run_meta"]["status"] == "complete"
    assert preserved["per_model_feature_cells"][0]["group_id"] == "iv"


def test_compound_ablation_survivors_voided(monkeypatch, tmp_path):
    """Compound workbook survivors are retired — no drops until leaf ablation completes."""
    import arch_competition.stack_bundle_eval_v1 as sbe
    from arch_competition.stack_bundle_eval_v1 import (
        AblatedTrainingUnavailable,
        ablation_confirm_pass_complete,
        compound_survivors_voided,
        resolve_ablation_drop_group_ids,
        void_compound_ablation_survivors,
    )

    compound_report = {
        "survivor_summary": {
            "scored_cell_count": 828,
            "confirm_pass": {
                "cells": [{"model_family": "xgb", "horizon_slug": "1c", "status": "ok", "safe_to_drop": True, "dropped_groups": ["vix"]}],
                "anchors_required": 1,
                "confirm_path_version": "2",
            },
        }
    }
    legacy = tmp_path / "feature_ablation_report.json"
    legacy.write_text(json.dumps(compound_report), encoding="utf-8")
    status = tmp_path / "ablation_survivor_status.json"
    monkeypatch.setattr(sbe, "LEGACY_COMPOUND_REPORT_PATH", legacy)
    monkeypatch.setattr(sbe, "ABLATION_SURVIVOR_STATUS_PATH", status)
    monkeypatch.setattr(sbe, "_authoritative_ablation_report_path", lambda: None)

    void_compound_ablation_survivors(write_artifacts=True)
    assert compound_survivors_voided()
    assert not ablation_confirm_pass_complete()
    monkeypatch.setenv("ED_APPLY_ABLATION_SURVIVORS", "1")
    sbe.ablated_drop_group_ids_for_model_horizon.cache_clear()
    assert resolve_ablation_drop_group_ids() == []
    with pytest.raises(AblatedTrainingUnavailable, match="VOID"):
        sbe.ablated_drop_group_ids_for_model_horizon("xgb", "1c")


def test_schwab_ablation_universe_contract():
    from tools.check_fix_everything_we_touch import check_ablation_schwab_universe_contract
    from tools.build_feature_assignment_matrix_v2 import (
        MIN_ABLATION_EXPANSION_FACTOR,
        resolve_expanded_schwab_ablation_universe,
    )

    payload = resolve_expanded_schwab_ablation_universe()
    reg_n = int(payload["totals"]["registered_ml_cone_columns"])
    ablate_n = int(payload["totals"]["ablation_group_count"])
    assert ablate_n >= reg_n * MIN_ABLATION_EXPANSION_FACTOR
    assert payload["ablation_method"]["feature_grain"] == "schwab_expanded_atomic"
    assert payload["ablation_method"]["primary_pass"] == "per_model_per_horizon_atomic_permutation_importance"
    assert "grouped" not in payload["ablation_method"]["primary_pass"]
    gids = {g["group_id"] for g in payload["groups"] if g.get("disposition") == "ABLATE"}
    for cf in (
        "cf_alignment_score",
        "cf_greek_support",
        "cf_momentum_5m",
        "cf_structure_15m",
        "cf_trend_1h",
        "cf_vwap_distance_pct",
    ):
        assert f"reg__atomic__{cf}" in gids, f"missing confluence feature group {cf}"
    assert int(payload["totals"]["schwab_dictionary_rows"]) >= 2300
    errs = check_ablation_schwab_universe_contract()
    assert errs == [], errs


def test_check_ablation_pipeline_parity_green():
    from tools.check_ablation_pipeline_parity import check_ablation_pipeline_parity

    assert check_ablation_pipeline_parity() == []


def test_null_snapshot_dict_for_drop_groups():
    from arch_competition.stack_bundle_eval_v1 import null_snapshot_dict_for_drop_groups

    manifest = {
        "groups": [
            {
                "group_id": "g1",
                "atomic_column": "dist_call_gamma_wall_pct",
                "ingest_status": "in_cone",
            }
        ]
    }
    snap = {"spot": 100.0, "dist_call_gamma_wall_pct": 0.5, "ticker": "SPY"}
    out = null_snapshot_dict_for_drop_groups(snap, manifest, ["g1"])
    assert out["spot"] == 100.0
    assert out["dist_call_gamma_wall_pct"] is None


def test_confirm_holdout_uses_drop_group_ids_not_production_mask():
    import tools.feature_curation_gate as gate

    src = inspect.getsource(gate.build_per_model_confirm_pass_section)
    assert "drop_group_ids" in src
    assert "use_production_survivor_mask" not in src


def test_lstm_serve_applies_post_norm_channel_zero():
    from ml_predict import _predict_lstm

    src = inspect.getsource(_predict_lstm)
    assert "zero_ablated_sequence_channels_for_model" in src
    idx_zero = src.index("zero_ablated_sequence_channels_for_model")
    idx_norm = src.index("apply_normalization")
    assert idx_zero > idx_norm


def test_ablation_confirm_path_version_required():
    from arch_competition.stack_bundle_eval_v1 import (
        ABLATION_CONFIRM_PATH_VERSION,
        ablation_confirm_pass_complete,
    )

    stale = {"confirm_pass": {"cells": [{"status": "ok"}], "confirm_path_version": "1"}}
    assert not ablation_confirm_pass_complete(stale)
    current = {
        "confirm_pass": {
            "cells": [{"status": "ok"}],
            "confirm_path_version": ABLATION_CONFIRM_PATH_VERSION,
        }
    }
    assert ablation_confirm_pass_complete(current)


def test_parallel_eval_includes_skip_stats_in_source():
    from ml_scheduler import _evaluate_parallel_on_full_rth

    src = inspect.getsource(_evaluate_parallel_on_full_rth)
    assert "skip_stats" in src
    assert "parallel_runtime=True" in src
    assert "triplet starvation" in src
    assert "max_eval_rows" in src


def test_confirm_fresh_start_refuses_partial_v2(tmp_path):
    from arch_competition.stack_bundle_eval_v1 import ABLATION_CONFIRM_PATH_VERSION
    from tools.feature_curation_gate import guard_ablation_confirm_fresh_start

    report_path = tmp_path / "feature_ablation_report.json"
    report_path.write_text(
        json.dumps(
            {
                "confirm_drop_cells": [
                    {
                        "anchor_ticker": "SPY",
                        "model_family": "lstm",
                        "horizon_slug": "15c",
                        "status": "ok",
                        "confirm_path_version": ABLATION_CONFIRM_PATH_VERSION,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="refusing fresh confirm"):
        guard_ablation_confirm_fresh_start(report_path, resume=False)
    guard_ablation_confirm_fresh_start(report_path, resume=True)
    guard_ablation_confirm_fresh_start(report_path, resume=False, force_restart=True)


def test_ablation_report_status_includes_confirm_progress(tmp_path, monkeypatch):
    from arch_competition.stack_bundle_eval_v1 import ABLATION_CONFIRM_PATH_VERSION
    from tools.feature_curation_gate import (
        PER_MODEL_CONFIRM_CELL_TARGET,
        ablation_report_status,
    )

    report_path = tmp_path / "feature_ablation_report.json"
    report_path.write_text(
        json.dumps(
            {
                "run_progress": {
                    "phase": "per_model_confirm",
                    "cells_done": 9,
                    "cells_total": PER_MODEL_CONFIRM_CELL_TARGET,
                },
                "confirm_drop_cells": [{"status": "ok"}] * 9,
                "survivor_summary": {
                    "confirm_pass": {
                        "cells": [{"status": "ok"}],
                        "confirm_path_version": None,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "tools.feature_curation_gate.ABLATION_LOCK_PATH",
        tmp_path / "missing.lock",
    )
    status = ablation_report_status(report_path)
    assert status["confirm_cells_done"] == 9
    assert status["confirm_cells_total"] == PER_MODEL_CONFIRM_CELL_TARGET
    assert status["confirm_complete"] is False
    assert status["confirm_resume_recommended"] is False


def test_confirm_cells_carry_path_version():
    from arch_competition.stack_bundle_eval_v1 import ABLATION_CONFIRM_PATH_VERSION
    from tools.feature_curation_gate import _confirm_resume_cells_from_report

    report = {
        "confirm_drop_cells": [
            {
                "anchor_ticker": "SPY",
                "model_family": "xgb",
                "horizon_slug": "1c",
                "status": "ok",
                "confirm_path_version": ABLATION_CONFIRM_PATH_VERSION,
            }
        ],
        "survivor_summary": {
            "confirm_pass": {
                "cells": [
                    {
                        "anchor_ticker": "SPY",
                        "model_family": "lstm",
                        "horizon_slug": "5c",
                        "status": "ok",
                    }
                ]
            }
        },
    }
    resumed = _confirm_resume_cells_from_report(report)
    assert len(resumed) == 1
    assert "SPY|xgb|1c" in resumed


def test_parallel_cascade_bridge_cache_roundtrip(tmp_path):
    from training_cache import (
        load_parallel_cascade_bridge,
        save_parallel_cascade_bridge,
    )

    ticker = "SPY"
    data_fp = {
        "table": "snapshots_1m_normalized",
        "timeframe": "1m",
        "ticker": ticker,
        "min_ts_utc": 1.0,
        "max_ts_utc": 2.0,
        "row_count": 100,
    }
    fk = "test_bridge_key"
    cache_dir = tmp_path / fk
    probs = np.array([[0.2, 0.3, 0.5], [0.4, 0.3, 0.3]], dtype=np.float32)
    xgb_pkl = tmp_path / "xgb_SPY_1c.pkl"
    xgb_meta = tmp_path / "xgb_SPY_1c_meta.json"
    xgb_pkl.write_bytes(b"xgb")
    xgb_meta.write_text('{"features": []}', encoding="utf-8")
    save_parallel_cascade_bridge(cache_dir, ticker, data_fp, fk, probs, xgb_pkl, xgb_meta)
    loaded = load_parallel_cascade_bridge(
        cache_dir, ticker, data_fp, fk, expected_n_samples=2,
    )
    assert loaded is not None
    assert loaded.shape == (2, 3)


def test_full_stack_models_contract():
    from tools.check_fix_everything_we_touch import check_full_stack_models_contract

    errs = check_full_stack_models_contract()
    assert errs == [], errs


def test_ml_pipeline_efficiency_checker_green():
    from tools.check_ml_pipeline_efficiency import check_ml_pipeline_efficiency

    assert check_ml_pipeline_efficiency() == []


def test_ablation_parity_includes_bridge_and_backtest_hooks():
    from tools.check_ablation_pipeline_parity import check_ablation_pipeline_parity

    assert check_ablation_pipeline_parity() == []

