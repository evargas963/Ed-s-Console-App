"""Adversarial — UNIVERSAL_BYPASS_REGISTER reconciliation integrity."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

VALID_STATES = frozenset(
    {
        "open",
        "partially_mitigated",
        "closed_by_runtime_gate",
        "closed_by_adversarial_test",
        "classified_non_production",
        "still_unproven",
    }
)


def _reconciled_bypass_register() -> dict:
    spec = importlib.util.spec_from_file_location(
        "phase3c_builder", REPO / "tools" / "_build_institutional_audit_phase3c.py"
    )
    phase3c = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(phase3c)
    phase2 = phase3c._load_phase2()
    reg = phase2.build_universal_bypass_register(phase2._load_phase1_register())
    return phase3c.reconcile_bypass_register(reg)


def test_bypass_register_has_reconciliation_summary():
    data = _reconciled_bypass_register()
    recon = data["reconciliation"]
    assert recon["bypass_paths_total"] > 0
    counted = (
        int(recon["open"])
        + int(recon["partially_mitigated"])
        + int(recon["closed_by_runtime_gate"])
        + int(recon["closed_by_adversarial_test"])
        + int(recon["classified_non_production"])
        + int(recon["still_unproven"])
    )
    assert counted == recon["bypass_paths_total"]


def test_closed_bypasses_have_evidence():
    data = _reconciled_bypass_register()
    assert data["entries"], "an empty register would pass this loop vacuously"
    for entry in data["entries"]:
        for bp in entry.get("bypass_paths") or []:
            state = bp["reconciliation_state"]
            assert state in VALID_STATES
            if state in ("closed_by_runtime_gate", "closed_by_adversarial_test"):
                assert bp.get("evidence") or bp.get("evidence_test"), (
                    f"closed bypass without evidence: {entry.get('control_id')} {bp.get('path')}"
                )


def test_i28_wrong_price_bypasses_reconciled_closed():
    data = _reconciled_bypass_register()
    i28 = next(e for e in data["entries"] if e["control_id"] == "I-28")
    closed = {
        bp["path"]: bp.get("reconciliation_state")
        for bp in i28.get("bypass_paths") or []
        if "wrong but finite price" in bp["path"]
        or "R-005 no_valid_expiry" in bp["path"]
    }
    assert closed.get("wrong but finite price (e.g. SPY 0.01 or 50000)") == "closed_by_runtime_gate"
    assert closed.get("R-005 no_valid_expiry synthetic bundle without live quotes") in (
        "closed_by_runtime_gate",
        "partially_mitigated",
    )


def test_summary_not_stale_29_open_only():
    data = _reconciled_bypass_register()
    recon = data.get("reconciliation") or {}
    assert "bypasses_open" in recon
    assert recon["bypasses_open"] < recon["bypass_paths_total"]
