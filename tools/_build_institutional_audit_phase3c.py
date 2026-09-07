"""Build Institutional Audit Phase 3C — route inventory closure + bypass reconciliation.

Run:
  python -m pytest tests/adversarial/ -q
  python tools/_build_institutional_audit_phase2.py
  python tools/_build_institutional_audit_phase3b.py
  python tools/_build_institutional_audit_phase3c.py
  python tools/_build_institutional_audit_phase3.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ART = REPO / "reports" / "artifacts"
TODAY = date.today().isoformat()
DB_PATH = REPO / "data" / "ed_console.db"


def _load_phase2():
    spec = importlib.util.spec_from_file_location(
        "phase2_builder", REPO / "tools" / "_build_institutional_audit_phase2.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _run_pytest(path: str) -> dict:
    cmd = [sys.executable, "-m", "pytest", path, "-q"]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    tail = (proc.stdout or proc.stderr or "").strip().splitlines()
    return {"exit_code": proc.returncode, "summary": tail[-1] if tail else "", "command": " ".join(cmd)}


def _reconcile_bypass_path(path: str, control_id: str) -> tuple[str, str | None]:
    """Return (reconciliation_state, evidence)."""
    p = path.lower()
    if "wrong but finite price" in path:
        return "closed_by_runtime_gate", "tests/adversarial/test_wrong_price_quarantine.py"
    if "r-005 no_valid_expiry" in p or "no_valid_expiry synthetic" in p:
        return "closed_by_runtime_gate", "tests/adversarial/test_route_universality.py"
    if "stale quote under ttl" in p or "stale tier c" in p:
        return "partially_mitigated", "tests/adversarial/test_stale_cache_revalidation.py"
    if "malformed option chain" in p:
        return "partially_mitigated", "tests/adversarial/test_route_universality.py"
    if "no get /api/decision" in p:
        return "closed_by_adversarial_test", "tests/decision_reconstruction/test_immutable_decision_id.py"
    if "decision_generation_id in-process only" in p:
        return "partially_mitigated", "decision_record.production_like_decision_emission"
    if "post /api/prediction/override" in p and control_id in ("I-30", "I-29"):
        return "closed_by_runtime_gate", "tests/adversarial/test_override_registry.py"
    if "manual copy to models/active" in p:
        return "still_unproven", None
    if "git commit --no-verify" in p:
        return "open", None
    if "manual db write" in p:
        return "open", None
    if "runtime ed_" in p and "override" in p:
        return "open", None
    if "disabled or skipped daily_health" in p:
        return "open", None
    if "models/fusion run before risk" in p:
        return "still_unproven", None
    return "open", None


def reconcile_bypass_register(register: dict) -> dict:
    counts = {
        "open": 0,
        "partially_mitigated": 0,
        "closed_by_runtime_gate": 0,
        "closed_by_adversarial_test": 0,
        "classified_non_production": 0,
        "still_unproven": 0,
    }
    total = 0
    for entry in register.get("entries") or []:
        cid = entry.get("control_id", "")
        implemented = entry.get("adversarial_tests_implemented") or []
        for bp in entry.get("bypass_paths") or []:
            state, evidence = _reconcile_bypass_path(str(bp.get("path", "")), cid)
            if state == "open" and implemented:
                for test in implemented:
                    if test and test.split("::")[0] in str(bp.get("path", "")):
                        state = "closed_by_adversarial_test"
                        evidence = test
                        break
            bp["reconciliation_state"] = state
            if evidence:
                bp["evidence"] = evidence
            counts[state] = counts.get(state, 0) + 1
            total += 1
        if cid == "I-28":
            entry["adversarial_tests_implemented"] = [
                "tests/adversarial/test_wrong_price_quarantine.py",
                "tests/adversarial/test_stale_cache_revalidation.py",
                "tests/adversarial/test_route_universality.py",
            ]

    register["reconciliation"] = {
        "bypass_paths_total": total,
        "bypasses_open": counts["open"],
        "bypasses_partially_mitigated": counts["partially_mitigated"],
        "bypasses_closed_by_runtime_gate": counts["closed_by_runtime_gate"],
        "bypasses_closed_by_adversarial_test": counts["closed_by_adversarial_test"],
        "bypasses_classified_non_production": counts["classified_non_production"],
        "bypasses_still_unproven": counts["still_unproven"],
        **counts,
    }
    register["summary"]["controls_without_bypass_detection_test"] = counts["open"] + counts["still_unproven"]
    register["summary"]["bypass_reconciliation_phase"] = "3C"
    register["generated"] = TODAY
    return register


def reconcile_decision_path_registry(registry: dict) -> dict:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from trade_impacting_gate import ROUTE_INVENTORY_EVIDENCE

    summary = {
        "routes_proven_gated": 0,
        "routes_blocked": 0,
        "routes_classified_non_production": 0,
        "routes_still_unproven": 0,
    }
    routes_with_gaps: list[str] = []

    for row in registry.get("routes") or []:
        rid = row.get("route_id", "")
        evidence = ROUTE_INVENTORY_EVIDENCE.get(rid)
        if evidence:
            state = str(evidence["enforcement_state"])
            row["enforcement_state"] = state
            row["source_file"] = evidence.get("source_file")
            row["source_function"] = evidence.get("source_function")
            row["evidence_tests"] = evidence.get("evidence_tests")
            row["runtime_gate"] = evidence.get("runtime_gate")
            if state == "classified_non_production":
                row["trade_impacting"] = False
                row["gaps"] = []
            elif state in ("proven_gated", "blocked"):
                row["gaps"] = []
                row["passes_mandatory_controls"] = state == "proven_gated"
        elif row.get("passes_mandatory_controls"):
            row["enforcement_state"] = "proven_gated"
        else:
            row["enforcement_state"] = "still_unproven_with_reason"
            routes_with_gaps.append(rid)

        state = row.get("enforcement_state", "")
        if state == "proven_gated":
            summary["routes_proven_gated"] += 1
        elif state == "blocked":
            summary["routes_blocked"] += 1
        elif state == "classified_non_production":
            summary["routes_classified_non_production"] += 1
        elif state == "still_unproven_with_reason":
            summary["routes_still_unproven"] += 1

    registry["route_inventory_summary"] = {
        "routes_total": len(registry.get("routes") or []),
        **summary,
    }
    registry["route_universality"] = {
        "proven": False,
        "label": "partial runtime enforcement — priority routes only (Phase 3B/3C)",
        "mandatory_controls": registry.get("route_universality", {}).get("mandatory_controls", []),
        "trade_impacting_routes": sum(
            1 for r in registry.get("routes") or [] if r.get("trade_impacting")
        ),
        "routes_with_gaps": routes_with_gaps,
        "conclusion": (
            "NOT universal route enforcement. R-005 blocked; R-010/R-017 proven gated; "
            "R-011/R-027/R-033/R-034 classified non-production. "
            "Branch protection and full route walk remain Phase 3D."
        ),
    }
    registry["generated"] = TODAY
    return registry


def _production_like_proof() -> dict:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from decision_record import production_like_decision_emission

    db = DB_PATH.parent / "_phase3c_prod_like.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.is_file():
        db.unlink()
    return production_like_decision_emission(db)


def _blind_reconstruction_with_source(phase2) -> dict:
    blind = phase2.run_blind_reconstruction_test()
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import sqlite3

    from decision_record import ensure_production_decision_schema

    source = "unknown"
    sample_route = None
    if DB_PATH.is_file():
        conn = sqlite3.connect(str(DB_PATH))
        try:
            ensure_production_decision_schema(conn)
            row = conn.execute(
                "SELECT route FROM production_decision_records ORDER BY decision_ts_utc DESC LIMIT 1"
            ).fetchone()
            if row:
                sample_route = row[0]
                if str(sample_route).startswith("audit."):
                    source = "audit_seed"
                elif str(sample_route) == "server._fetch_state":
                    source = "production_like_or_live"
                else:
                    source = "other"
        finally:
            conn.close()
    blind["reconstruction_source"] = source
    blind["sample_route"] = sample_route
    blind["generated"] = TODAY
    return blind


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    phase2 = _load_phase2()
    adv = _run_pytest("tests/adversarial/")

    dpr = reconcile_decision_path_registry(phase2.build_decision_path_registry())
    (ART / "DECISION_PATH_REGISTRY.json").write_text(
        json.dumps(dpr, indent=2) + "\n", encoding="utf-8"
    )

    bypass = reconcile_bypass_register(phase2.build_universal_bypass_register(phase2._load_phase1_register()))
    (ART / "UNIVERSAL_BYPASS_REGISTER.json").write_text(
        json.dumps(bypass, indent=2) + "\n", encoding="utf-8"
    )

    prod_like = _production_like_proof()
    blind = _blind_reconstruction_with_source(phase2)
    (ART / "BLIND_RECONSTRUCTION_TEST_RESULT.json").write_text(
        json.dumps(blind, indent=2) + "\n", encoding="utf-8"
    )

    inv = dpr.get("route_inventory_summary") or {}
    recon = bypass.get("reconciliation") or {}
    adv_summary = str(adv.get("summary") or "")
    adv_count = 0
    if " passed" in adv_summary:
        adv_count = int(adv_summary.split(" passed")[0].strip().split()[-1])

    evidence = {
        "schema_version": 1,
        "artifact": "reports/artifacts/INSTITUTIONAL_AUDIT_PHASE3C_EVIDENCE.json",
        "generated": TODAY,
        "phase": "3C",
        "label": "route inventory closure and bypass register reconciliation",
        "routes_total": inv.get("routes_total"),
        "routes_proven_gated": inv.get("routes_proven_gated"),
        "routes_blocked": inv.get("routes_blocked"),
        "routes_classified_non_production": inv.get("routes_classified_non_production"),
        "routes_still_unproven": inv.get("routes_still_unproven"),
        "bypasses_total": recon.get("bypass_paths_total"),
        "bypasses_closed": (
            int(recon.get("closed_by_runtime_gate", 0))
            + int(recon.get("closed_by_adversarial_test", 0))
        ),
        "bypasses_partially_mitigated": recon.get("partially_mitigated"),
        "bypasses_open": recon.get("open"),
        "adversarial_tests_count": adv_count,
        "adversarial_pytest": adv,
        "live_decision_record_proof": {
            "source": prod_like.get("source"),
            "decision_id": prod_like.get("decision_id"),
            "release_id": prod_like.get("release_id"),
            "reconstruction_complete": prod_like.get("reconstruction_complete"),
            "limitation": "Post-pipeline ms_dict harness — not live Schwab _fetch_state traffic",
        },
        "blind_reconstruction_source": blind.get("reconstruction_source"),
        "blind_reconstruction_verdict": blind.get("verdict"),
        "maturity_changes_proposed": [],
        "maturity_changes_rejected": [
            "Universal route enforcement — partial only",
            "I-31 L3+ — production_like harness exists; live production traffic not proven",
            "Any L5 claim",
        ],
        "remaining_gaps": [
            "Live _fetch_state production traffic blind PASS not proven",
            "Branch protection / CI required checks (Phase 3D)",
            "--no-verify bypasses local pre-commit",
        ],
    }
    (ART / "INSTITUTIONAL_AUDIT_PHASE3C_EVIDENCE.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"wrote Phase 3C adv_exit={adv.get('exit_code')} "
        f"routes_unproven={inv.get('routes_still_unproven')} "
        f"bypasses_open={recon.get('open')} "
        f"prod_like={prod_like.get('reconstruction_complete')}"
    )
    return 0 if adv.get("exit_code") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
