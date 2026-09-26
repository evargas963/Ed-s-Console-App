"""Governed notification delivery: downstream of operational_policy / alert_routing only."""
from __future__ import annotations

from pathlib import Path






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


















def test_production_default_runtime_unchanged_by_delivery_module():
    import arch_competition.notification_delivery as nd

    src = Path(nd.__file__).read_text(encoding="utf-8")
    assert "production_default_runtime" not in src
    assert "run_unified_stack_ml_once" not in src




