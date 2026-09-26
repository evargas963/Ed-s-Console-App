"""Layer 5 training_cache.py fail-closed fingerprint and cache-load guards."""

from __future__ import annotations





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










# ── Expanding-window OOF folds (Workstream B2) ──────────────────────────────






















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
