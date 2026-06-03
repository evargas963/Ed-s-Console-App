"""Out-of-fold (OOF) stacker training — Workstream B2.

Locks the invariant the operator verifies: the parallel meta-learner trains on
EXPANDING-WINDOW OUT-OF-FOLD base predictions (each held-out fold scored by base
models trained ONLY on strictly-earlier sessions) — never on in-sample base probs —
while the deployed base artifacts stay full-data trained.

These tests monkeypatch the expensive base-training and base-prediction seams so the
orchestration contract is provable without training real models: we assert WHICH model
directory each meta-vector batch came from (fold dirs = OOF, out_dir = in-sample) and
WHEN the in-sample fallback is taken.
"""
from __future__ import annotations

from pathlib import Path

import ml_scheduler


def _patch_base_train_ok(monkeypatch):
    monkeypatch.setattr(
        ml_scheduler, "_train_parallel_base_models_into",
        lambda *a, **k: True,
    )


def _patch_load_data_nonempty(monkeypatch):
    import ml_train

    monkeypatch.setattr(ml_train, "load_data", lambda *a, **k: [{"r": i} for i in range(4)])


def test_parallel_meta_trains_on_oof_fold_dirs_not_in_sample(monkeypatch, tmp_path):
    out_dir = tmp_path / "deployed"
    out_dir.mkdir()
    days = [f"2026-06-{d:02d}" for d in range(1, 13)]  # 12 sessions -> 3 OOF folds

    _patch_base_train_ok(monkeypatch)
    _patch_load_data_nonempty(monkeypatch)

    seen_dirs: list[Path] = []

    def fake_assemble(model_dir, ticker, db_path, rows_df, target_column, hz):
        seen_dirs.append(Path(model_dir))
        return ([[0.4, 0.3, 0.3, 0.4, 0.3, 0.3, 0.4, 0.3, 0.3]] * 5, [0] * 5)

    monkeypatch.setattr(ml_scheduler, "_assemble_meta_base_prob_vectors", fake_assemble)

    X, y, basis = ml_scheduler._train_parallel_meta_oof(
        out_dir, "SPY", "db", ["full_df"], days, "outcome_1c", "1c", data_fp={"row_count": 9},
    )

    assert basis == "expanding_window_oof"
    assert len(seen_dirs) == 3                      # one assemble per OOF fold
    assert all("fold" in d.name for d in seen_dirs) # every batch came from a fold dir...
    assert out_dir not in seen_dirs                 # ...NOT the deployed (in-sample) dir
    assert len(X) == 15 and len(y) == 15            # 3 folds x 5 rows concatenated


def test_parallel_meta_falls_back_in_sample_when_no_folds(monkeypatch, tmp_path):
    out_dir = tmp_path / "deployed"
    out_dir.mkdir()
    days = ["d1", "d2", "d3"]  # < 4 -> no folds possible

    _patch_base_train_ok(monkeypatch)
    _patch_load_data_nonempty(monkeypatch)

    seen_dirs: list[Path] = []

    def fake_assemble(model_dir, ticker, db_path, rows_df, target_column, hz):
        seen_dirs.append(Path(model_dir))
        return ([[0.4, 0.3, 0.3, 0.4, 0.3, 0.3, 0.4, 0.3, 0.3]] * 12, [0] * 12)

    monkeypatch.setattr(ml_scheduler, "_assemble_meta_base_prob_vectors", fake_assemble)

    X, y, basis = ml_scheduler._train_parallel_meta_oof(
        out_dir, "SPY", "db", ["full_df"], days, "outcome_1c", "1c", data_fp=None,
    )

    assert basis == "in_sample_no_folds"
    assert seen_dirs == [out_dir]                   # assembled once, from the deployed dir
    assert len(X) == 12


def test_parallel_meta_falls_back_when_oof_too_thin(monkeypatch, tmp_path):
    out_dir = tmp_path / "deployed"
    out_dir.mkdir()
    days = [f"2026-06-{d:02d}" for d in range(1, 13)]  # 3 folds, but OOF rows too few

    _patch_base_train_ok(monkeypatch)
    _patch_load_data_nonempty(monkeypatch)

    def fake_assemble(model_dir, ticker, db_path, rows_df, target_column, hz):
        # Fold dirs yield 2 rows each (3*2 = 6 < 10) -> forces in-sample fallback;
        # the deployed dir yields a healthy matrix.
        if Path(model_dir) == out_dir:
            return ([[0.4, 0.3, 0.3, 0.4, 0.3, 0.3, 0.4, 0.3, 0.3]] * 20, [0] * 20)
        return ([[0.4, 0.3, 0.3, 0.4, 0.3, 0.3, 0.4, 0.3, 0.3]] * 2, [0] * 2)

    monkeypatch.setattr(ml_scheduler, "_assemble_meta_base_prob_vectors", fake_assemble)

    X, y, basis = ml_scheduler._train_parallel_meta_oof(
        out_dir, "SPY", "db", ["full_df"], days, "outcome_1c", "1c", data_fp=None,
    )

    assert basis == "in_sample_fallback"
    assert len(X) == 20                             # fell back to the deployed full-data matrix


# ── Cascade OOF (Workstream B2, commit 2) ───────────────────────────────────


def test_oof_day_to_fold_map_excludes_seed_assigns_strictly_earlier():
    from training_cache import expanding_window_oof_folds

    days = [f"2026-06-{d:02d}" for d in range(1, 13)]  # 12 sessions -> 3 folds
    folds = expanding_window_oof_folds(days, n_folds=3)
    m = ml_scheduler._oof_day_to_fold_map(folds)

    seed_block = folds[0][0]                         # B0: fold-0 train == the seed block
    for d in seed_block:
        assert d not in m                            # seed days NEVER feed the stacker
    assert len(m) == 9                               # 3/4 coverage (B1+B2+B3)
    for day, fi in m.items():
        train_days, oof_days = folds[fi]
        assert day in oof_days                       # mapped to the fold that held it out
        assert max(train_days) < day                 # scored by STRICTLY-earlier base models


def test_train_cascade_xgb_lstm_into_fails_closed_on_empty_data(monkeypatch, tmp_path):
    import ml_train

    monkeypatch.setattr(ml_train, "load_data", lambda *a, **k: [])
    ok = ml_scheduler._train_cascade_xgb_lstm_into(
        tmp_path / "fold0", "SPY", "db", {"2026-06-01"}, data_fp=None, hz="1c",
    )
    assert ok is False


def test_cascade_meta_trains_on_oof_fold_dirs_not_in_sample(monkeypatch, tmp_path):
    out_dir = tmp_path / "deployed"
    out_dir.mkdir()
    days = [f"2026-06-{d:02d}" for d in range(1, 13)]

    monkeypatch.setattr(
        ml_scheduler, "_train_cascade_base_models_into",
        lambda *a, **k: True,
    )
    _patch_load_data_nonempty(monkeypatch)

    seen_dirs: list[Path] = []

    def fake_assemble(model_dir, ticker, db_path, rows_df, target_column, hz):
        seen_dirs.append(Path(model_dir))
        return ([[0.4, 0.3, 0.3, 0.4, 0.3, 0.3, 0.4, 0.3, 0.3]] * 5, [0] * 5)

    monkeypatch.setattr(ml_scheduler, "_assemble_meta_base_prob_vectors", fake_assemble)

    X, y, basis = ml_scheduler._train_cascade_meta_oof(
        out_dir, "SPY", "db", ["full_df"], days, "outcome_1c", "1c", data_fp={"row_count": 9},
    )

    assert basis == "expanding_window_oof"
    assert len(seen_dirs) == 3
    assert all("fold" in d.name for d in seen_dirs)
    assert out_dir not in seen_dirs
    assert len(X) == 15 and len(y) == 15


def test_cascade_meta_falls_back_in_sample_when_no_folds(monkeypatch, tmp_path):
    out_dir = tmp_path / "deployed"
    out_dir.mkdir()
    days = ["d1", "d2", "d3"]

    monkeypatch.setattr(
        ml_scheduler, "_train_cascade_base_models_into",
        lambda *a, **k: True,
    )
    _patch_load_data_nonempty(monkeypatch)

    seen_dirs: list[Path] = []

    def fake_assemble(model_dir, ticker, db_path, rows_df, target_column, hz):
        seen_dirs.append(Path(model_dir))
        return ([[0.4, 0.3, 0.3, 0.4, 0.3, 0.3, 0.4, 0.3, 0.3]] * 12, [0] * 12)

    monkeypatch.setattr(ml_scheduler, "_assemble_meta_base_prob_vectors", fake_assemble)

    X, y, basis = ml_scheduler._train_cascade_meta_oof(
        out_dir, "SPY", "db", ["full_df"], days, "outcome_1c", "1c", data_fp=None,
    )

    assert basis == "in_sample_no_folds"
    assert seen_dirs == [out_dir]
    assert len(X) == 12


def test_cascade_meta_falls_back_when_oof_too_thin(monkeypatch, tmp_path):
    out_dir = tmp_path / "deployed"
    out_dir.mkdir()
    days = [f"2026-06-{d:02d}" for d in range(1, 13)]

    monkeypatch.setattr(
        ml_scheduler, "_train_cascade_base_models_into",
        lambda *a, **k: True,
    )
    _patch_load_data_nonempty(monkeypatch)

    def fake_assemble(model_dir, ticker, db_path, rows_df, target_column, hz):
        if Path(model_dir) == out_dir:
            return ([[0.4, 0.3, 0.3, 0.4, 0.3, 0.3, 0.4, 0.3, 0.3]] * 20, [0] * 20)
        return ([[0.4, 0.3, 0.3, 0.4, 0.3, 0.3, 0.4, 0.3, 0.3]] * 2, [0] * 2)

    monkeypatch.setattr(ml_scheduler, "_assemble_meta_base_prob_vectors", fake_assemble)

    X, y, basis = ml_scheduler._train_cascade_meta_oof(
        out_dir, "SPY", "db", ["full_df"], days, "outcome_1c", "1c", data_fp=None,
    )

    assert basis == "in_sample_fallback"
    assert len(X) == 20


# ── CLOSEOUT #3 — meta-training assembly excludes collapsed bases ──────────────────────
def test_meta_base_triplet_collapsed_base_is_neutral():
    """A single-class-collapsed base feeds the neutral filler, not its degenerate probs."""
    probs = {"up": 0.8, "down": 0.1, "flat": 0.1}
    assert ml_scheduler._meta_base_triplet("xgb", probs, {"xgb"}) == [0.333, 0.333, 0.334]


def test_meta_base_triplet_absent_base_is_neutral():
    assert ml_scheduler._meta_base_triplet("lstm", None, set()) == [0.333, 0.333, 0.334]


def test_meta_base_triplet_healthy_base_passes_through():
    probs = {"up": 0.5, "down": 0.3, "flat": 0.2}
    assert ml_scheduler._meta_base_triplet("xgb", probs, set()) == [0.5, 0.3, 0.2]


def test_meta_base_triplet_backcompat_missing_key_uses_0333_filler():
    """Empty collapsed + present probs reproduces the prior `.get(c, 0.333)` exactly."""
    probs = {"up": 0.5, "down": 0.3}  # missing 'flat'
    assert ml_scheduler._meta_base_triplet("xgb", probs, set()) == [0.5, 0.3, 0.333]
