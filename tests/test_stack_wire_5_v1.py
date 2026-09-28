"""STACK-WIRE-5 — order_flow_engine → stack vote (FIND-WIRE5-1..3)."""

from __future__ import annotations

import app.options.order_flow.state as ofls


def test_order_flow_state_rth_actually_behaves_at_the_boundaries(monkeypatch):
    """Driven by pinning the clock, because the real one makes the answer depend on when the
    suite happens to run.
    """
    import datetime as _dt

    from time_et import ET

    def _at(y, m, d, hh, mm):
        monkeypatch.setattr(ofls, "now_et",
                            lambda: _dt.datetime(y, m, d, hh, mm, tzinfo=ET), raising=True)
        return ofls.is_rth_open()

    # 2026-08-07 is a Friday; 2026-08-08 a Saturday.
    assert _at(2026, 8, 7, 9, 29) is False, "one minute before the open must not be RTH"
    assert _at(2026, 8, 7, 9, 30) is True, "the open itself is RTH (inclusive lower bound)"
    assert _at(2026, 8, 7, 12, 0) is True
    assert _at(2026, 8, 7, 15, 59) is True
    assert _at(2026, 8, 7, 16, 0) is False, "16:00 is the exclusive upper bound"
    assert _at(2026, 8, 8, 12, 0) is False, "Saturday is never RTH regardless of clock"
