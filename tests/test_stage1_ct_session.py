"""Stage 1 Central Time (America/Chicago) session contract tests (research-only).

Proves the CT session authority resolves CST/CDT, spring-forward, fall-back,
holidays, and half-days via zoneinfo + the exchange calendar — with NO fixed
offset and NO stored et_hour dependency.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from research.stage1_target_foundation.ct_session import (
    classify_session,
    ct_label,
    is_early_close,
    is_full_closure,
    is_rth_ct,
    rth_bounds_utc,
)

CT = ZoneInfo("America/Chicago")
GOV = Path(__file__).resolve().parents[1] / "governance" / "research" / "stage1_target_label_foundation"


def _ct_epoch(y, mo, d, h, mi) -> int:
    return int(datetime(y, mo, d, h, mi, tzinfo=CT).timestamp())


def test_contract_declares_ct_canonical_and_utc_storage():
    c = json.loads((GOV / "time_session_contract_v1.json").read_text(encoding="utf-8"))
    assert c["canonical_storage_timezone"] == "UTC"
    assert c["canonical_application_timezone"] == "America/Chicago"
    assert "08:30-15:00 Central" in c["rth_label_ct"]


def test_ordinary_cst_day_rth():
    assert is_rth_ct(_ct_epoch(2026, 1, 5, 8, 35)) is True
    assert "CST" in ct_label(_ct_epoch(2026, 1, 5, 8, 35))


def test_ordinary_cdt_day_rth():
    assert is_rth_ct(_ct_epoch(2026, 7, 6, 8, 35)) is True
    assert "CDT" in ct_label(_ct_epoch(2026, 7, 6, 8, 35))


def test_spring_forward_and_monday_after():
    # 2026 spring-forward is Sun 2026-03-08; Monday 03-09 must be a normal CDT RTH day
    assert is_rth_ct(_ct_epoch(2026, 3, 9, 8, 35)) is True
    assert "CDT" in ct_label(_ct_epoch(2026, 3, 9, 8, 35))


def test_fall_back_and_monday_after():
    # 2026 fall-back is Sun 2026-11-01; Monday 11-02 must be a normal CST RTH day
    assert is_rth_ct(_ct_epoch(2026, 11, 2, 8, 35)) is True
    assert "CST" in ct_label(_ct_epoch(2026, 11, 2, 8, 35))


def test_rth_open_and_close_boundaries_ct():
    assert classify_session(_ct_epoch(2026, 1, 5, 8, 30)) == "rth"      # open inclusive
    assert classify_session(_ct_epoch(2026, 1, 5, 14, 59)) == "rth"
    assert classify_session(_ct_epoch(2026, 1, 5, 15, 0)) == "afterhours"  # close exclusive


def test_premarket_and_afterhours_boundaries_ct():
    assert classify_session(_ct_epoch(2026, 1, 5, 8, 29)) == "premarket"
    assert classify_session(_ct_epoch(2026, 1, 5, 7, 0)) == "premarket"
    assert classify_session(_ct_epoch(2026, 1, 5, 16, 0)) == "afterhours"


def test_holiday_closure():
    assert is_full_closure(date(2026, 1, 1)) is True
    assert classify_session(_ct_epoch(2026, 1, 1, 8, 35)) == "closed"
    assert rth_bounds_utc(date(2026, 1, 1)) is None


def test_early_close_half_day():
    # 2026-11-27 early close 13:00 ET = 12:00 CT
    assert is_early_close(date(2026, 11, 27)) is True
    assert classify_session(_ct_epoch(2026, 11, 27, 11, 0)) == "rth"
    assert classify_session(_ct_epoch(2026, 11, 27, 12, 30)) == "afterhours"


def test_weekend_is_closed():
    assert classify_session(_ct_epoch(2026, 1, 3, 10, 0)) == "closed"  # Saturday


def test_no_fixed_offset():
    """A CST RTH-open instant and a CDT RTH-open instant must have DIFFERENT UTC
    hours (proving DST is resolved, not a fixed offset)."""
    cst_open = _ct_epoch(2026, 1, 5, 8, 30)
    cdt_open = _ct_epoch(2026, 7, 6, 8, 30)
    cst_utc_h = datetime.fromtimestamp(cst_open, tz=timezone.utc).hour
    cdt_utc_h = datetime.fromtimestamp(cdt_open, tz=timezone.utc).hour
    assert cst_utc_h != cdt_utc_h
    assert cst_utc_h == 14 and cdt_utc_h == 13


def test_no_hardcoded_offset_in_module_source():
    src = (Path(__file__).resolve().parents[1] / "research" / "stage1_target_foundation"
           / "ct_session.py").read_text(encoding="utf-8")
    # no manual +/- 5h/6h/21600/18000 offset arithmetic
    for banned in ("timedelta(hours=5", "timedelta(hours=6", "21600", "18000", "- 5 * 3600", "- 6 * 3600"):
        assert banned not in src, f"hard-coded offset {banned!r} present"
