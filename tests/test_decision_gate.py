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
import re

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


def audited_status_changes_missing_required_check(text: str) -> list[str]:
    """STATUS_CHANGE that names an audit and a SHA must cite run + RED/GREEN.

    Does not prove the run id belongs to that SHA (needs the Actions API).
    Catches the omit-the-conclusion shape that slice lock (4) names.
    """
    sha = re.compile(r"`[0-9a-f]{7,40}`")
    audit = re.compile(r"\baudit\b|\bre-audit\b", re.I)
    run_id = re.compile(r"\brun\s+\d{8,}\b")
    verdict = re.compile(r"\b(RED|GREEN)\b")
    missing: list[str] = []
    for line in text.splitlines():
        if not line.lstrip().startswith("- **STATUS_CHANGE"):
            continue
        if not audit.search(line) or not sha.search(line):
            continue
        if not (run_id.search(line) and verdict.search(line)):
            missing.append(line[:120])
    return missing


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


def test_board_checkbox_x_did_not_increase_versus_origin_main():
    """Failure 4: whole-board checkbox `[x]` rows, not raw `[x]` in prose."""
    import re
    import subprocess
    from pathlib import Path

    main = subprocess.check_output(
        ["git", "show", "origin/main:OPEN_ITEMS.md"], text=True
    )
    head = Path(__file__).resolve().parent.parent.joinpath("OPEN_ITEMS.md").read_text(
        encoding="utf-8"
    )

    def checkbox_x(text: str) -> list[str]:
        return re.findall(r"^\s*- \[x\].*$", text, flags=re.M)

    added = set(checkbox_x(head)) - set(checkbox_x(main))
    assert added == set(), f"new checkbox [x] vs origin/main: {sorted(added)[:8]}"
    assert len(checkbox_x(head)) <= len(checkbox_x(main)), (
        f"checkbox [x] count rose vs origin/main: "
        f"{len(checkbox_x(head))} > {len(checkbox_x(main))}"
    )


def test_audited_status_change_cites_required_check_conclusion():
    """Slice lock (4): audit STATUS_CHANGE + SHA must carry run id and RED/GREEN."""
    from pathlib import Path

    good = (
        "- **STATUS_CHANGE 2026-08-14 dual read-only audit @ `abc1234`:** "
        "Required checks at `abc1234`: pytest-full run 31804847117 RED."
    )
    omit = "- **STATUS_CHANGE 2026-08-14 dual read-only audit @ `abc1234`:** no CI cited."
    no_verdict = (
        "- **STATUS_CHANGE 2026-08-14 re-audit:** `abc1234` — pytest-full run 31804847117."
    )
    assert audited_status_changes_missing_required_check(good) == []
    assert audited_status_changes_missing_required_check(omit)
    assert audited_status_changes_missing_required_check(no_verdict)
    board = Path(__file__).resolve().parent.parent.joinpath("OPEN_ITEMS.md").read_text(
        encoding="utf-8"
    )
    assert audited_status_changes_missing_required_check(board) == []


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
        "Whys without the fix is unfinished",
        "fix the issue in the same program",
        "tests/test_mega2_traceable_audit.py in the edit loop",
        "tests/test_mega1_traceable_audit.py",
        "MEGA1_FILES or MEGA2_FILES",
        "STATUS_CHANGE that cites an audited SHA must also cite the required-check conclusion",
        "drift-audit skill before any done",
        "Bugbot when the diff is material",
        "security-review when secrets",
        "acceptance line is a measurement of the stated principle",
        "Presence of a test, a green proxy gate, or a SHA cite is not the principle",
        "enumerates every producer of that quantity across the tree",
        "do not merely patch the reported instance",
        "recurrence of the same failure class is mechanically prevented or detected",
        "not a specific file, ticker, route, field, model, horizon, subsystem, literal string, or auditor example",
        "semantic failure shape",
        "No example-locking",
        "complete semantic universe",
        "materially equivalent variants",
    ):
        assert needle in charter, f"named force function missing from AGENTS.md: {needle!r}"


def test_five_zone_acceptance_lines_are_operative():
    """Zone-close lock: each line exercises the principle on real inputs."""
    import subprocess
    from pathlib import Path

    from features.signal_layer_v1 import _volume_profile_proxy
    from governance.mega2_traceable_inventory import uninventoried_engine_modules
    from liquidity_value_engine import _volume_profile_poc_vah_val
    from math_exposure_core import KEY_LEVEL_CONSUMER_REGISTRY
    from tests.test_institutional_key_levels import hardcoded_kl_row_labels
    from tests.test_liquidity_engine import _frozen_close_price_12bin, _spy_session_bars
    from tools.check_absence_has_a_type import fabricated_absence_returns_in_source
    from verify_active_models import model_health_edge_from_meta

    # Z1 — unmeasured edge is None, not accuracy·100 (real meta dict)
    assert model_health_edge_from_meta({"val_accuracy": 0.55}, "edge_pp") is None
    assert model_health_edge_from_meta({"edge_pp": 0.0}, "edge_pp") == 0.0

    # Z2 — gate catch/miss on planted source, not a docstring string
    catch = fabricated_absence_returns_in_source(
        "def a(x: float) -> float:\n"
        "    try:\n        return float(x)\n"
        "    except TypeError:\n        return float(0)\n"
    )
    assert [(h[1], h[2]) for h in catch] == [("a", "0")]
    miss_opt = fabricated_absence_returns_in_source(
        "def b(x: float) -> float | None:\n"
        "    try:\n        return float(x)\n"
        "    except TypeError:\n        return 0.0\n"
    )
    assert miss_opt == []
    miss_or = fabricated_absence_returns_in_source(
        "def c(x: float) -> float:\n"
        "    try:\n        return x or 0.0\n"
        "    except TypeError:\n        return x or 0.0\n"
    )
    assert miss_or == []

    # Z3 — feature stability: live proxy == frozen close-price 12-bin ≠ engine
    bars = _spy_session_bars(60)
    assert len(bars) >= 50
    live = _volume_profile_proxy(bars, 50)
    frozen = _frozen_close_price_12bin(bars, 50)
    engine = _volume_profile_poc_vah_val(bars)
    assert live == frozen
    assert live[0] != engine[0]

    # Z4 — tree-fed scan of this repo, plus a real planted file
    repo_files = subprocess.check_output(["git", "ls-files"], text=True).split()
    assert uninventoried_engine_modules(repo_files) == []

    # Z5 — no painted label on any payload row (full HTML, not a string needle)
    html = Path(__file__).resolve().parent.parent.joinpath(
        "static/index.html"
    ).read_text(encoding="utf-8")
    assert len(KEY_LEVEL_CONSUMER_REGISTRY) == 17
    assert hardcoded_kl_row_labels(html) == []


def test_kl_hardcoded_label_class_is_detected_on_any_kl_row_not_just_cited_keys():
    """Z5 class: painted `label:` on a payload row — `kl_` prefix is not required."""
    from tests.test_institutional_key_levels import hardcoded_kl_row_labels

    plant = (
        "const KL_PRIMARY = [\n"
        "  { key: 'structural_unlisted', label: 'Planted Label', tip: 'x' },\n"
        "];\n"
    )
    found = hardcoded_kl_row_labels(plant)
    assert found == [("structural_unlisted", "Planted Label")], found


def test_volume_profile_class_is_detected_on_any_undelegated_def_not_just_cited_file():
    """Z3 class: a second POC/VAH/VAL algorithm — name need not contain volume_profile."""
    from tests.test_liquidity_engine import undelegated_volume_profile_defs

    plant = (
        "def _value_area_from_closes(bars):\n"
        "    nbin = 12\n"
        "    vol_by_price = {}\n"
        "    return bars[-1]['close'], bars[-1]['close'], bars[-1]['close']\n"
        "\n"
        "poc, vah, val = _value_area_from_closes(bars)\n"
    )
    found = undelegated_volume_profile_defs(plant, filename="features/unrelated_layer.py")
    assert "features/unrelated_layer.py:_value_area_from_closes" in found, found


def test_edge_key_miss_class_is_detected_on_any_meta_get_not_just_cited_function():
    """Z1 class: substitute field V when asked for field K — no `*_key` suffix required."""
    from tests.test_model_edge_absent_is_not_zero_v1 import (
        functions_that_get_unrelated_literal_on_key_miss,
    )

    plant = (
        "def published_from_blob(blob, requested):\n"
        "    return blob.get(requested, blob.get('train_accuracy', 0))\n"
    )
    found = functions_that_get_unrelated_literal_on_key_miss(plant)
    assert found == ["published_from_blob"], found
