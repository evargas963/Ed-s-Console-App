"""GOV_BRANCH_AUTHORIZATION_AND_MULTI_AGENT_OWNERSHIP_V1 — adversarial matrix.

Covers the mission's required cases via the module's pure functions plus
tmp-dir contract registries. Cases needing live remote infrastructure are
covered by the honest-limits artifact, not fabricated here.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import tools.mission_authorization as ma

NOW = time.time()


def _contract(**over) -> dict:
    doc = {
        "schema_version": "1",
        "mission_id": "M-TEST",
        "agent": "Claude",
        "mission_type": "feature_implementation",
        "authorized_branch": "feat-x",
        "authorized_worktree": "C:/wt/feat-x",
        "base_sha": "a" * 40,
        "authorized_push_target": "origin/feat-x",
        "target_branch": "feat-x",
        "direct_main_permission": False,
        "pr_required": True,
        "integration_owner": "OPERATOR",
        "authorized_scope": {"files": ["tools/x.py"], "semantic_domains": ["governance_gates"]},
        "shared_file_policy": "none",
        "lease_state": "active",
        "created_at_epoch": NOW,
        "expires_at_epoch": NOW + 86400,
        "operator_authorization": "operator text",
        "allowed_integration_method": "PR by operator",
        "required_checks": ["objective-audit"],
        "stop_conditions": ["red main"],
    }
    doc.update(over)
    return doc


@pytest.fixture()
def authdirs(tmp_path, monkeypatch):
    monkeypatch.setattr(ma, "ACTIVE_DIR", tmp_path / "active")
    monkeypatch.setattr(ma, "CONSUMED_DIR", tmp_path / "consumed")
    monkeypatch.setattr(ma, "INCIDENT_DIR", tmp_path / "incidents")
    (tmp_path / "active").mkdir()
    return tmp_path


def _write(authdirs: Path, doc: dict, name: str | None = None) -> None:
    (authdirs / "active" / f"{name or doc['mission_id']}.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )


# ── Cases 10-12: missing / malformed / broad-default authorization ──


def test_missing_authorization_fails(authdirs):
    c, reason = ma.load_contract("NOPE")
    assert c is None and "missing" in reason


def test_malformed_authorization_fails(authdirs):
    (authdirs / "active" / "BAD.json").write_text("{broken", encoding="utf-8")
    c, reason = ma.load_contract("BAD")
    assert c is None and "malformed" in reason


def test_missing_fields_never_default(authdirs):
    doc = _contract()
    del doc["direct_main_permission"]
    _write(authdirs, doc)
    c, reason = ma.load_contract("M-TEST")
    assert c is None and "missing fields" in reason and "no defaults" in reason


def test_broad_scope_default_refused(authdirs):
    _write(authdirs, _contract(authorized_scope="*"))
    c, reason = ma.load_contract("M-TEST")
    assert c is None and "broad defaults refused" in reason


# ── Cases 1-2, 5: main is never authorization; feature cannot carry main powers ──


def test_feature_mission_on_main_branch_refused(authdirs):
    _write(authdirs, _contract(authorized_branch="main"))
    c, reason = ma.load_contract("M-TEST")
    assert c is None and "may not target or work on main" in reason


def test_feature_mission_direct_main_permission_refused(authdirs):
    _write(authdirs, _contract(direct_main_permission=True))
    c, reason = ma.load_contract("M-TEST")
    assert c is None and "controlled_integration" in reason


# ── Case 9 + expiry/revocation ──


def test_stale_lease_fails(authdirs):
    _write(authdirs, _contract(lease_state="stale"))
    c, reason = ma.load_contract("M-TEST")
    assert c is None and "lease_state" in reason


def test_expired_authorization_fails(authdirs):
    _write(authdirs, _contract(expires_at_epoch=NOW - 10))
    c, reason = ma.load_contract("M-TEST")
    assert c is None and "EXPIRED" in reason


def test_operator_revocation_before_push(authdirs):
    _write(authdirs, _contract(lease_state="revoked"))
    c, reason = ma.load_contract("M-TEST")
    assert c is None


# ── Cases 4-7: actual destination-ref validation ──


def _lines(remote_ref: str) -> list[str]:
    return [f"refs/heads/feat-x {'b' * 40} {remote_ref} {'0' * 40}"]


def test_push_to_undeclared_branch_fails():
    errs = ma.validate_push_destination(
        _contract(), stdin_lines=_lines("refs/heads/other"), remote_url=None
    )
    assert any("!= authorized target" in e for e in errs)


def test_direct_main_push_from_feature_mission_fails():
    errs = ma.validate_push_destination(
        _contract(), stdin_lines=_lines("refs/heads/main"), remote_url=None
    )
    joined = " ".join(errs)
    assert "mission_type != controlled_integration" in joined
    assert "without explicit direct_main_permission" in joined
    assert "pr_required=true forbids" in joined


def test_controlled_integration_with_explicit_permission_passes_destination():
    c = _contract(
        mission_type="controlled_integration",
        direct_main_permission=True,
        pr_required=False,
        target_branch="main",
    )
    errs = ma.validate_push_destination(c, stdin_lines=_lines("refs/heads/main"), remote_url=None)
    assert errs == []


def test_missing_destination_refs_fail_closed():
    errs = ma.validate_push_destination(_contract(), stdin_lines=[], remote_url=None)
    assert any("fail closed" in e for e in errs)


def test_unparseable_ref_line_fails_closed():
    errs = ma.validate_push_destination(
        _contract(), stdin_lines=["garbage line"], remote_url=None
    )
    assert any("unparseable" in e for e in errs)


# ── Case 6-7: bypass-warning semantics (CAN_PUSH != AUTHORIZED_TO_PUSH) ──


def test_bypass_warning_lines_detected():
    out = (
        "Enumerating objects: 5, done.\n"
        "remote: Bypassed rule violations for refs/heads/main:\n"
        "remote: - Changes must be made through a pull request.\n"
        "To github.com:x/y.git\n"
    )
    hits = ma.classify_push_output(out)
    assert hits and any("Bypassed rule violations" in h for h in hits)


def test_clean_push_output_has_no_bypass_hits():
    assert ma.classify_push_output("To github.com:x/y.git\n   abc..def  feat-x -> feat-x\n") == []


def test_policy_violation_record_blocks_closure(authdirs):
    p = ma.record_policy_violation("M-TEST", "bypass_warning", {"lines": ["x"]})
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["closure_blocked"] is True


# ── Case 20 + red-main breaker ──


def test_red_main_breaker_blocks_until_operator_clears(authdirs):
    ma.record_policy_violation("M-TEST", "red_main", {"main_sha": "c" * 40})
    engaged, why = ma.red_main_breaker_engaged()
    assert engaged and "red-main" in why
    # operator clearance releases it
    inc = next((authdirs / "incidents").glob("*.red_main.*.json"))
    doc = json.loads(inc.read_text(encoding="utf-8"))
    doc["operator_cleared"] = True
    inc.write_text(json.dumps(doc), encoding="utf-8")
    engaged2, _ = ma.red_main_breaker_engaged()
    assert engaged2 is False


def test_feature_branch_red_ci_does_not_engage_breaker(authdirs):
    ma.record_policy_violation("M-TEST", "feature_red_ci", {"branch": "feat-x"})
    engaged, _ = ma.red_main_breaker_engaged()
    assert engaged is False, "ordinary feature-branch red CI must not trip the main breaker"


# ── Cases 16-18: single-use integration authorization ──


def test_integration_authorization_single_use(authdirs):
    c = _contract(
        mission_id="INT-1",
        mission_type="controlled_integration",
        direct_main_permission=True,
        pr_required=False,
        target_branch="main",
    )
    _write(authdirs, c, "INT-1")
    ok, msg = ma.consume_integration_authorization("INT-1")
    assert ok and msg == "consumed"
    ok2, msg2 = ma.consume_integration_authorization("INT-1")
    assert not ok2 and "already consumed" in msg2
    c3, reason3 = ma.load_contract("INT-1")
    assert c3 is None and "CONSUMED" in reason3


def test_feature_authorization_not_consumable(authdirs):
    _write(authdirs, _contract())
    ok, msg = ma.consume_integration_authorization("M-TEST")
    assert not ok and "controlled_integration" in msg


# ── Cases 13-15, 26, 30: registry overlap + unknown scope ──


def test_branch_and_worktree_collision_detected(authdirs):
    _write(authdirs, _contract())
    mine = _contract(mission_id="M-2")
    errs = ma.detect_mission_overlap(mine)
    joined = " ".join(errs)
    assert "branch collision" in joined and "worktree collision" in joined


def test_file_and_semantic_overlap_detected(authdirs):
    _write(authdirs, _contract())
    mine = _contract(
        mission_id="M-2", authorized_branch="feat-y", authorized_worktree="C:/wt/feat-y"
    )
    errs = ma.detect_mission_overlap(mine)
    joined = " ".join(errs)
    assert "file overlap" in joined and "semantic domain overlap" in joined


def test_sibling_with_undeclared_scope_stops(authdirs):
    other = _contract(mission_id="M-OLD", authorized_branch="feat-z",
                      authorized_worktree="C:/wt/z", authorized_scope={})
    (authdirs / "active" / "M-OLD.json").write_text(json.dumps(other), encoding="utf-8")
    mine = _contract(mission_id="M-2", authorized_branch="feat-y",
                     authorized_worktree="C:/wt/y",
                     authorized_scope={"files": ["a.py"], "semantic_domains": []})
    errs = ma.detect_mission_overlap(mine)
    assert any("UNDECLARED scope" in e for e in errs)


def test_unknown_semantic_domain_fails_closed(authdirs):
    mine = _contract(
        mission_id="M-2",
        authorized_scope={"files": [], "semantic_domains": ["totally_new_domain"]},
    )
    errs = ma.detect_mission_overlap(mine)
    assert any("unknown semantic domain" in e.lower() for e in errs)


def test_unreadable_sibling_contract_fails_closed(authdirs):
    (authdirs / "active" / "CORRUPT.json").write_text("{bad", encoding="utf-8")
    errs = ma.detect_mission_overlap(_contract(mission_id="M-2"))
    assert any("unreadable sibling" in e for e in errs)


# ── Case: prompt/mission-document completeness lock ──


def test_mission_document_missing_fields_rejected():
    errs = ma.validate_mission_document_text("MISSION = X\nsome text")
    assert len(errs) >= 8


def test_mission_document_branch_may_not_be_main_or_current():
    text = (
        "AUTHORIZED_AGENT = Claude\nAUTHORIZED_FEATURE_BRANCH = main\n"
        "AUTHORIZED_WORKTREE = w\nEXPECTED_BASE_SHA = abc\n"
        "AUTHORIZED_PUSH_TARGET = origin/x\nDIRECT_MAIN_PUSH = FORBIDDEN\n"
        "PR_REQUIRED = YES\nMAIN_INTEGRATION_OWNER = OPERATOR\n"
    )
    errs = ma.validate_mission_document_text(text)
    assert any("explicit non-main branch" in e for e in errs)


def test_complete_mission_document_passes():
    text = (
        "AUTHORIZED_AGENT = Claude\nAUTHORIZED_FEATURE_BRANCH = gov-x-v1\n"
        "AUTHORIZED_WORKTREE = C:/wt/x\nEXPECTED_BASE_SHA = abc123\n"
        "AUTHORIZED_PUSH_TARGET = origin/gov-x-v1\nDIRECT_MAIN_PUSH = FORBIDDEN\n"
        "PR_REQUIRED = YES\nMAIN_INTEGRATION_OWNER = OPERATOR\n"
    )
    assert ma.validate_mission_document_text(text) == []


# ── Windows/POSIX + this mission's own live contract (dogfood) ──


def test_worktree_comparison_normalizes_separators(authdirs, monkeypatch):
    c = _contract(authorized_worktree="C:\\wt\\feat-x")
    monkeypatch.setattr(ma, "_git", lambda args, cwd=None: {
        ("branch", "--show-current"): "feat-x",
        ("rev-parse", "--show-toplevel"): "C:/wt/feat-x",
        ("rev-parse", "HEAD"): "b" * 40,
    }.get(tuple(args), ""))
    monkeypatch.setattr(ma.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 0})())
    errs = ma.validate_workspace(c, cwd=Path("."))
    assert not any("worktree" in e for e in errs)


def test_live_mission_contracts_are_valid_and_loadable():
    """Dogfood: EVERY contract in the live active registry must load through the
    fail-closed loader, and no feature mission may carry main powers. Retired
    contracts (moved to consumed/) must refuse to load. Generic over mission ids
    so completing one mission never breaks this lock."""
    live = sorted(ma.ACTIVE_DIR.glob("*.json")) if ma.ACTIVE_DIR.is_dir() else []
    for p in live:
        doc = json.loads(p.read_text(encoding="utf-8"))
        c, reason = ma.load_contract(doc["mission_id"])
        assert c is not None, f"{p.name}: {reason}"
        if c["mission_type"] != "controlled_integration":
            assert c["direct_main_permission"] is False, p.name
            assert c["pr_required"] is True, p.name
    consumed_dir = ma.ACTIVE_DIR.parent / "consumed"
    for p in sorted(consumed_dir.glob("*.json")) if consumed_dir.is_dir() else []:
        doc = json.loads(p.read_text(encoding="utf-8"))
        c, reason = ma.load_contract(doc["mission_id"])
        assert c is None, f"retired contract {p.name} must refuse to load"

def test_mission_authorization_hooks_stay_wired():
    """Recurrence lock (Phase 12): removing either mission-authorization hook
    from .pre-commit-config.yaml, or the breaker/single-use surface from the
    module, must turn this suite red — silent de-wiring is the incident class
    this mission exists to prevent."""
    cfg = (ma.REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "mission-authorization-precommit" in cfg
    assert "mission-authorization-prepush" in cfg
    assert "tools/check_mission_authorization.py" in cfg
    assert callable(ma.red_main_breaker_engaged)
    assert callable(ma.consume_integration_authorization)


def test_precommit_env_channel_reconstructs_destination(monkeypatch, authdirs, capsys):
    """pre-commit consumes git's pre-push stdin; the CLI must reconstruct the
    destination from PRE_COMMIT_* env vars — and still refuse when BOTH
    channels are absent (fail-closed, proven live on the first push attempt)."""
    import io as _io
    import sys as _sys

    import tools.check_mission_authorization as cli

    _write(authdirs, _contract(mission_id="ENVTEST", authorized_branch="feat-x"))
    monkeypatch.setenv("ED_MISSION_ID", "ENVTEST")
    monkeypatch.setattr(cli, "validate_workspace", lambda c, cwd: [])
    monkeypatch.setattr(cli, "detect_mission_overlap", lambda c: [])
    monkeypatch.setattr(cli, "red_main_breaker_engaged", lambda: (False, ""))
    monkeypatch.setattr(cli, "load_contract", lambda mid: ma.load_contract(mid))
    # env channel present: wrong destination refused
    monkeypatch.setenv("PRE_COMMIT_LOCAL_BRANCH", "refs/heads/feat-x")
    monkeypatch.setenv("PRE_COMMIT_REMOTE_BRANCH", "refs/heads/main")
    monkeypatch.setattr(_sys, "stdin", _io.StringIO(""))
    assert cli.main(["--pre-push"]) == 1
    # env channel present: authorized destination passes
    monkeypatch.setenv("PRE_COMMIT_REMOTE_BRANCH", "refs/heads/feat-x")
    monkeypatch.setattr(_sys, "stdin", _io.StringIO(""))
    assert cli.main(["--pre-push"]) == 0
    # both channels absent: refuse
    monkeypatch.delenv("PRE_COMMIT_LOCAL_BRANCH")
    monkeypatch.delenv("PRE_COMMIT_REMOTE_BRANCH")
    monkeypatch.setattr(_sys, "stdin", _io.StringIO(""))
    assert cli.main(["--pre-push"]) == 1
