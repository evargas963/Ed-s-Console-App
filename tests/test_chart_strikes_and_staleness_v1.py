"""The Chart page's per-strike bars and the levels' staleness yardstick."""
from __future__ import annotations

# RC-367: this suite drives the Chart page's real reader/endpoint path — declare
# ownership so the turn audit maps static/chart.html changes to a running suite
# instead of an unknown owner (html cannot appear in an import graph).
TURN_AUDIT_OWNS = [
    "static/chart.html",
]


def test_chart_still_reads_the_same_paint_fields():
    """The Chart's per-strike bars: yellow is r[2], gamma is r[1], from strikes.today[scope]."""
    from pathlib import Path
    ui = (Path(__file__).resolve().parent.parent / "static" / "chart.html").read_text(
        encoding="utf-8")
    assert "/api/terrain/strikes?ticker=" in ui
    assert "strikes.today" in ui or "(strikes && strikes.today)" in ui
    assert "r[2]" in ui, "the yellow option-volume field is no longer read"


def test_staleness_is_judged_against_the_delivered_cycle_not_the_sleep_floor(monkeypatch):
    """RC-165: `TERRAIN_REFRESH_SEC` is a sleep FLOOR between cycles, not a promise. A full sweep
    over ~40 tickers on 2 workers against a 2-slot chain gate costs more than that. MEASURED
    2026-07-31 12:57 ET: SPY inter-observation spacing median 156s, while a fixed 180s threshold
    and a hard-coded "60s cadence" sentence reported MSFT at 234s — barely 1.5 sweeps, entirely
    healthy — as "the loop is inside its window but not producing". That is RC-146's defect
    through a different door: a working scheduler described as broken, because the yardstick was
    a number the loop cannot reach.

    RC-169: this test used to assert the DELIVERED wording unconditionally and so passed during
    the session and FAILED at night — `terrain_staleness` takes an earlier branch once the
    background-logging window closes at 16:30 ET, and that branch's sentence is correct for a
    loop that has legitimately stopped. A test whose verdict depends on when it runs is not a
    test of the code. The window is now PINNED, so the branch under test is the branch chosen.
    """
    import time

    import server as s

    now = time.time()
    prev = s._terrain_last_cycle_sec
    prev_gate = s._is_loggable_session
    try:
        # Pin the branch instead of the clock: this test is about the CADENCE yardstick, so the
        # loop must be inside its window for the whole of it, whatever hour the suite runs at.
        s._is_loggable_session = lambda *a, **k: True
        s._terrain_last_cycle_sec = 156.0
        healthy = s.terrain_staleness(now - 234, "ZZTEST")
        assert healthy["levels_stale"] is False, (
            "234s at a 156s delivered cycle is 1.5 sweeps — flagging it stale calls a healthy "
            "scheduler broken"
        )
        behind = s.terrain_staleness(now - 400, "ZZTEST")
        assert behind["levels_stale"] is True, "400s is 2.6 sweeps — genuinely behind"
        assert "DELIVERED" in behind["levels_stale_reason"]
        assert "156s" in behind["levels_stale_reason"], (
            "the reason must quote the cycle actually delivered, not only the floor"
        )
        assert "not producing" not in behind["levels_stale_reason"], (
            "the retired sentence asserted a malfunction from a cadence the loop never meets"
        )
        # a FAST loop must not be allowed to hide staleness: the floor still applies
        s._terrain_last_cycle_sec = 10.0
        assert s.terrain_staleness(now - 200, "ZZTEST")["levels_stale"] is True, (
            "a fast cycle dropped the floor — staleness could be hidden by a quick sweep"
        )
        # before the first cycle completes, fall back to the nominal floor rather than 0
        s._terrain_last_cycle_sec = 0.0
        assert s.terrain_staleness(now - 400, "ZZTEST")["levels_stale"] is True

        # And the closed market: nothing refreshes by design, so the last session's levels are
        # labeled with their time -- never judged by the cadence yardstick.
        s._is_loggable_session = lambda *a, **k: False
        s._terrain_last_cycle_sec = 156.0
        closed = s.terrain_staleness(now - 400, "ZZTEST")
        assert closed["levels_market_closed"] is True and closed["levels_stale"] is False
        assert closed["levels_as_of"] and "DELIVERED" not in closed["levels_stale_reason"]
    finally:
        s._terrain_last_cycle_sec = prev
        s._is_loggable_session = prev_gate


def test_loop_publishes_the_cycle_duration_it_already_measures():
    """The number existed and was only logged; readers had no access, which is why staleness was
    left comparing against the floor."""
    import inspect

    import server as s

    src = inspect.getsource(s._terrain_loop)
    assert "_terrain_last_cycle_sec" in src, (
        "the loop still keeps its measured cycle duration to itself"
    )
    assert "elapsed" in src
    assert isinstance(s._terrain_last_cycle_sec, float)


