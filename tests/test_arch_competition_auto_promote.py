"""PR4 auto-promote execution skip paths (governed record, env off)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arch_competition.promotion_execution import execute_promotion_if_eligible


def _write_minimal_governed(model_dir: Path, *, would_promote: bool) -> None:
    hz = "1c"
    tku = "SPY"
    base = model_dir / "arch_competition" / hz / tku
    base.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1",
        "ticker": tku,
        "ml_horizon_slug": hz,
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "lineage": {
            "feature_cache_key": "fk",
            "data_fingerprint": "df",
            "ml_horizon_suffix": hz,
            "training_code_fingerprint": "cf",
        },
        "metrics": {"parallel": {"n_rows_scored": 100}, "cascade": {"n_rows_scored": 100}},
    }
    record = {
        "schema_version": "1",
        "promotion_decision": "promote_cascade" if would_promote else "keep_incumbent",
        "would_promote_challenger": would_promote,
        "blocked_promotion_flags": [],
        "evaluation_manifest_reference": {
            "lineage_feature_cache_key": "fk",
            "ml_horizon_slug": hz,
        },
    }
    (base / "evaluation_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (base / "promotion_decision.json").write_text(json.dumps(record), encoding="utf-8")


def test_auto_promote_skipped_when_env_off(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE", "0")
    _write_minimal_governed(tmp_path, would_promote=True)
    result = execute_promotion_if_eligible(
        tmp_path,
        "SPY",
        "1c",
        scheduler_run_id="test-run",
    )
    assert result["executed"] is False
    assert result["skipped_reason"] == "auto_promote_disabled"


def test_auto_promote_parallel_on_keep_incumbent_train_success_live(tmp_path: Path, monkeypatch):
    """Train-success-live: keep_incumbent still refreshes parallel into active/."""
    from tests.test_manual_governance import _minimal_governed_files, _write_candidate_manifests, _write_horizon_bundle

    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE", "1")
    monkeypatch.delenv("ED_DISABLE_AUTO_PROMOTE", raising=False)
    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE_REQUIRE_VERIFY", "0")
    _minimal_governed_files(tmp_path, cascade_ok=False)
    pdir = tmp_path / "parallel" / "SPY"
    cdir = tmp_path / "cascade" / "SPY"
    _write_horizon_bundle(pdir, "SPY", "1c")
    _write_horizon_bundle(cdir, "SPY", "1c")
    _write_candidate_manifests(pdir, cdir)
    result = execute_promotion_if_eligible(
        tmp_path,
        "SPY",
        "1c",
        scheduler_run_id="train-success-live",
    )
    assert result["executed"] is True
    assert (tmp_path / "active" / "SPY" / "xgb_SPY_1c.pkl").is_file()
    assert (tmp_path / "active" / "SPY" / "meta_SPY_1c.pkl").is_file()


# ── Workstream A1 — per-ticker fail-closed data floor ──────────────────────────


def test_meets_per_ticker_data_floor_predicate():
    from training_provenance import (
        MIN_ROWS_FOR_PROMOTION,
        MIN_USABLE_DAYS_FOR_PROMOTION,
        meets_per_ticker_data_floor,
    )

    ok, reason = meets_per_ticker_data_floor(MIN_ROWS_FOR_PROMOTION, MIN_USABLE_DAYS_FOR_PROMOTION)
    assert ok and reason == "ok"
    ok, reason = meets_per_ticker_data_floor(499, 10)
    assert not ok and "labeled_rows=499" in reason
    ok, reason = meets_per_ticker_data_floor(5000, 4)
    assert not ok and "usable_days=4" in reason
    ok, reason = meets_per_ticker_data_floor(100, 1)
    assert not ok and "labeled_rows" in reason and "usable_days" in reason


def test_db_training_floor_stats_counts_usable_days(tmp_path: Path, monkeypatch):
    import sqlite3

    import ml_data_common as mdc
    from training_cache import db_training_floor_stats

    db = tmp_path / "floor.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE snapshots_1m_normalized (ticker TEXT, timeframe TEXT, ts_utc REAL, ts_et TEXT, outcome_1c TEXT)"
    )
    # day1 + day2 each 60 labeled rows (usable); day3 only 10 rows (not usable)
    rid = 0.0
    for day, n in (("2026-05-01", 60), ("2026-05-02", 60), ("2026-05-03", 10)):
        for i in range(n):
            conn.execute(
                "INSERT INTO snapshots_1m_normalized VALUES (?,?,?,?,?)",
                ("ZZZ", "1m", rid, f"{day} 10:{i % 60:02d}:00", "UP"),
            )
            rid += 1.0
    conn.commit()
    conn.close()

    monkeypatch.setattr(mdc, "filter_ts_utc_list_to_rth", lambda ts: ts)
    monkeypatch.setattr(mdc, "training_base_where_clause", lambda col, include_ticker=True: "timeframe = ? AND ticker = ?")

    stats = db_training_floor_stats(str(db), "ZZZ", label_column="outcome_1c")
    assert stats["labeled_rows"] == 130
    assert stats["usable_days"] == 2  # day3's 10 rows < 60


def test_auto_promote_skipped_when_data_floor_not_met(tmp_path: Path, monkeypatch):
    """Starved ticker: db_path provided → fail-closed, no copy to active/."""
    from tests.test_manual_governance import _minimal_governed_files, _write_candidate_manifests, _write_horizon_bundle

    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE", "1")
    monkeypatch.delenv("ED_DISABLE_AUTO_PROMOTE", raising=False)
    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE_REQUIRE_VERIFY", "0")
    _minimal_governed_files(tmp_path, cascade_ok=False)
    pdir = tmp_path / "parallel" / "SPY"
    cdir = tmp_path / "cascade" / "SPY"
    _write_horizon_bundle(pdir, "SPY", "1c")
    _write_horizon_bundle(cdir, "SPY", "1c")
    _write_candidate_manifests(pdir, cdir)

    import training_cache
    monkeypatch.setattr(
        training_cache,
        "db_training_floor_stats",
        lambda db_path, ticker, label_column="outcome_1c": {
            "ticker": ticker, "labeled_rows": 120, "usable_days": 1, "label_column": label_column,
        },
    )
    result = execute_promotion_if_eligible(
        tmp_path, "SPY", "1c", scheduler_run_id="starved", db_path=str(tmp_path / "x.db"),
    )
    assert result["executed"] is False
    assert result["skipped_reason"] == "data_floor_not_met"
    assert not (tmp_path / "active" / "SPY" / "xgb_SPY_1c.pkl").is_file()


def test_auto_promote_proceeds_when_data_floor_met(tmp_path: Path, monkeypatch):
    """Floor cleared with db_path provided → promotion proceeds (copy lands)."""
    from tests.test_manual_governance import _minimal_governed_files, _write_candidate_manifests, _write_horizon_bundle

    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE", "1")
    monkeypatch.delenv("ED_DISABLE_AUTO_PROMOTE", raising=False)
    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE_REQUIRE_VERIFY", "0")
    _minimal_governed_files(tmp_path, cascade_ok=False)
    pdir = tmp_path / "parallel" / "SPY"
    cdir = tmp_path / "cascade" / "SPY"
    _write_horizon_bundle(pdir, "SPY", "1c")
    _write_horizon_bundle(cdir, "SPY", "1c")
    _write_candidate_manifests(pdir, cdir)

    import training_cache
    monkeypatch.setattr(
        training_cache,
        "db_training_floor_stats",
        lambda db_path, ticker, label_column="outcome_1c": {
            "ticker": ticker, "labeled_rows": 5000, "usable_days": 20, "label_column": label_column,
        },
    )
    result = execute_promotion_if_eligible(
        tmp_path, "SPY", "1c", scheduler_run_id="healthy", db_path=str(tmp_path / "x.db"),
    )
    assert result["executed"] is True
    assert (tmp_path / "active" / "SPY" / "xgb_SPY_1c.pkl").is_file()


# ── Workstream B1 — fail-closed when no walk-forward holdout (in-sample eval) ───


def test_auto_promote_skipped_when_walk_forward_holdout_unavailable(tmp_path: Path, monkeypatch):
    """Thin ticker (<10 RTH sessions) → no holdout → in-sample eval → no copy to active/,
    recorded audit reason (no silent skip)."""
    from arch_competition.audit import load_recent_audit_records
    from tests.test_manual_governance import _minimal_governed_files, _write_candidate_manifests, _write_horizon_bundle

    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE", "1")
    monkeypatch.delenv("ED_DISABLE_AUTO_PROMOTE", raising=False)
    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE_REQUIRE_VERIFY", "0")
    _minimal_governed_files(tmp_path, cascade_ok=False)
    pdir = tmp_path / "parallel" / "SPY"
    cdir = tmp_path / "cascade" / "SPY"
    _write_horizon_bundle(pdir, "SPY", "1c")
    _write_horizon_bundle(cdir, "SPY", "1c")
    _write_candidate_manifests(pdir, cdir)

    # db_path provided + healthy floor: proves the BLOCK is the holdout guard, not A1.
    import training_cache
    monkeypatch.setattr(
        training_cache,
        "db_training_floor_stats",
        lambda db_path, ticker, label_column="outcome_1c": {
            "ticker": ticker, "labeled_rows": 5000, "usable_days": 20, "label_column": label_column,
        },
    )
    result = execute_promotion_if_eligible(
        tmp_path, "SPY", "1c", scheduler_run_id="thin",
        db_path=str(tmp_path / "x.db"),
        walk_forward_holdout_available=False,
    )
    assert result["executed"] is False
    assert result["skipped_reason"] == "walk_forward_holdout_unavailable"
    assert not (tmp_path / "active" / "SPY" / "xgb_SPY_1c.pkl").is_file()
    audit = load_recent_audit_records(tmp_path)
    assert any(r.get("outcome") == "in_sample_eval_not_promotion_clean" for r in audit)


def test_auto_promote_proceeds_when_walk_forward_holdout_available(tmp_path: Path, monkeypatch):
    """>= 10-session path unaffected: holdout available (default True) → promotion proceeds."""
    from tests.test_manual_governance import _minimal_governed_files, _write_candidate_manifests, _write_horizon_bundle

    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE", "1")
    monkeypatch.delenv("ED_DISABLE_AUTO_PROMOTE", raising=False)
    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE_REQUIRE_VERIFY", "0")
    _minimal_governed_files(tmp_path, cascade_ok=False)
    pdir = tmp_path / "parallel" / "SPY"
    cdir = tmp_path / "cascade" / "SPY"
    _write_horizon_bundle(pdir, "SPY", "1c")
    _write_horizon_bundle(cdir, "SPY", "1c")
    _write_candidate_manifests(pdir, cdir)

    result = execute_promotion_if_eligible(
        tmp_path, "SPY", "1c", scheduler_run_id="healthy-wf",
        walk_forward_holdout_available=True,
    )
    assert result["executed"] is True
    assert (tmp_path / "active" / "SPY" / "xgb_SPY_1c.pkl").is_file()


# ── Workstream A2 — candidate score + rows_used gate on the auto path ───────────


def _write_active_incumbent(model_dir: Path, *, promotion_score: float, target_column: str = "outcome_1c"):
    """Place a pre-existing active incumbent xgb meta with a known promotion_score."""
    from ml_horizon import target_definition as _td

    active = model_dir / "active" / "SPY"
    active.mkdir(parents=True, exist_ok=True)
    tdef = _td("1c") if target_column == "outcome_1c" else "outcome_5c ~5 min ahead (5×1m bars)"
    meta = {
        "model_type": "XGBClassifier",
        "ticker": "SPY",
        "training_timeframe": "1m",
        "target_column": target_column,
        "target_definition": tdef,
        "rows_used": 5000,
        "promotion_score": promotion_score,
        "promotion_metric": "ensemble_eval_accuracy",
        "balanced_accuracy": max(promotion_score - 0.02, 0.0),
    }
    (active / "xgb_SPY_1c_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _governed_auto_setup(tmp_path: Path, monkeypatch):
    from tests.test_manual_governance import _minimal_governed_files, _write_candidate_manifests, _write_horizon_bundle

    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE", "1")
    monkeypatch.delenv("ED_DISABLE_AUTO_PROMOTE", raising=False)
    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE_REQUIRE_VERIFY", "0")
    _minimal_governed_files(tmp_path, cascade_ok=False)  # candidate parallel acc = 0.45 (fixture)
    pdir = tmp_path / "parallel" / "SPY"
    cdir = tmp_path / "cascade" / "SPY"
    _write_horizon_bundle(pdir, "SPY", "1c")
    _write_horizon_bundle(cdir, "SPY", "1c")
    _write_candidate_manifests(pdir, cdir)


def test_auto_promote_blocked_when_candidate_worse_than_existing(tmp_path: Path, monkeypatch):
    _governed_auto_setup(tmp_path, monkeypatch)
    _write_active_incumbent(tmp_path, promotion_score=0.60)  # candidate 0.45 < 0.60
    result = execute_promotion_if_eligible(tmp_path, "SPY", "1c", scheduler_run_id="worse")
    assert result["executed"] is False
    assert result["skipped_reason"] == "promotion_gate_failed"
    assert "< existing" in result["promotion_gate_reason"]


def test_auto_promote_proceeds_when_candidate_beats_existing(tmp_path: Path, monkeypatch):
    _governed_auto_setup(tmp_path, monkeypatch)
    _write_active_incumbent(tmp_path, promotion_score=0.40)  # candidate 0.45 >= 0.40
    result = execute_promotion_if_eligible(tmp_path, "SPY", "1c", scheduler_run_id="better")
    assert result["executed"] is True
    assert (tmp_path / "active" / "SPY" / "xgb_SPY_1c.pkl").is_file()


def test_auto_promote_reconciles_pre_b_inflated_incumbent_before_gate(tmp_path: Path, monkeypatch):
    """Pre-B xgb-only incumbent scores (e.g. 0.8079) deadlock auto-promote until reconciled."""
    _governed_auto_setup(tmp_path, monkeypatch)
    active = tmp_path / "active" / "SPY"
    active.mkdir(parents=True, exist_ok=True)
    from ml_horizon import target_definition as _td

    meta = {
        "model_type": "XGBClassifier",
        "ticker": "SPY",
        "training_timeframe": "1m",
        "target_column": "outcome_1c",
        "target_definition": _td("1c"),
        "rows_used": 5000,
        "promotion_score": 0.8079,
        "promotion_metric": "accuracy",
        "balanced_accuracy": 0.75,
    }
    (active / "xgb_SPY_1c_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    result = execute_promotion_if_eligible(tmp_path, "SPY", "1c", scheduler_run_id="reconcile-auto")
    assert result["executed"] is True
    after = json.loads((active / "xgb_SPY_1c_meta.json").read_text(encoding="utf-8"))
    assert after["promotion_metric"] == "ensemble_eval_accuracy"
    assert after["promotion_score"] == pytest.approx(0.45)


def test_auto_promote_blocked_when_candidate_base_collapsed_single_class(tmp_path: Path, monkeypatch):
    """B3+ degeneracy guard: a candidate whose base predicts ONE class on its eval tail
    (all-flat collapse) is blocked regardless of top-line ensemble accuracy. The candidate
    ensemble (0.45) beats the incumbent (0.40), so it would clear the score gate — only the
    collapse flag blocks it."""
    _governed_auto_setup(tmp_path, monkeypatch)
    _write_active_incumbent(tmp_path, promotion_score=0.40)  # 0.45 >= 0.40 → score gate would pass
    cand_meta_path = tmp_path / "parallel" / "SPY" / "xgb_SPY_1c_meta.json"
    cand_meta = json.loads(cand_meta_path.read_text(encoding="utf-8"))
    cand_meta["val_single_class_collapse"] = True
    cand_meta_path.write_text(json.dumps(cand_meta), encoding="utf-8")

    result = execute_promotion_if_eligible(tmp_path, "SPY", "1c", scheduler_run_id="collapse")
    assert result["executed"] is False
    assert result["skipped_reason"] == "promotion_gate_failed"
    assert "single_class_collapse" in result["promotion_gate_reason"]
    assert not (tmp_path / "active" / "SPY" / "xgb_SPY_1c.pkl").is_file()


def test_auto_promote_force_replace_noncompliant_incumbent(tmp_path: Path, monkeypatch):
    _governed_auto_setup(tmp_path, monkeypatch)
    # incumbent scores higher but is non-compliant for 1c (wrong target_column) → force replace.
    _write_active_incumbent(tmp_path, promotion_score=0.99, target_column="outcome_5c")
    result = execute_promotion_if_eligible(tmp_path, "SPY", "1c", scheduler_run_id="forcerepl")
    assert result["executed"] is True


def test_auto_promote_stamps_active_incumbent_with_ensemble_score(tmp_path: Path, monkeypatch):
    """Basis-consistency: after promote, active meta promotion_score == manifest ENSEMBLE
    accuracy (0.45), not the xgb-only value copied verbatim from the candidate."""
    _governed_auto_setup(tmp_path, monkeypatch)
    # Candidate xgb meta carries an xgb-only val_accuracy distinct from the ensemble 0.45.
    cand_meta_path = tmp_path / "parallel" / "SPY" / "xgb_SPY_1c_meta.json"
    cand_meta = json.loads(cand_meta_path.read_text(encoding="utf-8"))
    cand_meta["val_accuracy"] = 0.30
    cand_meta_path.write_text(json.dumps(cand_meta), encoding="utf-8")

    result = execute_promotion_if_eligible(tmp_path, "SPY", "1c", scheduler_run_id="stamp")
    assert result["executed"] is True
    active_meta = json.loads(
        (tmp_path / "active" / "SPY" / "xgb_SPY_1c_meta.json").read_text(encoding="utf-8")
    )
    assert active_meta["promotion_score"] == pytest.approx(0.45)  # ensemble, not 0.30 xgb-only
    assert active_meta["promotion_metric"] == "ensemble_eval_accuracy"
    assert active_meta["balanced_accuracy"] == pytest.approx(0.40)


def test_auto_promote_blocked_when_worse_ensemble_than_ensemble_incumbent(tmp_path: Path, monkeypatch):
    """Realistic incumbent stored on the ENSEMBLE basis: a worse-ensemble candidate is
    rejected (the case the same-basis synthetic tests cannot exercise)."""
    _governed_auto_setup(tmp_path, monkeypatch)
    active = tmp_path / "active" / "SPY"
    active.mkdir(parents=True, exist_ok=True)
    from ml_horizon import target_definition as _td

    meta = {
        "model_type": "XGBClassifier",
        "ticker": "SPY",
        "training_timeframe": "1m",
        "target_column": "outcome_1c",
        "target_definition": _td("1c"),
        "rows_used": 5000,
        "promotion_score": 0.72,            # ensemble basis (as A2 now stamps)
        "promotion_metric": "ensemble_eval_accuracy",
        "balanced_accuracy": 0.68,
    }
    (active / "xgb_SPY_1c_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    # Candidate ensemble accuracy 0.45 (fixture) < incumbent ensemble 0.72 → blocked.
    result = execute_promotion_if_eligible(tmp_path, "SPY", "1c", scheduler_run_id="worse-ens")
    assert result["executed"] is False
    assert result["skipped_reason"] == "promotion_gate_failed"
    assert "< existing" in result["promotion_gate_reason"]
    # Incumbent meta untouched (no copy happened).
    after = json.loads((active / "xgb_SPY_1c_meta.json").read_text(encoding="utf-8"))
    assert after["promotion_score"] == pytest.approx(0.72)


def test_manual_promote_stamps_ensemble_basis(tmp_path: Path):
    """Symmetric stamp: manual promotion stays ungated but still stamps the incumbent
    with the ensemble basis, so the next auto challenger compares like-for-like."""
    from arch_competition.manual_control import (
        MANUAL_PROMOTE_CASCADE_INTENT,
        manual_promote_to_active_explicit,
    )
    from tests.test_manual_governance import _minimal_governed_files

    _minimal_governed_files(tmp_path, cascade_ok=True)  # manifest cascade accuracy = 0.45
    out = manual_promote_to_active_explicit(
        tmp_path,
        "SPY",
        "1c",
        target_architecture="cascade",
        operator_id="op1",
        manual_intent=MANUAL_PROMOTE_CASCADE_INTENT,
    )
    assert "checkpoint_id" in out
    active_meta = json.loads(
        (tmp_path / "active" / "SPY" / "xgb_SPY_1c_meta.json").read_text(encoding="utf-8")
    )
    assert active_meta["promotion_score"] == pytest.approx(0.45)
    assert active_meta["promotion_metric"] == "ensemble_eval_accuracy"
    assert active_meta["balanced_accuracy"] == pytest.approx(0.40)


def test_auto_promote_blocked_when_manifest_accuracy_missing(tmp_path: Path, monkeypatch):
    _governed_auto_setup(tmp_path, monkeypatch)
    ed = tmp_path / "arch_competition" / "1c" / "SPY"
    man = json.loads((ed / "evaluation_manifest.json").read_text(encoding="utf-8"))
    man["metrics"]["parallel"].pop("accuracy", None)
    rec = json.loads((ed / "promotion_decision.json").read_text(encoding="utf-8"))
    result = execute_promotion_if_eligible(
        tmp_path, "SPY", "1c", manifest=man, promotion_record=rec, scheduler_run_id="noacc",
    )
    assert result["executed"] is False
    assert result["skipped_reason"] == "promotion_gate_failed"
    assert "accuracy" in result["promotion_gate_reason"]


# ── CORRECTNESS-CLOSEOUT #4 — A2 first-cycle deadlock reconcile ────────────────
from timeframe_config import CANONICAL_TIMEFRAME


def _write_active_xgb_meta(model_dir: Path, tku: str, hz: str, *, score, metric=None,
                           root_name="active") -> Path:
    """Write a minimal active xgb meta (load_provenance-readable + score fields)."""
    d = model_dir / root_name / tku
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "model_type": "XGBClassifier",
        "ticker": tku,
        "training_timeframe": CANONICAL_TIMEFRAME,
        "target_column": f"outcome_{hz}",
        "target_definition": "",
        "rows_used": 1000,
        "promotion_score": score,
        "balanced_accuracy": 0.70,
    }
    if metric is not None:
        meta["promotion_metric"] = metric
    p = d / f"xgb_{tku}_{hz}_meta.json"
    p.write_text(json.dumps(meta), encoding="utf-8")
    return p


def _honest_candidate_prov():
    from training_provenance import TrainingProvenance

    return TrainingProvenance.from_dict({
        "model_type": "XGBClassifier", "ticker": "SPY",
        "training_timeframe": CANONICAL_TIMEFRAME, "target_column": "outcome_1c",
        "target_definition": "", "rows_used": 1000, "promotion_score": 0.45,
        "balanced_accuracy": 0.45,
    })


def test_reconcile_resets_pre_b_incumbent_and_unblocks_gate(tmp_path: Path):
    from arch_competition.promotion_execution import (
        PRE_B_RECONCILED_METRIC,
        reconcile_pre_b_incumbent_scores,
    )
    from training_provenance import load_provenance, validate_for_promotion

    meta = _write_active_xgb_meta(tmp_path, "SPY", "1c", score=0.8079)  # pre-B (no ensemble metric)

    # BEFORE: honest ensemble challenger (0.45) is blocked by the inflated incumbent 0.8079.
    cand = _honest_candidate_prov()
    ok_before, _ = validate_for_promotion(
        cand, 0.45, existing_provenance=load_provenance(meta),
        balanced_accuracy=0.45, horizon_slug="1c",
    )
    assert ok_before is False  # the deadlock

    out = reconcile_pre_b_incumbent_scores(tmp_path, ["SPY"], ["1c"], dry_run=False)
    assert out["reset_count"] == 1
    data = json.loads(meta.read_text(encoding="utf-8"))
    assert data["promotion_score"] == 0.0
    assert data["promotion_metric"] == PRE_B_RECONCILED_METRIC
    assert data["pre_b_reconciled_from_score"] == pytest.approx(0.8079)

    # AFTER: the same challenger now clears the score comparison (quality floors still gate).
    ok_after, reason = validate_for_promotion(
        cand, 0.45, existing_provenance=load_provenance(meta),
        balanced_accuracy=0.45, horizon_slug="1c",
    )
    assert ok_after is True, reason


def test_reconcile_dry_run_does_not_write(tmp_path: Path):
    from arch_competition.promotion_execution import reconcile_pre_b_incumbent_scores

    meta = _write_active_xgb_meta(tmp_path, "SPY", "1c", score=0.8079)
    out = reconcile_pre_b_incumbent_scores(tmp_path, ["SPY"], ["1c"], dry_run=True)
    assert out["dry_run"] is True
    assert out["would_reset"] == 1
    assert out["reset"][0]["old_score"] == pytest.approx(0.8079)
    assert out["reset"][0]["written"] is False
    # file untouched
    assert json.loads(meta.read_text(encoding="utf-8"))["promotion_score"] == pytest.approx(0.8079)


def test_reconcile_idempotent_second_run_zero(tmp_path: Path):
    from arch_competition.promotion_execution import reconcile_pre_b_incumbent_scores

    _write_active_xgb_meta(tmp_path, "SPY", "1c", score=0.8079)
    first = reconcile_pre_b_incumbent_scores(tmp_path, ["SPY"], ["1c"], dry_run=False)
    assert first["reset_count"] == 1
    second = reconcile_pre_b_incumbent_scores(tmp_path, ["SPY"], ["1c"], dry_run=False)
    assert second["reset_count"] == 0
    assert len(second["skipped"]) == 1


def test_reconcile_skips_ensemble_basis_incumbent(tmp_path: Path):
    from arch_competition.promotion_execution import reconcile_pre_b_incumbent_scores

    meta = _write_active_xgb_meta(
        tmp_path, "SPY", "1c", score=0.62, metric="ensemble_eval_accuracy"
    )
    out = reconcile_pre_b_incumbent_scores(tmp_path, ["SPY"], ["1c"], dry_run=False)
    assert out["reset_count"] == 0
    assert json.loads(meta.read_text(encoding="utf-8"))["promotion_score"] == pytest.approx(0.62)


def test_reconcile_resolves_horizon_specific_root(tmp_path: Path):
    """5c incumbents live under models/active_5c, not models/active — the horizon
    root must be derived per-horizon or non-1c incumbents stay deadlocked."""
    from arch_competition.promotion_execution import reconcile_pre_b_incumbent_scores

    meta_5c = _write_active_xgb_meta(tmp_path, "SPY", "5c", score=0.71, root_name="active_5c")
    out = reconcile_pre_b_incumbent_scores(tmp_path, ["SPY"], ["5c"], dry_run=False)
    assert out["reset_count"] == 1
    assert json.loads(meta_5c.read_text(encoding="utf-8"))["promotion_score"] == 0.0
    # nothing was created/needed under the 1c root
    assert not (tmp_path / "active" / "SPY").exists()


def test_reconcile_missing_meta_recorded_not_crash(tmp_path: Path):
    from arch_competition.promotion_execution import reconcile_pre_b_incumbent_scores

    out = reconcile_pre_b_incumbent_scores(tmp_path, ["NOPE"], ["1c"], dry_run=True)
    assert out["would_reset"] == 0
    assert len(out["missing"]) == 1


def test_reconcile_survivor_retrain_resets_ensemble_basis(tmp_path: Path):
    """O-56: ablated retrain must not compare against full-feature ensemble incumbents."""
    from arch_competition.promotion_execution import reconcile_pre_b_incumbent_scores

    meta = _write_active_xgb_meta(
        tmp_path, "SPY", "15c", score=0.55, root_name="active_15c", metric="ensemble_eval_accuracy"
    )
    out = reconcile_pre_b_incumbent_scores(
        tmp_path, ["SPY"], ["15c"], dry_run=False, survivor_retrain_reset=True
    )
    assert out["reset_count"] == 1
    assert json.loads(meta.read_text(encoding="utf-8"))["promotion_score"] == 0.0


def test_ensure_survivor_retrain_run_start_resets_all_horizons_once(monkeypatch, tmp_path: Path):
    """Scheduler run_once entry must reset ensemble incumbents on every governed horizon once."""
    import arch_competition.promotion_execution as pe

    monkeypatch.setattr(
        "arch_competition.stack_bundle_eval_v1.ablation_survivors_training_enabled",
        lambda: True,
    )
    pe._survivor_retrain_run_reset_done = False
    metas = []
    for hz, root in [("1c", "active"), ("5c", "active_5c"), ("15c", "active_15c"), ("60c", "active_60c")]:
        metas.append(
            _write_active_xgb_meta(
                tmp_path, "SPY", hz, score=0.44, root_name=root, metric="ensemble_eval_accuracy"
            )
        )
    first = pe.ensure_survivor_retrain_incumbent_reset_at_run_start(tmp_path, ["SPY"])
    assert first["reset_count"] == 4
    for meta in metas:
        assert json.loads(meta.read_text(encoding="utf-8"))["promotion_score"] == 0.0
    second = pe.ensure_survivor_retrain_incumbent_reset_at_run_start(tmp_path, ["SPY"])
    assert second["skipped"] is True
    assert second["reason"] == "already_reset_this_process"


def test_reconcile_write_outside_governed_scope_raises(tmp_path: Path):
    from arch_competition.exceptions import ManualGovernanceError
    from arch_competition.promotion_execution import _reset_pre_b_incumbent_meta

    meta = _write_active_xgb_meta(tmp_path, "SPY", "1c", score=0.8079)
    # calling the writer outside governed_active_write_scope must fail closed
    with pytest.raises(ManualGovernanceError):
        _reset_pre_b_incumbent_meta(meta, 0.8079)
