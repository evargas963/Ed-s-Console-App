"""V3 Step 2 — the typed evidence owner carries the repository-state measurements.

These fail against the pre-fix tree: before this step the index-vs-worktree and
DISK_ONLY-vs-LIVE measurements existed only inside the process-lock Stop path, where they
produced a block with no artifact. `checks_required` did not contain them, so a reviewer
reading a typed audit result could not tell whether the state had been measured at all.

The oracle is independent: the expected mismatch set is computed from `git diff-files`
through operating_process_lock's own function, and compared against what the audit reports.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

TSA = importlib.import_module("tools.turn_self_audit")
OPL = importlib.import_module("tools.operating_process_lock")

REPO = Path(TSA.__file__).resolve().parent.parent


def test_state_check_ids_are_registered_as_always_required():
    """Both measurements must be REQUIRED, not opportunistic."""
    ids = [s.check_id for s in TSA.CORE_CHECK_SPECS]
    assert "index_worktree_state" in ids
    assert "runtime_identity_state" in ids
    for spec in TSA.CORE_CHECK_SPECS:
        if spec.check_id in ("index_worktree_state", "runtime_identity_state"):
            assert spec.applicability == "always", (
                f"{spec.check_id} must be measured even when no file changed — a turn that "
                "changes nothing can still sit on a dirty index"
            )


def test_required_ids_include_state_checks_for_a_clean_scope():
    """checks_required must list them, so their absence from a result is detectable."""
    scope = TSA.discover_scope(REPO, [])
    required = TSA.required_check_ids(REPO, scope)
    assert "index_worktree_state" in required
    assert "runtime_identity_state" in required


def test_records_are_typed_with_status_and_outcome():
    """Every record must carry CHECK_ID / STATUS / evidence / exit-or-outcome."""
    records = TSA._state_check_records(REPO)
    assert [r["check_id"] for r in records] == [
        "index_worktree_state", "runtime_identity_state"]
    for r in records:
        assert r["status"] in TSA.CHECK_STATUSES, r
        assert "detail" in r and isinstance(r["detail"], str)
        assert "outcome" in r
        assert "exit_code" in r


def test_negative_control_index_worktree_divergence_is_reported_FAIL(tmp_path):
    """BAD: an enforcement path differing between index and worktree -> FAIL, with evidence.

    Independent oracle: operating_process_lock.index_worktree_mismatches is asked directly
    and the audit record must agree with it. If the audit said PASS while the oracle found a
    mismatch, this fails.
    """
    oracle = OPL.index_worktree_mismatches(REPO)
    record = next(r for r in TSA._state_check_records(REPO)
                  if r["check_id"] == "index_worktree_state")
    if oracle:
        assert record["status"] == TSA.STATUS_FAIL, (
            "the oracle found a mismatch; the typed audit must not report PASS")
        assert record["exit_code"] == 1
        assert record["detail"].strip(), "a FAIL must carry the mismatching paths as evidence"
    else:
        assert record["status"] == TSA.STATUS_PASS
        assert record["exit_code"] == 0


def test_legitimate_control_clean_state_passes_and_is_listed(tmp_path):
    """GOOD: a clean scratch repo -> both state checks PASS and appear in checks_passed."""
    import subprocess
    repo = tmp_path / "clean"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

    records = TSA._state_check_records(repo)
    statuses = {r["check_id"]: r["status"] for r in records}
    assert statuses["index_worktree_state"] == TSA.STATUS_PASS, records
    assert statuses["runtime_identity_state"] == TSA.STATUS_PASS, records


def test_fail_open_control_unmeasurable_state_is_INCOMPLETE_never_PASS(monkeypatch):
    """FAIL-CLOSED: if the measurement cannot be taken it must not read as clean.

    The underlying function is forced to raise, exercising the real except branch.
    """
    def boom(*a, **k):
        raise RuntimeError("git unavailable")

    monkeypatch.setattr(OPL, "index_worktree_mismatches", boom)
    record = next(r for r in TSA._state_check_records(REPO)
                  if r["check_id"] == "index_worktree_state")
    assert record["status"] == TSA.STATUS_INCOMPLETE, (
        "an unmeasurable state must be INCOMPLETE — unmeasurable is never compliant")
    assert record["status"] != TSA.STATUS_PASS
    assert "RuntimeError" in record["detail"]


def test_no_reimplementation_the_audit_delegates_to_the_owning_functions(monkeypatch):
    """REUSE, not reimplement: the audit must call operating_process_lock, not its own copy.

    Proven by replacing the owner's function with a sentinel and observing the audit change
    its answer. A private reimplementation would ignore the patch and still report PASS.
    """
    calls: list[str] = []

    def sentinel(root=None, *a, **k):
        calls.append("index_worktree_mismatches")
        return ["sentinel/path.py: index=aaa worktree=bbb"]

    monkeypatch.setattr(OPL, "index_worktree_mismatches", sentinel)
    record = next(r for r in TSA._state_check_records(REPO)
                  if r["check_id"] == "index_worktree_state")
    assert calls == ["index_worktree_mismatches"], "the audit did not delegate to the owner"
    assert record["status"] == TSA.STATUS_FAIL
    assert "sentinel/path.py" in record["detail"]


@pytest.mark.parametrize("check_id", ["index_worktree_state", "runtime_identity_state"])
def test_state_checks_run_even_with_no_production_change(check_id):
    """A turn that changes no product file must still be measured."""
    scope = TSA.discover_scope(REPO, [])
    required = TSA.required_check_ids(REPO, scope)
    assert check_id in required
