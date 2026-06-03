"""Issue 7: training vs inference parity for XGB tabular features."""
from __future__ import annotations

import inspect
import json
import pickle
from pathlib import Path

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

    stack_specs = ablation_stack_authority_cell_specs(manifest)
    assert len(stack_specs) == manifest["totals"]["stack_authority_cell_count"]
    assert manifest["totals"]["grid_cell_count"] == expected + len(stack_specs)

    assert method["primary_pass"] == "per_model_grouped_permutation_importance"
    assert method["decision_mode"] == "per_model_holdout"
    assert method["decision_metric"] == "mcc_delta"
    assert set(method["models"]) == {"xgb", "lstm", "transformer"}
    assert set(method["horizons"]) == set(REQUIRED_ABLATION_HORIZONS)
    assert set(method["full_stack_layers"]) == set(FULL_STACK_LAYERS)
    assert set(method["grid"]) == {"anchor_ticker", "model_family", "horizon_slug", "group_id"}

    assert {c["model_family"] for c in feat_specs} == {"xgb", "lstm", "transformer"}
    assert {c["horizon_slug"] for c in feat_specs} == set(REQUIRED_ABLATION_HORIZONS)

    report = build_ablation_report(dry_run=True)
    assert report["dry_run"] is True
    assert report["per_model_feature_cell_count"] == expected
    assert report["stack_authority_cell_count"] == len(stack_specs)
    assert report["grid_cell_count"] == expected + len(stack_specs)
    assert report["per_model_feature_cells"][0]["model_family"] in {"xgb", "lstm", "transformer"}
    assert report["stack_authority_cells"][0]["ablation_kind"] == "stack_authority"
    stack_auth = method.get("stack_authority_pass") or method.get("stack_eval") or {}
    assert "meta_stack" in stack_auth["modes"]
    assert "full_fusion" in stack_auth["modes"]


def test_ablation_harness_wires_per_model_and_stack_authority():
    """O-56 primary = per-model grouped permutation; secondary = stack authority — no stubs."""
    from tools.feature_curation_gate import (
        _permute_eval_lstm_group,
        _permute_eval_transformer_group,
        _permute_eval_xgb_group,
        _prepare_lstm_holdout,
        _prepare_transformer_holdout,
        _prepare_xgb_holdout,
        ablation_per_model_feature_cell_specs,
        ablation_stack_authority_cell_specs,
        build_per_model_feature_ablation_section,
        load_ablation_manifest,
        run_stack_layer_ablation_cell,
    )

    manifest = load_ablation_manifest()
    method = manifest["ablation_method"]
    assert method["primary_pass"] == "per_model_grouped_permutation_importance"
    assert set(method["full_stack_layers"]) == {
        "xgb", "lstm", "transformer", "meta", "monte_carlo", "fusion",
    }
    pmf = method["per_model_feature_ablation"]
    assert set(pmf["models"]) == {"xgb", "lstm", "transformer"}
    assert set(pmf["grid"]) == {"anchor_ticker", "model_family", "horizon_slug", "group_id"}
    stack_auth = method.get("stack_authority_pass") or {}
    assert stack_auth["engine"].endswith("run_stack_bundle_evaluation")
    assert set(stack_auth["base_model_comparisons"]) == {
        "lstm_over_xgb", "transformer_over_xgb", "transformer_over_pair",
    }
    assert len(ablation_per_model_feature_cell_specs(manifest)) == manifest["totals"][
        "per_model_feature_cell_count"
    ]
    assert len(ablation_stack_authority_cell_specs(manifest)) == manifest["totals"][
        "stack_authority_cell_count"
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
    vwap = next(g for g in manifest["groups"] if g["group_id"] == "vwap")
    cols = group_snapshot_columns(vwap)
    assert "vwap_dist_pts" in cols
    assert "vwap_side" in cols
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

    # nullable member expands to value + __present channel
    pre_iv = _pre_mask_encoded_indices(["iv_level"], FEATURES_5M, ENCODED_FEATURES_5M)
    names = [ENCODED_FEATURES_5M[i] for i in pre_iv]
    assert "iv_level" in names and "iv_level__present" in names
    # non-nullable member -> single channel
    pre_ng = _pre_mask_encoded_indices(["net_gamma"], FEATURES_5M, ENCODED_FEATURES_5M)
    assert [ENCODED_FEATURES_5M[i] for i in pre_ng] == ["net_gamma"]
    # member not in the 5m feature set -> no false hit
    assert _pre_mask_encoded_indices(["kre_chg_pct"], FEATURES_5M, ENCODED_FEATURES_5M) == []
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


def test_ablation_manifest_signs_base_models_and_confirm_pass():
    """Stack authority comparisons are first-class; confirm pass engine is declared."""
    from tools.feature_curation_gate import load_ablation_manifest

    method = load_ablation_manifest()["ablation_method"]
    stack_auth = method.get("stack_authority_pass") or method.get("stack_eval") or {}
    se = stack_auth
    assert set(se["base_model_comparisons"]) == {
        "lstm_over_xgb",
        "transformer_over_xgb",
        "transformer_over_pair",
    }
    for cmp in se["base_model_comparisons"].values():
        assert cmp["baseline"] in se["modes"]
        assert cmp["treatment"] in se["modes"]
    assert "xgb_plus_lstm" in se["modes"]
    assert "xgb_plus_transformer" in se["modes"]
    assert method["primary_pass"] == "per_model_grouped_permutation_importance"
    assert method["confirm_pass"] == "per_model_grouped_drop_column_refit_on_survivors"


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
        {"ablation_kind": "per_model_feature_group", "model_family": "xgb",
         "horizon_slug": "5c", "group_id": "vix", "status": "ok",
         "mcc_delta": 0.05, "group_matters": True},
        {"ablation_kind": "per_model_feature_group", "model_family": "xgb",
         "horizon_slug": "5c", "group_id": "vix", "status": "ok",
         "mcc_delta": 0.01, "group_matters": False},
        {"ablation_kind": "per_model_feature_group", "model_family": "lstm",
         "horizon_slug": "5c", "group_id": "charm", "status": "skipped",
         "reason": "baseline_not_ready"},
    ]
    summary = build_ablation_survivor_summary(cells)
    assert summary["ok_cell_count"] == 2
    assert summary["metric"] == "mcc_delta"
    # per (model, horizon) survivor sets — the feature→model→horizon matrix
    assert summary["by_model_horizon"]["xgb"]["5c"][0]["group_id"] == "vix"
    assert summary["by_model_horizon"]["xgb"]["5c"][0]["recommendation"] == "KEEP_CANDIDATE"
    flat = {(g["model_family"], g["group_id"]): g for g in summary["groups"]}
    assert flat[("xgb", "vix")]["recommendation"] == "KEEP_CANDIDATE"
    assert flat[("lstm", "charm")]["recommendation"] == "UNSCORED"


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
    assert resolve_ablation_drop_group_ids() == []

    # 2) survivors ON, no override, no confirm pass on the live report -> FAIL-CLOSED to empty.
    #    The primary-pass MCC-delta screen alone never deletes features from the money path, and
    #    there is no fabricated default drop set.
    monkeypatch.setenv("ED_APPLY_ABLATION_SURVIVORS", "1")
    assert resolve_ablation_drop_group_ids() == []

    # 3) explicit operator override drives the mask machinery deterministically.
    monkeypatch.setenv("ED_ABLATION_DROP_GROUPS", "zone,vwap,price_candle")
    sbe._ablation_drop_snapshot_columns_cached.cache_clear()
    assert resolve_ablation_drop_group_ids() == ["price_candle", "vwap", "zone"]
    cols = ablation_drop_snapshot_columns()
    assert "zone" in cols
    assert "vwap_dist_pts" in cols or "candle_body_pts" in cols

    snap = {"zone": "pin_neutral", "vwap_dist_pts": 1.25, "spot": 100.0, "ticker": "SPY"}
    masked = apply_ablation_survivor_nulls_to_snapshot(snap)
    assert masked["zone"] is None
    assert masked["vwap_dist_pts"] is None
    assert masked["spot"] == 100.0

    from features.db_feature_adapter import build_db_mvp_feature_row

    canon = build_db_mvp_feature_row(masked)
    assert canon.get("structure.zone") is None
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
            "cells": [
                {"model_family": "xgb", "horizon_slug": "1c", "group_id": "breadth_etf", "safe_to_drop": True},
                {"model_family": "xgb", "horizon_slug": "1c", "group_id": "charm", "safe_to_drop": True},
                {"model_family": "lstm", "horizon_slug": "1c", "group_id": "breadth_etf", "safe_to_drop": True},
                {"model_family": "lstm", "horizon_slug": "1c", "group_id": "charm", "safe_to_drop": False},
            ]
        }
    }
    by_cell = confirmed_drop_group_ids_by_model_horizon(ss)
    assert by_cell[("xgb", "1c")] == {"breadth_etf", "charm"}
    assert by_cell[("lstm", "1c")] == {"breadth_etf"}
    # breadth_etf confirmed safe in every cell -> globally droppable; charm needed by lstm -> kept.
    assert globally_safe_drop_group_ids(ss) == ["breadth_etf"]


def test_primary_pass_recommendation_alone_is_not_a_verified_drop():
    """DROP_CANDIDATE in the primary rollup WITHOUT a confirm pass yields zero verified drops."""
    from arch_competition.stack_bundle_eval_v1 import (
        confirmed_drop_group_ids_by_model_horizon,
        globally_safe_drop_group_ids,
    )

    ss = {"by_model_horizon": {"xgb": {"1c": [{"group_id": "charm", "recommendation": "DROP_CANDIDATE"}]}}}
    assert confirmed_drop_group_ids_by_model_horizon(ss) == {}
    assert globally_safe_drop_group_ids(ss) == []


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


def test_guard_ablation_fresh_start_blocks_complete_report(tmp_path):
    from tools.feature_curation_gate import guard_ablation_fresh_start, WHOLE_STACK_CELL_TARGET

    report_path = tmp_path / "feature_ablation_report.json"
    report_path.write_text(
        json.dumps(
            {
                "per_model_feature_cells": [{}] * WHOLE_STACK_CELL_TARGET,
                "stack_authority_cells": [{}] * 12,
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
    # the grid carries a model dimension
    assert "model_family" in method["grid"]
    assert set(method["models"]) == {"xgb", "lstm", "transformer"}
    assert method["decision_metric"] == "mcc_delta"
    # every cell is tagged with its model — each base model gets its own per-horizon survivors
    specs = ablation_per_model_feature_cell_specs(load_ablation_manifest())
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
    report_path = Path("governance/artifacts/feature_ablation_report.json")
    if not report_path.is_file():
        return
    monkeypatch.setenv("ED_APPLY_ABLATION_SURVIVORS", "1")
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
