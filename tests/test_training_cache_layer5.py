"""Layer 5 training_cache.py fail-closed fingerprint and cache-load guards."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from training_cache import (
    _normalize_data_fp,
    compute_feature_cache_key,
    expanding_window_oof_folds,
    load_lstm_feature_cache,
    split_sessions_walk_forward,
    walk_forward_session_split,
    xgb_meta_content_sha256,
)
from features.training_canonical_input import training_canonical_lineage_header


# ── Workstream B1 — single authoritative walk-forward split ────────────────────


def test_inline_normsync_skip_env(monkeypatch):
    from normalized_training_sync import inline_normsync_enabled

    monkeypatch.delenv("ED_TRAINING_SKIP_INLINE_NORMSYNC", raising=False)
    assert inline_normsync_enabled() is True
    monkeypatch.setenv("ED_TRAINING_SKIP_INLINE_NORMSYNC", "1")
    assert inline_normsync_enabled() is False


def test_cross_process_materialize_lock_exclusive(tmp_path):
    from normalized_training_sync import (
        _materialize_lock_path,
        cross_process_materialize_lock,
    )

    db = tmp_path / "training.db"
    db.write_bytes(b"")
    lock_path = _materialize_lock_path(db)
    with cross_process_materialize_lock(db, timeout_sec=2.0):
        assert lock_path.is_file()
    assert not lock_path.is_file()


def test_cross_process_materialize_lock_reclaims_dead_holder(tmp_path):
    from normalized_training_sync import (
        _materialize_lock_path,
        cross_process_materialize_lock,
    )

    db = tmp_path / "training.db"
    db.write_bytes(b"")
    lock_path = _materialize_lock_path(db)
    lock_path.write_text("99999999\n", encoding="utf-8")
    with cross_process_materialize_lock(db, timeout_sec=2.0):
        assert lock_path.read_text(encoding="utf-8").strip() != "99999999"
    assert not lock_path.is_file()


def test_split_sessions_walk_forward_holds_out_later_tail():
    days = [f"2026-01-{d:02d}" for d in range(1, 21)]  # 20 sorted sessions
    train, val = split_sessions_walk_forward(days)
    assert val == days[-3:]                     # last 3 held out (cap)
    assert train == days[:-3]
    assert set(train).isdisjoint(val)           # provably disjoint
    assert max(train) < min(val)                # strictly earlier than eval


def test_split_sessions_walk_forward_caps_val_at_three():
    # 13 sessions -> n_val = min(3, max(1, 13-10)) = 3
    days = [f"2026-02-{d:02d}" for d in range(1, 14)]
    train, val = split_sessions_walk_forward(days)
    assert len(val) == 3 and len(train) == 10


def test_split_sessions_walk_forward_eleven_sessions_one_val():
    # 11 sessions -> n_val = min(3, max(1, 11-10)) = 1
    days = [f"2026-03-{d:02d}" for d in range(1, 12)]
    train, val = split_sessions_walk_forward(days)
    assert len(val) == 1 and len(train) == 10


def test_split_sessions_walk_forward_too_few_sessions_no_holdout():
    days = [f"2026-04-{d:02d}" for d in range(1, 8)]  # 7 < 10
    train, val = split_sessions_walk_forward(days)
    assert val == []                # holdout impossible -> caller falls back
    assert train == days


# ── Expanding-window OOF folds (Workstream B2) ──────────────────────────────


def test_expanding_window_oof_folds_three_folds_strictly_earlier_train():
    days = [f"2026-06-{d:02d}" for d in range(1, 13)]  # 12 sessions, n_folds=3 -> 4 blocks of 3
    folds = expanding_window_oof_folds(days, n_folds=3)
    assert len(folds) == 3
    seen_oof: list[str] = []
    prev_train_len = 0
    for train_days, oof_days in folds:
        assert set(train_days).isdisjoint(oof_days)        # OOF row never in its own train set
        assert max(train_days) < min(oof_days)             # train is STRICTLY earlier (no leakage)
        assert len(train_days) > prev_train_len            # window expands each fold
        prev_train_len = len(train_days)
        seen_oof.extend(oof_days)
    # Seed block B0 is excluded from OOF; coverage == n_folds/(n_folds+1) == 3/4 of rows.
    assert seen_oof == days[3:]
    assert len(seen_oof) == 9
    assert len(set(seen_oof)) == 9                          # folds partition the OOF region


def test_expanding_window_oof_folds_minimum_four_sessions():
    days = ["d1", "d2", "d3", "d4"]
    folds = expanding_window_oof_folds(days, n_folds=3)
    assert [tuple(map(list, f)) for f in folds] == [
        (["d1"], ["d2"]),
        (["d1", "d2"], ["d3"]),
        (["d1", "d2", "d3"], ["d4"]),
    ]


def test_expanding_window_oof_folds_too_few_sessions_empty():
    # Fewer sessions than blocks (n_folds+1) -> no clean OOF possible -> caller falls back.
    assert expanding_window_oof_folds(["d1", "d2", "d3"], n_folds=3) == []
    assert expanding_window_oof_folds([], n_folds=3) == []
    assert expanding_window_oof_folds(["d1"], n_folds=1) == []  # 1 < 2 blocks


def test_expanding_window_oof_folds_invalid_n_folds_empty():
    assert expanding_window_oof_folds([f"d{i}" for i in range(10)], n_folds=0) == []


def test_walk_forward_session_split_db_backed(tmp_path, monkeypatch):
    import sqlite3

    import ml_data_common as mdc

    db = tmp_path / "wf.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE snapshots_1m_normalized (ticker TEXT, timeframe TEXT, ts_utc REAL, ts_et TEXT, outcome_1c TEXT)"
    )
    rid = 0.0
    days = [f"2026-05-{d:02d}" for d in range(1, 16)]  # 15 sessions
    for day in days:
        for i in range(3):
            conn.execute(
                "INSERT INTO snapshots_1m_normalized VALUES (?,?,?,?,?)",
                ("ZZZ", "1m", rid, f"{day} 10:{i:02d}:00", "UP"),
            )
            rid += 1.0
    conn.commit()
    conn.close()

    monkeypatch.setattr(mdc, "filter_ts_utc_list_to_rth", lambda ts: ts)
    monkeypatch.setattr(mdc, "training_base_where_clause", lambda col, include_ticker=True: "timeframe = ? AND ticker = ?")
    monkeypatch.setattr(mdc, "et_date_str_from_ts_utc", lambda ts: days[int(ts) // 3])

    train, val = walk_forward_session_split(str(db), "ZZZ", label_column="outcome_1c")
    assert val == days[-3:]
    assert train == days[:-3]
    assert set(train).isdisjoint(val)


def test_normalize_data_fp_distinguishes_missing_row_count_from_zero():
    assert _normalize_data_fp({"row_count": 0}) != _normalize_data_fp({})
    assert _normalize_data_fp({"row_count": 0})["row_count"] == 0
    assert _normalize_data_fp({}).get("row_count") is None


def test_feature_cache_key_differs_when_row_count_missing_vs_zero():
    base = {
        "min_ts_utc": 1.0,
        "max_ts_utc": 2.0,
        "table": "snapshots_1m_normalized",
        "timeframe": "1m",
    }
    code_fp = "abc"
    k_missing = compute_feature_cache_key("SPY", base, code_fp, target_column="outcome_5c")
    k_zero = compute_feature_cache_key(
        "SPY", {**base, "row_count": 0}, code_fp, target_column="outcome_5c"
    )
    assert k_missing != k_zero


def test_xgb_meta_content_sha256_missing_paths_do_not_collide_to_empty():
    a = Path("/tmp/nonexistent_xgb_meta_a.json")
    b = Path("/tmp/nonexistent_xgb_meta_b.json")
    assert xgb_meta_content_sha256(a) != xgb_meta_content_sha256(b)
    assert xgb_meta_content_sha256(a).startswith("MISSING:")


def test_load_lstm_feature_cache_rejects_missing_feature_dimensions(tmp_path: Path):

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    X = np.zeros((2, 1), dtype=np.float32)
    y = np.array([0, 1], dtype=np.int64)
    np.savez_compressed(
        cache_dir / "lstm_tensors.npz",
        X_5m=X,
        X_1m=X,
        X_conf=X,
        y=y,
    )
    meta = {
        "tickers": ["SPY"],
        "timestamps": [1.0, 2.0],
        "days": ["2026-05-05"],
        **training_canonical_lineage_header(),
    }
    (cache_dir / "lstm_dataset_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    data_fp = {
        "table": "snapshots_1m_normalized",
        "timeframe": "1m",
        "ticker": "SPY",
        "min_ts_utc": 1.0,
        "max_ts_utc": 2.0,
        "row_count": 2,
    }
    feature_key = "test_key"
    identity = {
        "ticker": "SPY",
        "feature_cache_key": feature_key,
        "data_fingerprint": data_fp,
        **training_canonical_lineage_header(),
    }
    (cache_dir / "feature_cache_identity.json").write_text(
        json.dumps(identity), encoding="utf-8"
    )

    assert (
        load_lstm_feature_cache(cache_dir, "SPY", data_fp, feature_key) is None
    )


def test_load_lstm_feature_cache_accepts_valid_meta(tmp_path: Path):
    cache_dir = tmp_path / "cache2"
    cache_dir.mkdir()
    X = np.zeros((2, 3), dtype=np.float32)
    y = np.array([0, 1], dtype=np.int64)
    np.savez_compressed(
        cache_dir / "lstm_tensors.npz",
        X_5m=X,
        X_1m=X,
        X_conf=X,
        y=y,
    )
    meta = {
        "tickers": ["SPY"],
        "timestamps": [1.0, 2.0],
        "days": ["2026-05-05"],
        "n_features_5m": 3,
        "n_features_1m": 3,
        "n_confluence": 3,
        "n_samples": 2,
        **training_canonical_lineage_header(),
    }
    (cache_dir / "lstm_dataset_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    data_fp = {
        "table": "snapshots_1m_normalized",
        "timeframe": "1m",
        "ticker": "SPY",
        "min_ts_utc": 1.0,
        "max_ts_utc": 2.0,
        "row_count": 2,
    }
    feature_key = "test_key2"
    identity = {
        "ticker": "SPY",
        "feature_cache_key": feature_key,
        "data_fingerprint": data_fp,
        **training_canonical_lineage_header(),
    }
    (cache_dir / "feature_cache_identity.json").write_text(
        json.dumps(identity), encoding="utf-8"
    )

    ds = load_lstm_feature_cache(cache_dir, "SPY", data_fp, feature_key)
    assert ds is not None
    assert ds.n_features_5m == 3


# ── Training epochs runtime override (per-anchor production retrain lever, 2026-06-03) ──


def test_env_epochs_override_floor_and_fallback(monkeypatch):
    from training_cache_policy import _env_epochs

    monkeypatch.delenv("ED_TEST_EPOCHS_OVR", raising=False)
    assert _env_epochs("ED_TEST_EPOCHS_OVR", 50) == 50      # unset -> default (no behavior change)
    monkeypatch.setenv("ED_TEST_EPOCHS_OVR", "12")
    assert _env_epochs("ED_TEST_EPOCHS_OVR", 50) == 12       # explicit override wins
    monkeypatch.setenv("ED_TEST_EPOCHS_OVR", "0")
    assert _env_epochs("ED_TEST_EPOCHS_OVR", 50) == 1        # floors at 1 (never 0 epochs)
    monkeypatch.setenv("ED_TEST_EPOCHS_OVR", "  ")
    assert _env_epochs("ED_TEST_EPOCHS_OVR", 50) == 50       # blank -> default
    monkeypatch.setenv("ED_TEST_EPOCHS_OVR", "abc")
    assert _env_epochs("ED_TEST_EPOCHS_OVR", 50) == 50       # invalid -> default (no crash)


def test_default_train_epochs_are_canonical():
    import os

    import training_cache_policy as p

    # Canonical defaults must hold when the override env vars are unset at import time, so an
    # unconfigured run trains the full 50/60 (no silent shrink). lstm_model.EPOCHS /
    # transformer_train.EPOCHS bind to these.
    if not os.environ.get("ED_TRAIN_EPOCHS_LSTM"):
        assert p.LSTM_TRAIN_EPOCHS == 50
    if not os.environ.get("ED_TRAIN_EPOCHS_TRANSFORMER"):
        assert p.TRANSFORMER_TRAIN_EPOCHS == 60


def test_should_early_stop_never_fires_without_holdout():
    # Safety invariant: with no held-out val signal, selection falls back to in-sample train loss,
    # which monotonically decreases — early stop must NEVER fire on it regardless of the streak.
    from training_cache_policy import should_early_stop

    assert should_early_stop(enabled=True, has_holdout=False, patience=3, epochs_no_improve=999) is False


def test_should_early_stop_fires_at_patience_when_holdout_present():
    from training_cache_policy import should_early_stop

    # below patience -> keep training; at/above patience -> stop
    assert should_early_stop(enabled=True, has_holdout=True, patience=3, epochs_no_improve=2) is False
    assert should_early_stop(enabled=True, has_holdout=True, patience=3, epochs_no_improve=3) is True
    assert should_early_stop(enabled=True, has_holdout=True, patience=3, epochs_no_improve=9) is True


def test_should_early_stop_respects_disable_and_zero_patience():
    from training_cache_policy import should_early_stop

    assert should_early_stop(enabled=False, has_holdout=True, patience=3, epochs_no_improve=99) is False
    assert should_early_stop(enabled=True, has_holdout=True, patience=0, epochs_no_improve=99) is False


# ── ML-PIPE-V2 Phase 6: split entry-point registry (governed splitters only) ──


def test_no_ungoverned_random_splitters_anywhere_in_production_code():
    """Measured 2026-07-11: zero sklearn-style random/shuffled splitters exist in
    the repo — the temporal-split surface is exclusively the governed
    implementations (calibration.v2_a1_calibration.WalkForwardSplit,
    training_cache.expanding_window_oof_folds, training_cache walk-forward).
    This registry lock keeps it that way: ANY new random K-fold/shuffle split on
    time-series data fails here; a legitimate governed addition must be added to
    the ALLOWED registry below in the same reviewed diff."""
    import ast
    import io as _io
    import os as _os

    TOKENS = {
        "train_test_split", "KFold", "StratifiedKFold", "TimeSeriesSplit",
        "GroupKFold", "ShuffleSplit", "StratifiedShuffleSplit",
    }
    ALLOWED: set[tuple[str, str]] = set()  # (path, token) — empty by measurement
    SKIP_DIRS = {
        ".git", "node_modules", "__pycache__", ".venv", "venv", "models",
        "data", "reports", ".github", "static", "templates", "docs",
        "tests",  # tests may construct adversarial splitters deliberately
    }
    violations: list[str] = []
    for root, dirs, files in _os.walk("."):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            rel = _os.path.join(root, fn).replace("\\", "/")[2:]
            try:
                src = _io.open(rel, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            if not any(t in src for t in TOKENS):
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                name = None
                if isinstance(node, ast.Name) and node.id in TOKENS:
                    name = node.id
                elif isinstance(node, ast.Attribute) and node.attr in TOKENS:
                    name = node.attr
                if name and (rel, name) not in ALLOWED:
                    violations.append(f"{rel}:{node.lineno}: ungoverned splitter {name}")
    assert violations == [], (
        "ungoverned split entry point(s) — temporal data requires the governed "
        f"walk-forward/purged implementations: {violations}"
    )
