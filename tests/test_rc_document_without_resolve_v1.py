# institutional-synthetic-ok: inject OPEN RC parking lots + mission COMPLETE to prove RC-228 BLOCKs.
"""rc_resolve_lock library controls (RC-228).

RC-470: the commit-time registration (check_rc_document_without_resolve) is retired -
governance/retired_checks.md - so the three registration-wrapper tests left with it.
The library stays: operating_process_lock's mission-completion clause still consumes it,
and these controls pin the library's behavior.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.rc_resolve_lock as RRL  # noqa: E402


def _open_row(rc_id: str, fix: str, *, mission: str = "") -> str:
    defect = f"synthetic parking lot for {rc_id}"
    if mission:
        defect += f" (mission {mission})"
    why = (
        "(1) defect documented -> (2) no resolve path named -> (3) backlog grows -> "
        "(4) COMPLETE claimed over OPEN rows -> (5) ROOT: document-without-resolve"
    )
    return (
        f"| {rc_id} | OPEN | 2026-08-03 | 2026-08-10 | {defect} | {why} | {fix} |"
    )


def test_clause_a_blocks_open_rc_with_no_fix():
    """PROVEN BLOCK: add OPEN RC with empty/TBD fix → fail."""
    bad = RRL.added_open_rows_without_resolve([
        _open_row("RC-99901", ""),
        _open_row("RC-99902", "TBD"),
        _open_row("RC-99903", "TODO"),
    ])
    assert len(bad) >= 3
    assert any("RC-99901" in m for m in bad)
    assert any("RC-99902" in m for m in bad)


def test_clause_a_blocks_open_without_resolve_marker():
    """OPEN with prose but no FIXED:/NEXT-DEPTH:/OUT-OF-SCOPE: → fail."""
    bad = RRL.added_open_rows_without_resolve([
        _open_row("RC-99904", "will look at this later somehow"),
    ])
    assert bad and any("RC-99904" in m for m in bad)
    assert any("resolve path" in m for m in bad)


def test_clause_a_allows_open_with_fixed_or_next_depth():
    """OPEN + named resolve path is legal (front-loaded five-why before the kill lands)."""
    good = RRL.added_open_rows_without_resolve([
        _open_row("RC-99905", "FIXED: pending kill of second faucet; proof owed tonight"),
        _open_row("RC-99906", "NEXT-DEPTH: re-run scorecard under is_trading_day_et"),
        _open_row("RC-99907", "OUT-OF-SCOPE: tracked under RC-99905"),
    ])
    assert good == []


def test_clause_b_blocks_mission_done_with_open_mission_rc():
    """PROVEN BLOCK: mission→DONE while OPEN RC names that mission_id → fail."""
    mid = "drain-neg-mission-v1"
    lines = [_open_row("RC-99910", "FIXED: still open residual", mission=mid)]
    msgs = RRL.mission_complete_open_rc_violations(
        {"status": "active", "mission_id": mid},
        {"status": "DONE", "mission_id": mid},
        lines,
    )
    assert msgs and any("RC-99910" in m for m in msgs)
    assert any(mid in m for m in msgs)


def test_clause_b_allows_done_when_mission_rcs_closed():
    mid = "drain-neg-mission-v1"
    closed = (
        f"| RC-99911 | CLOSED | 2026-08-03 | 2026-08-03 | defect (mission {mid}) | "
        f"(1) a -> (2) b -> (3) c -> (4) d -> (5) ROOT: x | "
        f"FIXED: killed; END-TO-END: a->b. |"
    )
    msgs = RRL.mission_complete_open_rc_violations(
        {"status": "active", "mission_id": mid},
        {"status": "COMPLETE", "mission_id": mid},
        [closed],
    )
    assert msgs == []


def test_clause_b_allows_partial_out_of_scope_not_open():
    """PARTIAL is honest incompleteness — only OPEN blocks mission terminal."""
    mid = "drain-neg-mission-v1"
    partial = (
        f"| RC-99912 | PARTIAL | 2026-08-03 | 2026-08-10 | defect (mission {mid}) | "
        f"(1) a -> (2) b -> (3) c -> (4) d -> (5) ROOT: x | "
        f"FIXED: code path; OUT-OF-SCOPE: live restart tracked RC-99912. |"
    )
    msgs = RRL.mission_complete_open_rc_violations(
        {"status": "active", "mission_id": mid},
        {"status": "idle", "mission_id": mid},
        [partial],
    )
    assert msgs == []


def test_clause_b_escape_marker_in_staged_mission_text():
    mid = "drain-neg-mission-v1"
    lines = [_open_row("RC-99913", "FIXED: residual", mission=mid)]
    msgs = RRL.mission_complete_open_rc_violations(
        {"status": "active", "mission_id": mid},
        {"status": "DONE", "mission_id": mid},
        lines,
        staged_mission_text='# mission-rc-open-ok: operator waived quiet prove',
    )
    assert msgs == []


def test_staged_combine_blocks_parking_lot():
    """Full callee: OPEN+no-fix in added lines → violation even without mission change."""
    msgs = RRL.staged_rc_resolve_violations(
        added_rc_lines=[_open_row("RC-99920", "")],
        old_mission=None,
        new_mission=None,
        rc_file_lines=[],
    )
    assert msgs and any("RC-99920" in m for m in msgs)
