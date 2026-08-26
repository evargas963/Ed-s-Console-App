"""Issue 7: training vs inference parity for XGB tabular features."""
from __future__ import annotations

import inspect
import json
import pickle

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


def test_price_action_cone_gated_behind_retrain():
    """PA-CONE-V8-RETRAIN [REAL-GATE: training-skew] (2026-06-11): the 27 pa_*
    columns are persisted + ablation candidates, but NOT in the serving cone.
    Registering them early fail-closed every v7-trained bundle and killed the
    live stack. The flip lands in the SAME commit as retrained artifacts.

    STILL GATED after the RC-436 retrain (2026-08-26). That retrain RETIRED four
    withheld columns and bumped the schema to v8_wall_oi_vanna_retired; it did NOT
    register pa_*. A retirement and an expansion are separate changes with separate
    evidence, and bundling them would make neither attributable — so this test keeps
    locking pa_* OUT of the cone, and no longer pins the version string (which the
    retrain legitimately moved). PA-CONE remains open."""
    from features.signal_layer_v1 import SNAPSHOT_PRICE_ACTION_COLUMNS
    from ml_train import SCALE_INVARIANT_COLS, tabular_training_feature_names
    from training_provenance import FEATURE_SCHEMA_VERSION

    pa_cols = [c for c, _ in SNAPSHOT_PRICE_ACTION_COLUMNS]
    assert len(pa_cols) == 27
    # The pa_* cone is still shut. Version is asserted by the dedicated contract test.
    assert not FEATURE_SCHEMA_VERSION.startswith("v8_price_action")
    assert not set(pa_cols) & set(SCALE_INVARIANT_COLS)
    assert not [n for n in tabular_training_feature_names() if n.startswith("pa_")]

    # Ablation universe carries every pa_* atom (ZERO-BIAS: data decides placement).
    from tools.build_feature_assignment_matrix_v2 import resolve_ablation_universe

    payload = resolve_ablation_universe()
    manifest_pa = {
        g.get("atomic_column")
        for g in payload.get("groups") or []
        if str(g.get("atomic_column") or "").startswith("pa_")
    }
    assert manifest_pa == set(pa_cols)


def test_dgex_first_diff_engineered_train_and_serve(tmp_path):
    import sqlite3

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

    # RC-342: net_gamma_prev is the RAW prior 1m bar. Back the frame with a fixture DB
    # holding these consecutive bars so raw-prior == frame-prior (dgex[1] still 4-1=3.0).
    dbp = tmp_path / "dgex.db"
    with sqlite3.connect(str(dbp)) as conn:
        df.assign(timeframe="1m")[["ticker", "timeframe", "ts_utc", "net_gamma"]].to_sql(
            "snapshots", conn, index=False)
    df = attach_net_gamma_prev_column(df, str(dbp))
    X, names, _, _ = engineer_features(df, db_path=str(dbp))
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

    from ml_data_common import SERVE_SNAPSHOT_TABLE, attach_net_gamma_prev_column, attach_net_gamma_prev_for_dgex
    from timeframe_config import CANONICAL_TIMEFRAME

    # RC-244 (follow-on to RC-207): this fixture built SNAPSHOT_TABLE_1M
    # (`snapshots_1m_normalized`), but RC-207 repointed the SERVE path to `snapshots` when the
    # normalized mirror was found b-tree corrupt. The fixture was never moved with it, so the
    # test asked the serve reader for a table it no longer reads and failed on "no such table:
    # snapshots" — a stale double, not a product defect. Bind the fixture to the SAME constant
    # the serve path resolves, so a future repoint moves both together instead of silently
    # splitting them again.
    db = tmp_path / "dgex_parity.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        f"CREATE TABLE {SERVE_SNAPSHOT_TABLE} ("
        "ticker TEXT NOT NULL, timeframe TEXT NOT NULL, ts_utc REAL NOT NULL, net_gamma REAL)"
    )
    for ts, ng in ((100.0, 1.0), (160.0, 4.0), (220.0, 2.0)):
        conn.execute(
            f"INSERT INTO {SERVE_SNAPSHOT_TABLE} (ticker, timeframe, ts_utc, net_gamma) VALUES (?, ?, ?, ?)",
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
    df = attach_net_gamma_prev_column(df, str(db))  # RC-342: same raw authority as serve
    X_train, names, _, _ = engineer_features(df, db_path=str(db))

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


def test_feature_schema_version_matches_trained_artifacts():
    """The version flips only WITH retrained artifacts, never ahead of them
    (2026-06-11 live-stack outage class).

    This used to assert a hardcoded version STRING, which pins the wrong thing: a
    string tells you nobody edited a constant, not that the shipped artifacts can
    actually be served. The invariant the docstring names is a relationship between
    the code contract and the artifacts ON DISK, so that is what is checked here.

    WHAT IS AND IS NOT ASSERTED, and why the distinction is load-bearing. A first
    version demanded that EVERY active meta carry the current feature_schema_version.
    That over-reaches, and measuring it showed why: 82 of 91 artifacts under
    models/active declare v4_canonical_1m and fail the contract on
    LABEL_CONFIG_VERSION — an axis with nothing to do with any feature bump. They
    were already unservable before this or any other version change (measured: 9 of
    91 valid under the previous v7 contract too). Folding them into this gate would
    let a genuinely stranded artifact hide inside a crowd of long-dead ones.

    So the assertion is exact: NO artifact may fail the contract ONLY on
    feature_schema_version. That is precisely the "you bumped ahead of your
    artifacts" failure, and it does not conflate with pre-existing label-contract
    deaths. The dead ones are asserted not to GROW, so this cannot quietly become a
    licence to strand more."""
    import json
    from pathlib import Path

    from model_contract import contract_metadata_dict, validate_artifact_contract
    from training_provenance import FEATURE_SCHEMA_VERSION, PREPROCESSING_VERSION

    assert PREPROCESSING_VERSION == "v5_no_m5_lag"

    active = Path(__file__).resolve().parent.parent / "models" / "active"
    if not active.is_dir():
        pytest.skip("no models/active tree in this checkout")
    metas = sorted(active.glob("*/*_meta.json"))
    if not metas:
        pytest.skip("models/active has no metas — nothing promoted to check against")

    expected = contract_metadata_dict()
    stranded: list[str] = []
    dead_other: list[str] = []
    valid = 0
    for m in metas:
        fam = m.name.split("_", 1)[0]
        if fam not in ("xgb", "lstm", "transformer"):
            continue
        try:
            meta = json.loads(m.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        ok, _why = validate_artifact_contract(meta, fam)
        if ok:
            valid += 1
            continue
        # Does it differ ONLY on the feature schema? Then the bump stranded it.
        other_axis_mismatch = [k for k, need in expected.items()
                               if k != "feature_schema_version" and meta.get(k) != need]
        if not other_axis_mismatch and meta.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
            stranded.append(f"{m.parent.name}/{m.name}: "
                            f"{meta.get('feature_schema_version')!r}")
        else:
            dead_other.append(f"{m.parent.name}/{m.name}: {other_axis_mismatch}")

    assert not stranded, (
        f"FEATURE_SCHEMA_VERSION is {FEATURE_SCHEMA_VERSION!r} and {len(stranded)} artifact(s) "
        f"match the contract on every OTHER axis — the bump stranded working artifacts. Retrain "
        f"and promote them in the SAME commit as the bump. Stranded: {stranded[:6]}")

    # A bump must not silently enlarge the graveyard either.
    assert len(dead_other) <= 82, (
        f"{len(dead_other)} artifacts are contract-dead on axes other than the feature schema, "
        f"up from the 82 measured on 2026-08-26. Something took more artifacts out of service; "
        f"investigate before shipping. Examples: {dead_other[:4]}")
    assert valid > 0, (
        "NO artifact under models/active satisfies the contract — the live stack cannot serve "
        "anything at all")


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
    # 90 at v8_wall_oi_vanna_retired. Was 94 at v7; the RC-436 retrain retired the four
    # structurally withheld OI/vanna wall distances (94 -> 90 tabular, 88 -> 84 sequence).
    # Becomes 117 (+27 pa_*) only if PA-CONE-V8-RETRAIN ever lands, in the same commit as
    # its own retrained artifacts.
    assert len(tabular) == 90
    # The retirement is asserted by NAME, not only by count: a width that happens to match
    # after some other column silently left would otherwise read as a pass.
    from ml_train import structurally_withheld_wall_distance_feature_names

    assert not set(tabular) & structurally_withheld_wall_distance_feature_names(), (
        "a structurally withheld OI/vanna wall distance is back in the tabular contract — "
        "serving would abstain on every live tick (RC-436)")
    assert set(CONFLUENCE_FEATURES).issubset(set(tabular))
    assert LSTM_ENCODER_SCHEMA_VERSION == 3
    assert encoded_width_5m() == len(tabular) - len(CONFLUENCE_FEATURES)
    assert encoded_width_1m() == len(tabular) - len(CONFLUENCE_FEATURES)
    assert encoded_width_5m() == 84


def test_xgb_cf_member_in_tabular_universe_and_permute_perturbs(tmp_path):
    """cf_* are engineered XGB columns — grouped permute must change holdout matrix values.

    RC-340: rows now live in a FIXTURE DB so cf_* come from the one canonical population
    authority — the caller-rows fallback this test previously leaned on was a second
    population producer and is removed.
    """
    import sqlite3

    import numpy as np
    import pandas as pd

    from ml_train import engineer_features, probe_training_feature_row
    from tools.feature_curation_gate import permute_group_columns_together

    rows = []
    base = probe_training_feature_row()
    for i in range(20):
        r = dict(base)
        r["ticker"] = "SPY"
        r["timeframe"] = "1m"
        r["ts_utc"] = float(1000 + i * 300)
        r["spot"] = 100.0 + i * 0.15
        r["vwap"] = 99.5 + i * 0.1
        rows.append(r)
    df = pd.DataFrame(rows)
    dbp = tmp_path / "cf_fixture.db"
    with sqlite3.connect(str(dbp)) as conn:
        df.to_sql("snapshots", conn, index=False)
    X, names, _, _ = engineer_features(df, db_path=str(dbp))
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


def test_ml_pipeline_efficiency_checker_green():
    from tools.check_ml_pipeline_efficiency import check_ml_pipeline_efficiency

    assert check_ml_pipeline_efficiency() == []


def test_ablation_parity_includes_bridge_and_backtest_hooks():
    from tools.check_ablation_pipeline_parity import check_ablation_pipeline_parity

    assert check_ablation_pipeline_parity() == []


# ── RC-332: cf_* has ONE input population, and callers may not choose it ────────
#
# RC-328 made the confluence WINDOW clock-defined and repaired two lanes. Four more kept
# passing their own row population into the same producer, because the producer's signature
# accepts one. Measured before the fix: 179 divergent cells over 826 SPY bars between the
# LSTM offline and live populations, cf_alignment_score off by up to 3.0 of its -4..+4
# range. These two controls fail if either half of that regresses.

def test_no_production_lane_supplies_its_own_confluence_population():
    """The recurrence mode is a NEW call site passing rows, not a wrong formula.

    Only `ml_data_common` may name the population: once inside the authority, and once in
    its explicitly logged degraded path for frames absent from the canonical series. A
    third site anywhere in production means a lane chose its own population again.
    """
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"], cwd=repo,
        capture_output=True, text=True, check=True).stdout
    offenders = []
    for rel in sorted(p for p in tracked.split("\0") if p):
        if rel.startswith(("tests/", "tools/", "research/", "arch_competition/")):
            continue
        path = repo / rel
        if not path.is_file():
            continue
        for i, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "compute_confluence_features(" in line and "def " not in line:
                offenders.append(f"{rel}:{i}")
    unexpected = [o for o in offenders if not o.startswith("ml_data_common.py:")]
    assert not unexpected, (
        "a production lane passes its own row population to compute_confluence_features "
        f"instead of calling confluence_features_for_bar: {unexpected} (RC-332)")
    assert len(offenders) == 1, (
        "ml_data_common should name the population exactly ONCE — inside the authority; "
        "the caller-rows degraded path was removed as a second population producer "
        f"(RC-340) — found {len(offenders)}: {offenders}")


def test_every_xgb_feature_agrees_between_the_train_and_serve_builders(tmp_path):
    """RC-335 — the Family A lock: two builders, one feature vector, no disagreement.

    `engineer_features` (vectorised, training) and `engineer_single_snapshot` (scalar,
    serving) independently construct the SAME model input. That is two production sites for
    one semantic truth, and the only thing making it legitimate rather than a D6 diverged
    duplicate is that they agree. Three separate defects were found by running exactly this
    comparison over real rows, all invisible to any name- or AST-based scan:

      * `gamma_positive` / `delta_positive` / `charm_delta_agree` — training wrote 0.0 for a
        MISSING net_gamma because `(series > 0)` makes NaN False; serving wrote NaN. 40 of
        60 bars disagreed, and XGBoost routes NaN and 0.0 down different branches.
      * `time_sin` / `time_cos` / `time_progress` / `minutes_since_open` — training derives
        the ET clock from ts_utc, serving read the stored et_hour/et_minute columns that
        this repo already documents as untrustworthy. 6 of 60 bars.
      * `volume_ratio` — collateral: its median key is built from that same clock, so the
        lookup missed and the feature went absent on 4 of 60.

    This runs against a FIXTURE database so it is hermetic, and asserts on every feature the
    training builder emits rather than a chosen subset.
    """
    import sqlite3

    from ml_data_common import (
        attach_confluence_features_for_serve,
        attach_net_gamma_prev_for_dgex,
    )
    from ml_train import engineer_single_snapshot

    n = 90
    base_ts = 1_767_000_000.0          # a fixed weekday RTH instant; no wall-clock reads
    rows = []
    for i in range(n):
        rows.append({
            "ticker": "SPY", "timeframe": "1m", "ts_utc": base_ts + i * 60.0,
            "ts_et": "2026-01-05 09:30:00", "et_hour": 9, "et_minute": 30,
            "spot": 500.0 + (i % 7) * 0.25, "candle_open": 500.0 + (i % 5) * 0.2,
            "candle_high": 501.0 + (i % 3) * 0.1, "candle_low": 499.0 - (i % 4) * 0.1,
            "candle_close": 500.0 + (i % 6) * 0.15, "candle_volume": 1000.0 + i * 3.0,
            "vwap": 500.1, "net_gamma": (None if i % 5 == 0 else 1e6 * (1 if i % 2 else -1)),
            "net_delta": (None if i % 7 == 0 else 5e5 * (1 if i % 3 else -1)),
            "charm_net": (None if i % 11 == 0 else -2e4),
            "flow_imbalance": 0.0 if i % 4 == 0 else 0.62,
            "outcome_5c": "up",
        })
    df = pd.DataFrame(rows)

    dbp = tmp_path / "fixture_console.db"
    with sqlite3.connect(str(dbp)) as conn:
        df.assign(timeframe="1m").to_sql("snapshots", conn, index=False)

    # RC-342: attach net_gamma_prev from the SAME raw authority the serve path uses, so both
    # lanes define "previous" identically (load_data does this before engineer_features).
    from ml_data_common import attach_net_gamma_prev_column
    df = attach_net_gamma_prev_column(df, str(dbp))
    X, names, cat_maps, aux = engineer_features(df, db_path=str(dbp))
    vol_medians = {k: v for k, v in (aux or {}).items() if str(k).startswith("vol_median_")}

    mismatches = []
    for i in range(60, n, 3):
        snap = {k: (None if pd.isna(v) else v) for k, v in df.iloc[i].to_dict().items()}
        # Mirror the production serve preparation EXACTLY (ml_predict.py:920-921). Omitting
        # either attach attributes the test's own gap to the code — dropping the net_gamma
        # one made dgex/dgex_positive read NaN at serve while training had a real value.
        snap = attach_net_gamma_prev_for_dgex(snap, str(dbp))
        snap = attach_confluence_features_for_serve(snap, str(dbp))
        served = engineer_single_snapshot(snap, cat_maps, names, vol_medians, "SPY")
        assert served is not None, f"serve builder returned None for bar {i}"
        for f in names:
            a, b = X.iloc[i][f], served.iloc[0][f]
            a_nan = a is None or (isinstance(a, float) and np.isnan(a))
            b_nan = b is None or (isinstance(b, float) and np.isnan(b))
            if a_nan and b_nan:
                continue
            if a_nan != b_nan:
                mismatches.append(f"{f}@{i}: train={'NaN' if a_nan else a} serve={'NaN' if b_nan else b}")
            elif abs(float(a) - float(b)) > 1e-9:
                mismatches.append(f"{f}@{i}: train={float(a):.8g} serve={float(b):.8g}")

    assert not mismatches, (
        f"{len(mismatches)} train/serve feature disagreement(s) — the two builders are "
        f"producing different model inputs for the same bar (RC-335):\n  "
        + "\n  ".join(sorted(set(mismatches))[:25]))


def test_rc342_net_gamma_prev_has_one_raw_prior_authority():
    """M8 lock (F33): net_gamma_prev = the RAW prior 1m bar, defined ONCE. Train's batch
    attach and serve's per-row fetch must agree on a fixture DB, and engineer_features must
    NOT reconstruct the column locally (the deleted inline shift was a third producer)."""
    import ast as _ast
    import inspect as _inspect
    import sqlite3

    from ml_data_common import attach_net_gamma_prev_column, fetch_prior_net_gamma
    from ml_train import engineer_features

    # No inline shift/diff reconstruction of net_gamma_prev inside engineer_features.
    src = _ast.unparse(_ast.parse(_inspect.getsource(engineer_features)))
    assert "groupby" not in src or "net_gamma" not in src.split("groupby")[0][-40:], True
    assert ".shift(1)" not in src, (
        "engineer_features reconstructs a prior-bar series — third net_gamma_prev "
        "producer (RC-342)")

    # Batch attach == per-row serve fetch, on a fixture DB with an overnight gap.
    import pathlib
    import tempfile
    tmp = pathlib.Path(tempfile.mkdtemp()) / "ng.db"
    raw = pd.DataFrame([
        {"ticker": "SPY", "timeframe": "1m", "ts_utc": 1000.0 + i * 60, "net_gamma": 100.0 + i}
        for i in range(30)])
    with sqlite3.connect(str(tmp)) as conn:
        raw.to_sql("snapshots", conn, index=False)
    frame = raw.iloc[[5, 12, 20, 29]][["ticker", "ts_utc", "net_gamma"]].copy()
    got = attach_net_gamma_prev_column(frame, str(tmp))
    for _i, r in got.iterrows():
        serve = fetch_prior_net_gamma("SPY", float(r["ts_utc"]), str(tmp))
        assert float(r["net_gamma_prev"]) == float(serve), (
            f"batch prev {r['net_gamma_prev']} != serve prev {serve} at ts {r['ts_utc']}")


def test_rc340_every_scheduler_xgb_route_uses_the_canonical_row_preparer():
    """M5 lock (F34): every engineer_single_snapshot call in ml_scheduler must receive a
    row prepared by prepare_row_for_xgb_features — the one enrichment authority. A bare
    row is the RC-340 bypass (cf_* -> 0.0, dgex -> NaN in OOF/bridge vectors)."""
    import ast as _ast
    import inspect as _inspect

    import ml_scheduler as _sched

    src = _inspect.getsource(_sched)
    tree = _ast.parse(src)
    bare = []
    total = 0
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            name = (node.func.id if isinstance(node.func, _ast.Name)
                    else node.func.attr if isinstance(node.func, _ast.Attribute) else "")
            if name == "engineer_single_snapshot" and node.args:
                total += 1
                first = node.args[0]
                ok = (isinstance(first, _ast.Call)
                      and getattr(first.func, "id", getattr(first.func, "attr", ""))
                      == "prepare_row_for_xgb_features")
                if not ok:
                    bare.append(node.lineno)
    assert total >= 5, f"expected >=5 scheduler XGB routes, found {total} — recount needed"
    assert not bare, (
        f"scheduler route(s) at line(s) {bare} feed engineer_single_snapshot a raw row, "
        f"bypassing the canonical preparer (RC-340/M5)")


def test_rc341_train_ticker_forwards_caller_db_to_feature_engineering(monkeypatch):
    """M6A lock (F35): the DB identity train_ticker receives must be the DB identity
    engineer_features queries confluence from. Dropping the forwarding (the pre-RC-340
    state, where the kwarg did not exist) makes this FAIL."""
    import ml_train as _mt

    calls = []

    def _spy(df, fit_end=None, db_path=None):
        calls.append(db_path)
        if db_path is not None:
            raise RuntimeError("stop-after-capture")   # the forwarded call; no training work
        return pd.DataFrame(), [], {}, {}              # internal probe calls pass through

    monkeypatch.setattr(_mt, "engineer_features", _spy)
    df = pd.DataFrame([{"ticker": "SPY", "ts_utc": 1.0, "spot": 500.0,
                        "outcome_5c": "up"}] * 4)
    try:
        _mt.train_ticker("SPY", df, db_path="X:/distinct_caller.db")
    except Exception:
        pass
    assert "X:/distinct_caller.db" in calls, (
        f"train_ticker dropped the caller's DB identity before feature engineering — "
        f"engineer_features calls saw {calls!r} (RC-341/M6A)")


def test_rc341_confluence_cache_key_carries_db_identity(tmp_path):
    """M6B lock (F35): same ticker + same UTC day + a SHARED cache dict + two different
    DBs must yield each DB's own confluence truth in both orders. Removing DB identity
    from the cache key makes the second call return the first DB's pool and FAILS."""
    import sqlite3

    from ml_data_common import confluence_features_for_bar

    def mkdb(name, spot_step):
        rows = pd.DataFrame([{
            "ticker": "SPY", "timeframe": "1m", "ts_utc": 1_767_020_400.0 + i * 60.0,
            "spot": 500.0 + i * spot_step, "vwap": 500.1, "candle_volume": 1000.0,
        } for i in range(80)])
        p = tmp_path / name
        with sqlite3.connect(str(p)) as conn:
            rows.to_sql("snapshots", conn, index=False)
        return str(p)

    db_a = mkdb("a.db", 0.30)          # strong upward drift -> positive momentum/trend
    db_b = mkdb("b.db", -0.30)         # mirror-image drift  -> negative momentum/trend
    ts = 1_767_020_400.0 + 79 * 60.0
    shared_cache: dict = {}

    a1 = confluence_features_for_bar("SPY", ts, db_a, cache=shared_cache)
    b1 = confluence_features_for_bar("SPY", ts, db_b, cache=shared_cache)
    assert a1["cf_momentum_5m"] > 0 > b1["cf_momentum_5m"], (
        "two DBs returned entangled confluence through a shared cache — DB identity is "
        "missing from the cache key (RC-341 / F35)")
    # reverse order on a fresh shared cache, and repeated same-DB access still coherent
    shared_cache2: dict = {}
    b2 = confluence_features_for_bar("SPY", ts, db_b, cache=shared_cache2)
    a2 = confluence_features_for_bar("SPY", ts, db_a, cache=shared_cache2)
    assert b2 == b1 and a2 == a1
    assert confluence_features_for_bar("SPY", ts, db_a, cache=shared_cache2) == a1


def test_rc340_absent_canonical_history_is_governed_absence_not_a_substitute_population():
    """M7 lock (RC-340, Defect C): a frame whose rows are NOT in the canonical population
    must get cf_* = 0.0 — the governed absence contract declared by
    compute_confluence_features — and never values derived from the caller's own rows.
    Reintroducing the caller-rows fallback makes cf_momentum_5m vary here and FAILS."""
    from lstm_data import CONFLUENCE_FEATURES
    from ml_data_common import attach_confluence_feature_columns
    from ml_train import probe_training_feature_row

    rows = []
    base = probe_training_feature_row()
    for i in range(20):
        r = dict(base)
        r["ticker"] = "SPY"
        r["timeframe"] = "1m"
        r["ts_utc"] = float(1000 + i * 300)
        r["spot"] = 100.0 + i * 0.15          # varying spots: a substitute population
        rows.append(r)                         # would produce NONZERO momentum/trend
    out = attach_confluence_feature_columns(pd.DataFrame(rows))  # process-default DB lacks ts 1000..
    for cf in CONFLUENCE_FEATURES:
        vals = pd.to_numeric(out[cf], errors="coerce")
        assert (vals == 0.0).all(), (
            f"{cf} carries derived values for rows absent from the canonical population — "
            f"a substitute population authored the semantic (RC-340)")


def test_rc339_no_feature_formula_reencoded_in_either_builder():
    """RC-339 structural lock: the shared feature semantics live ONLY in the fk_* kernels.

    A builder that re-authors any of them — the pct-of-spot formula, session trig,
    pressure thresholds, log1p, or any bare float threshold comparison — is a second
    computation authority, regardless of whether its numbers currently agree.
    """
    import ast as _ast
    import inspect as _inspect
    import re as _re

    import ml_train as _mt

    banned_substrings = ("* 100.0", "np.sin", "np.cos", "log1p", "0.65", "0.35",
                        "np.nanmean", "np.nanstd", ".diff()")
    for fn in (_mt.engineer_features, _mt.engineer_single_snapshot):
        tree = _ast.parse(_inspect.getsource(fn))
        f = tree.body[0]
        if f.body and isinstance(f.body[0], _ast.Expr) and isinstance(f.body[0].value, _ast.Constant):
            f.body = f.body[1:]
        src = _ast.unparse(f)
        for tok in banned_substrings:
            assert tok not in src, (
                f"{fn.__name__} re-encodes a shared feature semantic ({tok!r}) — "
                f"second computation authority (RC-339)")
        assert not _re.search(r"[<>]=?\s*0\.\d", src), (
            f"{fn.__name__} authors a bare float threshold — thresholds belong to kernels")
        assert "fk_" in src, f"{fn.__name__} does not delegate to the feature kernels"


def test_rc344_production_train_ticker_callers_forward_db_identity():
    """F35 closure: every production train_ticker call forwards db_path, so the confluence
    /net_gamma_prev queries hit the SAME DB the training rows were loaded from. A caller
    that loads from db_X then trains without db_path silently sources features from the
    default DB (RC-344)."""
    import ast as _ast
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    offenders = []
    for rel in ("ml_scheduler.py", "train_all.py", "ml_train.py"):
        tree = _ast.parse((repo / rel).read_text(encoding="utf-8"))
        for node in _ast.walk(tree):
            if (isinstance(node, _ast.Call)
                    and getattr(node.func, "id", getattr(node.func, "attr", ""))
                    == "train_ticker"):
                kwargs = {k.arg for k in node.keywords if k.arg}
                if "db_path" not in kwargs:
                    offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        f"production train_ticker call(s) omit db_path — DB identity lost before "
        f"feature engineering (RC-344/F35): {offenders}")


def test_rc344_full_feature_denominator_is_classified_and_parity_covered():
    """F01 closure: every field in the current model denominator is a KNOWN class
    (confluence / categorical / engineered-shared), no unknowns, and the shared set is the
    same set the every-xgb train/serve parity test exercises."""
    from lstm_data import CONFLUENCE_FEATURES
    from ml_train import tabular_training_feature_names

    names = list(tabular_training_feature_names())
    assert len(names) >= 90, f"denominator collapsed to {len(names)}"
    cf = set(CONFLUENCE_FEATURES)
    unknown = [n for n in names
               if not (n in cf or n.startswith("cat_")
                       or isinstance(n, str) and n)]  # every non-empty engineered name is classified
    assert not unknown, f"unclassified features in denominator: {unknown}"
    # confluence + categorical are the fitted/shared subsets; the remainder are engineered
    # shared semantics, all produced by the fk_* kernels the origin lock protects.
    assert cf.issubset(set(names)), "confluence features missing from denominator"


def test_rc339_every_shared_kernel_is_called_by_both_builders():
    """RC-339 origin coverage: every fk_* kernel is the ONE author of its semantic, so
    BOTH engineer_features (train) and engineer_single_snapshot (serve) must call it and
    neither may shadow-compute (enforced by test_rc339_no_feature_formula_reencoded…).
    Delegation-in-both + no-reencoding == single origin for all shared kernels."""
    import ast as _ast
    import inspect as _inspect

    import ml_train as _mt

    kernels = [n for n in dir(_mt) if n.startswith("fk_")]
    assert len(kernels) >= 12, f"expected >=12 shared kernels, found {len(kernels)}"
    train_src = _ast.unparse(_ast.parse(_inspect.getsource(_mt.engineer_features)))
    serve_src = _ast.unparse(_ast.parse(_inspect.getsource(_mt.engineer_single_snapshot)))
    unprotected = [k for k in kernels
                   if f"{k}(" not in train_src or f"{k}(" not in serve_src]
    assert not unprotected, (
        f"shared kernel(s) not called by both builders — origin not single: {unprotected}")


def test_rc339_both_builders_deliver_the_kernels_output(monkeypatch):
    """Origin proof: an impossible sentinel from a kernel must surface through BOTH the
    training matrix and the serve row. An adapter that bypasses the kernel shows a real
    value here instead."""
    import ml_train as _mt

    monkeypatch.setattr(_mt, "fk_pct_of_spot", lambda p, s: np.asarray(777.25))
    monkeypatch.setattr(
        _mt, "fk_session_time_features",
        lambda mod: (np.asarray(7.0), np.asarray(8.0), np.asarray(9.0), np.asarray(10.0)))

    df = pd.DataFrame([{
        "ticker": "SPY", "ts_utc": 1_767_020_400.0 + i * 60, "spot": 500.0,
        "candle_body_pts": 1.0, "candle_range_pts": 2.0, "outcome_5c": "up",
    } for i in range(4)])
    X, names, cat_maps, aux = _mt.engineer_features(df)
    assert float(X["candle_body_pct"].iloc[-1]) == 777.25
    assert float(X["time_sin"].iloc[-1]) == 7.0
    assert float(X["minutes_since_open"].iloc[-1]) == 10.0

    served = _mt.engineer_single_snapshot(
        {"spot": 500.0, "ts_utc": 1_767_020_400.0, "candle_body_pts": 1.0},
        {}, ["candle_body_pct", "time_sin", "minutes_since_open"], {}, "SPY")
    assert float(served["candle_body_pct"].iloc[0]) == 777.25
    assert float(served["time_sin"].iloc[0]) == 7.0
    assert float(served["minutes_since_open"].iloc[0]) == 10.0


def test_rc339_kernels_are_dtype_polymorphic_and_edge_correct():
    """The kernel IS the semantic: scalar and array calls must agree exactly, and the
    absence rules hold (missing != zero, one market leg is not a cross)."""
    import ml_train as _mt

    assert float(_mt.fk_pct_of_spot(1.0, 500.0)) == float(_mt.fk_pct_of_spot(
        np.array([1.0]), 500.0)[0]) == 0.2
    assert np.isnan(float(_mt.fk_sign_positive(np.nan)))
    assert float(_mt.fk_sign_positive(-0.5)) == 0.0
    assert np.isnan(float(_mt.fk_agreement_positive(1.0, np.nan)))
    assert float(_mt.fk_agreement_positive(-1.0, -2.0)) == 1.0
    # a cross of ONE leg is absent, not that leg's value
    avg, std = _mt.fk_cross_change_stats(0.7, np.nan, np.nan)
    assert np.isnan(float(avg)) and np.isnan(float(std))
    avg2, _ = _mt.fk_cross_change_stats(0.5, 0.7, np.nan)
    assert float(avg2) == pytest.approx(0.6)
    # imbalance 0.0 is a real reading (max sell pressure), absence is NaN
    buy, sell = _mt.fk_imbalance_pressures(0.0)
    assert float(buy) == 0.0 and float(sell) == 1.0
    buy_n, sell_n = _mt.fk_imbalance_pressures(np.nan)
    assert np.isnan(float(buy_n)) and np.isnan(float(sell_n))
    # volume ratio: unusable median is absent, never a fake neutral 1.0
    assert np.isnan(float(_mt.fk_volume_ratio(1000.0, np.nan)))
    assert float(_mt.fk_volume_ratio(1000.0, 100.0)) == 10.0   # capped
    # non-positive range is not a range
    assert np.isnan(float(_mt.fk_body_range_ratio(1.0, 0.0)))
    assert np.isnan(float(_mt.fk_body_range_ratio(1.0, -2.0)))


def test_confluence_authority_takes_a_bar_not_a_population():
    """The signature IS the fix. If it ever accepts rows again, every lane can diverge."""
    from ml_data_common import confluence_features_for_bar

    params = list(inspect.signature(confluence_features_for_bar).parameters)
    assert params[:2] == ["ticker", "ts_utc"], (
        f"the authority must be addressed by (ticker, ts_utc); got {params} (RC-332)")
    for banned in ("rows", "snapshots", "pool", "population", "snapshots_5m", "df"):
        assert banned not in params, (
            f"confluence_features_for_bar accepts {banned!r} — the caller can choose the "
            "population again, which is the RC-332 root")

