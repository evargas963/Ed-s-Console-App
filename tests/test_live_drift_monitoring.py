"""Live drift surveillance: governed baselines, stable schema, no production runtime change."""
from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from arch_competition.governance_visibility import build_governance_panel_payload
from arch_competition.live_drift_monitoring import (
    LIVE_DRIFT_MONITORING_SCHEMA_VERSION,
    REASON_BASELINE_MANIFEST_INVALID,
    REASON_BASELINE_MANIFEST_MISSING,
    REASON_CALIBRATION_DRIFT_MATERIAL,
    REASON_MODEL_DIR_UNAVAILABLE,
    REASON_MODEL_MANIFEST_INVALID,
    REASON_RECENT_SLICE_DISABLED,
    REASON_RECENT_SLICE_INSUFFICIENT,
    build_live_drift_monitoring_payload,
    live_drift_monitoring_artifact_path,
    persist_live_drift_monitoring,
)
from calibration.statistical_integrity import MIN_SAMPLES_STATISTICAL


def _write_minimal_governed(model_dir: Path, *, with_lineage: bool = True):
    hz = "1c"
    tku = "SPY"
    pdir = model_dir / "parallel" / tku
    cdir = model_dir / "cascade" / tku
    pdir.mkdir(parents=True)
    cdir.mkdir(parents=True)
    common = {
        "schema_version": "2",
        "ticker": "SPY",
        "ml_horizon_suffix": "1c",
        "trained_at": "2026-01-15T00:00:00+00:00",
        "data_fingerprint": {
            "min_ts_utc": 1.0,
            "max_ts_utc": 2.0,
            "row_count": 100,
            "table": "snapshots_1m_normalized",
            "timeframe": "1m",
            "ticker": "SPY",
        },
        "training_code_fingerprint": "fp_test",
        "feature_cache_key": "fk",
    }
    (pdir / "scheduler_run_manifest.json").write_text(json.dumps(common), encoding="utf-8")
    (cdir / "scheduler_run_manifest.json").write_text(json.dumps(common), encoding="utf-8")

    lineage = {
        "feature_cache_key": "fk",
        "data_fingerprint": common["data_fingerprint"],
        "ml_horizon_suffix": "1c",
        "training_code_fingerprint": "fp_test",
        "canonical_feature_contract_version": "v1",
        "canonical_timeframe": "1m",
    }
    if not with_lineage:
        lineage = {"feature_cache_key": "fk", "data_fingerprint": common["data_fingerprint"], "ml_horizon_suffix": "1c"}

    ev = {
        "schema_version": "1",
        "created_at_utc": "2026-01-10T00:00:00+00:00",
        "ticker": "SPY",
        "ml_horizon_slug": "1c",
        "target_column": "outcome_1c",
        "db_path": str(model_dir / "db.sqlite"),
        "parallel_model_dir": str(pdir.resolve()),
        "cascade_model_dir": str(cdir.resolve()),
        "lineage": lineage,
        "metrics": {
            "parallel": {"n_rows_scored": 100, "calibration_ece": 0.08},
            "cascade": {"n_rows_scored": 100, "calibration_ece": 0.09},
        },
        "rolling_oos_windows": [],
        "architecture_comparison_summary": {},
        "confidence_reliability_summary": {
            "schema_version": "1",
            "by_architecture": {
                "parallel": {"confidence_hit_correlation": 0.1},
                "cascade": {"confidence_hit_correlation": 0.1},
            },
        },
        "calibration_summary": {"schema_version": "1", "regime_conditional_ece": {}},
        "rolling_stability_summary": {"schema_version": "1", "by_architecture": {}},
        "empirical_validation": {"schema_version": "1"},
        "lineage_fingerprints": {},
        "metric_breakdown": {},
    }
    pr = {
        "schema_version": "1",
        "created_at_utc": "2026-01-10T00:00:00+00:00",
        "incumbent_architecture": "parallel",
        "challenger_architecture": "cascade",
        "promotion_decision": "keep_incumbent",
        "would_promote_challenger": False,
        "auto_promote_executed": False,
        "policy": {},
        "reason_codes": [],
        "blocked_promotion_flags": [],
        "rollback_demotion_ready": True,
        "evaluation_manifest_reference": {},
    }
    ed = model_dir / "arch_competition" / hz / tku
    ed.mkdir(parents=True)
    (ed / "evaluation_manifest.json").write_text(json.dumps(ev), encoding="utf-8")
    (ed / "promotion_decision.json").write_text(json.dumps(pr), encoding="utf-8")


def test_missing_model_dirs_emits_warning_and_unavailable_summary(tmp_path: Path):
    _write_minimal_governed(tmp_path)
    ev_path = tmp_path / "arch_competition" / "1c" / "SPY" / "evaluation_manifest.json"
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    ev["parallel_model_dir"] = ""
    ev["cascade_model_dir"] = ""
    ev_path.write_text(json.dumps(ev), encoding="utf-8")
    pl = build_live_drift_monitoring_payload(
        tmp_path,
        "1c",
        "SPY",
        db_path=None,
        include_recent_slice_evaluation=False,
    )
    assert pl["ok"] is True
    assert pl["model_freshness_summary"]["state"] == "unavailable"
    assert pl["model_freshness_summary"]["reason_code"] == REASON_MODEL_DIR_UNAVAILABLE
    codes = [s.get("reason_code") for s in pl.get("signals", [])]
    assert REASON_MODEL_DIR_UNAVAILABLE in codes


def test_recent_slice_n_below_min_samples_statistical_unavailable(tmp_path: Path):
    _write_minimal_governed(tmp_path)
    dbfile = tmp_path / "db.sqlite"
    dbfile.write_bytes(b"")
    fp = {
        "table": "snapshots_1m_normalized",
        "timeframe": "1m",
        "ticker": "SPY",
        "min_ts_utc": 1.0,
        "max_ts_utc": 2.0,
        "row_count": 500,
    }
    dates = [f"2026-01-{i:02d}" for i in range(1, 8)]
    n_recent = MIN_SAMPLES_STATISTICAL - 1
    fake_recent = {
        "metrics": {
            "parallel": {"n_rows_scored": n_recent, "calibration_ece": 0.12},
            "cascade": {"n_rows_scored": n_recent, "calibration_ece": 0.12},
        },
        "confidence_reliability_summary": {
            "schema_version": "1",
            "by_architecture": {
                "parallel": {"confidence_hit_correlation": 0.1},
                "cascade": {"confidence_hit_correlation": 0.1},
            },
        },
        "calibration_summary": {"schema_version": "1", "regime_conditional_ece": {}},
    }
    with (
        patch("arch_competition.live_drift_monitoring.db_training_fingerprint", return_value=fp),
        patch("arch_competition.live_drift_monitoring.db_distinct_rth_et_dates_for_ticker", return_value=dates),
        patch(
            "arch_competition.live_drift_monitoring.run_architecture_pair_evaluation",
            return_value=fake_recent,
        ),
    ):
        pl = build_live_drift_monitoring_payload(
            tmp_path,
            "1c",
            "SPY",
            db_path=dbfile,
            include_recent_slice_evaluation=True,
            recent_rth_sessions=5,
            calibration_ece_drift_critical=0.12,
        )
    assert pl["calibration_drift_summary"]["state"] == "unavailable"
    assert pl["calibration_drift_summary"]["reason_code"] == REASON_RECENT_SLICE_INSUFFICIENT
    codes = [s.get("reason_code") for s in pl.get("signals", [])]
    assert REASON_CALIBRATION_DRIFT_MATERIAL not in codes


def test_live_drift_schema_and_sections(tmp_path: Path):
    _write_minimal_governed(tmp_path)
    payload = build_live_drift_monitoring_payload(
        tmp_path,
        "1c",
        "SPY",
        db_path=tmp_path / "nonexistent.db",
        include_recent_slice_evaluation=False,
    )
    assert payload["schema_version"] == LIVE_DRIFT_MONITORING_SCHEMA_VERSION
    assert payload["ok"] is True
    assert "live_drift_summary" in payload
    assert "calibration_drift_summary" in payload
    assert payload["calibration_drift_summary"].get("reason_code") == REASON_RECENT_SLICE_DISABLED
    assert "model_freshness_summary" in payload
    assert "evaluation_freshness_summary" in payload
    assert "promotion_validity_summary" in payload
    assert "regime_shift_summary" in payload


def test_missing_baseline_manifest_error(tmp_path: Path):
    payload = build_live_drift_monitoring_payload(tmp_path, "1c", "SPY")
    assert payload["ok"] is False
    assert payload["live_drift_summary"].get("reason_code") == REASON_BASELINE_MANIFEST_MISSING


def test_corrupt_evaluation_manifest_uses_invalid_reason_code(tmp_path: Path):
    _write_minimal_governed(tmp_path)
    ev_path = tmp_path / "arch_competition" / "1c" / "SPY" / "evaluation_manifest.json"
    ev_path.write_text("{not-json", encoding="utf-8")
    payload = build_live_drift_monitoring_payload(tmp_path, "1c", "SPY", db_path=None)
    assert payload["ok"] is False
    assert payload["live_drift_summary"]["reason_code"] == REASON_BASELINE_MANIFEST_INVALID
    assert payload["live_drift_summary"]["reason_code"] != REASON_BASELINE_MANIFEST_MISSING
    assert "invalid JSON" in (payload.get("error") or "")


def test_evaluation_manifest_schema_mismatch_maps_invalid_reason(tmp_path: Path):
    _write_minimal_governed(tmp_path)
    ev_path = tmp_path / "arch_competition" / "1c" / "SPY" / "evaluation_manifest.json"
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    ev["schema_version"] = "wrong"
    ev_path.write_text(json.dumps(ev), encoding="utf-8")
    payload = build_live_drift_monitoring_payload(tmp_path, "1c", "SPY", db_path=None)
    assert payload["ok"] is False
    assert payload["live_drift_summary"]["reason_code"] == REASON_BASELINE_MANIFEST_INVALID
    assert "schema mismatch" in (payload.get("error") or "").lower()


def test_persist_live_drift_uses_atomic_write_helper(tmp_path: Path, monkeypatch):
    _write_minimal_governed(tmp_path)
    calls: list[tuple] = []

    def _capture(path, payload, **kwargs):
        calls.append((path, payload, kwargs))
        from arch_competition.atomic_io import write_json_file_atomically as real

        return real(path, payload, **kwargs)

    monkeypatch.setattr(
        "arch_competition.live_drift_monitoring.write_json_file_atomically",
        _capture,
    )
    pl = build_live_drift_monitoring_payload(tmp_path, "1c", "SPY", db_path=None)
    persist_live_drift_monitoring(tmp_path, "1c", "SPY", pl)
    assert len(calls) == 1
    assert calls[0][0] == live_drift_monitoring_artifact_path(tmp_path, "1c", "SPY")


def test_recent_slice_unexpected_exception_propagates(tmp_path: Path, monkeypatch):
    _write_minimal_governed(tmp_path)
    dbfile = tmp_path / "db.sqlite"
    dbfile.write_bytes(b"")
    fp = {
        "table": "snapshots_1m_normalized",
        "timeframe": "1m",
        "ticker": "SPY",
        "min_ts_utc": 1.0,
        "max_ts_utc": 2.0,
        "row_count": 500,
    }
    dates = [f"2026-01-{i:02d}" for i in range(1, 8)]

    def _boom(*_args, **_kwargs):
        raise RuntimeError("unexpected eval failure")

    with (
        patch("arch_competition.live_drift_monitoring.db_training_fingerprint", return_value=fp),
        patch("arch_competition.live_drift_monitoring.db_distinct_rth_et_dates_for_ticker", return_value=dates),
        patch("arch_competition.live_drift_monitoring.run_architecture_pair_evaluation", _boom),
    ):
        with pytest.raises(RuntimeError, match="unexpected eval failure"):
            build_live_drift_monitoring_payload(
                tmp_path,
                "1c",
                "SPY",
                db_path=dbfile,
                include_recent_slice_evaluation=True,
            )


def test_corrupt_scheduler_manifest_emits_invalid_signal(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    _write_minimal_governed(tmp_path)
    (tmp_path / "parallel" / "SPY" / "scheduler_run_manifest.json").write_text("{bad", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="arch_competition.live_drift_monitoring"):
        payload = build_live_drift_monitoring_payload(tmp_path, "1c", "SPY", db_path=None)
    assert payload["ok"] is True
    codes = [s.get("reason_code") for s in payload.get("signals", [])]
    assert REASON_MODEL_MANIFEST_INVALID in codes
    assert any("invalid scheduler manifest" in r.message for r in caplog.records)


def test_malformed_created_at_utc_logs_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    _write_minimal_governed(tmp_path)
    ev_path = tmp_path / "arch_competition" / "1c" / "SPY" / "evaluation_manifest.json"
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    ev["created_at_utc"] = "not-a-timestamp"
    ev_path.write_text(json.dumps(ev), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="arch_competition.live_drift_monitoring"):
        payload = build_live_drift_monitoring_payload(tmp_path, "1c", "SPY", db_path=None)
    assert payload["ok"] is True
    assert payload["evaluation_freshness_summary"]["age_days"] is None
    assert any("could not parse iso utc" in r.message for r in caplog.records)


def test_persist_live_drift_atomic_preserves_prior_on_replace_failure(tmp_path: Path, monkeypatch):
    _write_minimal_governed(tmp_path)
    p = live_drift_monitoring_artifact_path(tmp_path, "1c", "SPY")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema_version": "1", "ok": True, "prior": True}), encoding="utf-8")
    pl = build_live_drift_monitoring_payload(tmp_path, "1c", "SPY", db_path=None)
    pl["marker"] = "new"

    def _fail_replace(*_args, **_kwargs):
        raise OSError("simulated crash before replace")

    monkeypatch.setattr("arch_competition.atomic_io.os.replace", _fail_replace)
    with pytest.raises(OSError, match="simulated crash"):
        persist_live_drift_monitoring(tmp_path, "1c", "SPY", pl)
    kept = json.loads(p.read_text(encoding="utf-8"))
    assert kept.get("prior") is True
    assert "marker" not in kept


def test_lineage_incomplete_fail_closed(tmp_path: Path):
    _write_minimal_governed(tmp_path, with_lineage=False)
    payload = build_live_drift_monitoring_payload(tmp_path, "1c", "SPY", db_path=None)
    assert payload["ok"] is False
    assert "lineage" in (payload.get("error") or "").lower()


def test_persist_artifact_path(tmp_path: Path):
    _write_minimal_governed(tmp_path)
    p = live_drift_monitoring_artifact_path(tmp_path, "1c", "SPY")
    pl = build_live_drift_monitoring_payload(tmp_path, "1c", "SPY", db_path=None)
    out = persist_live_drift_monitoring(tmp_path, "1c", "SPY", pl)
    assert out == p
    assert p.is_file()


def test_governance_panel_includes_live_drift(tmp_path: Path):
    _write_minimal_governed(tmp_path)
    (tmp_path / "arch_competition" / "governance_audit.jsonl").write_text("", encoding="utf-8")
    panel = build_governance_panel_payload(tmp_path, "1c", "SPY", include_live_drift=True, db_path=None)
    assert panel.get("ok") is True
    assert "live_drift_monitoring" in panel
    assert panel["live_drift_monitoring"]["schema_version"] == LIVE_DRIFT_MONITORING_SCHEMA_VERSION


def test_insufficient_sessions_recent_slice_unavailable(tmp_path: Path):
    _write_minimal_governed(tmp_path)
    dbfile = tmp_path / "db.sqlite"
    dbfile.write_bytes(b"")
    fp = {
        "table": "snapshots_1m_normalized",
        "timeframe": "1m",
        "ticker": "SPY",
        "min_ts_utc": 1.0,
        "max_ts_utc": 2.0,
        "row_count": 10,
    }
    with (
        patch("arch_competition.live_drift_monitoring.db_training_fingerprint", return_value=fp),
        patch("arch_competition.live_drift_monitoring.db_distinct_rth_et_dates_for_ticker", return_value=["2026-01-01"]),
    ):
        pl = build_live_drift_monitoring_payload(
            tmp_path,
            "1c",
            "SPY",
            db_path=dbfile,
            include_recent_slice_evaluation=True,
            recent_rth_sessions=5,
        )
    assert pl["calibration_drift_summary"].get("state") == "unavailable"
    assert pl["calibration_drift_summary"].get("reason_code") == REASON_RECENT_SLICE_INSUFFICIENT


def test_live_drift_module_does_not_call_run_base_models_once():
    root = Path(__file__).resolve().parents[1] / "arch_competition" / "live_drift_monitoring.py"
    tree = ast.parse(root.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "run_base_models_once":
                pytest.fail("live_drift_monitoring must not call run_base_models_once")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "run_base_models_once":
                pytest.fail("live_drift_monitoring must not call run_base_models_once")


def test_ml_predict_default_parallel_runtime_unchanged():
    from ml_predict import run_base_models_once
    import inspect

    assert "parallel_runtime=True" in inspect.getsource(run_base_models_once)


def test_calibration_drift_material_emits_signal_when_recent_slice_degrades(tmp_path: Path):
    _write_minimal_governed(tmp_path)
    dbfile = tmp_path / "db.sqlite"
    dbfile.write_bytes(b"")
    fp = {
        "table": "snapshots_1m_normalized",
        "timeframe": "1m",
        "ticker": "SPY",
        "min_ts_utc": 1.0,
        "max_ts_utc": 2.0,
        "row_count": 500,
    }
    dates = [f"2026-01-{i:02d}" for i in range(1, 8)]
    fake_recent = {
        "metrics": {
            "parallel": {"n_rows_scored": 100, "calibration_ece": 0.45},
            "cascade": {"n_rows_scored": 100, "calibration_ece": 0.45},
        },
        "confidence_reliability_summary": {
            "schema_version": "1",
            "by_architecture": {
                "parallel": {"confidence_hit_correlation": 0.1},
                "cascade": {"confidence_hit_correlation": 0.1},
            },
        },
        "calibration_summary": {"schema_version": "1", "regime_conditional_ece": {}},
    }
    with (
        patch("arch_competition.live_drift_monitoring.db_training_fingerprint", return_value=fp),
        patch("arch_competition.live_drift_monitoring.db_distinct_rth_et_dates_for_ticker", return_value=dates),
        patch(
            "arch_competition.live_drift_monitoring.run_architecture_pair_evaluation",
            return_value=fake_recent,
        ),
    ):
        pl = build_live_drift_monitoring_payload(
            tmp_path,
            "1c",
            "SPY",
            db_path=dbfile,
            include_recent_slice_evaluation=True,
            recent_rth_sessions=5,
            calibration_ece_drift_critical=0.12,
        )
    codes = [s.get("reason_code") for s in pl.get("signals", [])]
    assert REASON_CALIBRATION_DRIFT_MATERIAL in codes
