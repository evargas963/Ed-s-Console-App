"""Stage 1 open-world session/RTH blast-radius sweep locks (Objective D; read-only)."""
from __future__ import annotations

import json
from pathlib import Path

from research.stage1_target_foundation.rth_integrity_audit import audit
from research.stage1_target_foundation.session_blast_radius import sweep

ART = (Path(__file__).resolve().parents[1] / "governance" / "research"
       / "stage1_target_label_foundation" / "session_blast_radius_v1.json")


def test_sweep_is_open_world_and_wellformed():
    art = sweep()
    assert art["schema"] == "STAGE1_SESSION_BLAST_RADIUS"
    assert art["partial_scan"] is False
    cats = set(art["totals"]["by_category"])
    for required in ("STORED_CLOCK_AUTHORITY", "CT_CALENDAR_AUTHORITY",
                     "TS_UTC_ET_AUTHORITY", "EXCHANGE_CONVENTION", "SESSION_REFERENCE"):
        assert required in cats, required
    assert art["totals"]["sites"] > 100


def test_committed_artifact_exists_and_matches_schema():
    assert ART.exists(), "session_blast_radius_v1.json must be committed"
    art = json.loads(ART.read_text(encoding="utf-8"))
    assert art["schema"] == "STAGE1_SESSION_BLAST_RADIUS"
    assert art["partial_scan"] is False
    assert "exclusion_rationale" in art


def test_known_stored_clock_contradiction_sites_are_classified():
    """db.py + audit_model_readiness.py + math_volatility.py stored-clock RTH sites
    must appear as STORED_CLOCK_AUTHORITY production records."""
    art = sweep()
    stored = {
        r["path"] for r in art["records"]
        if r["category"] == "STORED_CLOCK_AUTHORITY" and r["is_production"]
    }
    for f in ("db.py", "audit_model_readiness.py", "math_volatility.py"):
        assert any(p.endswith(f) for p in stored), f"{f} missing from stored-clock sites"


def test_production_sites_marked_do_not_fix():
    art = sweep()
    for r in art["records"]:
        if r["is_production"]:
            assert r["do_not_fix_in_this_mission"] is True


def test_ct_authority_module_is_classified_ct():
    art = sweep()
    ct = {r["path"] for r in art["records"] if r["category"] == "CT_CALENDAR_AUTHORITY"}
    assert any(p.endswith("ct_session.py") for p in ct)


def test_blast_radius_superset_of_targeted_audit():
    """The narrow rth_integrity_audit sites must all be present in the open-world
    stored-clock production inventory (the sweep is a superset)."""
    a = audit()
    art = sweep()
    stored_files = {
        r["path"].split("/")[-1] for r in art["records"]
        if r["category"] == "STORED_CLOCK_AUTHORITY" and r["is_production"]
    }
    for site in a["live_cohort_stored_clock_rth_sites"]:
        fname = site.split(":")[0].split("/")[-1]
        assert fname in stored_files, f"targeted audit site {site} absent from sweep"
