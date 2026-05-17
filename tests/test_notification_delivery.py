"""Governed notification delivery: downstream of operational_policy / alert_routing only."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arch_competition.governance_visibility import build_governance_panel_payload
from arch_competition.notification_delivery import (
    NOTIFICATION_DELIVERY_RECORD_SCHEMA_VERSION,
    NotificationDeliveryConfig,
    NotificationDeliveryError,
    process_notification_deliveries,
    read_recent_notification_delivery_records,
    validate_alert_routing_payload,
    validate_governed_alert_for_delivery,
)
from arch_competition.operational_policy import ALERT_ROUTING_SCHEMA_VERSION


def _minimal_op_payload(*, alert: dict | None = None, schema_alerts: list | None = None):
    alerts = schema_alerts if schema_alerts is not None else ([alert] if alert else [])
    return {
        "schema_version": "1",
        "state": "ok",
        "last_policy_evaluation_timestamp": "2026-04-10T12:00:00+00:00",
        "alert_routing": {
            "schema_version": ALERT_ROUTING_SCHEMA_VERSION,
            "alerts": alerts,
            "dedup_semantics": "test",
        },
        "operational_policy_state": {},
    }


def _valid_alert():
    return {
        "alert_id": "a1b2c3d4e5f6g7h8",
        "reason_code": "TEST_REASON",
        "severity": "warning",
        "routing_class": "ops",
        "recommended_operator_action": "noop",
        "evidence_refs": [{"kind": "evaluation_manifest", "path": "/x"}],
        "suppression_key": "SPY|1c|test",
    }


def test_stable_delivery_record_schema(tmp_path: Path):
    p = _minimal_op_payload(alert=_valid_alert())
    cfg = NotificationDeliveryConfig(True, False, "", False, False)
    r = process_notification_deliveries(tmp_path, "1c", "SPY", p, config=cfg)
    assert r["ok"] is True
    lines = (tmp_path / "arch_competition" / "1c" / "SPY" / "notification_delivery_log.jsonl").read_text(
        encoding="utf-8"
    ).strip()
    rec = json.loads(lines.splitlines()[0])
    assert rec["schema_version"] == NOTIFICATION_DELIVERY_RECORD_SCHEMA_VERSION
    assert "timestamp_utc" in rec
    assert "dedup_decision" in rec
    assert "delivery_outcome" in rec


def test_valid_governed_alert_produces_records(tmp_path: Path):
    p = _minimal_op_payload(alert=_valid_alert())
    cfg = NotificationDeliveryConfig(True, False, "", False, False)
    r = process_notification_deliveries(tmp_path, "1c", "SPY", p, config=cfg)
    assert r["records_written"] >= 1
    recent = read_recent_notification_delivery_records(tmp_path, "1c", "SPY", limit=10)
    assert len(recent) >= 1
    assert any(x.get("delivery_outcome") == "delivered" and x.get("sink_type") == "file" for x in recent)


def test_duplicate_alerts_suppressed(tmp_path: Path):
    alert = _valid_alert()
    p = _minimal_op_payload(alert=alert)
    cfg = NotificationDeliveryConfig(True, False, "", False, False)
    r1 = process_notification_deliveries(tmp_path, "1c", "SPY", p, config=cfg)
    p2 = _minimal_op_payload(alert=alert)
    p2["last_policy_evaluation_timestamp"] = "2026-04-10T13:00:00+00:00"
    r2 = process_notification_deliveries(tmp_path, "1c", "SPY", p2, config=cfg)
    assert r1["ok"] and r2["ok"]
    recent = read_recent_notification_delivery_records(tmp_path, "1c", "SPY", limit=20)
    assert any(x.get("dedup_decision") in ("suppressed_same_policy_cycle", "suppressed_utc_day") for x in recent)


def test_malformed_alert_fail_closed(tmp_path: Path):
    bad = {**_valid_alert()}
    del bad["evidence_refs"]
    p = _minimal_op_payload(alert=bad)
    cfg = NotificationDeliveryConfig(True, False, "", False, False)
    r = process_notification_deliveries(tmp_path, "1c", "SPY", p, config=cfg)
    assert r["ok"] is False
    recent = read_recent_notification_delivery_records(tmp_path, "1c", "SPY", limit=10)
    assert any(x.get("delivery_outcome") == "failed_validation" for x in recent)


def test_invalid_alert_routing_fail_closed(tmp_path: Path):
    p = _minimal_op_payload(schema_alerts=[])
    p["alert_routing"] = {"schema_version": "99", "alerts": []}
    cfg = NotificationDeliveryConfig(True, False, "", False, False)
    r = process_notification_deliveries(tmp_path, "1c", "SPY", p, config=cfg)
    assert r["ok"] is False
    assert r.get("error")


def test_webhook_enabled_without_url_fail_closed(tmp_path: Path):
    p = _minimal_op_payload(alert=_valid_alert())
    cfg = NotificationDeliveryConfig(False, True, "", False, False)
    r = process_notification_deliveries(tmp_path, "1c", "SPY", p, config=cfg)
    assert r["ok"] is False
    assert "WEBHOOK_URL" in (r.get("error") or "")


def test_delivery_does_not_mutate_arch_state(tmp_path: Path):
    arch = tmp_path / "arch_state.json"
    arch.write_text(json.dumps({"SPY": {"active_architecture": "parallel"}}), encoding="utf-8")
    before = arch.read_text(encoding="utf-8")
    p = _minimal_op_payload(alert=_valid_alert())
    cfg = NotificationDeliveryConfig(True, False, "", False, False)
    process_notification_deliveries(tmp_path, "1c", "SPY", p, config=cfg)
    assert arch.read_text(encoding="utf-8") == before


def test_governance_visibility_reads_notification_records(tmp_path: Path, monkeypatch):
    from tests.test_operational_policy import _minimal_governed_files_for_panel

    monkeypatch.delenv("ED_NOTIFICATION_WEBHOOK_ENABLED", raising=False)
    monkeypatch.delenv("ED_NOTIFICATION_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("ED_NOTIFICATION_SINK_FILE", "1")
    _minimal_governed_files_for_panel(tmp_path, cascade_ok=True)
    (tmp_path / "arch_state.json").write_text('{"SPY": {"active_architecture": "parallel"}}', encoding="utf-8")
    p = build_governance_panel_payload(
        tmp_path,
        "1c",
        "SPY",
        include_live_drift=False,
        emit_notification_delivery=True,
    )
    assert p["ok"] is True
    assert p.get("notification_delivery_schema_version") == NOTIFICATION_DELIVERY_RECORD_SCHEMA_VERSION
    assert isinstance(p.get("recent_notification_deliveries"), list)
    assert "notification_delivery_log_path" in p
    assert p["production_default_runtime"] == "parallel"


def test_production_default_runtime_unchanged_by_delivery_module():
    import arch_competition.notification_delivery as nd

    src = Path(nd.__file__).read_text(encoding="utf-8")
    assert "production_default_runtime" not in src
    assert "run_base_models_once" not in src


def test_validate_governed_alert_raises():
    with pytest.raises(NotificationDeliveryError):
        validate_governed_alert_for_delivery({"alert_id": "x"})
    with pytest.raises(NotificationDeliveryError):
        validate_alert_routing_payload(None)


def test_webhook_deliver_success_records(tmp_path: Path, monkeypatch):
    p = _minimal_op_payload(alert=_valid_alert())
    cfg = NotificationDeliveryConfig(False, True, "http://example.invalid/webhook", False, False)

    def _ok(url: str, body: dict):
        return (True, None)

    monkeypatch.setattr(
        "arch_competition.notification_delivery.deliver_webhook",
        _ok,
    )
    r = process_notification_deliveries(tmp_path, "1c", "SPY", p, config=cfg)
    assert r["ok"] is True
    recent = read_recent_notification_delivery_records(tmp_path, "1c", "SPY", limit=20)
    assert any(x.get("sink_type") == "webhook" and x.get("delivery_outcome") == "delivered" for x in recent)
