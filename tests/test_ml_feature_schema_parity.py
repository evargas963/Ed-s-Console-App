"""Issue 7: training vs inference parity for XGB tabular features."""
from __future__ import annotations

import inspect
import json
import pickle

import numpy as np
import pandas as pd
import pytest



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










def test_slice_a_cross_asset_cols_registered_in_scale_invariant():
    from ml_train import SCALE_INVARIANT_COLS

    for col in ("tnx_yield", "tnx_chg", "qqq_vs_spy", "spy_iwm_divergence"):
        assert col in SCALE_INVARIANT_COLS










def test_feature_schema_version_matches_trained_artifacts():
    """v7 until PA-CONE-V8-RETRAIN lands: the version flips only WITH retrained
    artifacts, never ahead of them (2026-06-11 live-stack outage class)."""
    from training_provenance import FEATURE_SCHEMA_VERSION, PREPROCESSING_VERSION

    assert FEATURE_SCHEMA_VERSION == "v7_m5_strip"
    assert PREPROCESSING_VERSION == "v5_no_m5_lag"



























def test_stage2_sequence_encoder_width_matches_xgb_tabular_universe():
    """Stage 2: LSTM streams = tabular minus cf_*; cf_* on X_conf only (no double representation)."""
    from lstm_data import CONFLUENCE_FEATURES, LSTM_ENCODER_SCHEMA_VERSION, encoded_width_5m, encoded_width_1m
    from ml_train import tabular_training_feature_names

    tabular = tabular_training_feature_names()
    # 94 at v7. Becomes 121 (+27 pa_*) only when PA-CONE-V8-RETRAIN lands
    # (registration + retrained artifacts in the same commit).
    assert len(tabular) == 94
    assert set(CONFLUENCE_FEATURES).issubset(set(tabular))
    assert LSTM_ENCODER_SCHEMA_VERSION == 3
    assert encoded_width_5m() == len(tabular) - len(CONFLUENCE_FEATURES)
    assert encoded_width_1m() == len(tabular) - len(CONFLUENCE_FEATURES)
    assert encoded_width_5m() == 88














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






def test_check_ablation_pipeline_parity_green():
    from tools.check_ablation_pipeline_parity import check_ablation_pipeline_parity

    assert check_ablation_pipeline_parity() == []






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


# ── RC-332: cf_* has ONE input population, and callers may not choose it ────────
#
# RC-328 made the confluence WINDOW clock-defined and repaired two lanes. Four more kept
# passing their own row population into the same producer, because the producer's signature
# accepts one. Measured before the fix: 179 divergent cells over 826 SPY bars between the
# LSTM offline and live populations, cf_alignment_score off by up to 3.0 of its -4..+4
# range. These two controls fail if either half of that regresses.

def test_no_production_lane_supplies_its_own_confluence_population(repo_index):
    """The recurrence mode is a NEW call site passing rows, not a wrong formula.

    Only `ml_data_common` may name the population: once inside the authority, and once in
    its explicitly logged degraded path for frames absent from the canonical series. A
    third site anywhere in production means a lane chose its own population again.
    """
    offenders = []
    for relpath, text, _tree in repo_index.items():
        rel = relpath.as_posix()
        if rel.startswith(("tests/", "tools/", "research/", "arch_competition/")):
            continue
        for i, line in enumerate(text.splitlines(), 1):
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

