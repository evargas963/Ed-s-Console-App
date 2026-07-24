"""RC-32 regression lock: future-anchored joins can never enter the scored confusion.

governance/root_cause_log.md RC-32: `nearest_later` rows carry outcomes whose
anchor bar closes AFTER the decision (28,622 measured store-wide 2026-07-23);
`unknown_join` rows have no provable alignment. Both must be DISCLOSED in
identity_cohorts and EXCLUDED from accuracy/MCC/confusion, with the exclusion
counted per cell. Drives the real accumulate/finalize pair, no mocks.
"""
from __future__ import annotations

from calibration.daily_scoreboard import (
    _V4_SCORED_JOIN_COHORTS,
    JOIN_COHORTS,
    _finalize_v4_cell,
    _new_v4_cell,
    _v4_accumulate,
)


def _row(cohort: str, *, pred: str = "up", truth: str = "up", ts: float = 1_784_500_000.0):
    return {
        "horizon": "1c",
        "decision_ts_utc": ts,
        "pred": pred,
        "truth": truth,
        "join_cohort": cohort,
        "bundle_identity_proven": True,
    }


def test_nearest_later_and_unknown_join_never_enter_confusion():
    cell = _new_v4_cell()
    _v4_accumulate(cell, _row("identity", ts=1_784_500_000.0))
    _v4_accumulate(cell, _row("exact_timestamp", ts=1_784_500_060.0))
    _v4_accumulate(cell, _row("nearest_earlier", ts=1_784_500_120.0))
    _v4_accumulate(cell, _row("nearest_later", ts=1_784_500_180.0))
    _v4_accumulate(cell, _row("unknown_join", ts=1_784_500_240.0))
    fin = _finalize_v4_cell(cell)
    # Scored = the three provably-aligned cohorts only.
    assert fin["n_scored"] == 3
    assert fin["n_excluded_lookahead_join"] == 2
    # Disclosure preserved: every cohort still counted.
    assert fin["identity_cohorts"]["nearest_later"] == 1
    assert fin["identity_cohorts"]["unknown_join"] == 1
    assert fin["identity_cohorts"]["identity"] == 1
    # All five predictions were seen.
    assert fin["n_pred"] == 5


def test_excluded_rows_cannot_shift_accuracy_in_either_direction():
    """A flood of look-ahead rows — correct OR wrong — must leave accuracy unchanged."""
    base = _new_v4_cell()
    _v4_accumulate(base, _row("identity", pred="up", truth="up"))
    _v4_accumulate(base, _row("identity", pred="down", truth="up", ts=1_784_500_060.0))
    acc_before = _finalize_v4_cell(base)["accuracy"]

    flooded = _new_v4_cell()
    _v4_accumulate(flooded, _row("identity", pred="up", truth="up"))
    _v4_accumulate(flooded, _row("identity", pred="down", truth="up", ts=1_784_500_060.0))
    for i in range(50):  # 50 "perfect" look-ahead rows
        _v4_accumulate(flooded, _row("nearest_later", pred="up", truth="up", ts=1_784_500_300.0 + 60 * i))
    fin = _finalize_v4_cell(flooded)
    assert fin["accuracy"] == acc_before
    assert fin["n_scored"] == 2
    assert fin["n_excluded_lookahead_join"] == 50


def test_scoring_allowlist_is_explicit_membership_not_complement():
    assert set(_V4_SCORED_JOIN_COHORTS) == {"identity", "exact_timestamp", "nearest_earlier"}
    assert set(JOIN_COHORTS) - set(_V4_SCORED_JOIN_COHORTS) == {"nearest_later", "unknown_join"}


def test_bundle_identity_counter_tracks_scored_rows_only():
    cell = _new_v4_cell()
    row = _row("nearest_later")
    row["bundle_identity_proven"] = False
    _v4_accumulate(cell, row)
    fin = _finalize_v4_cell(cell)
    # Excluded row must not inflate the scored-row identity counter.
    assert fin["n_bundle_identity_unproven"] == 0
    assert fin["n_excluded_lookahead_join"] == 1
