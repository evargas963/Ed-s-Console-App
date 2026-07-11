"""GOV-GATE-PARITY-01 — adversarial proofs for the pre-push parity gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.check_prepush_parity import (
    FULL_SAFE_BUNDLE,
    aggregate_exit,
    enforce_static_remote_command,
    parse_workflow_run_command,
    ruff_remote_command,
)

REPO = Path(__file__).resolve().parents[1]


# ── Parity by construction: commands come FROM the workflow file ──


def test_ruff_command_is_parsed_from_hardening_workflow():
    cmd = ruff_remote_command()
    wf = (REPO / ".github" / "workflows" / "hardening.yml").read_text(encoding="utf-8")
    assert cmd in wf, "local ruff command must be the literal remote command"
    assert "ruff" in cmd and "--select" in cmd


def test_enforce_static_command_is_parsed_from_hardening_workflow():
    cmd = enforce_static_remote_command()
    wf = (REPO / ".github" / "workflows" / "hardening.yml").read_text(encoding="utf-8")
    assert cmd in wf
    assert "--enforce-static" in cmd, "local twin must run enforce-static, not enforce-all"


def test_missing_remote_step_fails_loud(tmp_path):
    wf = tmp_path / "w.yml"
    wf.write_text("jobs:\n  x:\n    steps:\n      - name: other\n        run: echo hi\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        parse_workflow_run_command(wf, "ruff (correctness rules")


# ── Failure propagation: no child failure can be masked ──


def test_child_failure_propagates_nonzero():
    assert aggregate_exit({"ruff": 1, "static": 0, "csv_first": 0, "owner_tests": 0}) == 1
    assert aggregate_exit({"ruff": 0, "static": 1, "csv_first": 0, "owner_tests": 0}) == 1
    assert aggregate_exit({"ruff": 0, "static": 0, "csv_first": 1, "owner_tests": 0}) == 1
    assert aggregate_exit({"ruff": 0, "static": 0, "csv_first": 0, "owner_tests": 1}) == 1
    assert aggregate_exit({"ruff": 0, "static": 0, "csv_first": 0, "owner_tests": 0}) == 0


def test_wrapper_cannot_return_zero_after_any_failure_combination():
    import itertools

    stages = ("ruff", "static", "csv_first", "owner_tests")
    for combo in itertools.product((0, 1), repeat=4):
        res = dict(zip(stages, combo))
        expected = 0 if sum(combo) == 0 else 1
        assert aggregate_exit(res) == expected, res


# ── Selector consumption: mandatory, unknown scope → full safe bundle ──


def test_selector_unknown_scope_maps_to_full_safe_bundle(monkeypatch):
    import tools.check_prepush_parity as pp

    calls = {}

    def fake_run(cmd, shell=False):
        key = "pytest" if (isinstance(cmd, list) and "-m" in cmd) else str(cmd)[:20]
        calls.setdefault("cmds", []).append(cmd)
        return 0, ""

    monkeypatch.setattr(pp, "_run", fake_run)
    monkeypatch.setattr(pp, "outgoing_changed_files", lambda base_ref="x": ["totally_unmapped.py"])
    monkeypatch.setattr(pp, "write_outgoing_diff", lambda base_ref="x": Path("nul"))
    rc = pp.run_parity_gate(emit=lambda *_: None)
    assert rc == 0
    pytest_cmd = [c for c in calls["cmds"] if isinstance(c, list) and "pytest" in " ".join(map(str, c))]
    assert pytest_cmd, "owner tests stage must execute"
    joined = " ".join(map(str, pytest_cmd[-1]))
    present_bundle = [s for s in FULL_SAFE_BUNDLE if (REPO / s).is_file()]
    for s in present_bundle:
        assert s in joined, f"unknown scope must run the full safe bundle (missing {s})"


def test_selector_narrow_scope_runs_owner_union_not_full_bundle(monkeypatch):
    import tools.check_prepush_parity as pp

    calls = {}

    def fake_run(cmd, shell=False):
        calls.setdefault("cmds", []).append(cmd)
        return 0, ""

    monkeypatch.setattr(pp, "_run", fake_run)
    monkeypatch.setattr(
        pp, "outgoing_changed_files", lambda base_ref="x": ["replay_hold_bars.py"]
    )
    monkeypatch.setattr(pp, "write_outgoing_diff", lambda base_ref="x": Path("nul"))
    rc = pp.run_parity_gate(emit=lambda *_: None)
    assert rc == 0
    joined = " ".join(
        " ".join(map(str, c)) for c in calls["cmds"] if isinstance(c, list)
    )
    assert "tests/test_replay_hold_bars.py" in joined
    assert "tests/test_governance_consolidation.py" not in joined, (
        "an unrelated narrow diff must not pay the full bundle"
    )


def test_empty_suite_list_fails_closed(monkeypatch):
    import tools.check_prepush_parity as pp

    monkeypatch.setattr(pp, "_run", lambda cmd, shell=False: (0, ""))
    monkeypatch.setattr(pp, "outgoing_changed_files", lambda base_ref="x": ["unknown.py"])
    monkeypatch.setattr(pp, "write_outgoing_diff", lambda base_ref="x": Path("nul"))
    monkeypatch.setattr(pp, "FULL_SAFE_BUNDLE", ("tests/does_not_exist_anywhere.py",))
    rc = pp.run_parity_gate(emit=lambda *_: None)
    assert rc == 1, "no runnable suites can never be a pass"


def test_owner_suite_failure_fails_the_gate(monkeypatch):
    import tools.check_prepush_parity as pp

    def fake_run(cmd, shell=False):
        if isinstance(cmd, list) and "pytest" in " ".join(map(str, cmd)):
            return 1, "1 failed"
        return 0, ""

    monkeypatch.setattr(pp, "_run", fake_run)
    monkeypatch.setattr(pp, "outgoing_changed_files", lambda base_ref="x": ["replay_hold_bars.py"])
    monkeypatch.setattr(pp, "write_outgoing_diff", lambda base_ref="x": Path("nul"))
    assert pp.run_parity_gate(emit=lambda *_: None) == 1


def test_csv_first_failure_fails_the_gate(monkeypatch):
    import tools.check_prepush_parity as pp

    def fake_run(cmd, shell=False):
        if isinstance(cmd, list) and "check_schwab_csv_first" in " ".join(map(str, cmd)):
            return 1, "guard FAILED"
        return 0, ""

    monkeypatch.setattr(pp, "_run", fake_run)
    monkeypatch.setattr(pp, "outgoing_changed_files", lambda base_ref="x": ["replay_hold_bars.py"])
    monkeypatch.setattr(pp, "write_outgoing_diff", lambda base_ref="x": Path("nul"))
    assert pp.run_parity_gate(emit=lambda *_: None) == 1


def test_ruff_or_static_failure_fails_the_gate(monkeypatch):
    import tools.check_prepush_parity as pp

    for target in ("ruff", "--enforce-static"):
        def fake_run(cmd, shell=False, _t=target):
            if isinstance(cmd, str) and _t in cmd:
                return 1, f"{_t} failed"
            return 0, ""

        monkeypatch.setattr(pp, "_run", fake_run)
        monkeypatch.setattr(pp, "outgoing_changed_files", lambda base_ref="x": ["replay_hold_bars.py"])
        monkeypatch.setattr(pp, "write_outgoing_diff", lambda base_ref="x": Path("nul"))
        assert pp.run_parity_gate(emit=lambda *_: None) == 1, target


# ── Hook wiring: mandatory pre-push consumption, remote suite untouched ──


def test_parity_hook_wired_mandatory_at_pre_push():
    pc = (REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "id: prepush-parity-gate" in pc
    idx_art = pc.find("id: generated-artifacts-clean-check")
    idx_par = pc.find("id: prepush-parity-gate")
    assert 0 < idx_art < idx_par, "parity gate runs after the fast gates"
    block = pc[idx_par:]
    assert "check_prepush_parity.py" in block[:600]
    assert "pre-push" in block[:600]


def test_remote_full_suite_workflows_unchanged_by_this_lane():
    wf = (REPO / ".github" / "workflows" / "pytest.yml").read_text(encoding="utf-8")
    assert "npm run test:all" in wf, "remote full suite must remain the authority"
