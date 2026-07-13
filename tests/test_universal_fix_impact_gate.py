"""UNIVERSAL_FIX_IMPACT_GATE_V1 — adversarial mutation tests (audit mutations A–O)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_universal_fix_impact_gate import (  # noqa: E402
    FC_CONSUMER,
    FC_HORIZON,
    FC_INVENTORY,
    FC_MANIFEST_MISSING,
    FC_NOT_PROVEN,
    FC_REPRESENTATIVE,
    FC_TICKER,
    check_manifest_for_changes,
    check_manifest_schema,
    run_static_checks,
    scan_conditional_universality_violations,
)
from tools.check_universal_ticker_lock import (  # noqa: E402
    check_packet_text,
    scan_python_source_for_ticker_literals,
)


def _manifest(**overrides) -> dict:
    base = {
        "change_id": "test-change",
        "claimed_scope": "SCOPED_AND_HONEST",
        "root_cause_artifact": "signals.py:100",
        "affected_production_paths": ["signals.py"],
        "connected_consumers": {
            "signals.py": [
                "prediction_engine.py",
                "server.py",
                "call_engine.py",
                "live_decision_bundle.py",
            ]
        },
        "ticker_classes": ["all_tickers"],
        "horizons": ["1c", "5c", "15c", "60c"],
        "runtime_classes": ["full"],
        "proof_matrix": {"unit": "tests/test_universal_fix_impact_gate.py"},
        "recurrence_guard": "tests/test_universal_fix_impact_gate.py",
        "lanes_not_closed": ["CARD_FIDELITY_OVERALL"],
    }
    base.update(overrides)
    return base


def test_mutation_a_spy_only_branch_fails_ticker_scan():
    src = (
        "def score(ticker, x):\n"
        "    if ticker == 'SPY':\n"
        "        return x * 2\n"
        "    return x\n"
    )
    errs = scan_python_source_for_ticker_literals(src, "signals.py", allowlist={})
    assert errs and "SPY" in errs[0]
    errs2 = scan_conditional_universality_violations(src, "signals.py")
    assert any(FC_TICKER in e for e in errs2)


def test_mutation_b_open_items_parent_inflation_fails():
    text = "CARD_FIDELITY_OVERALL = CLOSED_WITH_EVIDENCE\n"
    errs = check_packet_text(text, "OPEN_ITEMS.md")
    assert any("CARD_FIDELITY_OVERALL" in e for e in errs)


def test_mutation_c_horizon_only_branch_fails():
    src = (
        "def fuse(horizon_slug, p):\n"
        "    if horizon_slug == '1c':\n"
        "        return p\n"
        "    return p\n"
    )
    errs = scan_conditional_universality_violations(src, "ml_horizon.py")
    assert any(FC_HORIZON in e for e in errs)


def test_mutation_d_manifest_missing_on_material_change():
    errs = check_manifest_for_changes(["signals.py"])
    assert any(FC_MANIFEST_MISSING in e for e in errs)


def test_mutation_f_consumer_omission_when_manifest_present(tmp_path, monkeypatch):
    manifest_path = tmp_path / "governance" / "universal_fix_impact_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    m = _manifest(connected_consumers={"signals.py": ["prediction_engine.py"]})
    manifest_path.write_text(json.dumps(m), encoding="utf-8")
    import tools.check_universal_fix_impact_gate as gate

    monkeypatch.setattr(gate, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    errs = gate.check_manifest_for_changes(["signals.py"], root=tmp_path)
    assert any(FC_CONSUMER in e for e in errs)


def test_mutation_h_representative_inflated_fails():
    m = _manifest(
        claimed_scope="UNIVERSAL_BEHAVIOR_PROVEN",
        proof_matrix={},
        representative_only_limitations="SPY only",
    )
    errs = check_manifest_schema(m)
    assert any(FC_REPRESENTATIVE in e for e in errs)


def test_mutation_i_closed_with_not_proven_same_line(tmp_path, monkeypatch):
    import tools.check_universal_fix_impact_gate as gate

    items = tmp_path / "OPEN_ITEMS.md"
    items.write_text(
        "ML_PIPE_ITEM_4 = CLOSED_WITH_EVIDENCE HISTORICAL_REPLAY = NOT_PROVEN\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "CONTROL_RECORDS", ("OPEN_ITEMS.md",))
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    errs = gate.check_control_record_closures(tmp_path)
    assert any(FC_NOT_PROVEN in e for e in errs)


def test_mutation_j_parent_closed_without_packet():
    text = "CARD_FIDELITY_OVERALL = PROVEN\n"
    errs = check_packet_text(text, "OPEN_ITEMS.md")
    assert any("CARD_FIDELITY_OVERALL" in e for e in errs)


def test_mutation_k_inventory_drift_detected(tmp_path, monkeypatch):
    import tools.build_universal_repository_inventory as builder
    import tools.check_universal_fix_impact_gate as gate

    inv_path = tmp_path / "governance" / "artifacts" / "universal_repository_inventory.json"
    inv_path.parent.mkdir(parents=True)
    doc = builder.build_inventory()
    doc["routes"] = []
    inv_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    monkeypatch.setattr(gate, "INVENTORY_PATH", inv_path)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    errs = gate.check_inventory_freshness(tmp_path)
    assert any(FC_INVENTORY in e for e in errs)


def test_mutation_l_doc_universal_without_packet():
    text = "# Claim\nUniversal closure proven repo-wide.\n"
    errs = check_packet_text(text, "governance/fixture.md")
    assert errs


def test_scoped_fix_manifest_schema_passes():
    m = _manifest(
        claimed_scope="SCOPED_AND_HONEST",
        representative_only_limitations="calibration tooling only",
    )
    assert check_manifest_schema(m) == []


def test_gate_wired_in_repo_wide_static():
    from tools import check_fix_everything_we_touch as cfe

    assert "check_universal_fix_impact_gate" in cfe._REPO_WIDE_STATIC_CHECK_FUNCS


def test_run_static_checks_passes_on_clean_main():
    assert run_static_checks() == []
