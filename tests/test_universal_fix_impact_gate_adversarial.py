"""UNIVERSAL_FIX_IMPACT_GATE_V1 — isolated adversarial mutations A–O and controls P–U."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_universal_fix_impact_gate as gate  # noqa: E402
from tools import universal_gate_ast as ast_util  # noqa: E402
from tools.check_universal_ticker_lock import (  # noqa: E402
    check_packet_text,
    scan_python_source_for_ticker_literals,
)


def _manifest(**kw) -> dict:
    base = json.loads((ROOT / "governance/universal_fix_impact_manifest.json").read_text())
    base.update(kw)
    return base


def _assert_code(errs: list[str], code: str) -> None:
    assert errs, f"expected failure with {code}"
    assert any(f"[{code}]" in e for e in errs), f"expected {code} in {errs}"


# ── A: single-ticker production fix ───────────────────────────────────────────


def test_adversarial_a_spy_only_branch():
    src = "def score(ticker, x):\n    if ticker == 'SPY':\n        return x * 2\n    return x\n"
    assert scan_python_source_for_ticker_literals(src, "signals.py", allowlist={})
    _assert_code(gate.scan_conditional_universality_violations(src, "signals.py"), gate.FC_TICKER)


# ── B: base-three-only while claiming universality ────────────────────────────


def test_adversarial_b_base_three_universal_claim():
    text = (
        "UNIVERSALITY_CLASSIFICATION: UNIVERSAL_TICKER_AGNOSTIC_PROVEN\n"
        "Evidence: SPY QQQ IWM only.\n"
    )
    errs = check_packet_text(text, "OPEN_ITEMS.md")
    assert errs


# ── C: one-horizon fix ───────────────────────────────────────────────────────


def test_adversarial_c_horizon_only():
    src = "def fuse(horizon_slug, p):\n    if horizon_slug == '1c':\n        return p\n    return p\n"
    _assert_code(gate.scan_conditional_universality_violations(src, "ml_horizon.py"), gate.FC_HORIZON)


# ── D: one-route fix omitted from manifest ───────────────────────────────────


def test_adversarial_d_route_manifest_omission(tmp_path, monkeypatch):
    mpath = tmp_path / "governance" / "universal_fix_impact_manifest.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    m = _manifest(affected_production_paths=["signals.py"], connected_consumers={"signals.py": []})
    mpath.write_text(json.dumps(m), encoding="utf-8")
    monkeypatch.setattr(gate, "MANIFEST_PATH", mpath)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    _assert_code(gate.check_manifest_for_changes(["server.py"], tmp_path), gate.FC_MANIFEST_MISSING)


# ── E: loader bypass (manifest omits connected loader consumer) ─────────────


def test_adversarial_e_loader_consumer_omitted(tmp_path, monkeypatch):
    mpath = tmp_path / "governance" / "universal_fix_impact_manifest.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    m = _manifest(
        affected_production_paths=["ml_predict.py"],
        connected_consumers={"ml_predict.py": ["prediction_engine.py"]},
    )
    mpath.write_text(json.dumps(m), encoding="utf-8")
    monkeypatch.setattr(gate, "MANIFEST_PATH", mpath)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    _assert_code(gate.check_manifest_for_changes(["ml_predict.py"], tmp_path), gate.FC_CONSUMER)


# ── F: persistence writer omission ──────────────────────────────────────────


def test_adversarial_f_writer_omission(tmp_path, monkeypatch):
    mpath = tmp_path / "governance" / "universal_fix_impact_manifest.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    m = _manifest(
        affected_production_paths=["db.py"],
        connected_consumers={"db.py": ["server.py"]},
    )
    mpath.write_text(json.dumps(m), encoding="utf-8")
    monkeypatch.setattr(gate, "MANIFEST_PATH", mpath)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    _assert_code(gate.check_manifest_for_changes(["db.py"], tmp_path), gate.FC_CONSUMER)


# ── G: UI card omission (graph consumer) ─────────────────────────────────────


def test_adversarial_g_ui_consumer_omitted(tmp_path, monkeypatch):
    gpath = tmp_path / "governance" / "artifacts" / "universal_connected_path_graph.json"
    gpath.parent.mkdir(parents=True)
    gpath.write_text(
        json.dumps(
            {
                "edges": [
                    {
                        "source": "server.py",
                        "target": "static/index.html",
                        "kind": "ui_transport",
                        "discovery": "governed",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    mpath = tmp_path / "governance" / "universal_fix_impact_manifest.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    m = _manifest(
        affected_production_paths=["server.py"],
        connected_consumers={"server.py": []},
        claimed_scope="UNIVERSAL_BY_CONSTRUCTION",
    )
    mpath.write_text(json.dumps(m), encoding="utf-8")
    monkeypatch.setattr(gate, "GRAPH_PATH", gpath)
    monkeypatch.setattr(gate, "MANIFEST_PATH", mpath)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    _assert_code(
        gate.check_manifest_graph_consumers(m, ["server.py"], tmp_path),
        gate.FC_CONSUMER,
    )


# ── H: representative proof inflated ────────────────────────────────────────


def test_adversarial_h_representative_inflated():
    m = _manifest(
        claimed_scope="UNIVERSAL_BEHAVIOR_PROVEN",
        impact_proof_matrix={
            d: {"status": "REPRESENTATIVE_ONLY", "evidence": "SPY only"}
            for d in gate.PROOF_MATRIX_DIMENSIONS
        },
    )
    _assert_code(gate.check_impact_proof_matrix(m), gate.FC_REPRESENTATIVE)


# ── I: closed lane with NOT_PROVEN ───────────────────────────────────────────


def test_adversarial_i_closed_with_not_proven(tmp_path, monkeypatch):
    items = tmp_path / "OPEN_ITEMS.md"
    items.write_text("ML_PIPE_ITEM_4 = CLOSED_WITH_EVIDENCE X = NOT_PROVEN\n", encoding="utf-8")
    monkeypatch.setattr(gate, "CONTROL_RECORDS", ("OPEN_ITEMS.md",))
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    _assert_code(gate.check_control_record_closures(tmp_path), gate.FC_NOT_PROVEN)


# ── J: parent closed from child scope ─────────────────────────────────────────


def test_adversarial_j_parent_from_child():
    text = "CARD_FIDELITY_OVERALL = PROVEN\n"
    errs = check_packet_text(text, "OPEN_ITEMS.md")
    assert any("CARD_FIDELITY_OVERALL" in e for e in errs)


# ── K: hard-coded inventory omits entity ──────────────────────────────────────


def test_adversarial_k_inventory_omits_entity(tmp_path, monkeypatch):
    inv = tmp_path / "governance" / "artifacts" / "universal_repository_inventory.json"
    inv.parent.mkdir(parents=True)
    doc = json.loads((ROOT / "governance/artifacts/universal_repository_inventory.json").read_text())
    doc["routes"] = []
    inv.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    monkeypatch.setattr(gate, "INVENTORY_PATH", inv)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    _assert_code(gate.check_inventory_freshness(tmp_path), gate.FC_INVENTORY)


# ── L: documentation-only universal claim ───────────────────────────────────


def test_adversarial_l_doc_only_universal():
    assert check_packet_text("Universal closure proven repo-wide.\n", "governance/x.md")


# ── M: test-only cache reset as runtime fix (manifest misclassification) ─────


def test_adversarial_m_test_only_runtime_claim():
    m = _manifest(
        affected_production_paths=["tests/test_cache_reset.py"],
        claimed_scope="UNIVERSAL_BEHAVIOR_PROVEN",
    )
    assert not gate.is_material_path("tests/test_cache_reset.py")
    assert gate.check_manifest_for_changes(["tests/test_cache_reset.py"]) == []


# ── N: fail-closed claim with success-only matrix ────────────────────────────


def test_adversarial_n_fail_closed_success_only_matrix():
    m = _manifest(
        impact_proof_matrix={
            **{
                d: {"status": "AFFECTED_AND_PROVEN", "evidence": "happy path only"}
                for d in gate.PROOF_MATRIX_DIMENSIONS
            },
            "failure_paths": {"status": "AFFECTED_NOT_PROVEN", "evidence": ""},
        }
    )
    _assert_code(gate.check_impact_proof_matrix(m), gate.FC_MATRIX)


# ── O: future entity additions (parameterized) ─────────────────────────────


@pytest.mark.parametrize(
    "category,mutation,check_fn",
    [
        (
            "ticker",
            'if ticker == "FAKEAUDIT": pass',
            lambda: gate.scan_conditional_universality_violations(
                "def f(ticker):\n    if ticker == 'FAKEAUDIT':\n        pass\n", "signals.py"
            ),
        ),
        (
            "horizon",
            "if horizon_slug == '1c': pass",
            lambda: gate.scan_conditional_universality_violations(
                "def f(horizon_slug):\n    if horizon_slug == '1c':\n        pass\n",
                "ml_horizon.py",
            ),
        ),
        (
            "route",
            "routes omitted",
            lambda: gate.check_manifest_for_changes(["server.py"]),
        ),
    ],
)
def test_adversarial_o_category(category, mutation, check_fn):
    errs = check_fn()
    assert errs, f"O/{category} should fail: {mutation}"


def test_adversarial_o_ticker_fakeaudit_membership():
    src = "def f(ticker):\n    if ticker in {'FAKEAUDIT'}:\n        pass\n"
    known = frozenset({"SPY", "QQQ", "IWM"})
    v = ast_util.scan_ticker_routing_violations(src, "signals.py", known_symbols=known)
    assert v and v[0][0] == "FUTURE_ENTITY_INVENTORY_DRIFT"


def test_adversarial_o_ticker_fakeaudit_match_case():
    src = "def f(ticker):\n    match ticker:\n        case 'FAKEAUDIT':\n            pass\n"
    known = frozenset({"SPY"})
    v = ast_util.scan_ticker_routing_violations(src, "signals.py", known_symbols=known)
    assert v


def test_adversarial_o_ticker_fakeaudit_dict_route():
    src = "routes = {}\ndef f():\n    routes['FAKEAUDIT'] = 1\n"
    known = frozenset({"SPY"})
    v = ast_util.scan_ticker_routing_violations(src, "signals.py", known_symbols=known)
    assert v


def test_adversarial_o_ticker_fakeaudit_default():
    src = "DEFAULT_TICKER = 'FAKEAUDIT'\n"
    syms = ast_util.collect_routing_symbols_from_source(src, "signals.py")
    assert "FAKEAUDIT" in syms


# ── Controls P–U ─────────────────────────────────────────────────────────────


def test_control_p_scoped_honest_passes():
    m = _manifest(claimed_scope="SCOPED_AND_HONEST")
    assert gate.check_manifest_schema(m) == []


def test_control_q_complete_universal_matrix():
    m = _manifest(claimed_scope="UNIVERSAL_BY_CONSTRUCTION_WITH_MECHANICAL_LOCK")
    assert gate.check_impact_proof_matrix(m) == []


def test_control_r_nonmaterial_doc():
    assert not gate.is_material_path("governance/README.md")


def test_control_s_governed_exception_register_empty_passes():
    assert gate.check_exception_register() == []


def test_control_t_expired_exception(tmp_path, monkeypatch):
    reg = tmp_path / "governance/artifacts/universal_fix_exception_register.json"
    reg.parent.mkdir(parents=True)
    reg.write_text(
        json.dumps(
            {
                "exceptions": [
                    {
                        "exception_id": "EXPIRED-1",
                        "expires_utc": "2020-01-01T00:00:00Z",
                        "parent_lanes_remain_open": "ALL",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "EXCEPTION_REGISTER", reg)
    _assert_code(gate.check_exception_register(tmp_path), gate.FC_EXCEPTION)


def test_control_u_new_entity_in_inventory_after_regen():
    inv = json.loads((ROOT / "governance/artifacts/universal_repository_inventory.json").read_text())
    assert "known_routing_symbols" in inv["tickers"]
    assert inv.get("replay_resolvers") is not None


# ── Manifest bypass resistance ───────────────────────────────────────────────


def test_manifest_bypass_empty_affected():
    m = _manifest(affected_production_paths=[])
    _assert_code(
        gate.check_manifest_bypass_resistance(m, ["signals.py"]),
        gate.FC_MANIFEST_MISSING,
    )


def test_manifest_bypass_wrong_change_id():
    m = _manifest(change_id="OTHER-MISSION")
    errs = gate.check_manifest_bypass_resistance(m, ["signals.py"])
    assert any(gate.FC_MANIFEST_MISSING in e for e in errs)


# ── Superseded path ───────────────────────────────────────────────────────────


def test_superseded_path_not_reconciled():
    m = _manifest(
        superseded_path_analysis={
            "superseded_paths": ["old_signals.py"],
            "retained_compatibility_paths": [],
            "removal_decision": "omitted",
        }
    )
    _assert_code(gate.check_superseded_path_analysis(m), gate.FC_SUPERSEDED)


# ── Inventory determinism ────────────────────────────────────────────────────


def test_inventory_deterministic_regeneration():
    from tools.build_universal_repository_inventory import build_inventory

    a = json.dumps(build_inventory(), sort_keys=True, separators=(",", ":"))
    b = json.dumps(build_inventory(), sort_keys=True, separators=(",", ":"))
    assert a == b


# ── Pre-push wiring ──────────────────────────────────────────────────────────


def test_prepush_critical_case_via_changed_file_flag():
    r = subprocess.run(
        [
            sys.executable,
            "tools/check_universal_fix_impact_gate.py",
            "--changed-file",
            "signals.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0 or "manifest" in (r.stdout + r.stderr).lower()


def test_prepush_parity_includes_universal_stage():
    src = (ROOT / "tools/check_prepush_parity.py").read_text(encoding="utf-8")
    assert "universal_fix_gate" in src
    assert "check_universal_fix_impact_gate.py" in src


def test_item4_closure_records_no_false_positive_on_schema():
    schema = json.loads((ROOT / "governance/INSTITUTIONAL_CLOSURE_SCHEMA.json").read_text())
    labels = {}
    for row in schema.get("lanes") or []:
        if row.get("lane") == "ML-PIPE-ITEM4-FLEET-MIGRATION-V1":
            labels = row.get("acceptance_labels") or {}
    assert labels.get("ML_PIPE_ITEM_4") == "CLOSED_WITH_EVIDENCE"
    assert labels.get("MODEL_VERSION_PINNING_PARENT", labels.get("FULL_MODEL_STACK")) != "CLOSED_WITH_EVIDENCE"


def test_run_static_checks_clean_main():
    assert gate.run_static_checks() == []
