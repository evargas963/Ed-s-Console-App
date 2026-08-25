"""LOCK-PM-VERIFY (RC-242) — negative controls.

Operator law (2026-08-04, role-free since the 2026-08-24 teardown): a verdict about repo
state carries a same-turn reading of the repo; prose from another agent is not evidence.
These prove the lock BLOCKS an unmeasured repo verdict, PASSES a measured one, and never
punishes honest hedging — a guard that made "I have not measured this" harder to say than
"VERIFIED" would push toward exactly the false confidence it exists to stop.
(The fresh-report satisfying path and its runner were removed with the PM machinery.)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.pm_verify_lock import (  # noqa: E402
    claimed_repo_fields,
    pm_verify_repo_violations,
)

VERDICT_ON_REPO = (
    "AUDIT — Claude's land. Control table: LOCK-1..7 ON HEAD. "
    "open-class = 3. log_law ENFORCED. VERIFIED."
)


def test_verdict_on_repo_state_without_any_measure_blocks(tmp_path):
    bad = pm_verify_repo_violations(VERDICT_ON_REPO, repo=tmp_path)
    assert bad and bad[0].startswith("PM_VERIFY_REPO:")
    assert "same-turn repo measure" in bad[0]


def test_verdict_with_inline_git_evidence_passes(tmp_path):
    """Pasting what the repo said IS the law — the reading is right there in the text."""
    text = (
        "VERIFIED on HEAD: `git rev-parse HEAD` -> 3e46caf726c10cd5bcf30f41c36818d12c0e185f; "
        "`git show HEAD:governance/retired_checks.md` read back. open-class = 3."
    )
    assert pm_verify_repo_violations(text, repo=tmp_path) == []


def test_a_report_file_no_longer_launders_a_verdict(tmp_path):
    """The fresh-report path was REMOVED with its runner (2026-08-24 teardown): a JSON on
    disk is no longer a same-turn reading, so the same verdict still blocks with one."""
    p = tmp_path / "reports" / "pm_verify_latest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"measured_at_utc": 9999999999, "open_class": 3}', encoding="utf-8")
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


def test_live_wiring_into_the_stop_path():
    """Both continua run honesty_guard at Stop, so one wire binds every author alike."""
    src = (REPO / "tools" / "honesty_guard.py").read_text(encoding="utf-8")
    assert "pm_verify_repo_violations" in src
    for hooks in (".claude/settings.json", ".cursor/hooks.json"):
        cfg = (REPO / hooks).read_text(encoding="utf-8")
        assert "honesty_guard.py" in cfg, f"{hooks} does not run honesty_guard at Stop"


# ── audit round 2 (2026-08-25): evidence must be ISSUED, hedges scope per paragraph ─────

def test_mentioned_git_without_issuing_blocks(tmp_path):
    """R4: when the Stop path supplies this turn's commands, a git read merely MENTIONED
    in prose is not a reading."""
    text = ("VERIFIED on HEAD: `git rev-parse HEAD` -> "
            "3e46caf726c10cd5bcf30f41c36818d12c0e185f. open-class = 3.")
    assert pm_verify_repo_violations(text, repo=tmp_path, executed=[])
    assert pm_verify_repo_violations(
        text, repo=tmp_path, executed=["git rev-parse HEAD"]) == []


def test_bare_invocation_without_value_blocks_head_sha_claim(tmp_path):
    """P2 shape: the sha precedes the citation and no value follows it — pasted output
    naturally follows the invocation; a bare command mention does not."""
    text = ("VERIFIED: RC-450 is ON HEAD at abc1234def. "
            "I ran `git rev-parse HEAD` to confirm.")
    assert pm_verify_repo_violations(
        text, repo=tmp_path, executed=["git rev-parse HEAD"])


def test_hedge_is_paragraph_scoped(tmp_path):
    """One hedge about an unrelated topic must not neutralize a separate verdict block."""
    text = ("VERIFIED on HEAD: open-class = 3, log_law ENFORCED.\n\n"
            "Separately, the charm question stays [UNVERIFIED] pending the wide capture.")
    assert pm_verify_repo_violations(text, repo=tmp_path, executed=[])
    hedged_inline = ("Open-class on HEAD: ACCEPTED as claim, [UNVERIFIED] — "
                     "open-class = 3 per the writer's report.")
    assert pm_verify_repo_violations(hedged_inline, repo=tmp_path, executed=[]) == []
