"""RC-233 PM full-prompt coverage lock — negative controls.

Operator law 2026-08-04: a PM (either agent) answering a multi-issue operator paste
must disposition EVERY distinct item (VERIFIED/ACCEPTED/REJECTED/QUEUED/BLOCKED);
headline-only replies BLOCK at Stop with deny prefix PM_COVERAGE:.

Fixtures follow reports/claude_encode_pm_full_coverage_lock.md:
  (1) multi-bullet paste + headline-only reply -> BLOCK
  (2) same paste + full coverage table -> ALLOW
  (3) single-issue chat -> ALLOW
  (4) '# pm-coverage-ok:' waiver -> ALLOW
  (5) FIXED-reach fixture: paste naming sole_writer + PDL/quiet/GO + a lock residual
  (6) live-path wiring: honesty_guard main path calls the predicate
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.operating_process_lock import (  # noqa: E402
    pm_coverage_issue_units,
    pm_coverage_violations,
)

MULTI_ISSUE_PASTE = """PM board, SLA <1h each:
1. sole_writer.json carries conflict markers again — repair and prove clean.
2. PDL on /api/levels still reads the truncated accumulator value.
3. quiet window is FAIL — do NOT claim PASS while the auth latch warns.
4. operator_go HEAD blob disagrees with the worktree — normalize it.
5. LOCK-5 remainder: the completion-claim trigger misses plain COMPLETE forms.
"""

FULL_COVERAGE_REPLY = """Coverage table:
1. sole_writer repair — VERIFIED: markers stripped, json parses, committed.
2. PDL fallthrough — ACCEPTED: floor landed, fixture green.
3. quiet window — BLOCKED: Schwab auth latch is operator-only; honest FAIL stands.
4. operator_go normalize — QUEUED: rides the next hooks-on commit.
5. LOCK-5 remainder — REJECTED: independent trigger already landed with its fixture.
"""


def test_headline_only_reply_blocks() -> None:
    bad = pm_coverage_violations(MULTI_ISSUE_PASTE, "sole_writer repaired. Done.")
    assert bad, "multi-issue paste with a headline-only reply must BLOCK"
    assert bad[0].startswith("PM_COVERAGE:"), bad[0]


def test_full_coverage_table_allows() -> None:
    assert pm_coverage_violations(MULTI_ISSUE_PASTE, FULL_COVERAGE_REPLY) == []


def test_single_issue_chat_allows() -> None:
    assert pm_coverage_violations(
        "is the chart strip rendering charm now?",
        "Yes — the strip renders the banked charm row.",
    ) == []


def test_pm_coverage_ok_waiver_allows() -> None:
    waived = MULTI_ISSUE_PASTE + "\n# pm-coverage-ok: items 3-5 deferred to Friday\n"
    assert pm_coverage_violations(waived, "sole_writer repaired. Done.") == []


def test_fixed_reach_fixture_sole_writer_pdl_quiet_go_lock_residual() -> None:
    """RC-233 FIXED reach: the exact class from the row — a paste naming sole_writer,
    PDL/quiet/GO, and a lock remainder — must BLOCK on a headline-only PM reply."""
    paste = (
        "status paste: sole_writer corruption is back; PDL residual unresolved; "
        "quiet FAIL stands; operator_go needs the GO closed; LOCK-5 remainder open; "
        "restart pending."
    )
    units = pm_coverage_issue_units(paste)
    assert len(units) >= 2, units
    bad = pm_coverage_violations(paste, "Headline: everything is basically on track.")
    assert bad and bad[0].startswith("PM_COVERAGE:")


def test_casual_two_token_sentence_does_not_block() -> None:
    """False-positive control from the encode addendum: two process tokens inside one
    conversational sentence are not a multi-issue paste."""
    assert pm_coverage_violations(
        "after the restart things went quiet, right?", "Yes — the log stayed clean."
    ) == []


def test_live_path_pm_coverage_is_retired_from_the_stop_wiring() -> None:
    """SIMPLICITY REHAB (operator full-go 2026-08-24): RC-233 PM_COVERAGE is UNWIRED
    from the Stop path — it forced disposition tokens onto chat prose, a formatting
    rule AGENTS.md assigns to operator review. The predicate above stays tested as a
    library; the Stop hook no longer calls it, and the retirement note must name it.
    The former env-off name must still never appear (a silent re-wire behind an env
    gate would be worse than either state)."""
    src = (REPO / "tools" / "honesty_guard.py").read_text(encoding="utf-8")
    assert "pm_coverage_violations(" not in src.replace(
        "# forced disposition tokens", "")  # only the retirement note may mention it
    assert "RC-233 PM_COVERAGE RETIRED" in src
    assert "ED_PM_COVERAGE_GUARD" not in src
