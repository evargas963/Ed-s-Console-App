"""UNIVERSAL_INSTITUTIONAL_ENGINEERING_STANDARD_V1 — deterministic enforcement tests.

Covers: canonical-source integrity, reference integrity, duplication prevention,
task-contract validation, exception handling, separation of concerns, and
anti-weakening — per the mission's required test matrix.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import check_universal_standard as us  # noqa: E402

# ── Canonical-source integrity ───────────────────────────────────────────────


def test_exactly_one_canonical_and_schema_valid():
    errs = us.check_universal_standard_canonical_integrity()
    assert errs == [], errs
    a = us._load_canonical()
    assert a["canonical"] is True
    assert a["standard_version"] == "1.0.0"
    assert a["primary_objective"]["id"] == "UIES-OBJ"
    assert "institutional-grade" in a["primary_objective"]["text"]
    ids = [p["id"] for p in a["universal_principles"]]
    assert ids == [f"UIES-P{i:02d}" for i in range(1, 13)]


def test_objective_present_and_undiluted():
    a = us._load_canonical()
    text = a["primary_objective"]["text"]
    for anchor in (
        "market data is trustworthy",
        "calculations are correct",
        "database history is temporally valid",
        "look-ahead contamination",
        "confidence values mean what the UI says they mean",
        "signals have measured outcome validity",
        "live behavior matches tested and backtested behavior",
        "failures are visible and fail closed",
        "operator surfaces are truthful",
        "runtime identity and evidence are reproducible",
        "real-money decisions can be reconstructed and audited",
    ):
        assert anchor in text, f"objective anchor missing: {anchor}"


# ── Reference integrity ──────────────────────────────────────────────────────


def test_all_governed_consumers_reference_canonical():
    errs = us.check_universal_standard_references()
    assert errs == [], errs
    token = us._load_canonical()["reference_contract"]["required_reference_token"]
    for rel in us.REFERENCE_ONLY_CONSUMERS:
        assert token in (REPO / rel).read_text(encoding="utf-8", errors="replace"), rel


def test_reference_token_embeds_version():
    a = us._load_canonical()
    assert a["standard_version"] in a["reference_contract"]["required_reference_token"]


# ── Duplication prevention ───────────────────────────────────────────────────


def test_duplicated_objective_rejected(tmp_path, monkeypatch):
    a = us._load_canonical()
    rogue = tmp_path / "ROGUE_AGENTS.md"
    rogue.write_text(
        "# rogue\n\n" + a["primary_objective"]["text"] + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(us, "_iter_governed_files", lambda globs=None: [rogue])
    errs = us.check_universal_standard_references()
    assert any("duplicates the primary objective" in e for e in errs), errs


def test_partially_paraphrased_duplicate_rejected(tmp_path, monkeypatch):
    a = us._load_canonical()
    words = a["primary_objective"]["text"].split()
    # Copy two long verbatim stretches inside otherwise-new prose (light paraphrase).
    chunk1, chunk2 = " ".join(words[5:25]), " ".join(words[60:80])
    rogue = tmp_path / "PARAPHRASE.md"
    rogue.write_text(f"Our goal: {chunk1}. Also, {chunk2}.\n", encoding="utf-8")
    monkeypatch.setattr(us, "_iter_governed_files", lambda globs=None: [rogue])
    errs = us.check_universal_standard_references()
    assert any("duplicates the primary objective" in e for e in errs), errs


def test_reference_only_file_passes(tmp_path, monkeypatch):
    a = us._load_canonical()
    ref = tmp_path / "REF_ONLY.md"
    ref.write_text(
        "Load and obey: " + a["reference_contract"]["required_reference_token"] + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(us, "_iter_governed_files", lambda globs=None: [ref])
    errs = us.check_universal_standard_references()
    assert errs == [], errs


def test_rendering_drift_rejected(tmp_path, monkeypatch):
    a = us._load_canonical()
    drifted = tmp_path / "RENDERED.md"
    drifted.write_text(us.render_markdown(a) + "\nrogue edit\n", encoding="utf-8")
    monkeypatch.setattr(us, "RENDERED_PATH", drifted)
    errs = us.check_universal_standard_rendering()
    assert any("rendering drift" in e for e in errs), errs


def test_rendering_current_matches_canonical():
    errs = us.check_universal_standard_rendering()
    assert errs == [], errs
    head = " | ".join(us.RENDERED_PATH.read_text(encoding="utf-8").splitlines()[:4])
    assert "GENERATED FILE" in head and "DO NOT EDIT" in head
    assert "**Classification:**" in head  # repo-wide scope-header contract


def test_competing_canonical_artifact_rejected(tmp_path, monkeypatch):
    # An independently edited duplicate claiming canonical status must fail.
    rogue_dir = tmp_path / "governance" / "standard2"
    rogue_dir.mkdir(parents=True)
    (rogue_dir / "competing.json").write_text(
        json.dumps({"artifact_id": "UNIVERSAL_INSTITUTIONAL_ENGINEERING_STANDARD_V1_COPY",
                    "canonical": True}),
        encoding="utf-8",
    )
    real_canonical = us.CANONICAL_PATH.read_text(encoding="utf-8")
    (tmp_path / "governance" / "standard").mkdir(parents=True)
    fake_canonical = tmp_path / "governance" / "standard" / us.CANONICAL_PATH.name
    fake_canonical.write_text(real_canonical, encoding="utf-8")
    monkeypatch.setattr(us, "REPO", tmp_path)
    monkeypatch.setattr(us, "CANONICAL_PATH", fake_canonical)
    errs = us.check_universal_standard_canonical_integrity()
    assert any("competing canonical standard" in e for e in errs), errs


# ── Task-contract validation ─────────────────────────────────────────────────

_COMPLETE_BLOCK = """STANDARD_VERSION = 1.0.0
INSTITUTIONAL_CAPABILITY_ADVANCED = immutable process-start identity for runtime proof
ROOT_CAUSE_TARGET = request-time repo HEAD read serving as process identity
MONEY_PATH_IMPACT = NO
UNIVERSALITY_DIMENSIONS = deployment modes, process lifecycles, git states
TRUTH_SEMANTICS = process_identity vs repository_state_now separated
FAIL_CLOSED_REQUIREMENT = capture failures reported as explicit nulls
MECHANICAL_REGRESSION_LOCK = tests/test_build_identity_process_drift_v1.py
REQUIRED_PROOF = focused tests + runtime SHA drift proof + CI
MISSION_OWNED_SCOPE = server.py + 3 governed companions
EXCEPTIONS = NONE
BINARY_ACCEPTANCE_CRITERIA = PROVEN or NOT_PROVEN
"""


def _block_errors(body: str) -> list[str]:
    return us._validate_task_block(REPO / "OPEN_ITEMS.md", 1, body)


def test_complete_task_declaration_passes():
    assert _block_errors(_COMPLETE_BLOCK) == []


def test_missing_capability_fails():
    body = _COMPLETE_BLOCK.replace(
        "INSTITUTIONAL_CAPABILITY_ADVANCED = immutable process-start identity for runtime proof\n", ""
    )
    errs = _block_errors(body)
    assert any("INSTITUTIONAL_CAPABILITY_ADVANCED" in e for e in errs)


def test_vague_capability_fails():
    body = _COMPLETE_BLOCK.replace(
        "immutable process-start identity for runtime proof", "institutional grade"
    )
    errs = _block_errors(body)
    assert any("vague" in e for e in errs)


def test_missing_root_cause_fails():
    body = _COMPLETE_BLOCK.replace(
        "ROOT_CAUSE_TARGET = request-time repo HEAD read serving as process identity\n", ""
    )
    assert any("ROOT_CAUSE_TARGET" in e for e in _block_errors(body))


def test_missing_universality_fails():
    body = _COMPLETE_BLOCK.replace(
        "UNIVERSALITY_DIMENSIONS = deployment modes, process lifecycles, git states\n", ""
    )
    assert any("UNIVERSALITY_DIMENSIONS" in e for e in _block_errors(body))


def test_missing_regression_lock_fails():
    body = _COMPLETE_BLOCK.replace(
        "MECHANICAL_REGRESSION_LOCK = tests/test_build_identity_process_drift_v1.py\n", ""
    )
    assert any("MECHANICAL_REGRESSION_LOCK" in e for e in _block_errors(body))


def test_missing_proof_fails():
    body = _COMPLETE_BLOCK.replace(
        "REQUIRED_PROOF = focused tests + runtime SHA drift proof + CI\n", ""
    )
    assert any("REQUIRED_PROOF" in e for e in _block_errors(body))


def test_wrong_standard_version_fails():
    body = _COMPLETE_BLOCK.replace("STANDARD_VERSION = 1.0.0", "STANDARD_VERSION = 0.9.0")
    assert any("does not match" in e for e in _block_errors(body))


def test_closure_without_contract_fails():
    body = _COMPLETE_BLOCK + "LANE = CLOSED_WITH_EVIDENCE @ abc\n"
    errs = _block_errors(body)
    assert any("CLOSURE_CONTRACT" in e for e in errs)


def test_closure_with_answered_contract_passes():
    body = (
        _COMPLETE_BLOCK
        + "LANE = CLOSED_WITH_EVIDENCE @ abc\n"
        + "CLOSURE_CONTRACT = ANSWERED @ governance/standard/universal_institutional_engineering_standard_v1.json\n"
    )
    errs = _block_errors(body)
    assert not any("CLOSURE_CONTRACT" in e for e in errs), errs


def test_ambiguous_status_language_fails():
    body = _COMPLETE_BLOCK + "LANE_STATUS = mostly done\n"
    errs = _block_errors(body)
    assert any("ambiguous status" in e for e in errs)


def test_binary_status_language_passes():
    body = _COMPLETE_BLOCK + "LANE_STATUS = NOT_PROVEN\n"
    errs = _block_errors(body)
    assert not any("ambiguous status" in e for e in errs), errs


# ── Exception handling ───────────────────────────────────────────────────────


def test_explicit_exception_passes():
    line = ("UIES_EXCEPTION_APPROVED: scope=legacy-artifact justification=pre-V2-vocabulary "
            "approved_by=operator-2026-07-09 bound=until-next-migration")
    assert us._EXCEPTION_RE.search(line)


def test_silent_exception_fails():
    assert not us._EXCEPTION_RE.search("UIES_EXCEPTION_APPROVED: scope=x")
    assert not us._EXCEPTION_RE.search(
        "UIES_EXCEPTION_APPROVED: scope=x justification=y approved_by=z"
    )  # unbounded


# ── Separation of concerns ───────────────────────────────────────────────────


def test_canonical_contains_no_priority_or_runtime_state():
    raw = us.CANONICAL_PATH.read_text(encoding="utf-8").lower()
    for tok in us._PRIORITY_LEAK_TOKENS:
        assert tok not in raw, tok
    assert not us._HEX40_RE.search(raw)


def test_priority_leak_in_canonical_rejected(tmp_path, monkeypatch):
    a = us._load_canonical()
    a["next_lane"] = "D1"
    leaky = tmp_path / us.CANONICAL_PATH.name
    leaky.write_text(json.dumps(a), encoding="utf-8")
    monkeypatch.setattr(us, "CANONICAL_PATH", leaky)
    monkeypatch.setattr(us, "REPO", tmp_path)
    errs = us.check_universal_standard_canonical_integrity()
    assert any("leak token" in e for e in errs), errs


def test_separate_queue_referencing_standard_passes(tmp_path, monkeypatch):
    ref = tmp_path / "ACTIVE_QUEUE.md"
    ref.write_text(
        "Next lane: D1 (queue data lives here, not in the standard).\n"
        "Standard: " + us._load_canonical()["reference_contract"]["required_reference_token"] + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(us, "_iter_governed_files", lambda globs=None: [ref])
    errs = us.check_universal_standard_references()
    assert errs == [], errs


# ── Anti-weakening ───────────────────────────────────────────────────────────


def test_weakening_agent_file_rejected(tmp_path, monkeypatch):
    rogue = tmp_path / "WEAK_AGENTS.md"
    rogue.write_text(
        "This file overrides the universal engineering standard for speed.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(us, "_iter_governed_files", lambda globs=None: [rogue])
    errs = us.check_universal_standard_references()
    assert any("weakens/overrides" in e for e in errs), errs


def test_reinforcing_reference_passes(tmp_path, monkeypatch):
    ok = tmp_path / "GOOD_AGENTS.md"
    ok.write_text(
        "All work follows the universal engineering standard; load "
        + us._load_canonical()["reference_contract"]["required_reference_token"]
        + " and obey it.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(us, "_iter_governed_files", lambda globs=None: [ok])
    errs = us.check_universal_standard_references()
    assert errs == [], errs


def test_local_redefinition_rejected(tmp_path, monkeypatch):
    rogue = tmp_path / "REDEF.md"
    rogue.write_text('"UIES-P03": "my own weaker meaning"\n', encoding="utf-8")
    monkeypatch.setattr(us, "_iter_governed_files", lambda globs=None: [rogue])
    errs = us.check_universal_standard_references()
    assert any("redefines UIES" in e for e in errs), errs


# ── Live repo end-to-end ─────────────────────────────────────────────────────


def test_full_checker_passes_on_current_repo():
    errs = us.check_universal_standard()
    assert errs == [], errs


def test_wired_into_enforcement_registry():
    import check_fix_everything_we_touch as cfe

    assert "check_universal_standard" in cfe._REPO_WIDE_STATIC_CHECK_FUNCS
    assert callable(getattr(cfe, "check_universal_standard"))
    # Delegator resolves to the single implementation and passes live.
    assert cfe.check_universal_standard() == []
