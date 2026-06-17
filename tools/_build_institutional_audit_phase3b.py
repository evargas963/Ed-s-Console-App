"""Build Institutional Audit Phase 3B — runtime enforcement evidence.

Run after Phase 3A preload + Phase 3B code:
  python -m pytest tests/adversarial/ -q
  python tools/_build_institutional_audit_phase2.py
  python tools/_build_institutional_audit_phase3b.py
  python tools/_build_institutional_audit_phase3.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ART = REPO / "governance" / "artifacts"
TODAY = date.today().isoformat()
DB_PATH = REPO / "data" / "ed_console.db"


def _run_pytest(path: str) -> dict:
    cmd = [sys.executable, "-m", "pytest", path, "-q"]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    tail = (proc.stdout or proc.stderr or "").strip().splitlines()
    summary = tail[-1] if tail else ""
    return {"exit_code": proc.returncode, "summary": summary, "command": " ".join(cmd)}


def _seed_gate_verified_production_row(db_path: Path) -> dict:
    """One row via production persist API when table empty — audit seed only."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import sqlite3

    from decision_record import ensure_production_decision_schema
    from live_decision_bundle import persist_stamped_decision, stamp_decision_bundle
    from release_object import initialize_release_at_startup

    os.environ.setdefault("ED_BUILD_GENERATION", "phase3b_audit_seed")
    initialize_release_at_startup(force=True)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_production_decision_schema(conn)
        n = conn.execute("SELECT COUNT(*) FROM production_decision_records").fetchone()[0]
    finally:
        conn.close()
    if int(n) > 0:
        return {"seeded": False, "reason": "production_decision_records already populated"}

    ms = {
        "ticker": "SPY",
        "spot": 500.0,
        "call_signal": "wait",
        "call_conviction": "low",
        "dominant_dir": "flat",
        "mhap_rows": [{"horizon": "1c", "signal": "wait"}],
        "fusion_by_horizon": {"1c": {"p_up": 0.33}},
        "validation_summary": "phase3b_audit_seed",
    }
    stamp_decision_bundle(ms, route="audit.phase3b_gate_verified")
    did = persist_stamped_decision(ms, route="audit.phase3b_gate_verified", db_path=db_path)
    return {"seeded": bool(did), "decision_id": did, "route": "audit.phase3b_gate_verified"}


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    adv = _run_pytest("tests/adversarial/")
    seed = _seed_gate_verified_production_row(DB_PATH) if DB_PATH.parent.exists() or True else {}

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "phase2_builder", REPO / "tools" / "_build_institutional_audit_phase2.py"
    )
    phase2 = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(phase2)
    blind = phase2.run_blind_reconstruction_test()
    (ART / "BLIND_RECONSTRUCTION_TEST_RESULT.json").write_text(
        json.dumps(blind, indent=2) + "\n", encoding="utf-8"
    )

    evidence = {
        "schema_version": 1,
        "artifact": "governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3B_EVIDENCE.json",
        "generated": TODAY,
        "phase": "3B",
        "runtime_enforcement": {
            "validation_gate_module": "trade_impacting_gate.py",
            "override_registry_module": "override_registry.py",
            "wired_paths": [
                "live_decision_bundle.stamp_decision_bundle",
                "live_decision_bundle.persist_stamped_decision",
                "server._finalize_production_decision",
                "server._tier_c_analytics_json_response",
                "server._fetch_state.no_valid_expiry",
                "signals._compute_signals_impl pred_override",
            ],
        },
        "adversarial_pytest": adv,
        "audit_seed": seed,
        "blind_reconstruction_verdict": blind.get("verdict"),
        "routes_addressed": {
            "R-005": "synthetic_non_production quarantine + no decision_id + no persist",
            "R-010": "revalidate_cached_decision on Tier C cache serve",
            "R-017": "append_override_record before override affects canonical",
        },
        "routes_still_unproven": [
            "R-011 debug prediction surface",
            "R-027/R-033/R-034 per DECISION_PATH_REGISTRY.json",
        ],
        "maturity_changes_proposed": [],
        "maturity_changes_rejected": [
            "I-28 L3+ — wrong-price quarantine wired but no live DB adversarial PASS bundle",
            "I-29 L3+ — gate wired on listed paths; route universality not fully proven",
            "I-31 L3+ until blind PASS on production traffic (audit seed alone insufficient)",
            "Any L5 claim",
        ],
        "remaining_gaps": [
            "branch protection not proven in-repo",
            "CI required checks not proven",
            "--no-verify bypasses local pre-commit",
            "full route inventory walk not complete",
        ],
    }

    (ART / "INSTITUTIONAL_AUDIT_PHASE3B_EVIDENCE.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"wrote Phase 3B evidence adv_exit={adv.get('exit_code')} "
        f"seed={seed.get('seeded')} blind={blind.get('verdict')}"
    )
    return 0 if adv.get("exit_code") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
