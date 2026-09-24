# institutional-synthetic-ok: these tests INJECT bare toLocaleDateString / missing SESSION_TZ
# to prove the RC-223 / census #7 clocks lock BLOCKS — that is their entire purpose.
"""RC-223: chart session date keys are ET; display labels are CT; bare locale dates banned."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.clocks_tz_lock as L  # noqa: E402

CHART = ROOT / "static" / "chart.html"


def test_shipped_static_has_no_bare_locale_dates():
    bad = L.scan_tracked_static(ROOT)
    assert bad == [], f"browser-ambient date clocks remain: {bad}"


def test_chart_binds_session_et_and_display_ct():
    src = CHART.read_text(encoding="utf-8")
    # session (ET) keys are the server's since the audit of #280 -- the page keys nothing
    assert "SESSION_TZ" not in src and "&tf=" in src
    assert "DISPLAY_TZ = 'America/Chicago'" in src
    # The daily roll-up (and its ET date key) is server-side since the audit of #280: the
    # browser no longer aggregates candles. The ET keying is pinned on the producer.
    assert "function aggregate(" not in src and "etDateKey(" not in src
    import inspect
    import server as srv
    assert "from time_et import ET" in inspect.getsource(srv.aggregate_bars)
    assert "displayDateLabel(" in src and "displayTimeLabel(" in src
    assert "toLocaleDateString()" not in src
    assert "toLocaleDateString(undefined" not in src


def test_index_catch_path_is_ct_explicit():
    """Same invariant legacy's own test enforced (an explicit America/Chicago timeZone, never
    a bare locale date) -- repointed to ed-core.js's tickClock() (/console cutover, operator
    directive 2026-09-14), which uses 'en-US' rather than legacy's 'en-CA' locale spelling but
    the same explicit-timeZone discipline."""
    core = (ROOT / "static" / "js" / "ed-core.js").read_text(encoding="utf-8")
    assert "toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: '2-digit', timeZone: 'America/Chicago' })" in core
    remainder = core.replace(
        "toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: '2-digit', timeZone: 'America/Chicago' })", ""
    )
    assert "toLocaleDateString('en-US')" not in remainder


def test_bare_locale_date_detector_screams():
    """Negative control: the exact census defect must BLOCK."""
    bad = L.bare_locale_date_violations(
        "const dkey = t => new Date(t * 1000).toLocaleDateString();\n",
        rel="static/chart.html",
    )
    assert bad, "bare toLocaleDateString() was not flagged"
    assert "timeZone" in bad[0]


def test_explicit_timezone_is_quiet():
    good = L.bare_locale_date_violations(
        "d.toLocaleDateString('en-US', { timeZone: 'America/Chicago', month: 'short' });\n",
        rel="static/chart.html",
    )
    assert good == []


def test_browser_side_grouping_screams():
    """Negative control: putting candle/date grouping back in the page is caught (the roll-up
    and its ET key are server-side, aggregate_bars)."""
    src = CHART.read_text(encoding="utf-8")
    regrouped = src.replace("function currentChartTicker() {",
                            "function etDateKey(t) { return ''; } function currentChartTicker() {", 1)
    bad = L.chart_session_clock_violations(regrouped)
    assert any("server-side" in m for m in bad), bad
    no_tf = src.replace("&tf=", "&xf=")
    assert any("tf=" in m for m in L.chart_session_clock_violations(no_tf))


def test_et_date_key_matches_time_et_authority():
    """The daily roll-up keys the ET trading date (server aggregate_bars, same calendar as
    time_et.et_date_str_from_ts_utc): 23:30 ET and 00:30 ET next day are two bars even though
    they fall on one UTC date; 11:00 ET and 23:30 ET are one bar."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    import server as srv
    from time_et import et_date_str_from_ts_utc

    et = ZoneInfo("America/New_York")
    ts = [datetime(2026, 8, 3, h, m, tzinfo=et).astimezone(timezone.utc).timestamp()
          for h, m in ((11, 0), (23, 30))]
    ts.append(datetime(2026, 8, 4, 0, 30, tzinfo=et).astimezone(timezone.utc).timestamp())
    assert [et_date_str_from_ts_utc(t) for t in ts] == ["2026-08-03", "2026-08-03", "2026-08-04"]
    bars = [{"t": t, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1} for t in ts]
    assert [b["v"] for b in srv.aggregate_bars(bars, "D")] == [2, 1]
