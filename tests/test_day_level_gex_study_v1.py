"""RC-7 seams for the day-level GEX study (pure units)."""
from __future__ import annotations

from tools.reversion_rule_a_study_v1 import M_SIGMA, STOP_SIGMA, RuleACandidate
from tools.run_day_level_gex_study_v1 import (
    chase_event,
    chase_multiples,
    morning_gamma_by_session,
    spearman,
)


def test_spearman_known_values_and_degenerate():
    assert abs(spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1.0) < 1e-9
    assert abs(spearman([1, 2, 3, 4], [40, 30, 20, 10]) + 1.0) < 1e-9
    assert spearman([1, 1, 1], [1, 2, 3]) is None          # zero rank variance
    assert spearman([1, 2], [1, 2]) is None                # n < 3


def test_chase_mirror_geometry_and_side_flip():
    cand = RuleACandidate(i_sig=40, side="SHORT", deviation=0.9, sigma=0.3, signal_ts=0.0)
    m = chase_multiples(cand, atr_t1=0.45)
    assert m is not None
    stop_atr, target_atr = m
    assert abs(stop_atr - STOP_SIGMA * 0.3 / 0.45) < 1e-9
    assert abs(target_atr - M_SIGMA * 0.3 / 0.45) < 1e-9   # 1.5 sigma WITH the move
    ev = chase_event(cand)
    assert ev.side == "LONG"                                # fade SHORT -> chase LONG
    assert ev.candidate_generator_id == "RULE_B_VWAP_CHASE_MIRROR_V1"
    assert chase_multiples(cand, 0.0) is None


def test_morning_gamma_takes_first_row_in_window_only():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")

    def ts(h, m):
        return datetime(2026, 7, 22, h, m, tzinfo=ET).timestamp()

    rows = [
        (ts(9, 20), 111.0),   # pre-open: outside window
        (ts(9, 35), 222.0),   # first in 09:30-10:15 -> the pick
        (ts(9, 50), 333.0),   # later in window: ignored
        (ts(11, 0), 444.0),   # midday: outside window
    ]
    out = morning_gamma_by_session(rows)
    assert out == {"2026-07-22": 222.0}
