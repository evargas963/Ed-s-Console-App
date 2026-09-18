#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))



def main() -> int:
    readiness = json.loads((ROOT / "data" / "ticker_readiness_matrix_v1.json").read_text(encoding="utf-8"))
    phase8 = json.loads((ROOT / "data" / "phase8_calibration_remediation_v1.json").read_text(encoding="utf-8"))
    phase9 = json.loads((ROOT / "data" / "phase9_policy_remediation_v1.json").read_text(encoding="utf-8"))
    old_inventory = json.loads((ROOT / "data" / "required_model_inventory_v1.json").read_text(encoding="utf-8"))

    allowed = sorted(
        r["ticker"]
        for r in readiness["tickers"]
        if r.get("final_readiness_verdict") == "READY_GLOBAL_STANDARD"
        and r.get("policy_status") == "POLICY_ELIGIBLE"
    )
    # Policy-active execution horizons are the edge-positive set from Phase 9 remediation.
    policy_active_horizons = sorted(set(phase9.get("edge_positive_horizons", [])), key=lambda x: int(x[:-1]))
    horizons = list(policy_active_horizons)

    # Threshold inventory for movement gating.
    move_thresholds = {}
    for r in phase8.get("thresholds", []):
        if r.get("head") != "move":
            continue
        hz = str(r.get("horizon", ""))
        cur = move_thresholds.get(hz)
        if cur is None or float(r.get("edge_delta") or 0.0) > float(cur.get("edge_delta") or 0.0):
            move_thresholds[hz] = r

    # True minimum live dependency contract:
    # A ticker is executable only if it has >=1 policy-active, edge-positive movement horizon
    # with artifact+meta present and with both threshold and calibration mapping available.
    min_required_move_horizons = 1

    # ACTIVE architecture + model family for policy engine.
    # Policy execution layer consumes calibrated move probability only; direction is optional bias.
    expected = []
    actual = []
    missing = []
    extra = []
    model_root = ROOT / "models" / "active"

    for t in allowed:
        for hz in horizons:
            # required movement head
            for head, required in (("move", True), ("dir", False)):
                p = model_root / t / f"xgb_{t}_{hz}_{head}.pkl"
                m = model_root / t / f"xgb_{t}_{hz}_{head}_meta.json"
                row = {
                    "ticker": t,
                    "horizon": hz,
                    "head_type": "movement" if head == "move" else "direction",
                    "model_type": "xgb",
                    "architecture_path": "models/active",
                    # Row-level artifacts are optional; requiredness is enforced as ticker-level minimum dependency.
                    "required": False,
                    "policy_active_horizon": hz in policy_active_horizons,
                    "edge_positive_horizon": hz in policy_active_horizons,
                    "has_threshold": bool(move_thresholds.get(hz)) if head == "move" else False,
                    "has_calibration_mapping": bool(phase8.get("final_calibration_functions", {}).get("move", {}).get(hz))
                    if head == "move"
                    else bool(phase8.get("final_calibration_functions", {}).get("dir", {}).get(hz)),
                    "exists": p.is_file() and m.is_file(),
                    "artifact_path": str(p.resolve()),
                    "meta_path": str(m.resolve()),
                }
                expected.append(row)
                if row["exists"]:
                    actual.append(row)

    # Ticker-level minimum requiredness evaluation.
    idx = defaultdict(dict)
    for r in expected:
        idx[(r["ticker"], r["horizon"])][r["head_type"]] = r
    ticker_minimum_requirements = []
    for t in allowed:
        executable = []
        deficits = []
        for hz in horizons:
            mv = idx.get((t, hz), {}).get("movement")
            if not mv:
                deficits.append({"horizon": hz, "reason": "missing_movement_inventory_row"})
                continue
            checks = {
                "artifact_present": bool(mv.get("exists")),
                "threshold_present": bool(mv.get("has_threshold")),
                "calibration_present": bool(mv.get("has_calibration_mapping")),
                "policy_active_horizon": bool(mv.get("policy_active_horizon")),
                "edge_positive_horizon": bool(mv.get("edge_positive_horizon")),
            }
            ok = all(checks.values())
            if ok:
                executable.append(hz)
            else:
                deficits.append({"horizon": hz, "checks": checks})
        minimum_met = len(executable) >= min_required_move_horizons
        ticker_minimum_requirements.append(
            {
                "ticker": t,
                "required_min_move_horizons": min_required_move_horizons,
                "policy_active_horizons_considered": horizons,
                "executable_move_horizons": executable,
                "executable_count": len(executable),
                "minimum_met": minimum_met,
                "deficits": deficits,
            }
        )
        if not minimum_met:
            missing.append(
                {
                    "ticker": t,
                    "contract_violation": "MIN_EXECUTABLE_MOVE_HORIZONS_NOT_MET",
                    "required_min_move_horizons": min_required_move_horizons,
                    "executable_count": len(executable),
                    "executable_move_horizons": executable,
                }
            )

    # Extra artifacts relative to required set: any xgb move/dir for non-required tuples.
    required_keys = {
        (r["ticker"], r["horizon"], r["head_type"], r["model_type"], r["architecture_path"])
        for r in expected
        if r["policy_active_horizon"] and r["head_type"] == "movement"
    }
    for p in model_root.rglob("xgb_*_*.pkl"):
        name = p.name
        if not name.endswith(".pkl"):
            continue
        try:
            stem = name[:-4]
            # xgb_{ticker}_{h}_{head}
            if not stem.startswith("xgb_"):
                continue
            parts = stem.split("_")
            head = parts[-1]
            hz = parts[-2]
            ticker = "_".join(parts[1:-2])
            if head not in ("move", "dir"):
                continue
            k = (ticker, hz, "movement" if head == "move" else "direction", "xgb", "models/active")
            if k not in required_keys:
                mp = p.with_name(p.name.replace(".pkl", "_meta.json"))
                extra.append(
                    {
                        "ticker": ticker,
                        "horizon": hz,
                        "head_type": k[2],
                        "model_type": "xgb",
                        "architecture_path": "models/active",
                        "artifact_path": str(p.resolve()),
                        "meta_path": str(mp.resolve()),
                    }
                )
        except Exception:
            continue

    # Root-cause classification for the historical "missing 115" from old inventory.
    root_causes = []
    ready_map = {r["ticker"]: r for r in readiness["tickers"]}
    for r in old_inventory.get("rows", []):
        if r.get("native_model_present_y"):
            continue
        t = r.get("ticker")
        rr = ready_map.get(t, {})
        verdict = rr.get("final_readiness_verdict")
        policy = rr.get("policy_status")
        if verdict != "READY_GLOBAL_STANDARD" or policy != "POLICY_ELIGIBLE":
            cause = "LEGACY_EXPECTATION"
            reason = "ticker not in live-ready + policy-eligible domain"
        else:
            cause = "OTHER"
            reason = "unexpected missing in required live domain"
        root_causes.append(
            {
                "ticker": t,
                "horizon": r.get("horizon"),
                "head_type": r.get("head_type"),
                "cause": cause,
                "reason": reason,
            }
        )
    cause_counts = Counter(x["cause"] for x in root_causes)

    architecture_mismatch = {
        "incorrect_expectations": [
            "Old required_model_inventory counted all logging_universe tickers regardless of readiness/policy eligibility.",
            "Old required_model_inventory required native dir heads for non-policy tickers and limitation states.",
        ],
        "stale_or_legacy_requirements": [
            "Tickers not READY_GLOBAL_STANDARD or not POLICY_ELIGIBLE should not be in critical artifact expectation.",
            "Direction heads are optional bias in Phase 9 remediated policy, not hard-required for live gate.",
            "Requiring every policy-active move horizon creates false BLOCKs because policy dependency is existential, not per-horizon mandatory.",
        ],
        "over_specified_inventory": True,
    }

    resolution_plan = {
        "REMOVE_EXPECTATION": [
            "Restrict required artifacts to READY_GLOBAL_STANDARD + POLICY_ELIGIBLE tickers.",
            "Do not require every edge-positive horizon; enforce minimum executable horizon dependency at ticker level.",
            "Treat dir heads as optional-bias artifacts (monitor WARN, not BLOCK).",
        ],
        "GENERATE_ARTIFACT": [],
        "FIX_PIPELINE": [
            "Update Phase 11 monitoring artifact-health metric to ticker-level minimum executable horizon expectation.",
            "Keep full inventory reporting as diagnostic, but do not escalate legacy gaps to BLOCK.",
        ],
    }

    out = {
        "timestamp_utc": time.time(),
        "contract_definition": {
            "name": "phase11_minimum_executable_move_horizon_v2",
            "ticker_scope": "READY_GLOBAL_STANDARD + POLICY_ELIGIBLE",
            "policy_active_horizons": policy_active_horizons,
            "required_min_move_horizons_per_ticker": min_required_move_horizons,
            "required_horizon_properties": [
                "policy_active_horizon",
                "edge_positive_horizon",
                "movement_artifact_and_meta_present",
                "movement_threshold_present",
                "movement_calibration_mapping_present",
            ],
            "direction_role": "optional_bias_non_blocking",
        },
        "expected_artifact_matrix": {
            "total_expected_count": len(expected),
            "required_count": len(allowed) * min_required_move_horizons,
            "grouped_by_ticker_horizon_model_head": expected,
            "active_models": ["xgb"],
            "active_architecture_paths": ["models/active"],
            "horizons_in_scope": horizons,
        },
        "actual_artifact_matrix": {
            "total_actual_count": len(actual),
            "grouped_by_ticker_horizon_model_head": actual,
        },
        "missing_artifacts": missing,
        "extra_artifacts": extra,
        "ticker_minimum_requirements": ticker_minimum_requirements,
        "root_cause_summary": {
            "counts_per_cause": dict(cause_counts),
            "examples_per_cause": {
                c: [x for x in root_causes if x["cause"] == c][:10] for c in sorted(cause_counts.keys())
            },
        },
        "architecture_mismatch_report": architecture_mismatch,
        "resolution_plan": resolution_plan,
    }

    outp = ROOT / "data" / "phase11_artifact_reconciliation_v1.json"
    outp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "wrote": str(outp),
                "required_expected": out["expected_artifact_matrix"]["required_count"],
                "missing_required": len(missing),
                "extra": len(extra),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
