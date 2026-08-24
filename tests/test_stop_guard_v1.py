"""RC-72: the Stop guard must refuse a turn that ends with self-declared unfinished work.

Every other lock in this repo fires on an ACTION. The agent's most damaging failure is the
ABSENCE of one — writing a summary that ends in "next: X" and stopping. No PreToolUse hook can
catch that, because no tool is called. Observed repeatedly 2026-07-27, including immediately
after the agent wrote "I'm not stopping here. Building the Stop hook now." and then stopped.
"""
from __future__ import annotations

import datetime

import tools.stop_guard as sg

TODAY = datetime.date.today().isoformat()


def _write_log(tmp_path, rows: list[str], monkeypatch):
    g = tmp_path / "governance"
    g.mkdir(exist_ok=True)
    p = g / "root_cause_log.md"
    p.write_text("| id | status | opened | due | defect | why | fix |\n" + "\n".join(rows) + "\n",
                 encoding="utf-8")
    monkeypatch.setattr(sg, "RC_LOG", p)
    return p


def test_blocks_when_a_row_opened_today_is_still_in_progress(tmp_path, monkeypatch):
    _write_log(tmp_path, [
        f"| RC-90 | OPEN | {TODAY} | 2099-01-01 | d | (1)->(5) ROOT: x | IN PROGRESS: half built |",
    ], monkeypatch)
    rows = sg.unfinished_rows_opened_today(TODAY)
    assert [r[0] for r in rows] == ["RC-90"]
    assert rows[0][1] == "IN PROGRESS"


def test_recognises_every_unfinished_marker(tmp_path, monkeypatch):
    _write_log(tmp_path, [
        f"| RC-91 | OPEN | {TODAY} | 2099-01-01 | d | w | VERIFICATION PENDING |",
        f"| RC-92 | OPEN | {TODAY} | 2099-01-01 | d | w | NOT FIXED - scoped |",
        f"| RC-93 | OPEN | {TODAY} | 2099-01-01 | d | w | PARTIALLY FIXED, rest open |",
    ], monkeypatch)
    assert {r[0] for r in sg.unfinished_rows_opened_today(TODAY)} == {"RC-91", "RC-92", "RC-93"}


def test_does_not_block_on_closed_or_finished_rows(tmp_path, monkeypatch):
    _write_log(tmp_path, [
        f"| RC-94 | CLOSED | {TODAY} | 2099-01-01 | d | w | MEASURED 5 tests. END-TO-END: a->b |",
        f"| RC-95 | OPEN | {TODAY} | 2099-01-01 | d | w | blocked on operator decision, due dated |",
    ], monkeypatch)
    assert sg.unfinished_rows_opened_today(TODAY) == []


def test_ignores_unfinished_rows_from_earlier_days(tmp_path, monkeypatch):
    """An older OPEN row is a dated backlog item — check_root_cause_log already fails a commit
    when it goes overdue. This guard is about work started and abandoned WITHIN a session."""
    _write_log(tmp_path, [
        "| RC-96 | OPEN | 2020-01-01 | 2099-01-01 | d | w | IN PROGRESS from long ago |",
    ], monkeypatch)
    assert sg.unfinished_rows_opened_today(TODAY) == []


def test_missing_log_is_never_a_block(tmp_path, monkeypatch):
    monkeypatch.setattr(sg, "RC_LOG", tmp_path / "nope" / "root_cause_log.md")
    assert sg.unfinished_rows_opened_today(TODAY) == []


def test_guard_honours_stop_hook_active_so_a_turn_can_always_end(monkeypatch):
    """A guard that cannot be satisfied is a hang, not a control."""
    import io

    monkeypatch.setattr(sg.sys, "stdin", io.StringIO('{"stop_hook_active": true}'))
    assert sg.main() == 0


def test_env_off_does_not_disable_unfinished_row_block(tmp_path, monkeypatch):
    import io

    _write_log(tmp_path, [
        f"| RC-90 | OPEN | {TODAY} | 2099-01-01 | d | (1)->(5) ROOT: x | IN PROGRESS: half built |",
    ], monkeypatch)
    monkeypatch.setenv("ED_STOP_GUARD", "off")
    monkeypatch.setattr(sg.sys, "stdin", io.StringIO('{"stop_hook_active": false}'))
    assert sg.main() == 2


# RC-470: the faucet (RC-73), freshness (RC-94/RC-235) and close-contract (RC-106)
# turn-end duties were removed from the guard with their equivalents named in
# tools/stop_guard.py and governance/retired_checks.md; their seams left with them.
# RC-72 - the guard's founding duty - is fully covered above.
