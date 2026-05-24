"""Paired test for tools/check_fix_everything_we_touch.py (AGENTS top rule)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import check_fix_everything_we_touch as mod  # noqa: E402


def test_commit_message_meta_describing_checker_passes(tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(
        "Mechanical lock — commit-message guard blocks read-only investigation "
        "and memo-only admissible when code edit is known.\n",
        encoding="utf-8",
    )
    assert mod.check_commit_message(msg) == []


@pytest.mark.parametrize(
    "phrase",
    [
        "CSV re-check was a read-only investigation.",
        "Investigation only — no code changes.",
        "Investigation complete with no fix required.",
        "No further code change needed on this path.",
        "Memo-only admissible for this walk.",
        "Flagged the FIND without landing the fix.",
    ],
)
def test_commit_message_investigation_only_phrases_fail(phrase: str, tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(phrase, encoding="utf-8")
    hits = mod.check_commit_message(msg)
    assert hits, f"expected investigation-only hit for: {phrase!r}"


def test_actionable_code_edit_detection() -> None:
    assert not mod.is_actionable_code_edit("none.")
    assert not mod.is_actionable_code_edit("none")
    assert not mod.is_actionable_code_edit("landed — removed fallbacks.")
    assert mod.is_actionable_code_edit("deferred — add provider wrappers.")


def test_v4_memo_blocks_actionable_code_edit_without_staged_py(tmp_path: Path) -> None:
    memo = tmp_path / "live_market_plane.py.md"
    memo.write_text(
        "- **code edit:** proposed — remove non-canonical BID/ASK fallbacks.\n",
        encoding="utf-8",
    )
    hits = mod.check_v4_memo(memo, staged={"governance/SCHWAB_V4_REVIEW_MEMOS/live_market_plane.py.md"})
    assert len(hits) == 1
    assert "live_market_plane.py" in hits[0]


def test_v4_memo_passes_when_py_staged(tmp_path: Path) -> None:
    memo = tmp_path / "live_market_plane.py.md"
    memo.write_text(
        "- **code edit:** proposed — remove non-canonical BID/ASK fallbacks.\n",
        encoding="utf-8",
    )
    hits = mod.check_v4_memo(
        memo,
        staged={
            "governance/SCHWAB_V4_REVIEW_MEMOS/live_market_plane.py.md",
            "live_market_plane.py",
            "tests/test_live_market_plane_streaming.py",
        },
    )
    assert hits == []


def test_v4_memo_landed_code_edit_passes_without_py(tmp_path: Path) -> None:
    memo = tmp_path / "live_market_plane.py.md"
    memo.write_text(
        "- **code edit:** landed — fallbacks removed.\n",
        encoding="utf-8",
    )
    hits = mod.check_v4_memo(memo, staged={"governance/SCHWAB_V4_REVIEW_MEMOS/live_market_plane.py.md"})
    assert hits == []


def test_open_audit_catch_requires_py(tmp_path: Path) -> None:
    memo = tmp_path / "order_flow_engine.py.md"
    memo.write_text(
        "**Audit catch flagged (S2a):** bare bidSize on streaming content.\n",
        encoding="utf-8",
    )
    hits = mod.check_v4_memo(memo, staged={"governance/SCHWAB_V4_REVIEW_MEMOS/order_flow_engine.py.md"})
    assert hits


def test_agents_md_documents_top_rule() -> None:
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Do not lie to the operator" in text
    assert "## Fix everything we touch" in text
    assert "## Self-governance quality loop" in text


def test_commit_message_do_not_lie_meta_describing_checker_passes(tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(
        "Partial coverage — commit-msg guard for unverified claim patterns (verified without evidence).\n",
        encoding="utf-8",
    )
    assert mod.check_commit_message(msg) == []


@pytest.mark.parametrize(
    "phrase",
    [
        "Verified the bid fix end-to-end.",
        "Confirmed all sites clean.",
        "This guarantees no regression.",
        "All clear on wire reads.",
    ],
)
def test_commit_message_unverified_claim_phrases_fail(phrase: str, tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(phrase, encoding="utf-8")
    hits = mod.check_commit_message(msg)
    assert hits, f"expected unverified-claim hit for: {phrase!r}"


@pytest.mark.parametrize(
    "phrase",
    [
        "Verified bid fix @ 71dafb2 in live_decision_bundle.py:120",
        "Confirmed via tests/test_live_market_plane_streaming.py",
        "pytest green — guarantees cited in tests/test_foo.py:42",
    ],
)
def test_commit_message_unverified_claim_with_evidence_passes(phrase: str, tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(phrase, encoding="utf-8")
    assert mod.check_commit_message(msg) == []
