"""Decision-path admission gate — charter §Decision-path admission (AGENTS.md).

Locks, fail-closed:
  1. Registry loading: missing / unreadable / malformed / wrong-schema / empty
     registries admit nothing, each with an honest detail string.
  2. Admission substance: only a record with status ADMITTED, all six evidence
     fields non-empty, and a complete operator_decision admits the component.
  3. The committed production registry is valid, EMPTY, and admits nothing.
  4. End-to-end through compute_call: a stack read that would emit LONG is
     forced to WAIT (zero-sized, NO_TRADE) under the production registry, with
     the would-be direction preserved in wait_blocker.gated_signal; the same
     read passes through as LONG when the decision path is ADMITTED.
"""
from __future__ import annotations

import json

import pytest

from decision_gate import (
    DECISION_PATH_COMPONENT,
    REQUIRED_EVIDENCE_FIELDS,
    SCHEMA_VERSION,
    STATE_ADMITTED,
    STATE_EMPTY,
    STATE_INVALID,
    STATE_MISSING,
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
        "operator_decision": {"date": "2026-07-16", "decided_by": "operator"},
    }


def _write_registry(tmp_path, admissions, schema_version=SCHEMA_VERSION):
    p = tmp_path / "decision_path_admissions.json"
    p.write_text(
        json.dumps({"schema_version": schema_version, "admissions": admissions}),
        encoding="utf-8",
    )
    return p


# ── 1. Registry loading fail-closed ─────────────────────────────────────────

def test_missing_registry_admits_nothing(tmp_path):
    v = evaluate_decision_path_admission(path=tmp_path / "nope.json")
    assert v.admitted is False
    assert v.registry_state == STATE_MISSING
    assert "WAIT" in v.detail


def test_malformed_json_admits_nothing(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert v.registry_state == STATE_INVALID
    assert "WAIT" in v.detail


def test_wrong_schema_version_admits_nothing(tmp_path):
    p = _write_registry(tmp_path, [_admitted_record()], schema_version=99)
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert v.registry_state == STATE_INVALID


def test_non_list_admissions_admits_nothing(tmp_path):
    p = tmp_path / "bad_shape.json"
    p.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "admissions": {}}), encoding="utf-8")
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert v.registry_state == STATE_INVALID


def test_empty_registry_admits_nothing(tmp_path):
    p = _write_registry(tmp_path, [])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert v.registry_state == STATE_EMPTY
    assert "abstains" in v.detail


# ── 2. Admission substance ──────────────────────────────────────────────────

def test_complete_admission_admits(tmp_path):
    p = _write_registry(tmp_path, [_admitted_record()])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is True
    assert v.registry_state == STATE_ADMITTED


def test_status_other_than_admitted_does_not_admit(tmp_path):
    rec = _admitted_record()
    rec["status"] = "CANDIDATE"
    p = _write_registry(tmp_path, [rec])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert v.registry_state == STATE_NOT_ADMITTED
    assert "CANDIDATE" in v.detail


def test_other_component_does_not_admit_the_call(tmp_path):
    p = _write_registry(tmp_path, [_admitted_record(component="some_signal")])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert v.registry_state == STATE_NOT_ADMITTED


@pytest.mark.parametrize("missing_field", REQUIRED_EVIDENCE_FIELDS)
def test_each_missing_evidence_field_blocks_admission(tmp_path, missing_field):
    rec = _admitted_record()
    del rec["evidence"][missing_field]
    p = _write_registry(tmp_path, [rec])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert missing_field in v.detail


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_evidence_value_blocks_admission(tmp_path, blank):
    rec = _admitted_record()
    rec["evidence"]["oos_results"] = blank
    p = _write_registry(tmp_path, [rec])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False


def test_missing_operator_decision_blocks_admission(tmp_path):
    rec = _admitted_record()
    del rec["operator_decision"]
    p = _write_registry(tmp_path, [rec])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert "operator_decision" in v.detail


def test_incomplete_operator_decision_blocks_admission(tmp_path):
    rec = _admitted_record()
    rec["operator_decision"] = {"date": "2026-07-16"}
    p = _write_registry(tmp_path, [rec])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is False
    assert "decided_by" in v.detail


def test_one_valid_admission_among_invalid_records_admits(tmp_path):
    rec_bad = _admitted_record()
    rec_bad["status"] = "REJECTED"
    p = _write_registry(tmp_path, [rec_bad, "not-a-record", _admitted_record()])
    v = evaluate_decision_path_admission(path=p)
    assert v.admitted is True


# ── 3. Committed production registry ────────────────────────────────────────

def test_committed_registry_is_valid_and_empty():
    doc = json.loads(_DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert doc["schema_version"] == SCHEMA_VERSION
    assert doc["admissions"] == []


def test_committed_registry_admits_nothing():
    v = evaluate_decision_path_admission(path=_DEFAULT_REGISTRY_PATH)
    assert v.admitted is False
    assert v.registry_state == STATE_EMPTY


def test_registry_path_env_override(monkeypatch, tmp_path):
    target = tmp_path / "override.json"
    monkeypatch.setenv("ED_DECISION_ADMISSIONS_PATH", str(target))
    assert registry_path() == target
    monkeypatch.delenv("ED_DECISION_ADMISSIONS_PATH")
    assert registry_path() == _DEFAULT_REGISTRY_PATH


# ── 4. End-to-end through compute_call ──────────────────────────────────────

def _would_be_long_call(monkeypatch, registry_file):
    """Run the phase-3 ALL-promoted-long scenario against a given registry."""
    from types import SimpleNamespace

    from call_engine import compute_call
    from multi_horizon_decision import compute_multi_horizon_synthesis
    from tests.mvp_test_fixtures import minimal_mvp_features
    from tests.test_call_engine_chunk1_fail_closed import (
        _phase3_canonical,
        _phase3_pred_bullish_all_horizons,
        _phase3_rules_long,
        _phase3_vol_regime,
        _strong_long_stack_input,
    )

    monkeypatch.setenv("ED_DECISION_ADMISSIONS_PATH", str(registry_file))

    inp = _strong_long_stack_input()
    inp.order_flow_direction = "neutral"
    inp.spy_chg_pct = 0.01
    inp.qqq_chg_pct = 0.01
    inp.iwm_chg_pct = 0.01
    inp.spy_weighted_push = 0.0
    inp.qqq_weighted_push = 0.0
    inp.iwm_weighted_push = 0.0
    inp.net_delta = 50.0
    inp.zone = "pin_bull"

    canonical = _phase3_canonical()
    pred = _phase3_pred_bullish_all_horizons()
    mh_policy = compute_multi_horizon_synthesis(inp, pred, canonical)
    assert mh_policy.final_tradeable_decision is True

    return compute_call(
        inp,
        _phase3_rules_long(),
        pred,
        regime=SimpleNamespace(primary="unknown", confidence="low"),
        fusion=None,
        vol_regime=_phase3_vol_regime(),
        canonical=canonical,
        mvp_features=minimal_mvp_features(zone="pin_bull"),
        mh_policy=mh_policy,
    )


def test_compute_call_forced_wait_under_production_empty_registry(monkeypatch):
    call = _would_be_long_call(monkeypatch, _DEFAULT_REGISTRY_PATH)
    assert call.signal == "wait"
    assert call.conviction == "low"
    assert call.r_units == 0.0
    assert call.execution_mode == "NO_TRADE"
    assert call.size_cue == "SKIP"
    assert call.wait_blocker is not None
    assert call.wait_blocker["reason"] == "decision_path_admission"
    assert call.wait_blocker["registry_state"] == STATE_EMPTY
    # Find & Prove evidence loop keeps the would-be direction.
    assert call.wait_blocker["gated_signal"] == "long"
    assert call.headline.startswith("WAIT — decision path not admitted")


def test_compute_call_forced_wait_when_registry_missing(monkeypatch, tmp_path):
    call = _would_be_long_call(monkeypatch, tmp_path / "absent.json")
    assert call.signal == "wait"
    assert call.wait_blocker["reason"] == "decision_path_admission"
    assert call.wait_blocker["registry_state"] == STATE_MISSING


def test_compute_call_directional_passes_when_admitted(monkeypatch, tmp_path):
    p = _write_registry(tmp_path, [_admitted_record()])
    call = _would_be_long_call(monkeypatch, p)
    assert call.signal == "long", (
        f"admitted decision path must pass the stack call through; got {call.signal!r} "
        f"blocker={call.wait_blocker!r}"
    )
    assert call.wait_blocker is None


def test_named_force_functions_remain_in_charter():
    """Chat is not a lock. Named force / bind sentences must remain in AGENTS.md.

    This proves the sentences still exist. It does not prove the agent ran
    drift-audit, Five Whys, Bugbot, or security-review on a given slice.
    """
    from pathlib import Path

    charter = Path(__file__).resolve().parent.parent.joinpath("AGENTS.md").read_text(
        encoding="utf-8"
    )
    for needle in (
        "chat is not a lock",
        "git merge-base --is-ancestor",
        "Five Whys",
        "drift-audit skill before any done",
        "Bugbot when the diff is material",
        "security-review when secrets",
    ):
        assert needle in charter, f"named force function missing from AGENTS.md: {needle!r}"
