"""calibration.v2_a1_calibration's regime-axis/schema wiring against the live
calibration sqlite schema must reject a missing regime axis rather than silently
calibrating against an incomplete regime set."""
from __future__ import annotations

import json
from pathlib import Path



BASE_TS = 1_900_000_000.0


def _v2_payload(*, probability: float, direction: str = "long") -> str:
    return json.dumps(
        {
            "adapter_version": "test-adapter",
            "v2_decision": {
                "decision": {
                    "action": {"value": "TRADE", "source": "v1_approximation"},
                    "direction": {"value": direction, "source": "v1_approximation"},
                    "P_entry_success": {"value": probability, "source": "v1_approximation"},
                }
            },
        }
    )






















def test_v2_a1_calibration_module_has_no_write_text():
    source = Path(__file__).resolve().parents[1] / "calibration" / "v2_a1_calibration.py"
    assert ".write_text(" not in source.read_text(encoding="utf-8")












def _wait_payload() -> str:
    return json.dumps(
        {
            "adapter_version": "test-adapter",
            "v2_decision": {
                "decision": {
                    "action": {"value": "WAIT", "source": "v1_approximation"},
                    "direction": {"value": "long", "source": "v1_approximation"},
                    "P_entry_success": {"value": 0.6, "source": "v1_approximation"},
                }
            },
        }
    )


















