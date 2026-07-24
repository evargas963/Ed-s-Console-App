"""Seams for the mechanical 5-why recursive lock (operator law 2026-07-24)."""
from __future__ import annotations

from pathlib import Path

from tools.check_institutional_correctness import (
    FIVE_WHY_LOCK_CUTOVER,
    _five_why_lock_violations,
)

_P = Path("governance/root_cause_log.md")


def _row(rc="RC-90", status="OPEN", opened="2026-07-24", why=None, fix=None):
    why = why if why is not None else "(1) a -> (2) b -> (3) c -> (4) d -> (5) ROOT: the cause"
    fix = fix if fix is not None else "NOT FIXED - scoped"
    return f"| {rc} | {status} | {opened} | 2026-08-08 | defect text | {why} | {fix} |"


def test_clean_new_row_passes():
    assert _five_why_lock_violations([_row()], _P) == []


def test_missing_root_is_flagged_globally_even_pre_cutover():
    v = _five_why_lock_violations([_row(opened="2026-05-01", why="(1) a -> (2) b -> (3) c -> (4) d -> (5) deep cause")], _P)
    assert len(v) == 1 and "ROOT" in v[0].msg


def test_dangling_child_reference_breaks_the_recursive_regime():
    v = _five_why_lock_violations([_row(why="(1) a -> (2) spawns RC-77 -> (3) c -> (4) d -> (5) ROOT: x")], _P)
    assert len(v) == 1 and "RC-77" in v[0].msg
    ok = _five_why_lock_violations(
        [_row(), _row(rc="RC-91", why="(1) a -> (2) see RC-90 -> (3) c -> (4) d -> (5) ROOT: y")], _P
    )
    assert ok == []


def test_patch_vocabulary_banned_post_cutover_only():
    bad = _row(status="CLOSED", fix="shipped a temporary fix END-TO-END: producer to consumer, PROVEN 3 tests")
    v = _five_why_lock_violations([bad], _P)
    assert any("banned patch vocabulary" in x.msg for x in v)
    grandfathered = _row(opened="2026-07-19", status="CLOSED",
                         fix="MEASURED: reverted 5 circular-import workarounds, PROVEN 14 pass")
    assert _five_why_lock_violations([grandfathered], _P) == []


def test_closure_requires_end_to_end_declaration_post_cutover():
    v = _five_why_lock_violations(
        [_row(status="CLOSED", fix="PROVEN with 12 tests, OBSERVED live values 3.14")], _P
    )
    assert len(v) == 1 and "END-TO-END" in v[0].msg
    ok = _five_why_lock_violations(
        [_row(status="CLOSED", fix="PROVEN 12 tests. END-TO-END: writer through loader through UI, 3 sites.")], _P
    )
    assert ok == []


def test_cutover_constant_is_the_operator_law_date():
    assert FIVE_WHY_LOCK_CUTOVER == "2026-07-24"


# ── No-terminal-null clause (operator law 2026-07-24, second clause) ─────────


def test_surrender_vocabulary_requires_next_depth():
    from tools.check_institutional_correctness import _surrender_violations

    bare = _row(why="(1) a -> (2) b -> (3) c -> (4) d -> (5) ROOT: this is a dead end")
    v = _surrender_violations([bare], _P)
    assert len(v) == 1 and "NEXT-DEPTH" in v[0].msg
    doored = _row(
        why="(1) a -> (2) b -> (3) c -> (4) d -> (5) ROOT: dead end at this depth. "
            "NEXT-DEPTH: external multi-year data acquisition unlocks it"
    )
    assert _surrender_violations([doored], _P) == []
    grandfathered = _row(opened="2026-07-19",
                         why="(1) a -> (2) b -> (3) c -> (4) d -> (5) ROOT: dead end")
    assert _surrender_violations([grandfathered], _P) == []


def test_null_reports_require_next_depth_post_cutover():
    from tools.check_institutional_correctness import _terminal_null_violations

    null_no_door = (_P, {"generated_utc": "2026-07-26T01:00:00", "n_survivors": 0})
    v = _terminal_null_violations([null_no_door])
    assert len(v) == 1 and "next_depth" in v[0].msg
    null_doored = (_P, {"generated_utc": "2026-07-26T01:00:00", "n_survivors": 0,
                        "next_depth": "run the reversion generator prereg"})
    assert _terminal_null_violations([null_doored]) == []
    pre_cutover = (_P, {"generated_utc": "2026-07-24T01:00:00", "n_survivors": 0})
    assert _terminal_null_violations([pre_cutover]) == []
    survivor = (_P, {"generated_utc": "2026-07-26T01:00:00", "n_survivors": 2})
    assert _terminal_null_violations([survivor]) == []
