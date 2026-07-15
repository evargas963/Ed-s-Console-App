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
        "worktree_lease_sha256": "ab" * 32,
        "authorized_remote": "https://github.com/example-org/example-repo.git",
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
    assert "branch collision" in joined and "worktree lease collision" in joined


def test_file_and_semantic_overlap_detected(authdirs):
    _write(authdirs, _contract())
    mine = _contract(
        mission_id="M-2", authorized_branch="feat-y", worktree_lease_sha256="cd" * 32
    )
    errs = ma.detect_mission_overlap(mine)
    joined = " ".join(errs)
    assert "file overlap" in joined and "semantic domain overlap" in joined


def test_sibling_with_undeclared_scope_stops(authdirs):
    other = _contract(mission_id="M-OLD", authorized_branch="feat-z",
                      worktree_lease_sha256="ee" * 32, authorized_scope={})
    (authdirs / "active" / "M-OLD.json").write_text(json.dumps(other), encoding="utf-8")
    mine = _contract(mission_id="M-2", authorized_branch="feat-y",
                     worktree_lease_sha256="ff" * 32,
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


# ── Path-free worktree lease binding (PR41 privacy root cause) ──
# The contract must never carry an absolute worktree path; identity is proven
# by POSSESSION of the untracked lease nonce in the worktree's private git dir
# plus the public authorized_remote repository binding. Fictional paths only.

_TEST_REMOTE = "https://github.com/example-org/example-repo.git"


def _tmp_repo(base: Path, name: str = "repo", branch: str = "feat-x",
              remote: str | None = _TEST_REMOTE) -> Path:
    import subprocess as sp

    repo = base / name
    repo.mkdir()

    def run(*a):
        sp.run(["git", *a], cwd=repo, capture_output=True, text=True, check=True)

    run("init", "-q", "-b", branch)
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (repo / "x.txt").write_text("x", encoding="utf-8")
    run("add", "x.txt")
    run("commit", "-q", "-m", "seed")
    if remote:
        run("remote", "add", "origin", remote)
    return repo


def _head(repo: Path) -> str:
    import subprocess as sp

    return sp.run(["git", "rev-parse", "HEAD"], cwd=repo,
                  capture_output=True, text=True, check=True).stdout.strip()


def _leased_contract(repo: Path, **over) -> dict:
    sha = ma.create_worktree_lease("M-TEST", repo)
    return _contract(worktree_lease_sha256=sha, base_sha=_head(repo), **over)


def test_lease_happy_path_authorizes_exact_worktree(tmp_path):
    repo = _tmp_repo(tmp_path)
    c = _leased_contract(repo)
    assert ma.validate_workspace(c, cwd=repo) == []


def test_missing_lease_fails_closed(tmp_path):
    repo = _tmp_repo(tmp_path)
    c = _contract(base_sha=_head(repo))  # pin never minted here
    errs = ma.validate_workspace(c, cwd=repo)
    assert any("lease MISSING" in e for e in errs)


def test_wrong_lease_sha_fails_closed(tmp_path):
    repo = _tmp_repo(tmp_path)
    ma.create_worktree_lease("M-TEST", repo)
    c = _contract(worktree_lease_sha256="12" * 32, base_sha=_head(repo))
    errs = ma.validate_workspace(c, cwd=repo)
    assert any("MISMATCH" in e for e in errs)


def test_copied_contract_in_another_clone_fails_closed(tmp_path):
    """The core threat: same branch, same remote, but the second clone cannot
    present the lease nonce minted in the authorized worktree."""
    repo_a = _tmp_repo(tmp_path, "a")
    repo_b = _tmp_repo(tmp_path, "b")
    c = _leased_contract(repo_a)
    c["base_sha"] = _head(repo_b)
    errs = ma.validate_workspace(c, cwd=repo_b)
    assert any("lease MISSING" in e for e in errs)


def test_wrong_repository_remote_fails_closed(tmp_path):
    repo = _tmp_repo(tmp_path, remote="https://github.com/example-org/OTHER-repo.git")
    c = _leased_contract(repo)
    errs = ma.validate_workspace(c, cwd=repo)
    assert any("wrong repository" in e for e in errs)


def test_missing_remote_fails_closed(tmp_path):
    repo = _tmp_repo(tmp_path, remote=None)
    c = _leased_contract(repo)
    errs = ma.validate_workspace(c, cwd=repo)
    assert any("cannot be proven" in e for e in errs)


def test_remote_normalization_tolerates_git_suffix_slash_and_case(tmp_path):
    repo = _tmp_repo(tmp_path, remote="https://github.com/Example-Org/Example-Repo")
    c = _leased_contract(repo, authorized_remote="https://github.com/example-org/example-repo.git/")
    errs = ma.validate_workspace(c, cwd=repo)
    assert not any("repository" in e for e in errs)


def test_detached_head_fails_branch_binding(tmp_path):
    import subprocess as sp

    repo = _tmp_repo(tmp_path)
    c = _leased_contract(repo)
    sp.run(["git", "checkout", "-q", "--detach"], cwd=repo, capture_output=True, check=True)
    errs = ma.validate_workspace(c, cwd=repo)
    assert any("authorized" in e and "branch" in e for e in errs)


def test_relocated_worktree_keeps_authorization(tmp_path):
    """No path is compared, so a legitimate relocation keeps working: the lease
    travels with the repository's private git dir."""
    repo = _tmp_repo(tmp_path)
    c = _leased_contract(repo)
    moved = tmp_path / "moved-elsewhere"
    repo.rename(moved)
    assert ma.validate_workspace(c, cwd=moved) == []


def test_environment_override_cannot_replace_lease(tmp_path, monkeypatch):
    repo = _tmp_repo(tmp_path)
    c = _contract(base_sha=_head(repo))
    monkeypatch.setenv("ED_MISSION_ID", "M-TEST")
    monkeypatch.setenv("AUTHORIZED_WORKTREE", str(repo))
    errs = ma.validate_workspace(c, cwd=repo)
    assert any("lease MISSING" in e for e in errs)


def test_legacy_private_path_contract_refused(authdirs):
    doc = _contract()
    doc["authorized_worktree"] = "C:/wt/feat-x"
    _write(authdirs, doc)
    c, reason = ma.load_contract("M-TEST")
    assert c is None and "legacy private-path field" in reason


def test_malformed_lease_pin_refused(authdirs):
    _write(authdirs, _contract(worktree_lease_sha256="not-a-sha"))
    c, reason = ma.load_contract("M-TEST")
    assert c is None and "64-hex" in reason


def test_missing_authorized_remote_refused(authdirs):
    _write(authdirs, _contract(authorized_remote=""))
    c, reason = ma.load_contract("M-TEST")
    assert c is None and "authorized_remote" in reason


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
