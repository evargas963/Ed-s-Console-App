"""eval_runner sample-size floor, manifest flags, and atomic manifest writes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from arch_competition.eval_runner import (
    _align_eval_detail_pair,
    run_architecture_pair_evaluation,
    write_evaluation_manifest,
)
from arch_competition.exceptions import EvaluationLineageError
from calibration.statistical_integrity import MIN_SAMPLES_STATISTICAL


def _base_lineage():
    return {
        "feature_cache_key": "shared_cache_key",
        "data_fingerprint": {"ticker": "SPY"},
        "ml_horizon_suffix": "1c",
        "training_code_fingerprint": "trainfp",
    }


def _detail(*, n: int, prob_rows: list | None = None, ts_base: float = 1_700_000_000.0):
    rows = prob_rows if prob_rows is not None else [[0.34, 0.33, 0.33]] * n
    return {
        "prob_rows": rows,
        "y_true": [1] * n,
        "rows_used": [{"vix_level": 18.0, "ts_utc": ts_base + float(i * 60)} for i in range(n)],
    }


def _run_mocked_eval(
    n: int,
    detail: dict,
    *,
    pr: tuple | None = None,
    cr: tuple | None = None,
):
    default = (0.5, 0.5, n, 0.5, {}, detail)
    mock_pr = default if pr is None else pr
    mock_cr = default if cr is None else cr
    with (
        patch(
            "arch_competition.eval_runner.validate_parallel_cascade_manifest_lineage",
            return_value=_base_lineage(),
        ),
        patch("ml_scheduler._evaluate_parallel_on_full_rth", return_value=mock_pr),
        patch("ml_scheduler._evaluate_cascade_on_full_rth", return_value=mock_cr),
    ):
        return run_architecture_pair_evaluation(
            db_path=":memory:",
            ticker="SPY",
            parallel_model_dir=Path("/p"),
            cascade_model_dir=Path("/c"),
            ml_horizon_slug="1c",
        )


def test_eval_manifest_flags_below_min_samples_statistical():
    n = MIN_SAMPLES_STATISTICAL - 1
    man = _run_mocked_eval(n, _detail(n=n))
    assert man["evaluation_n_below_min_samples_statistical"] is True
    assert man["metrics"]["parallel"]["n_rows_scored"] == n


def test_eval_manifest_no_flag_at_min_samples_statistical():
    n = MIN_SAMPLES_STATISTICAL
    man = _run_mocked_eval(n, _detail(n=n))
    assert man["evaluation_n_below_min_samples_statistical"] is False


def test_eval_missing_prob_rows_raises_at_min_samples_statistical():
    n = MIN_SAMPLES_STATISTICAL
    with pytest.raises(EvaluationLineageError, match="missing prob_rows"):
        _run_mocked_eval(n, _detail(n=n, prob_rows=[]))


def test_eval_aligns_mismatched_parallel_cascade_row_counts():
    """Parallel may score more rows than cascade when LSTM/TR fail on cascade path."""
    n = MIN_SAMPLES_STATISTICAL + 50
    parallel_only = 40
    pdet = _detail(n=n, ts_base=1_700_000_000.0)
    cdet = _detail(n=n - parallel_only, ts_base=1_700_000_000.0)
    man = _run_mocked_eval(
        n,
        pdet,
        pr=(0.5, 0.5, n, 0.5, {}, pdet),
        cr=(0.5, 0.5, n - parallel_only, 0.4, {}, cdet),
    )
    summary = man["architecture_comparison_summary"]
    assert summary["parallel_raw_n_rows_scored"] == n
    assert summary["cascade_raw_n_rows_scored"] == n - parallel_only
    assert summary["aligned_n_rows_scored"] == n - parallel_only
    assert man["metrics"]["parallel"]["n_rows_scored"] == n - parallel_only
    assert man["metrics"]["cascade"]["n_rows_scored"] == n - parallel_only


def test_align_eval_detail_pair_intersection_by_ts_utc():
    pdet = _detail(n=5, ts_base=100.0)
    cdet = _detail(n=3, ts_base=100.0 + 120.0)
    aligned_p, aligned_c, n, pn_raw, cn_raw = _align_eval_detail_pair(pdet, cdet)
    assert pn_raw == 5
    assert cn_raw == 3
    assert n == 3
    assert len(aligned_p["prob_rows"]) == 3
    assert len(aligned_c["prob_rows"]) == 3


def test_write_evaluation_manifest_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "eval" / "evaluation_manifest.json"
    manifest = {"schema_version": "arch_eval_v1", "metrics": {"parallel": {"n_rows_scored": 3}}}
    write_evaluation_manifest(path, manifest)
    assert json.loads(path.read_text(encoding="utf-8")) == manifest
    assert not list(tmp_path.rglob("*.tmp"))


def test_architecture_comparison_summary_nan_deltas_none_parallel_wins_false():
    n = MIN_SAMPLES_STATISTICAL
    detail = _detail(n=n)
    nan = float("nan")
    man = _run_mocked_eval(
        n,
        detail,
        pr=(0.5, 0.5, n, nan, {}, detail),
        cr=(0.5, 0.5, n, 0.4, {}, detail),
    )
    summary = man["architecture_comparison_summary"]
    assert summary["delta_log_loss_parallel_minus_cascade"] is None
    assert summary["parallel_wins_log_loss"] is False


def test_architecture_comparison_summary_none_balanced_accuracy_delta_none():
    n = MIN_SAMPLES_STATISTICAL
    detail = _detail(n=n)
    man = _run_mocked_eval(
        n,
        detail,
        pr=(0.5, None, n, 0.5, {}, detail),
        cr=(0.5, 0.6, n, 0.4, {}, detail),
    )
    summary = man["architecture_comparison_summary"]
    assert summary["delta_balanced_accuracy_cascade_minus_parallel"] is None


def test_architecture_comparison_summary_non_numeric_log_loss_no_value_error():
    n = MIN_SAMPLES_STATISTICAL
    detail = _detail(n=n)
    man = _run_mocked_eval(
        n,
        detail,
        pr=(0.5, 0.5, n, "bad", {}, detail),
        cr=(0.5, 0.5, n, 0.4, {}, detail),
    )
    summary = man["architecture_comparison_summary"]
    assert summary["delta_log_loss_parallel_minus_cascade"] is None
    assert summary["parallel_wins_log_loss"] is False


def test_ml_scheduler_import_error_raises_evaluation_lineage_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "ml_scheduler":
            raise ImportError("simulated missing ml_scheduler")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(EvaluationLineageError, match="ml_scheduler evaluation entrypoints"):
        run_architecture_pair_evaluation(
            db_path=":memory:",
            ticker="SPY",
            parallel_model_dir=Path("/p"),
            cascade_model_dir=Path("/c"),
            ml_horizon_slug="1c",
            require_manifest_lineage=False,
        )


def test_write_evaluation_manifest_removes_temp_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "evaluation_manifest.json"

    def _fail_replace(_src: os.PathLike[str], _dst: os.PathLike[str]) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", _fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        write_evaluation_manifest(path, {"ok": True})
    assert not path.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_preload_historical_db_for_eval_respects_min_ts_utc(tmp_path: Path) -> None:
    """Governed eval preload must include pre-history before the first scored row."""
    import sqlite3

    from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M
    from train_all import preload_historical_db_for_eval

    db = tmp_path / "eval_hist.db"
    conn = sqlite3.connect(db)
    conn.execute(
        f"CREATE TABLE {SNAPSHOT_TABLE_1M} (ticker TEXT, timeframe TEXT, ts_utc REAL, spot REAL)"
    )
    for ts in (100.0, 200.0, 300.0, 400.0):
        conn.execute(
            f"INSERT INTO {SNAPSHOT_TABLE_1M} VALUES ('SPY', ?, ?, 100.0)",
            (CANONICAL_TIMEFRAME, ts),
        )
    conn.commit()
    conn.close()

    pre = preload_historical_db_for_eval(str(db), "SPY", 400.0, min_ts_utc=250.0)
    assert [float(r["ts_utc"]) for r in pre._rows] == [300.0]


def test_parallel_eval_survives_lstm_sequence_error(monkeypatch) -> None:
    """First-row thin history must not abort the whole eval (META-style degrade)."""
    from ml_scheduler import _evaluate_parallel_on_full_rth

    rows = [
        {
            "ts_utc": 1000.0 + i * 60.0,
            "ts_et": "2026-01-02 10:00:00",
            "outcome_1c": "up" if i % 2 == 0 else "down",
            "spot": 100.0,
        }
        for i in range(12)
    ]
    monkeypatch.setattr(
        "ml_scheduler._load_rth_rows_for_ticker",
        lambda *a, **k: list(rows),
    )
    monkeypatch.setattr("ml_scheduler._eval_hist_db_for_labeled_rows", lambda *a, **k: object())

    lstm_calls = {"n": 0}

    def _fake_lstm(*args, **kwargs):
        lstm_calls["n"] += 1
        if lstm_calls["n"] == 1:
            from features.lstm_sequence_input import LstmSequenceInputError

            raise LstmSequenceInputError("LSTM needs at least 60 snapshots, got 0")
        return {"up": 0.4, "down": 0.3, "flat": 0.3}

    import ml_predict as mp

    monkeypatch.setattr(mp, "_predict_xgb", lambda *a, **k: {"up": 0.5, "down": 0.25, "flat": 0.25})
    monkeypatch.setattr(mp, "_predict_lstm", _fake_lstm)
    monkeypatch.setattr(mp, "_predict_transformer", lambda *a, **k: {"up": 0.4, "down": 0.3, "flat": 0.3})
    monkeypatch.setattr(mp, "_predict_meta", lambda *a, **k: None)
    monkeypatch.setattr(
        mp,
        "_weighted_average",
        lambda *a, **k: {"up": 0.34, "down": 0.33, "flat": 0.33},
    )
    monkeypatch.setattr(
        "realized_contract_eval.evaluate_realized_contract_trades_for_rows",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        "features.inference_snapshot.build_inference_snapshot_v1_from_db_row",
        lambda **k: {"as_of_ts": k.get("as_of_ts"), "features": {}, "ticker": "SPY"},
    )

    acc, bal, n, ll, realized, detail = _evaluate_parallel_on_full_rth(
        ":memory:",
        "SPY",
        Path("/models/parallel/SPY"),
        target_column="outcome_1c",
        return_detail=True,
    )
    assert n == 12
    assert len(detail["prob_rows"]) == 12
    assert lstm_calls["n"] == 12


def test_parallel_eval_total_failure_reports_zero_rows_scored(monkeypatch) -> None:
    """Outer eval failure must not claim n_rows_scored=len(candidate_rows) with empty prob_rows."""
    from ml_scheduler import _evaluate_parallel_on_full_rth

    monkeypatch.setattr(
        "ml_scheduler._load_rth_rows_for_ticker",
        lambda *a, **k: [{"ts_utc": float(i), "outcome_1c": "up"} for i in range(12)],
    )

    def _boom(*a, **k):
        raise RuntimeError("simulated eval abort")

    monkeypatch.setattr("ml_predict.reset_caches", _boom)

    _acc, _bal, n, _ll, _realized, detail = _evaluate_parallel_on_full_rth(
        ":memory:",
        "SPY",
        Path("/models/parallel/SPY"),
        target_column="outcome_1c",
        return_detail=True,
    )
    assert n == 0
    assert detail["prob_rows"] == []
