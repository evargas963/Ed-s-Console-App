"""Point 11: 1226 → 1125 must reconcile with a lineage row per removal/addition,
and discovery completeness must fail when an executable fallback is omitted.
"""
from __future__ import annotations

import json
from pathlib import Path

import tools.check_fallback_discovery_completeness as C
import tools.reconcile_no_fallback_inventory_lineage as L

ROOT = Path(__file__).resolve().parent.parent


def test_lineage_reconciles_1226_minus_101_to_1125():
    prior = L._load_prior()
    current = json.loads((ROOT / "reports" / "no_fallback_inventory.json").read_text(encoding="utf-8"))
    report = L.build_lineage(prior, current)
    assert report["prior_count"] == 1226
    assert report["current_count"] == 1125
    assert report["net_delta"] == -101
    assert report["removed"] - report["added"] == 101
    assert report["prior_count"] - report["removed"] + report["added"] == 1125
    assert len(report["removals"]) == report["removed"]
    required = {"old_id", "new_id", "file", "symbol", "reason", "evidence", "classification"}
    for row in report["removals"]:
        assert required <= set(row)
        assert row["old_id"]
        assert row["new_id"] is None
        assert row["classification"] in {"DELETED_FILE", "EXPRESSION_REMOVED_OR_RESHAPED"}
    for row in report["additions"]:
        assert required <= set(row)
        assert row["new_id"]
        assert row["old_id"] is None


def test_lineage_tool_writes_reconciling_artifact():
    assert L.main() == 0
    report = json.loads((ROOT / "reports" / "no_fallback_inventory_lineage_1226_to_1125.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "RECONCILED"
    assert len(report["removals"]) == report["removed"]
    assert report["removed"] - report["added"] == 101


def test_planted_executable_fallback_is_discovered():
    hits = C.prove_planted_fallback_is_discovered(C.PLANTED_FALLBACK_SRC)
    assert hits and hits[0]["pattern"] == C.PLANTED_PATTERN


def test_omitted_executable_fallback_fails_completeness_gate():
    C.prove_omitted_executable_fallback_fails(C.PLANTED_FALLBACK_SRC)
    decoy = C.discover("unrelated.py", "def ok(x):\n    return x\n")
    missing = C.completeness_ok(decoy, [(C.PLANTED_REL, C.PLANTED_PATTERN)])
    assert missing == [f"{C.PLANTED_REL}:{C.PLANTED_PATTERN}"]


def test_completeness_module_main_exits_zero():
    assert C.main() == 0
