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
INDEX = ROOT / "static" / "index.html"


def test_shipped_static_has_no_bare_locale_dates():
    bad = L.scan_tracked_static(ROOT)
    assert bad == [], f"browser-ambient date clocks remain: {bad}"


def test_chart_binds_session_et_and_display_ct():
    src = CHART.read_text(encoding="utf-8")
    assert "SESSION_TZ = 'America/New_York'" in src
    assert "DISPLAY_TZ = 'America/Chicago'" in src
    assert "function etDateKey" in src
    assert "etDateKey(b.t)" in src or "etDateKey(t)" in src
    assert "displayDateLabel(" in src and "displayTimeLabel(" in src
    assert "toLocaleDateString()" not in src
    assert "toLocaleDateString(undefined" not in src


def test_index_catch_path_is_ct_explicit():
    src = INDEX.read_text(encoding="utf-8")
    assert "toLocaleDateString('en-CA', { timeZone: 'America/Chicago' })" in src
    remainder = src.replace(
        "toLocaleDateString('en-CA', { timeZone: 'America/Chicago' })", ""
    )
    assert "toLocaleDateString('en-CA')" not in remainder


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


def test_missing_session_tz_screams():
    src = CHART.read_text(encoding="utf-8")
    stripped = src.replace("SESSION_TZ = 'America/New_York'", "SESSION_TZ = 'UTC'", 1)
    bad = L.chart_session_clock_violations(stripped)
    assert any("SESSION_TZ" in m or "America/New_York" in m for m in bad), bad


def test_et_date_key_matches_time_et_authority():
    """etDateKey contract: same YYYY-MM-DD as time_et.et_date_str_from_ts_utc for a known ET noon."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from time_et import et_date_str_from_ts_utc

    et_noon = datetime(2026, 8, 3, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    ts = et_noon.astimezone(timezone.utc).timestamp()
    assert et_date_str_from_ts_utc(ts) == "2026-08-03"
    src = CHART.read_text(encoding="utf-8")
    assert "timeZone: SESSION_TZ" in src
