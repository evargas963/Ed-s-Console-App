"""Decision-path admission gate — clause-level fail-closed lock (v2).

Extends tests/test_decision_gate.py. Every registry-validation clause in
decision_gate.py gets a fires-test (blocks admission with an honest state and
detail) and, where the clause tolerates normalization, a passes-test. All
registries here are explicit tmp files; nothing depends on the conftest
admitted-registry default (explicit ``path=`` always wins).

Clauses covered beyond the v1 file:
  - unreadable path (OSError, not FileNotFoundError)
  - top-level document not an object / schema_version wrong type or absent
  - admissions key absent / null
  - record-level: non-dict record, wrong-case status, non-string evidence
    values, non-string operator_decision values
  - normalization: whitespace-padded component/status still admit
  - custom component admission independence
  - detail truncation to the first three failure reasons
  - registry_path env override: blank / whitespace values fall back to default
"""
from __future__ import annotations

import json

import pytest

from decision_gate import (
    DECISION_PATH_COMPONENT,
    REQUIRED_EVIDENCE_FIELDS,
    SCHEMA_VERSION,
    STATE_ADMITTED,
    STATE_INVALID,
    STATE_NOT_ADMITTED,
    _DEFAULT_REGISTRY_PATH,
    evaluate_decision_path_admission,
    registry_path,
)


def _full_evidence() -> dict:
    return {f: f"ref:{f}" for f in REQUIRED_EVIDENCE_FIELDS}


def _admitted_record(component: str = DECISION_PATH_COMPONENT) -> dict:
    return {
        "component": component,
        "status": "ADMITTED",
        "evidence": _full_evidence(),
        "operator_decision": {"date": "2026-08-24", "decided_by": "operator"},
    }


def _write(tmp_path, doc, name="reg.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _write_registry(tmp_path, admissions):
    return _write(tmp_path, {"schema_version": SCHEMA_VERSION, "admissions": admissions})


# ── Registry loading clauses ─────────────────────────────────────────────────

def test_unreadable_registry_path_is_invalid_not_missing(tmp_path):
    # A directory raises OSError (not FileNotFoundError) on read_text.
    v = evaluate_decision_path_admission(path=tmp_path)
    assert v.admitted is False
    assert v.registry_state == STATE_INVALID
    assert "unreadable" in v.detail
    assert "WAIT" in v.detail


@pytest.mark.parametrize("top_level", [[], "a-string", 1, None, [{"schema_version": 1}]])
def test_non_object_top_level_document_admits_nothing(tmp_path, top_level):
    p = _write(tmp_path, top_level)
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert v.registry_state == STATE_INVALID


@pytest.mark.parametrize("version", ["1", None, 2, 0])
def test_schema_version_must_be_exact_int_match(tmp_path, version):
    doc = {"admissions": [_admitted_record()]}
    if version is not None:
        doc["schema_version"] = version
    # "1" (string), absent, and wrong ints all refuse — strict equality with 1.
    p = _write(tmp_path, doc)
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert v.registry_state == STATE_INVALID
    assert "schema_version" in v.detail


@pytest.mark.parametrize("admissions", [None, {}, "not-a-list", 7])
def test_admissions_key_absent_or_non_list_admits_nothing(tmp_path, admissions):
    doc = {"schema_version": SCHEMA_VERSION}
    if admissions is not None:
        doc["admissions"] = admissions
    p = _write(tmp_path, doc)
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert v.registry_state == STATE_INVALID


# ── Record-level clauses: fires ──────────────────────────────────────────────

@pytest.mark.parametrize("record", ["a-string", 42, ["nested"], None])
def test_non_object_record_blocks_with_honest_reason(tmp_path, record):
    p = _write_registry(tmp_path, [record])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert v.registry_state == STATE_NOT_ADMITTED
    assert "record is not an object" in v.detail


@pytest.mark.parametrize("status", ["admitted", "Admitted", "ADMITTED_", "APPROVED"])
def test_status_match_is_case_and_value_exact(tmp_path, status):
    rec = _admitted_record()
    rec["status"] = status
    p = _write_registry(tmp_path, [rec])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert v.registry_state == STATE_NOT_ADMITTED


@pytest.mark.parametrize("bad_value", [123, True, ["ref"], {"ref": "x"}, None])
def test_non_string_evidence_value_blocks_admission(tmp_path, bad_value):
    rec = _admitted_record()
    rec["evidence"]["oos_results"] = bad_value
    p = _write_registry(tmp_path, [rec])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert "oos_results" in v.detail


@pytest.mark.parametrize("evidence", [None, "complete", ["a", "b"], 5])
def test_non_dict_evidence_block_blocks_admission(tmp_path, evidence):
    rec = _admitted_record()
    rec["evidence"] = evidence
    p = _write_registry(tmp_path, [rec])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert "evidence block missing" in v.detail


@pytest.mark.parametrize("bad_value", [20260824, None, ["2026-08-24"]])
def test_non_string_operator_decision_value_blocks_admission(tmp_path, bad_value):
    rec = _admitted_record()
    rec["operator_decision"]["date"] = bad_value
    p = _write_registry(tmp_path, [rec])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert "date" in v.detail


# ── Record-level clauses: passes (normalization tolerance) ───────────────────

def test_whitespace_padded_component_and_status_still_admit(tmp_path):
    rec = _admitted_record()
    rec["component"] = f"  {DECISION_PATH_COMPONENT}  "
    rec["status"] = "  ADMITTED  "
    p = _write_registry(tmp_path, [rec])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is True
    assert v.registry_state == STATE_ADMITTED


def test_custom_component_admits_only_itself(tmp_path):
    p = _write_registry(tmp_path, [_admitted_record(component="other_component")])
    v_other = evaluate_decision_path_admission("other_component", path=p)
    assert v_other.admitted is True
    assert v_other.registry_state == STATE_ADMITTED
    v_call = evaluate_decision_path_admission(path=p)  # default: the_call
    assert v_call.admitted is False
    assert v_call.registry_state == STATE_NOT_ADMITTED


def test_valid_record_admits_even_when_listed_after_invalid_ones(tmp_path):
    bad1 = _admitted_record()
    bad1["status"] = "PENDING"
    p = _write_registry(tmp_path, [bad1, "junk", _admitted_record()])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is True


# ── Precedence and detail honesty ────────────────────────────────────────────

def test_detail_reports_at_most_first_three_failure_reasons(tmp_path):
    records = []
    for i in range(1, 6):
        rec = _admitted_record()
        rec["status"] = f"BAD{i}"
        records.append(rec)
    p = _write_registry(tmp_path, records)
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert v.registry_state == STATE_NOT_ADMITTED
    for present in ("BAD1", "BAD2", "BAD3"):
        assert present in v.detail
    for absent in ("BAD4", "BAD5"):
        assert absent not in v.detail


def test_schema_invalidity_takes_precedence_over_admissions_content(tmp_path):
    # A perfect admission under a wrong schema_version still admits nothing.
    p = _write(tmp_path, {"schema_version": 99, "admissions": [_admitted_record()]})
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert v.registry_state == STATE_INVALID


# ── registry_path env override edge cases ────────────────────────────────────

@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_blank_env_override_falls_back_to_default_path(monkeypatch, value):
    monkeypatch.setenv("ED_DECISION_ADMISSIONS_PATH", value)
    assert registry_path() == _DEFAULT_REGISTRY_PATH


def test_env_override_value_is_stripped(monkeypatch, tmp_path):
    target = tmp_path / "reg.json"
    monkeypatch.setenv("ED_DECISION_ADMISSIONS_PATH", f"  {target}  ")
    assert registry_path() == target
