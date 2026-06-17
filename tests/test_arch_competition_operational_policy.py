"""operational_policy manifest horizon cross-check (Finding CC)."""

from __future__ import annotations

from pathlib import Path

from arch_competition.operational_policy import build_operational_policy_payload
from tests.test_operational_policy import _manifest_and_promotion


def test_manifest_missing_ml_horizon_slug_freezes_promotion():
    ev, pr = _manifest_and_promotion()
    ev.pop("ml_horizon_slug", None)
    out = build_operational_policy_payload(
        model_dir=Path("/tmp"),
        ml_horizon_slug="1c",
        ticker="SPY",
        live_drift_monitoring=None,
        evaluation_manifest=ev,
        promotion_record=pr,
        recent_audit_records=[],
    )
    ops = out["operational_policy_state"]
    assert ops["system_untrusted"] is True
    assert ops["promotion_frozen"] is True
    codes = [r["code"] for r in ops["active_policy_reasons"]]
    assert "MANIFEST_HORIZON_MISSING" in codes
    alert_codes = [a["reason_code"] for a in out["alert_routing"]["alerts"]]
    assert "MANIFEST_HORIZON_MISSING" in alert_codes
