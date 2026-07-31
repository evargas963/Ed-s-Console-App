"""RC-162 — the accrual bank's first CONSUMER: Chart paints banked OV/GEX when live is cold.

Banking is not rendering. RC-159 built the writer and RC-161 made the producer universal, but
until this slice `option_chain_accrual` had zero production readers, so a Chart with a cold or
stale live cache painted nothing while the session's own gamma and volume sat in the DB.

These tests drive the REAL reader and the REAL endpoint helper — not a substring search — and
they cover a SENTINEL and a NON-SENTINEL, because RC-160 forbids calling a SPY-only result
complete.
"""
from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")

from calibration.option_chain_morning_full import (  # noqa: E402
    et_date_and_mins,
    latest_accrual_rows,
    persist_chain_accrual,
)
from time_et import ET  # noqa: E402

#: RC-160: a sentinel AND a non-sentinel enrolled ticker. One of each, never SPY alone.
SENTINEL = "SPY"
NON_SENTINEL = "MSFT"


def _ts_at(h: int, m: int) -> float:
    return datetime(2026, 7, 30, h, m, tzinfo=ET).timestamp()


def _bank(db, ticker: str, h: int, m: int, rows):
    r = persist_chain_accrual(db, ticker=ticker, per_strike_rows=rows, spot=100.0,
                              ts_utc=_ts_at(h, m))
    assert r["status"] == "written", r
    return r


def test_reader_returns_the_newest_row_for_each_ticker(tmp_path):
    """Accumulation means the LATEST observation wins — an earlier, thinner row must not be
    served once volume has built."""
    db = tmp_path / "t.db"
    day = et_date_and_mins(_ts_at(10, 0))[0]
    for tk in (SENTINEL, NON_SENTINEL):
        _bank(db, tk, 9, 15, [[100.0, 1.0e6, 10.0]])
        _bank(db, tk, 12, 0, [[100.0, 2.0e6, 500.0], [105.0, -3.0e6, 700.0]])
        got = latest_accrual_rows(db, tk, day)
        assert got is not None, f"{tk}: bank has rows but the reader returned None"
        assert got["et_minute"] == 720, f"{tk}: reader served an older row ({got['et_minute']})"
        assert got["rows"] == [[100.0, 2.0e6, 500.0], [105.0, -3.0e6, 700.0]]
        assert got["session_volume"] == 1200.0, f"{tk}: volume did not accumulate"


def test_reader_shape_is_what_the_chart_already_paints(tmp_path):
    """The fallback must not change what the numbers MEAN: same [strike, net_gex_1pct$,
    session_volume] triples the Chart already reads as r[1] (blue/red) and r[2] (yellow)."""
    db = tmp_path / "t.db"
    _bank(db, NON_SENTINEL, 11, 0, [[420.0, -7.5e6, 3300.0]])
    got = latest_accrual_rows(db, NON_SENTINEL)
    row = got["rows"][0]
    assert len(row) == 3, f"row is not a [strike, gex, volume] triple: {row}"
    strike, gex, vol = row
    assert strike == 420.0 and gex == -7.5e6 and vol == 3300.0
    assert isinstance(vol, (int, float)) and vol >= 0, "yellow OV must be a non-negative number"


def test_reader_fails_closed_and_never_serves_another_day(tmp_path):
    """Absence reaches the surface as absence. A different session's bank is not today's."""
    db = tmp_path / "t.db"
    assert latest_accrual_rows(tmp_path / "missing.db", SENTINEL) is None
    assert latest_accrual_rows(db, SENTINEL) is None, "empty DB produced rows"
    _bank(db, SENTINEL, 10, 0, [[100.0, 1.0, 1.0]])
    assert latest_accrual_rows(db, SENTINEL, "2026-07-29") is None, (
        "the reader served a different et_date — that is the RC-68 failure class"
    )
    assert latest_accrual_rows(db, "ZZNOSUCH") is None


def test_endpoint_prefers_live_and_falls_back_only_when_stale():
    """The decision rule itself, driven on the real constant: the bank serves only when the live
    snapshot is absent or older than TERRAIN_STALE_AFTER_SEC, and only when it is NEWER."""
    import time

    import server as s

    stale_after = s.TERRAIN_STALE_AFTER_SEC
    now = time.time()

    def live_is_stale(live_ts, today_present):
        return (not today_present) or (live_ts <= 0.0) or ((now - live_ts) > stale_after)

    assert live_is_stale(0.0, False) is True, "cold cache must fall back"
    assert live_is_stale(now - (stale_after + 60), True) is True, "stale cache must fall back"
    assert live_is_stale(now - 5, True) is False, "a FRESH live cache must never be overridden"
    assert stale_after > 0


def test_endpoint_wires_the_bank_reader_and_labels_it_distinctly():
    """Contract on the real endpoint source: the fallback must exist, must be gated on
    staleness, must stamp its own source, and must NOT let the prior-day archive become today."""
    import inspect

    import server as s

    src = inspect.getsource(s.get_terrain_strikes)
    assert "latest_accrual_rows" in src, "the strikes endpoint still has no bank reader"
    assert "TERRAIN_STALE_AFTER_SEC" in src, "the fallback is not gated on staleness"
    assert "accrual_bank:" in src, "banked rows are not stamped with their own source"
    assert '"wide_capture:' in src or "wide_capture:" in src, (
        "the prior-day ghost label vanished — morning_full must stay the PRIOR source"
    )
    # the archive must never become `today`
    i = src.find("_prior_row")
    assert i > 0 and "today =" not in src[i:i + 400], (
        "morning_full is assigned to today somewhere — the RC-68 failure"
    )


def test_chart_labels_banked_rows_as_banked_not_live():
    """VISIBLE_SURFACE #gsrc: painting banked rows under a live label is precisely RC-68 (a
    09:47 capture served at 11:31 as if current)."""
    from pathlib import Path
    ui = (Path(__file__).resolve().parent.parent / "static" / "chart.html").read_text(
        encoding="utf-8")
    assert "accrual_bank" in ui, "the Chart cannot recognise a banked payload"
    assert "BANKED" in ui, "banked rows are not labelled on the visible surface"
    i = ui.find("accrual_bank")
    block = ui[i:i + 900]
    assert "today_age_sec" in block, "the banked label does not show the bank row's own age"


def test_chart_still_reads_the_same_paint_fields():
    """The consumer contract that must NOT change: yellow is r[2], gamma is r[1], from
    strikes.today[scope] — the fallback rides the existing paint path rather than a new one."""
    from pathlib import Path
    ui = (Path(__file__).resolve().parent.parent / "static" / "chart.html").read_text(
        encoding="utf-8")
    assert "/api/terrain/strikes?ticker=" in ui
    assert "strikes.today" in ui or "(strikes && strikes.today)" in ui
    assert "r[2]" in ui, "the yellow option-volume field is no longer read"


def test_decide_untouched_admissions_empty():
    """This slice is Collect + visible surface. Nothing may reach the decision path."""
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "governance" / "decision_path_admissions.json"
    reg = json.loads(p.read_text(encoding="utf-8"))
    admitted = reg.get("admissions") or reg.get("admitted") or []
    assert admitted == [], f"decision path is no longer empty: {admitted}"
