"""RC-72: the Stop guard must refuse a turn that ends with self-declared unfinished work.

Every other lock in this repo fires on an ACTION. The agent's most damaging failure is the
ABSENCE of one — writing a summary that ends in "next: X" and stopping. No PreToolUse hook can
catch that, because no tool is called. Observed repeatedly 2026-07-27, including immediately
after the agent wrote "I'm not stopping here. Building the Stop hook now." and then stopped.
"""
from __future__ import annotations

import datetime

import tools.mission_latch as ml
import tools.stop_guard as sg

TODAY = datetime.date.today().isoformat()


def _write_log(tmp_path, rows: list[str], monkeypatch):
    g = tmp_path / "governance"
    g.mkdir(exist_ok=True)
    p = g / "root_cause_log.md"
    p.write_text("| id | status | opened | due | defect | why | fix |\n" + "\n".join(rows) + "\n",
                 encoding="utf-8")
    # RC-498 moved the ledger parser into tools/mission_latch.py so the repository holds ONE
    # row scan; stop_guard reads it from there, so that is where the redirect belongs. RC-500
    # made the ledger resolve from the repo that owns the target, so `ledger_path` is patched
    # too — a patched constant alone would be bypassed once a real path is passed. Rows written
    # here count as this worktree's own; the authority tests live in the latch suite.
    monkeypatch.setattr(ml, "RC_LOG", p)
    monkeypatch.setattr(ml, "ledger_path", lambda repo=None: p)
    monkeypatch.setattr(ml, "_rows_this_worktree_introduced",
                        lambda repo=None: {r.rc_id for r in ml.all_rows()})
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


def test_pending_verification_word_order_detected(tmp_path, monkeypatch):
    """R14 (audit round 2, 2026-08-25): observed marker variants — the reversed word
    order and NOT DONE — must not slip past the vocabulary."""
    _write_log(tmp_path, [
        f"| RC-97 | OPEN | {TODAY} | 2099-01-01 | d | w | PENDING VERIFICATION on restart |",
        f"| RC-98 | OPEN | {TODAY} | 2099-01-01 | d | w | NOT DONE - resumes tomorrow |",
    ], monkeypatch)
    assert {r[0] for r in sg.unfinished_rows_opened_today(TODAY)} == {"RC-97", "RC-98"}


def test_does_not_block_on_closed_or_finished_rows(tmp_path, monkeypatch):
    _write_log(tmp_path, [
        f"| RC-94 | CLOSED | {TODAY} | 2099-01-01 | d | w | MEASURED 5 tests. END-TO-END: a->b |",
        f"| RC-95 | OPEN | {TODAY} | 2099-01-01 | d | w | blocked on operator decision, due dated |",
    ], monkeypatch)
    assert sg.unfinished_rows_opened_today(TODAY) == []


def test_missing_log_is_never_a_block(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "RC_LOG", tmp_path / "nope" / "root_cause_log.md")
    assert sg.unfinished_rows_opened_today(TODAY) == []


def _run(payload: dict, monkeypatch) -> int:
    import io
    import json

    monkeypatch.setattr(sg.sys, "stdin", io.StringIO(json.dumps(payload)))
    return sg.main()


def _operator_says(tmp_path, text: str) -> str:
    """A transcript whose LAST USER message is the operator's instruction."""
    import json

    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in (
        {"type": "user", "message": {"role": "user",
                                     "content": [{"type": "text", "text": "do the work"}]}},
        {"type": "assistant", "message": {"role": "assistant",
                                          "content": [{"type": "text", "text": "working"}]}},
        {"type": "user", "message": {"role": "user",
                                     "content": [{"type": "text", "text": text}]}},
    )) + "\n", encoding="utf-8")
    return str(p)


_IN_PROGRESS = f"| RC-90 | OPEN | {TODAY} | 2099-01-01 | d | (1)->(5) ROOT: x | IN PROGRESS |"


def test_retry_flag_is_not_an_authorization(tmp_path, monkeypatch):
    """RC-498. RC-72 returned 0 whenever `stop_hook_active` was set, so the entire control was
    clearable by stopping twice — the agent stops, is blocked, stops again, and the flag waves
    it through with the work still unfinished. The flag proves only that the HOST is retrying;
    this guard now re-evaluates, exactly as operator_law_guard already does at this seam."""
    _write_log(tmp_path, [_IN_PROGRESS], monkeypatch)
    assert _run({"stop_hook_active": True}, monkeypatch) == 2


def test_every_blocking_state_has_an_escape_that_clears_it(tmp_path, monkeypatch):
    """THE ANTI-HANG PROPERTY, PROVEN RATHER THAN ASSERTED.

    The retired find-it-fix-it framework also re-blocked on the retry flag and DID hang,
    because a missing ledger was itself an offender — there was no action that could satisfy
    it. Honouring `stop_hook_active` was the old defence against that, and it doubled as the
    bypass above. The real property is that a satisfying action always EXISTS, so this drives
    each one and requires the block to lift."""
    _write_log(tmp_path, [_IN_PROGRESS], monkeypatch)
    assert _run({"stop_hook_active": True}, monkeypatch) == 2, "precondition: blocked"

    # ESCAPE 1 — finish it. (RC-500: a CLOSED row is no longer an active mission, so the
    # outcome clause runs; it is pinned above so this asserts the escape, not the checkout.)
    _write_log(tmp_path, [
        f"| RC-90 | CLOSED | {TODAY} | 2099-01-01 | d | (1)->(5) ROOT: x | FIXED: tools/x.py. "
        "MEASURED this turn: 12 passed. END-TO-END: edit -> guard -> block. |"], monkeypatch)
    assert _run({"stop_hook_active": True}, monkeypatch) == 0

    # ESCAPE 2 — declare the blocker STRUCTURALLY (RC-503): the status cell, plus a due date
    # that has not passed. The fix cell explains what is awaited but carries no authority.
    _write_log(tmp_path, [
        f"| RC-90 | BLOCKED | {TODAY} | 2099-01-01 | d | (1)->(5) ROOT: x | the proof needs a "
        "live RTH quote stream and the market is closed; resumes at the next RTH open. |"],
        monkeypatch)
    assert _run({"stop_hook_active": True}, monkeypatch) == 0

    # ESCAPE 3 — the operator says stop.
    _write_log(tmp_path, [_IN_PROGRESS], monkeypatch)
    assert _run({"transcript_path": _operator_says(tmp_path, "STOP. Hang it up for tonight.")},
                monkeypatch) == 0


def test_an_unreadable_ledger_abstains_rather_than_hanging_every_turn(tmp_path, monkeypatch):
    """The retired framework treated a missing/malformed ledger as an offender, which blocked
    every Stop AND every commit repo-wide. No rows means nothing to say, not a block."""
    monkeypatch.setattr(ml, "RC_LOG", tmp_path / "absent" / "root_cause_log.md")
    assert _run({"stop_hook_active": True}, monkeypatch) == 0


def test_env_off_does_not_disable_unfinished_row_block(tmp_path, monkeypatch):
    import io

    # MIDNIGHT-ROLLOVER FIX (2026-08-26): this is the ONLY test here that writes a TODAY-stamped row
    # and then calls sg.main(), which recomputes date.today() ITSELF. Module-level TODAY is captured
    # at import, so a suite crossing midnight wrote "yesterday" and asked the guard about "today" —
    # the row stopped matching and the expected BLOCK silently became a pass, failing the assert.
    # Observed exactly that: a full run finishing 00:08 failed this test alone, and it passed in
    # isolation minutes later. Re-derived at call time, so the window is microseconds rather than the
    # whole suite. The other tests here pass TODAY explicitly into the helper and are self-consistent.
    today = datetime.date.today().isoformat()
    _write_log(tmp_path, [
        f"| RC-90 | OPEN | {today} | 2099-01-01 | d | (1)->(5) ROOT: x | IN PROGRESS: half built |",
    ], monkeypatch)
    monkeypatch.setenv("ED_STOP_GUARD", "off")
    monkeypatch.setattr(sg.sys, "stdin", io.StringIO('{"stop_hook_active": false}'))
    assert sg.main() == 2


# RC-470: the faucet (RC-73), freshness (RC-94/RC-235) and close-contract (RC-106)
# turn-end duties were removed from the guard with their equivalents named in
# tools/stop_guard.py and governance/retired_checks.md; their seams left with them.
# RC-72 - the guard's founding duty - is fully covered above.
