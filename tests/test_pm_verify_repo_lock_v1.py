"""LOCK-PM-VERIFY (RC-242) — negative controls.

Operator law: the PM/auditor verifies material claims against the repo, same turn; prose from
the writer is not evidence. These prove the lock BLOCKS an unmeasured repo verdict, PASSES a
measured one, and never punishes honest hedging — a guard that made "I have not measured this"
harder to say than "VERIFIED" would push toward exactly the false confidence it exists to stop.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.pm_verify_lock import (  # noqa: E402
    FRESH_WINDOW_SEC,
    REPORT_REL,
    claimed_repo_fields,
    fresh_measurement,
    pm_verify_repo_violations,
)

VERDICT_ON_REPO = (
    "AUDIT — Claude's land. Control table: LOCK-1..7 ON HEAD. "
    "open-class = 3. log_law ENFORCED. VERIFIED."
)


def _write_report(root: Path, age_sec: float = 0.0) -> Path:
    p = root / REPORT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "measured_at_utc": time.time() - age_sec,
        "head_sha": "3e46caf726c10cd5bcf30f41c36818d12c0e185f",
        "open_class": 3,
        "go_granted": False,
        "on_head": {"log_law_enforced": True},
    }), encoding="utf-8")
    return p


def test_verdict_on_repo_state_without_any_measure_blocks(tmp_path):
    bad = pm_verify_repo_violations(VERDICT_ON_REPO, repo=tmp_path)
    assert bad and bad[0].startswith("PM_VERIFY_REPO:")
    assert "same-turn repo measure" in bad[0]


def test_verdict_with_inline_git_evidence_passes(tmp_path):
    """Pasting what the repo said IS the law — the reading is right there in the text."""
    text = (
        "VERIFIED on HEAD: `git rev-parse HEAD` -> 3e46caf726c10cd5bcf30f41c36818d12c0e185f; "
        "`git show HEAD:governance/operator_go.json` -> granted=false. open-class = 3."
    )
    assert pm_verify_repo_violations(text, repo=tmp_path) == []


def test_verdict_with_fresh_measurement_file_passes(tmp_path):
    _write_report(tmp_path, age_sec=10.0)
    assert pm_verify_repo_violations(VERDICT_ON_REPO, repo=tmp_path) == []


def test_stale_measurement_does_not_launder_a_verdict(tmp_path):
    """A measurement from hours ago is how yesterday's truth gets published as today's."""
    _write_report(tmp_path, age_sec=FRESH_WINDOW_SEC + 600.0)
    bad = pm_verify_repo_violations(VERDICT_ON_REPO, repo=tmp_path)
    assert bad and bad[0].startswith("PM_VERIFY_REPO:")


def test_hedged_prose_is_always_legal(tmp_path):
    for hedged in (
        "ACCEPTED as claim — [UNVERIFIED] pending verification against HEAD.",
        "Claude reports open-class = 3 on HEAD; ACCEPTED as claim, not measured this turn.",
        "COMPLETE per Claude's report — UNVERIFIED, I have not measured HEAD myself.",
    ):
        assert pm_verify_repo_violations(hedged, repo=tmp_path) == [], hedged


def test_verdict_about_prose_is_not_this_locks_business(tmp_path):
    """A verdict that asserts nothing about the tree must pass — scope discipline."""
    assert pm_verify_repo_violations(
        "ACCEPTED — your reasoning about the trade-off is sound and I agree with it.",
        repo=tmp_path) == []


def test_no_verdict_no_block(tmp_path):
    assert pm_verify_repo_violations(
        "open-class is 3 and log_law is ENFORCED on HEAD, for what it is worth.",
        repo=tmp_path) == []


def test_operator_escape(tmp_path):
    assert pm_verify_repo_violations(
        VERDICT_ON_REPO + "\n# pm-verify-ok: operator waived for this handoff",
        repo=tmp_path) == []


def test_env_kill_switch_does_not_disable(tmp_path, monkeypatch):
    monkeypatch.setenv("ED_PM_VERIFY_LOCK", "off")
    assert pm_verify_repo_violations(VERDICT_ON_REPO, repo=tmp_path)


def test_claimed_fields_are_named_so_the_block_is_actionable():
    fields = claimed_repo_fields(VERDICT_ON_REPO)
    assert "on_head" in fields and "open_class" in fields and "enforced" in fields


def test_fresh_measurement_rejects_a_report_with_no_timestamp(tmp_path):
    p = tmp_path / REPORT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"head_sha": "deadbeef"}), encoding="utf-8")
    assert fresh_measurement(tmp_path) is None


def test_live_wiring_into_the_stop_path():
    """Both continua run honesty_guard at Stop, so one wire binds PM and writer alike."""
    src = (REPO / "tools" / "honesty_guard.py").read_text(encoding="utf-8")
    assert "pm_verify_repo_violations" in src
    for hooks in (".claude/settings.json", ".cursor/hooks.json"):
        cfg = (REPO / hooks).read_text(encoding="utf-8")
        assert "honesty_guard.py" in cfg, f"{hooks} does not run honesty_guard at Stop"


def test_the_measurement_tool_reads_the_committed_tree_not_the_worktree():
    """The whole point: 'it works on my disk' is the claim that keeps being wrong."""
    src = (REPO / "tools" / "pm_verify_repo.py").read_text(encoding="utf-8")
    assert 'f"HEAD:{rel}"' in src, "pm_verify_repo must read HEAD blobs, not worktree files"
