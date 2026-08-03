# institutional-synthetic-ok: inject index≠WT and sole-writer violations to prove RC-217 BLOCKs.
"""Operating process lock — negative controls + quiet paths (RC-217)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.operating_process_lock as OPL  # noqa: E402
import tools.process_lock_guard as PLG  # noqa: E402


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "governance").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tools").mkdir(parents=True, exist_ok=True)
    checker = tmp_path / "tools" / "check_institutional_correctness.py"
    checker.write_text(
        'CHECKS = [\n    ("old_check", None, True),\n]\n',
        encoding="utf-8",
    )
    (tmp_path / "db.py").write_text("# RC-183\nis_collect_window_bar_end_ts_utc\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_sole_writer_blocks_cursor_on_db():
    msg = OPL.sole_writer_edit_violation("db.py", agent="cursor")
    assert msg and ("sole_writer" in msg or "PM-FIRST" in msg)


def test_sole_writer_allows_writer_agent():
    assert OPL.sole_writer_edit_violation("db.py", agent="claude") is None


def test_sole_writer_allows_governance_process_files():
    assert OPL.sole_writer_edit_violation("governance/sole_writer.json", agent="cursor") is None


def test_index_worktree_mismatch_detected(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    checker = repo / "tools" / "check_institutional_correctness.py"
    checker.write_text(checker.read_text(encoding="utf-8") + "\n# wt delta\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    mism = OPL.index_worktree_mismatches(repo)
    assert any("index≠WT" in m or "worktree=" in m for m in mism)


def test_index_parity_passes_when_clean(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    assert OPL.index_worktree_mismatches(repo) == []


def test_staged_checks_not_on_head_flags_delta(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    checker = repo / "tools" / "check_institutional_correctness.py"
    checker.write_text(
        'CHECKS = [\n    ("old_check", None, True),\n    ("new_lock", None, True),\n]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", checker], cwd=repo, check=True, capture_output=True)
    monkeypatch.chdir(repo)
    v = OPL.staged_enforced_checks_not_on_head(repo)
    assert v and "new_lock" in v[0]


def test_operator_go_suppresses_staged_check_block(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    go = repo / "governance" / "operator_go.json"
    go.write_text(
        json.dumps({"granted": True, "scope": ["staged_lock_surface"]}),
        encoding="utf-8",
    )
    checker = repo / "tools" / "check_institutional_correctness.py"
    checker.write_text(
        'CHECKS = [\n    ("brand_new", None, True),\n]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", checker], cwd=repo, check=True, capture_output=True)
    monkeypatch.setattr(OPL, "OPERATOR_GO_PATH", go)
    assert OPL.operator_go_granted("staged_lock_surface")
    assert OPL.commit_violations(repo) == [] or not any("brand_new" in x for x in OPL.commit_violations(repo))


def test_completion_claim_blocks_on_index_mismatch(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    checker = repo / "tools" / "check_institutional_correctness.py"
    checker.write_text(checker.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    monkeypatch.setattr(OPL, "REPO", repo)
    text = "We have one intentional tree ready to commit — all green."
    v = OPL.completion_claim_violations(text, repo)
    assert v and any("index≠WT" in x or "worktree" in x for x in v)


def test_live_claim_requires_disk_only_token_when_disk_only(monkeypatch):
    monkeypatch.setattr(
        OPL,
        "live_collect_disk_only",
        lambda repo=None, port=8000: "DISK_ONLY: pid old",
    )
    monkeypatch.setattr(OPL, "index_worktree_mismatches", lambda repo=None, **kw: [])
    bad = OPL.completion_claim_violations("Collect gate is LIVE_ENFORCED now.", OPL.REPO)
    assert bad and "LIVE_ENFORCED" in bad[0] or "DISK_ONLY" in bad[0]
    ok = OPL.completion_claim_violations(
        "DISK_ONLY_UNTIL_RESTART — gate on disk only.", OPL.REPO
    )
    assert not any("LIVE_ENFORCED" in x for x in ok)


def test_pretooluse_hook_blocks_sole_writer_edit(monkeypatch):
    # Pin the role: the block is for the NON-writer. Ambient env now declares the real
    # agent (ED_AGENT_ROLE=claude in .claude/settings.json), so the test must not inherit it.
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    bad = PLG.pretooluse_block("Write", {"file_path": str(ROOT / "db.py")})
    assert bad and any("sole_writer" in b or "PM-FIRST" in b for b in bad)


def test_pretooluse_hook_permits_sole_writer_edit(monkeypatch):
    # The named writer is NOT blocked on the same protected path (RC-217 negative control).
    monkeypatch.setenv("ED_AGENT_ROLE", "claude")
    bad = PLG.pretooluse_block("Write", {"file_path": str(ROOT / "db.py")})
    assert not [b for b in bad if "sole_writer" in b or "PM-FIRST" in b]


def test_pm_mission_idle_blocks_product_edit(monkeypatch, tmp_path):
    monkeypatch.setenv("ED_AGENT_ROLE", "claude")
    monkeypatch.delenv("ED_PM_MISSION_GUARD", raising=False)
    mission = tmp_path / "pm_mission.json"
    mission.write_text('{"status": "idle", "writer": "claude", "scope_paths": ["*"]}', encoding="utf-8")
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", mission)
    msg = OPL.pm_mission_edit_violation("db.py", agent="claude")
    assert msg and "PM-FIRST" in msg and "idle" in msg


def test_pm_mission_active_allows_scoped_writer(monkeypatch, tmp_path):
    monkeypatch.setenv("ED_AGENT_ROLE", "claude")
    mission = tmp_path / "pm_mission.json"
    mission.write_text(
        json.dumps(
            {
                "status": "active",
                "writer": "claude",
                "scope_paths": ["static/"],
                "mission_id": "ui-test",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", mission)
    assert OPL.pm_mission_edit_violation("static/index.html", agent="claude") is None
    assert OPL.pm_mission_edit_violation("db.py", agent="claude") is not None


def test_measure_report_has_enforcement_hashes():
    rep = OPL.measure_report()
    assert "enforcement_hashes" in rep
    assert "sole_writer" in rep
    assert "pm_mission" in rep


def test_main_precommit_exits_zero_on_clean_repo(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(OPL, "REPO", repo)
    monkeypatch.setattr(OPL, "SOLE_WRITER_PATH", repo / "governance" / "sole_writer.json")
    monkeypatch.setattr(OPL, "OPERATOR_GO_PATH", repo / "governance" / "operator_go.json")
    rc = OPL.main(["--pre-commit"])
    assert rc == 0
