"""Governance visibility panel + API hooks (read-only + manual_control only)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from arch_competition.governance_visibility import (
    GOVERNANCE_PANEL_SCHEMA_VERSION,
    _rollback_checkpoint_available,
    build_governance_panel_payload,
    is_governance_ui_actions_enabled,
)
from arch_competition.manual_control import MANUAL_PROMOTE_CASCADE_INTENT


def _minimal_governed_files(model_dir: Path, *, cascade_ok: bool = True):
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
        "trained_at": "2026-01-01T00:00:00+00:00",
        "data_fingerprint": {
            "min_ts_utc": 1577836800.0,
            "max_ts_utc": 1590998400.0,
            "row_count": 1000,
            "table": "snapshots_1m_normalized",
            "timeframe": "1m",
            "ticker": "SPY",
        },
        "training_code_fingerprint": "trainfp_shared",
        "feature_cache_key": "fk_shared",
    }
    (pdir / "scheduler_run_manifest.json").write_text(json.dumps(common), encoding="utf-8")
    (cdir / "scheduler_run_manifest.json").write_text(json.dumps(common), encoding="utf-8")

    ev = {
        "schema_version": "1",
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "ticker": "SPY",
        "ml_horizon_slug": "1c",
        "target_column": "outcome_1c",
        "db_path": str(model_dir / "db.sqlite"),
        "parallel_model_dir": str(pdir.resolve()),
        "cascade_model_dir": str(cdir.resolve()),
        "lineage": {
            "feature_cache_key": "fk_shared",
            "data_fingerprint": common["data_fingerprint"],
            "ml_horizon_suffix": "1c",
            "training_code_fingerprint": "trainfp_shared",
            "canonical_feature_contract_version": "v1",
            "canonical_timeframe": "1m",
        },
        "confidence_reliability_summary": {"schema_version": "1", "by_architecture": {}},
        "calibration_summary": {"schema_version": "1", "by_architecture": {}},
        "rolling_stability_summary": {"schema_version": "1", "by_architecture": {}},
        "empirical_validation": {"schema_version": "1"},
        "metrics": {
            "parallel": {"n_rows_scored": 10, "calibration_ece": 0.1},
            "cascade": {"n_rows_scored": 10, "calibration_ece": 0.1},
        },
        "rolling_oos_windows": [],
        "architecture_comparison_summary": {},
        "lineage_fingerprints": {},
        "metric_breakdown": {},
    }
    pr = {
        "schema_version": "1",
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "incumbent_architecture": "parallel",
        "challenger_architecture": "cascade",
        "promotion_decision": "promote_cascade" if cascade_ok else "keep_incumbent",
        "would_promote_challenger": cascade_ok,
        "auto_promote_executed": False,
        "policy": {},
        "reason_codes": [{"code": "OK", "detail": ""}] if cascade_ok else [],
        "blocked_promotion_flags": [] if cascade_ok else [{"code": "BLOCK", "detail": "x"}],
        "rollback_demotion_ready": True,
        "evaluation_manifest_reference": {
            "evaluation_manifest_schema": "1",
            "ticker": "SPY",
            "ml_horizon_slug": "1c",
            "lineage_feature_cache_key": "fk_shared",
        },
    }
    ed = model_dir / "arch_competition" / hz / tku
    ed.mkdir(parents=True)
    (ed / "evaluation_manifest.json").write_text(json.dumps(ev), encoding="utf-8")
    (ed / "promotion_decision.json").write_text(json.dumps(pr), encoding="utf-8")

    (model_dir / "arch_competition" / "governance_audit.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "action": "manual_promote_attempt",
                "outcome": "pending",
                "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "operator_id": "t",
                "ticker": "SPY",
                "ml_horizon_suffix": "1c",
                "prior_active_architecture": "parallel",
                "target_architecture": "cascade",
                "new_active_architecture": None,
                "evaluation_manifest_path": "/e",
                "promotion_decision_path": "/p",
                "checkpoint_id": "ck",
                "detail": "",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_visibility_panel_reads_governed_fields(tmp_path: Path):
    _minimal_governed_files(tmp_path, cascade_ok=True)
    (tmp_path / "arch_state.json").write_text(
        json.dumps(
            {
                "SPY": {
                    "active_architecture": "parallel",
                    "governed_competition": {"latest_evaluation_at": "2026-01-02T00:00:00+00:00"},
                }
            }
        ),
        encoding="utf-8",
    )
    p = build_governance_panel_payload(tmp_path, "1c", "SPY")
    assert p["ok"] is True
    assert p["schema_version"] == GOVERNANCE_PANEL_SCHEMA_VERSION
    assert p["latest_promotion_decision"] == "promote_cascade"
    assert p["would_promote_challenger"] is True
    assert p["blocked_promotion_flags"] == []
    assert p["incumbent_architecture"] == "parallel"
    assert p["challenger_architecture"] == "cascade"
    assert p["rollback_demotion_ready"] is True
    assert p["lineage_summary"]["from_manifest_lineage"]["feature_cache_key"] == "fk_shared"
    assert len(p["recent_audit_actions"]) >= 1


def test_blocked_reasons_when_not_promotable(tmp_path: Path):
    _minimal_governed_files(tmp_path, cascade_ok=False)
    p = build_governance_panel_payload(tmp_path, "1c", "SPY")
    assert p["ok"] is True
    assert p["would_promote_challenger"] is False
    assert p["blocked_promotion_flags"] and p["blocked_promotion_flags"][0]["code"] == "BLOCK"
    assert p["manual_promote_cascade_enabled"] is False


def test_panel_unavailable_when_artifacts_missing(tmp_path: Path):
    p = build_governance_panel_payload(tmp_path, "1c", "SPY")
    assert p["ok"] is False
    assert p["error"]
    assert p["actions_enabled"] is False
    assert p["manual_promote_cascade_enabled"] is False
    assert p["manual_promote_parallel_enabled"] is False
    assert p["manual_rollback_enabled"] is False


def test_production_default_parallel_in_panel(tmp_path: Path):
    _minimal_governed_files(tmp_path, cascade_ok=True)
    p = build_governance_panel_payload(tmp_path, "1c", "SPY")
    assert p["production_default_runtime"] == "parallel"


def test_panel_recent_audit_actions_empty_when_no_ticker_match(tmp_path: Path):
    _minimal_governed_files(tmp_path, cascade_ok=True)
    log_path = tmp_path / "arch_competition" / "governance_audit.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "action": "manual_promote_attempt",
                "outcome": "pending",
                "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "operator_id": "t",
                "ticker": "QQQ",
                "ml_horizon_suffix": "1c",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    p = build_governance_panel_payload(
        tmp_path,
        "1c",
        "SPY",
        include_live_drift=False,
        emit_notification_delivery=False,
    )
    assert p["ok"] is True
    assert p["recent_audit_actions"] == []


def test_corrupt_arch_state_surfaces_warning_ok_true(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    _minimal_governed_files(tmp_path, cascade_ok=True)
    (tmp_path / "arch_state.json").write_text("{not-json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="arch_competition.governance_visibility"):
        p = build_governance_panel_payload(
            tmp_path,
            "1c",
            "SPY",
            include_live_drift=False,
            emit_notification_delivery=False,
        )
    assert p["ok"] is True
    assert p["governed_competition"] is None
    assert p["warnings"][0]["code"] == "ARCH_STATE_UNREADABLE"
    assert any("arch_state" in r.message.lower() and "unreadable" in r.message.lower() for r in caplog.records)


def test_panel_surfaces_persistence_failures(tmp_path: Path, monkeypatch):
    _minimal_governed_files(tmp_path, cascade_ok=True)

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(
        "arch_competition.governance_visibility.persist_operational_policy_payload",
        _boom,
    )
    p = build_governance_panel_payload(
        tmp_path,
        "1c",
        "SPY",
        include_live_drift=False,
        emit_notification_delivery=False,
    )
    assert p["ok"] is True
    assert p["persistence_failures"]
    assert p["persistence_failures"][0]["operation"] == "persist_operational_policy_payload"
    assert "disk full" in p["persistence_failures"][0]["error"]


def test_panel_recent_audit_actions_are_ticker_scoped_only(tmp_path: Path):
    _minimal_governed_files(tmp_path, cascade_ok=True)
    p = build_governance_panel_payload(
        tmp_path,
        "1c",
        "SPY",
        include_live_drift=False,
        emit_notification_delivery=False,
    )
    assert all(str(a.get("ticker", "")).upper() == "SPY" for a in p["recent_audit_actions"])


def test_rollback_checkpoint_skips_corrupt_manifest_uses_valid_remaining(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    from arch_competition.manual_control import rollback_checkpoints_dir

    base = rollback_checkpoints_dir(tmp_path, "1c", "SPY")
    base.mkdir(parents=True)
    bad = base / "ck_bad"
    bad.mkdir()
    (bad / "checkpoint_manifest.json").write_text("{not-json", encoding="utf-8")
    good = base / "ck_good"
    good.mkdir()
    (good / "checkpoint_manifest.json").write_text(
        json.dumps({"snapshot_empty": False}),
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="arch_competition.governance_visibility"):
        assert _rollback_checkpoint_available(tmp_path, "1c", "SPY") is True
    assert any("corrupt checkpoint manifest" in r.message for r in caplog.records)


def test_manual_promote_endpoint_invokes_only_manual_control(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ED_GOVERNANCE_UI_ACTIONS", "1")
    monkeypatch.setenv("ED_GOVERNANCE_ALLOW_REMOTE", "1")
    project_root = tmp_path / "proj"
    models_dir = project_root / "models"
    _minimal_governed_files(models_dir)
    called: dict = {}

    def _fake(model_dir, ticker, ml_horizon_slug, **kwargs):
        called["model_dir"] = model_dir
        called["kwargs"] = kwargs
        return {"checkpoint_id": "test-ck", "active_dir": str(models_dir / "active" / "SPY")}

    monkeypatch.setattr(
        "arch_competition.manual_control.manual_promote_to_active_explicit",
        _fake,
    )
    import server

    monkeypatch.setattr(server, "APP_DIR", str(project_root))

    from fastapi.testclient import TestClient

    c = TestClient(server.app)
    r = c.post(
        "/api/governance/manual-promote",
        json={
            "ticker": "SPY",
            "horizon": "1c",
            "target_architecture": "cascade",
            "operator_id": "op",
            "manual_intent": MANUAL_PROMOTE_CASCADE_INTENT,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert called["model_dir"] == models_dir.resolve()
    assert called["kwargs"]["target_architecture"] == "cascade"
    assert called["kwargs"]["operator_id"] == "op"


def test_manual_promote_forbidden_when_ui_disabled(monkeypatch):
    monkeypatch.delenv("ED_GOVERNANCE_UI_ACTIONS", raising=False)
    assert is_governance_ui_actions_enabled() is False
    from fastapi.testclient import TestClient
    import server

    c = TestClient(server.app)
    r = c.post(
        "/api/governance/manual-promote",
        json={
            "ticker": "SPY",
            "horizon": "1c",
            "target_architecture": "cascade",
            "operator_id": "op",
            "manual_intent": MANUAL_PROMOTE_CASCADE_INTENT,
        },
    )
    assert r.status_code == 403
