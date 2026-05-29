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
