"""LSTM sequence input: canonical MVP merge + InferenceSnapshotV1 live bar."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolate_ablation_survivors_env(monkeypatch):
    """Encoder cone tests must not inherit operator shell ED_APPLY_ABLATION_SURVIVORS=1."""
    monkeypatch.delenv("ED_APPLY_ABLATION_SURVIVORS", raising=False)
    monkeypatch.delenv("ED_ABLATION_DROP_GROUPS", raising=False)
    try:
        from arch_competition import stack_bundle_eval_v1 as sbe

        sbe._ablation_drop_snapshot_columns_cached.cache_clear()
        sbe.ablated_drop_group_ids_for_model_horizon.cache_clear()
        sbe.ablated_drop_members_for_model_horizon.cache_clear()
    except Exception:
        pass


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
    from lstm_data import (
        encode_snapshot_5m,
        encode_snapshot_1m,
        ENCODED_FEATURES_5M,
        ENCODED_FEATURES_1M,
        encoded_width_5m,
        encoded_width_1m,
    )
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
    assert len(v5) == len(ENCODED_FEATURES_5M) == encoded_width_5m()
    assert len(v1) == len(ENCODED_FEATURES_1M) == encoded_width_1m()


def test_null_weighted_push_null_becomes_zero_in_tabular_encoder():
    """NULL spy_weighted_push → 0.0 in Stage 2 tabular encoder (no __present channel)."""
    from lstm_data import ENCODED_FEATURES_5M, encode_snapshot_5m

    row = _base_db_row(1.0)
    row["spy_weighted_push"] = None
    vec = encode_snapshot_5m(row, 450.0)
    idx = ENCODED_FEATURES_5M.index("spy_weighted_push")
    assert vec[idx] == 0.0


def test_weighted_push_present_in_tabular_encoder():
    from lstm_data import ENCODED_FEATURES_5M, encode_snapshot_5m

    row = _base_db_row(1.0)
    row["qqq_weighted_push"] = 0.42
    vec = encode_snapshot_5m(row, 450.0)
    idx = ENCODED_FEATURES_5M.index("qqq_weighted_push")
    assert vec[idx] == 0.42


def test_lstm_checkpoint_encoder_schema_guard():
    from lstm_data import (
        assert_lstm_encoder_checkpoint_compatible,
        LSTM_ENCODER_SCHEMA_VERSION,
        encoded_width_5m,
        encoded_width_1m,
    )

    assert_lstm_encoder_checkpoint_compatible(
        {
            "encoder_schema_version": LSTM_ENCODER_SCHEMA_VERSION,
            "encoder_width_5m_pre_mask": encoded_width_5m(),
            "encoder_width_1m_pre_mask": encoded_width_1m(),
        }
    )
    with pytest.raises(ValueError, match="encoder schema"):
        assert_lstm_encoder_checkpoint_compatible({"encoder_schema_version": 1})
    assert_lstm_encoder_checkpoint_compatible(
        {
            "encoder_schema_version": 2,
            "encoder_width_5m_pre_mask": 31,
            "encoder_width_1m_pre_mask": 16,
        }
    )


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


# ── Workstream B3 — LSTM trains/selects on a time-ordered held-out tail ──────────


def _synthetic_lstm_dataset(n: int, seed: int = 0):
    import numpy as np

    from lstm_data import LSTMDataset, STREAM_1M_LOOKBACK, STREAM_5M_LOOKBACK

    rng = np.random.default_rng(seed)
    f5, f1, fc = 6, 5, 4
    return LSTMDataset(
        X_5m=rng.normal(size=(n, STREAM_5M_LOOKBACK, f5)).astype(np.float32),
        X_1m=rng.normal(size=(n, STREAM_1M_LOOKBACK, f1)).astype(np.float32),
        X_conf=rng.normal(size=(n, fc)).astype(np.float32),
        y=rng.integers(0, 3, n).astype(np.int64),
        tickers=["XXT"] * n,
        timestamps=[f"2026-03-{1 + i % 20:02d} 10:30:00" for i in range(n)],
        days=[f"2026-03-{1 + i % 20:02d}" for i in range(n)],
        ml_horizon_slug="1c",
        n_samples=n,
    )


def test_extract_rth_snapshots_hoists_imports_outside_row_loop():
    """Regression: per-row import + ablation manifest re-read hung 40-session extract for 40+ min."""
    import ast
    import inspect

    from lstm_data import extract_rth_snapshots

    tree = ast.parse(inspect.getsource(extract_rth_snapshots))
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        if not (
            isinstance(node.target, ast.Name)
            and node.target.id == "row"
        ):
            continue
        for child in ast.walk(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                raise AssertionError(
                    "extract_rth_snapshots must not import inside the row loop"
                )


def test_build_lstm_dataset_uses_end_idx_minus_one_for_confluence(monkeypatch):
    """Regression: snapshots.index(current) inside the slide loop is O(n²) and hung 40-session builds.

    RC-332 moved the population choice out of this lane — it now asks
    `ml_data_common.confluence_features_for_bar` for a BAR instead of handing
    `compute_confluence_features` its own rows and an index. The guarantee under test is
    unchanged and still the point of the regression: the confluence value must belong to
    the CURRENT bar, `snapshots[end_idx - 1]`, and must be located without an O(n) scan.
    Asserting on the ts_utc the lane requests proves the same off-by-one it always did,
    at the boundary the lane now uses.
    """
    from lstm_data import STREAM_5M_LOOKBACK, build_lstm_dataset

    seen_ts: list[float] = []

    def _spy_for_bar(ticker, ts_utc, db_path=None, *, cache=None):
        seen_ts.append(float(ts_utc))
        from lstm_data import CONFLUENCE_FEATURES

        return {k: 0.0 for k in CONFLUENCE_FEATURES}

    n_snaps = STREAM_5M_LOOKBACK + 5
    day_snaps = [{"ts_utc": float(i), "spot": 100.0 + i * 0.01, "outcome_5c": "up"} for i in range(n_snaps)]
    for s in day_snaps:
        s["ts_et"] = "2026-01-02 10:00:00"

    monkeypatch.setattr("ml_data_common.confluence_features_for_bar", _spy_for_bar)
    monkeypatch.setattr(
        "lstm_data.extract_rth_snapshots",
        lambda *a, **k: {"2026-01-02": day_snaps},
    )
    monkeypatch.setattr(
        "features.training_canonical_input.training_snapshot_for_sequence_encode",
        lambda snap: snap,
    )
    from lstm_data import encoded_width_5m, encoded_width_1m

    monkeypatch.setattr(
        "features.lstm_sequence_input.encode_lstm_structure_sequence_bar",
        lambda merged, ref: [0.0] * encoded_width_5m(),
    )
    monkeypatch.setattr(
        "features.lstm_sequence_input.encode_lstm_micro_sequence_bar",
        lambda merged, ref: [0.0] * encoded_width_1m(),
    )

    ds = build_lstm_dataset(["SPY"], require_outcome=True, ml_horizon_slug="5c")
    assert ds.n_samples == 5
    # day_snaps[i]["ts_utc"] == float(i), so the requested bar's ts IS its index — the same
    # end_idx-1 sequence the pre-RC-332 assertion checked, read through the new boundary.
    assert seen_ts == [float(i) for i in range(STREAM_5M_LOOKBACK - 1, n_snaps - 1)]


def test_train_lstm_b3_reports_out_of_sample_holdout(tmp_path, monkeypatch):
    """B3: LSTM reports an out-of-sample val metric, selects best_state on the val tail, and
    fits normalization on the train partition only."""
    import json

    import lstm_model as lm

    monkeypatch.setattr(lm, "EPOCHS", 2)
    n = 240
    ds = _synthetic_lstm_dataset(n)
    lm.train_lstm(dataset=ds, ticker="XXT", model_dir=tmp_path / "models", ml_horizon_slug="1c")
    meta = json.loads((tmp_path / "models" / "lstm_XXT_1c_meta.json").read_text(encoding="utf-8"))
    assert meta["val_basis"] == "time_ordered_tail"
    assert meta["n_val"] == round(n * 0.15)
    assert 0.0 <= float(meta["val_accuracy"]) <= 1.0
    assert 1 <= int(meta["best_epoch"]) <= 2


def test_train_lstm_b3_no_holdout_when_too_few_rows(tmp_path, monkeypatch):
    """Thin ticker: no honest holdout -> in-sample (disclosed)."""
    import json

    import lstm_model as lm

    monkeypatch.setattr(lm, "EPOCHS", 2)
    ds = _synthetic_lstm_dataset(80, seed=1)
    lm.train_lstm(dataset=ds, ticker="XXT", model_dir=tmp_path / "models", ml_horizon_slug="1c")
    meta = json.loads((tmp_path / "models" / "lstm_XXT_1c_meta.json").read_text(encoding="utf-8"))
    assert meta["val_basis"] == "in_sample_no_holdout"
    assert int(meta["n_val"]) == 0


# ── ML-PIPE-V3 item 2: merged-window point-in-time invariance (as-of chain) ──
# Proof target: the EXACT history chain _predict_lstm uses —
# EdDB.get_recent_snapshots(as_of_ts_utc) → reversed → window slice →
# build_lstm_merged_windows. Rows at/after the as-of instant must be unable to
# change the merged windows by append OR aggressive mutation; other tickers and
# other horizons must be isolated; no full-series state may leak in.


def _mw_seed_db(tmp_path, *, ticker="SPY", n=90):
    import datetime as _dt

    from db import EdDB

    db = EdDB(tmp_path / "mw_asof.db", allow_noncanonical=True)
    base = _dt.datetime(2026, 6, 1, 14, 0, tzinfo=_dt.timezone.utc).timestamp()
    with db._connect() as con:
        for i in range(n):
            con.execute(
                "INSERT INTO snapshots (ticker, timeframe, ts_utc, ts_et, spot, "
                "candle_open, candle_high, candle_low, candle_close, et_hour, et_minute) "
                "VALUES (?, '1m', ?, ?, ?, ?, ?, ?, ?, 10, ?)",
                (
                    ticker, base + i * 60, f"2026-06-01 10:{i % 60:02d}:00 ET",
                    500.0 + i * 0.1, 500.0 + i * 0.1, 500.2 + i * 0.1,
                    499.8 + i * 0.1, 500.1 + i * 0.1, i % 60,
                ),
            )
        con.commit()
    return db, base


def _mw_build(db, as_of_ts, ticker="SPY"):
    from features.inference_snapshot import build_inference_snapshot_v1_from_db_row
    from features.lstm_sequence_input import build_lstm_merged_windows
    from lstm_data import STREAM_5M_LOOKBACK

    recent = db.get_recent_snapshots(
        ticker, "1m", n=STREAM_5M_LOOKBACK + 5, filled_only=False, as_of_ts_utc=as_of_ts
    )
    assert recent and len(recent) >= STREAM_5M_LOOKBACK, "fixture too small for lookback"
    recent = list(reversed(recent))
    window = recent[-STREAM_5M_LOOKBACK:]
    day_snaps = list(
        reversed(
            db.get_recent_snapshots(ticker, "1m", n=100, filled_only=False, as_of_ts_utc=as_of_ts)
        )
    )
    inf_v1 = build_inference_snapshot_v1_from_db_row(
        ticker=ticker, expiry=None, as_of_ts=as_of_ts, db_row=dict(window[-1]),
    )
    merged_window, merged_days = build_lstm_merged_windows(
        window, day_snaps, inference_snapshot_v1=inf_v1
    )
    return merged_window, merged_days


def test_merged_windows_invariant_under_future_append_and_mutation(tmp_path):
    db, base = _mw_seed_db(tmp_path)
    as_of = base + 70 * 60  # decision instant: row 70's timestamp (exclusive)
    before_w, before_d = _mw_build(db, as_of)
    with db._connect() as con:
        # aggressive future mutation + new future rows + a row AT the as-of instant
        con.execute("UPDATE snapshots SET spot = -999, candle_close = -999 WHERE ts_utc >= ?", (as_of,))
        for i in range(200, 206):
            con.execute(
                "INSERT INTO snapshots (ticker, timeframe, ts_utc, ts_et, spot, "
                "candle_open, candle_high, candle_low, candle_close, et_hour, et_minute) "
                "VALUES ('SPY', '1m', ?, 'future', 1.0, 1.0, 1.0, 1.0, 1.0, 10, 0)",
                (base + i * 60,),
            )
        con.commit()
    after_w, after_d = _mw_build(db, as_of)
    assert after_w == before_w, "merged 5m window changed after future append/mutation"
    assert after_d == before_d, "merged day window changed after future append/mutation"


def test_merged_windows_exact_as_of_cutoff_excludes_boundary_row(tmp_path):
    db, base = _mw_seed_db(tmp_path)
    as_of = base + 70 * 60
    w, d = _mw_build(db, as_of)
    max_ts = max(float(b["ts_utc"]) for b in w if isinstance(b, dict) and b.get("ts_utc") is not None)
    assert max_ts < as_of, "a bar at/after the as-of instant entered the merged window"
    max_ts_d = max(float(b["ts_utc"]) for b in d if isinstance(b, dict) and b.get("ts_utc") is not None)
    assert max_ts_d < as_of


def test_merged_windows_ticker_isolation(tmp_path):
    db, base = _mw_seed_db(tmp_path)
    as_of = base + 70 * 60
    before_w, before_d = _mw_build(db, as_of)
    with db._connect() as con:
        for i in range(90):
            con.execute(
                "INSERT INTO snapshots (ticker, timeframe, ts_utc, ts_et, spot, "
                "candle_open, candle_high, candle_low, candle_close, et_hour, et_minute) "
                "VALUES ('QQQ', '1m', ?, 'other', 400.0, 400.0, 400.2, 399.8, 400.1, 10, 0)",
                (base + i * 60,),
            )
        con.commit()
    after_w, after_d = _mw_build(db, as_of)
    assert after_w == before_w and after_d == before_d, "foreign-ticker rows leaked into windows"


def test_merged_windows_no_full_series_state_between_builds(tmp_path):
    """Two consecutive builds at the same as-of must be identical (no cross-call
    normalization/caching state), and a build at an EARLIER as-of must not be
    influenced by having built a later one first."""
    db, base = _mw_seed_db(tmp_path)
    late = base + 80 * 60
    early = base + 70 * 60
    w_late1, _ = _mw_build(db, late)
    w_early_after_late, d_early_after_late = _mw_build(db, early)
    w_late2, _ = _mw_build(db, late)
    w_early_fresh, d_early_fresh = _mw_build(db, early)
    assert w_late1 == w_late2, "same as-of rebuild differs — hidden state"
    assert w_early_after_late == w_early_fresh
    assert d_early_after_late == d_early_fresh


def test_rc343_zone_encoding_has_one_authority():
    """M9 lock (F37b): both LSTM zone-encode sites delegate to encode_zone — the mapping
    logic (None->missing, unknown->neutral, else ZONE_MAP) is authored once. A second
    inline ZONE_MAP.get(...) in the sequence encoder is a shadow producer."""
    import inspect

    import lstm_data
    from features import lstm_sequence_input
    from lstm_data import ZONE_MAP, ZONE_MISSING_ENCODED, encode_zone

    assert encode_zone(None) == ZONE_MISSING_ENCODED
    assert encode_zone("pin_bull") == ZONE_MAP["pin_bull"]
    assert encode_zone("not_a_zone") == ZONE_MAP["pin_neutral"]
    assert encode_zone("PIN_BEAR") == ZONE_MAP["pin_bear"]

    inline = [ln for ln in inspect.getsource(lstm_sequence_input).splitlines()
              if "ZONE_MAP.get(" in ln]
    assert not inline, f"lstm_sequence_input re-encodes zone inline: {inline} (RC-343)"
    assert "encode_zone(" in inspect.getsource(lstm_data._encode_zone_feature)
