"""RC-161 — the terrain refresh scheduler covers every enrolled ticker across [09:15, 16:15] ET.

2026-09-27: the per-minute chain accrual (and its window/persistence tests) was deleted with
the /exposure page it fed (P2-4); the scheduler tests remain.
"""
from __future__ import annotations

import os

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")

# 09:15 and 16:15 ET: the first and last minutes the terrain board is refreshed for.
PREMARKET_START_MINS = 555
SESSION_END_MINS = 975


# ── RC-161: the refresh scheduler is UNIVERSAL, not sentinel-only ─────────────────────────
def _server():
    import server
    return server


def _board(n: int = 57) -> list[str]:
    return [f"T{i:02d}" for i in range(n)]


def test_non_sentinels_are_not_excluded_anywhere_in_the_accrual_window():
    """RC-161 GUN: widening MORNING_START_MINS 570 -> 555 for the archive also widened the
    scheduler's sentinel-only filter, because ONE constant answered two questions. Result: the
    accrual mandate claimed [555, 975] UNIVERSAL while three tickers met it and 54 enrolled ones
    were dropped for the first 45 minutes. No enrolled ticker may be excluded for a whole
    window."""
    s = _server()
    board = _board()
    depth = max(1, -(-int(s.CONTENTION_ROTATION_SEC) // max(1, int(s.TERRAIN_REFRESH_SEC))))
    for mins in (PREMARKET_START_MINS, 560, 569, 570, 575, 599, 600, 601, 720, SESSION_END_MINS):
        seen: set[str] = set()
        for cycle in range(1, depth + 1):
            now, _deferred = s.terrain_cycle_tickers(board, mins, cycle)
            seen |= set(now)
        missing = [t for t in board if t not in seen]
        assert not missing, (
            f"at ET minute {mins}, {len(missing)} enrolled tickers never refreshed across "
            f"{depth} cycles (e.g. {missing[:4]}) — accrual is not universal there"
        )


def test_premarket_window_refreshes_the_whole_enrolled_board_every_cycle():
    """09:15-09:29 ET is the stretch my own RC-159 edit starved. There is no money-path wide
    capture before the open, so there is nothing to contend with and no reason to defer."""
    s = _server()
    board = _board()
    for mins in range(PREMARKET_START_MINS, s.TERRAIN_CONTENTION_START_MINS):
        now, deferred = s.terrain_cycle_tickers(board, mins, 1)
        assert deferred == [], f"ET minute {mins} still defers {len(deferred)} tickers pre-open"
        assert len(now) == len(board)


def test_viewed_tickers_refresh_every_cycle_inside_contention_whatever_their_name():
    """Priority is by what the operator is viewing, never by symbol name (universality,
    operator 2026-09-23): any viewed ticker refreshes every cycle; an unviewed SPY rotates
    like every other ticker."""
    s = _server()
    board = _board() + ["SPY"]
    for cycle in range(1, 11):
        now, _ = s.terrain_cycle_tickers(board, 575, cycle, viewed=["T07", "T33"])
        assert {"T07", "T33"} <= set(now), f"a viewed ticker was deferred on cycle {cycle}"
    deferred_spy = any("SPY" in s.terrain_cycle_tickers(board, 575, cyc, viewed=[])[1]
                       for cyc in range(1, 11))
    assert deferred_spy, "SPY must rotate like any unviewed ticker, not be privileged by name"


def test_contention_window_still_spreads_the_load():
    """The original budget intent (RC-146) survives: the open must not take a full 57-ticker
    sweep on top of the money-path wide fetches. Deferral is spreading, not starving."""
    s = _server()
    board = _board()
    now, deferred = s.terrain_cycle_tickers(board, 575, 1)
    assert deferred, "the contention window no longer spreads load at all"
    assert len(now) < len(board) / 2, (
        f"cycle refreshes {len(now)} of {len(board)} inside contention — load is not spread"
    )


def test_outside_contention_nothing_is_deferred():
    s = _server()
    board = _board()
    for mins in (0, 540, 554, 601, 900, SESSION_END_MINS, 1439):
        now, deferred = s.terrain_cycle_tickers(board, mins, 3)
        assert deferred == [] and now == board, f"ET minute {mins} deferred unexpectedly"
