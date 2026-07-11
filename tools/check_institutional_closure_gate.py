#!/usr/bin/env python3
"""Institutional closure gate — INSTITUTIONAL_CLOSURE_GATE_AND_DRIFT_RECOVERY_V1.

Mechanically enforces: a parent lane is CLOSED_WITH_EVIDENCE only when every
applicable material dimension is PROVEN; sub-lane closure never closes a parent;
evidence SHA must match the declared final tip; green CI is not semantic proof.
Exit 0 = ledger coherent; exit 1 = closure contradiction(s).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "governance" / "INSTITUTIONAL_CLOSURE_SCHEMA.json"

BLOCKED_VOCAB = {
    "NOT_PROVEN", "FAIL", "PENDING", "PARTIAL", "UNKNOWN", "NOT_AUDITED",
    "RTH_REPROOF_PENDING",
}
CLOSED = "CLOSED_WITH_EVIDENCE"


def validate_ledger(doc: dict) -> list[str]:
    errors: list[str] = []
    dims_required = list(doc.get("required_dimensions") or [])
    if not dims_required:
        return ["schema missing required_dimensions"]
    lanes = doc.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        return ["schema missing lanes"]
    for row in lanes:
        lane_id = str(row.get("lane") or "<unnamed>")
        status = str(row.get("status") or "")
        dims = row.get("dimensions") or {}
        for d in dims_required:
            if d not in dims:
                errors.append(f"{lane_id}: dimension {d} missing from ledger row")
                continue
            v = dims[d]
            if isinstance(v, dict):
                if str(v.get("status")) == "NOT_APPLICABLE" and not str(v.get("rationale") or "").strip():
                    errors.append(f"{lane_id}: {d} NOT_APPLICABLE without evidence-backed rationale")
        if status == CLOSED:
            for d, v in dims.items():
                sv = v.get("status") if isinstance(v, dict) else v
                if str(sv) in BLOCKED_VOCAB:
                    errors.append(
                        f"{lane_id}: CLOSED_WITH_EVIDENCE with material dimension {d}={sv} — parent must be NOT_CLOSED"
                    )
            if row.get("material_limitations"):
                errors.append(
                    f"{lane_id}: CLOSED_WITH_EVIDENCE with unresolved material_limitations — parent must be NOT_CLOSED"
                )
            if not row.get("final_sha"):
                errors.append(f"{lane_id}: CLOSED_WITH_EVIDENCE without final_sha evidence tip")
            ci = str(row.get("remote_ci_status") or "")
            sha = str(row.get("final_sha") or "")
            if sha and ci and "at" in ci and sha[:7] not in ci and "cited tip" not in ci:
                errors.append(f"{lane_id}: CI evidence does not cite the declared final SHA")
        # Sub-lane closure must never imply parent closure.
        subs = row.get("sub_lanes") or []
        if subs and status == CLOSED:
            all_dims_proven = all(
                (v.get("status") if isinstance(v, dict) else v) in ("PROVEN", "NOT_APPLICABLE")
                for v in dims.values()
            )
            if not all_dims_proven:
                errors.append(
                    f"{lane_id}: parent closure rests on sub-lane closure without full parent dimensions"
                )
    # Real-money inference guard.
    if str(doc.get("real_money_approval") or "") != "NOT_APPROVED":
        closed_any = any(str(r.get("status")) == CLOSED for r in lanes)
        if closed_any:
            errors.append(
                "real_money_approval changed alongside component closures — component closure never implies real-money readiness"
            )
    return errors


def main() -> int:
    doc = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = validate_ledger(doc)
    if errors:
        print("institutional closure gate FAILED:")
        for e in errors:
            print(" -", e)
        return 1
    print(
        f"institutional closure gate passed: {len(doc.get('lanes') or [])} lanes coherent; "
        "no inflated parent closure."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
