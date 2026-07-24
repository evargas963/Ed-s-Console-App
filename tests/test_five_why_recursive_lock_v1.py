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
