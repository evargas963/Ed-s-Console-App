#!/usr/bin/env python3
"""
Static compliance: governed policy/calibration paths must read fusion-derived snapshot
columns (fused_move_prob_*, fused_dir_up_prob_*), not legacy XGB movement heads.

batch_backfill_movement_predictions_v1.py may still persist pred_* for legacy/features —
that is not policy authority.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml_horizon import ML_HORIZON_SLUGS


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    violations: list[str] = []
    signals_txt = _read(ROOT / "signals.py")
    if "model_prob_up=None" in signals_txt or "model_prob_down=None" in signals_txt:
        violations.append("signals.py still passes literal None model_prob_* to monte_carlo.simulate")

    policy_authority_files = [
        ROOT / "tools" / "run_phase8_calibration_global_v1.py",
        ROOT / "tools" / "legacy" / "horizon_7" / "run_phase9_policy_remediation_v1.py",
        ROOT / "tools" / "legacy" / "horizon_7" / "run_phase9_decision_policy_v1.py",
        ROOT / "tools" / "run_phase10_reliability_enforcement_v1.py",
        ROOT / "tools" / "legacy" / "horizon_7" / "run_phase11_monitoring_drift_live_readiness_v1.py",
        ROOT / "tools" / "legacy" / "horizon_7" / "enforce_universal_ticker_readiness_v1.py",
        ROOT / "tools" / "legacy" / "horizon_7" / "validate_movement_prediction_coverage_v1.py",
        ROOT / "calibration" / "eval_movement_targets_phase_style_v1.py",
    ]
    for fp in policy_authority_files:
        if not fp.is_file():
            violations.append(f"missing policy file {fp.relative_to(ROOT)}")
            continue
        txt = _read(fp)
        if "pred_move_prob_" in txt:
            violations.append(f"{fp.relative_to(ROOT)} references pred_move_prob_* (legacy XGB policy substrate)")
        if "pred_dir_up_prob_" in txt:
            violations.append(f"{fp.relative_to(ROOT)} references pred_dir_up_prob_* (legacy XGB policy substrate)")

    _policy_src = "fusion_snapshot_columns" if not violations else "violation"
    horizon_matrix = {
        hz: {
            "governed": hz in ML_HORIZON_SLUGS,
            "policy_input_substrate": _policy_src,
        }
        for hz in ML_HORIZON_SLUGS
    }

    out = {
        "governed_horizons": list(ML_HORIZON_SLUGS),
        "violations": violations,
        "verdict": "PASS" if not violations else "FAIL",
        "horizon_policy_substrate": horizon_matrix,
        "note": "Live signals persist fused_* per horizon (base → MC → fusion). Legacy pred_* may exist for features.",
    }
    outp = ROOT / "data" / "governed_stack_policy_compliance_v1.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(outp), "verdict": out["verdict"], "n_violations": len(violations)}, indent=2))
    return 0 if not violations else 3


if __name__ == "__main__":
    raise SystemExit(main())
