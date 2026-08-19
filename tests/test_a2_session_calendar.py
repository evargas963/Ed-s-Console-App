from __future__ import annotations

import json
from datetime import date, datetime

from v2_decision.a2_session_calendar import (
    SessionInfo,
    get_session_info,
    load_a2_session_calendar,
)


from time_et import ET
def _epoch_ms_et(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=ET).timestamp() * 1000)


def _calendar(**overrides) -> dict:
    base = {
        "schema_version": "1",
        "scope": "us_equities",
        "exchange": "NYSE/NASDAQ unified",
        "valid_through_date": "2026-12-31",
        "last_updated_epoch_seconds": 1778113676,
        "regular_session": {
            "open_et": "09:30",
            "close_et": "16:00",
        },
        "full_closures": [
            "2026-01-01",
            "2026-07-03",
        ],
        "early_closes": [
            {
                "date": "2026-11-27",
                "close_et": "13:00",
            },
        ],
    }
    base.update(overrides)
    return base


def _write_calendar(data_root, calendar: dict) -> None:
    path = data_root / "trading_calendar"
    path.mkdir(parents=True)
    (path / "us_equities.json").write_text(json.dumps(calendar), encoding="utf-8")


def test_loads_valid_calendar_when_present_and_fresh(tmp_path):
    cal = _calendar()
    _write_calendar(tmp_path, cal)

    loaded = load_a2_session_calendar(data_root=tmp_path, now_et_date=date(2026, 6, 1))

    assert loaded == cal


def test_returns_none_when_calendar_file_missing(tmp_path):
    assert load_a2_session_calendar(data_root=tmp_path, now_et_date=date(2026, 6, 1)) is None


def test_returns_none_when_json_malformed(tmp_path):
    path = tmp_path / "trading_calendar"
    path.mkdir(parents=True)
    (path / "us_equities.json").write_text("{not-json", encoding="utf-8")

    assert load_a2_session_calendar(data_root=tmp_path, now_et_date=date(2026, 6, 1)) is None


def test_returns_none_when_schema_version_mismatch(tmp_path):
    _write_calendar(tmp_path, _calendar(schema_version="2"))

    assert load_a2_session_calendar(data_root=tmp_path, now_et_date=date(2026, 6, 1)) is None


def test_returns_none_when_calendar_stale_per_valid_through_date(tmp_path):
    _write_calendar(tmp_path, _calendar(valid_through_date="2026-06-30"))

    assert load_a2_session_calendar(data_root=tmp_path, now_et_date=date(2026, 7, 1)) is None


def test_load_does_not_raise_on_unexpected_io_failure(tmp_path):
    blocking_file = tmp_path / "not_a_directory"
    blocking_file.write_text("x", encoding="utf-8")

    assert load_a2_session_calendar(data_root=blocking_file, now_et_date=date(2026, 6, 1)) is None


def test_load_uses_now_et_date_parameter_when_provided(tmp_path):
    _write_calendar(tmp_path, _calendar(valid_through_date="2026-06-30"))

    assert load_a2_session_calendar(data_root=tmp_path, now_et_date=date(2026, 6, 30)) is not None
    assert load_a2_session_calendar(data_root=tmp_path, now_et_date=date(2026, 7, 1)) is None


def test_classifies_16_00_as_out_of_session_exclusive_close():
    info = get_session_info(decision_time_ms=_epoch_ms_et(2026, 6, 1, 16, 0), calendar=_calendar())
    assert info is not None
    assert info.session_type == "out_of_session"
    assert info.session_open_et == "09:30"
    assert info.session_close_et == "16:00"


def test_classifies_normal_rth_during_regular_session():
    info = get_session_info(decision_time_ms=_epoch_ms_et(2026, 6, 1, 10, 0), calendar=_calendar())

    assert info == SessionInfo(
        session_type="normal_rth",
        session_open_et="09:30",
        session_close_et="16:00",
        decision_date_et="2026-06-01",
        decision_minute_et=600,
    )


def test_classifies_weekend_as_full_closure():
    info = get_session_info(decision_time_ms=_epoch_ms_et(2026, 6, 6, 10, 0), calendar=_calendar())

    assert info == SessionInfo(
        session_type="full_closure",
        session_open_et=None,
        session_close_et=None,
        decision_date_et="2026-06-06",
        decision_minute_et=600,
    )


def test_classifies_full_closure_date_regardless_of_time():
    info = get_session_info(decision_time_ms=_epoch_ms_et(2026, 7, 3, 12, 0), calendar=_calendar())

    assert info == SessionInfo(
        session_type="full_closure",
        session_open_et=None,
        session_close_et=None,
        decision_date_et="2026-07-03",
        decision_minute_et=720,
    )


def test_classifies_early_close_during_early_session_window():
    info = get_session_info(decision_time_ms=_epoch_ms_et(2026, 11, 27, 12, 30), calendar=_calendar())

    assert info == SessionInfo(
        session_type="early_close",
        session_open_et="09:30",
        session_close_et="13:00",
        decision_date_et="2026-11-27",
        decision_minute_et=750,
    )


def test_classifies_post_early_close_as_out_of_session():
    info = get_session_info(decision_time_ms=_epoch_ms_et(2026, 11, 27, 13, 1), calendar=_calendar())

    assert info == SessionInfo(
        session_type="out_of_session",
        session_open_et="09:30",
        session_close_et="13:00",
        decision_date_et="2026-11-27",
        decision_minute_et=781,
    )


def test_full_closure_takes_precedence_over_early_close():
    cal = _calendar(
        full_closures=["2026-11-27"],
        early_closes=[{"date": "2026-11-27", "close_et": "13:00"}],
    )

    info = get_session_info(decision_time_ms=_epoch_ms_et(2026, 11, 27, 12, 0), calendar=cal)

    assert info is not None
    assert info.session_type == "full_closure"
    assert info.session_open_et is None
    assert info.session_close_et is None


def test_get_session_info_does_not_raise_on_unexpected_failure():
    assert get_session_info(decision_time_ms=object(), calendar=_calendar()) is None
    assert get_session_info(decision_time_ms=_epoch_ms_et(2026, 6, 1, 10, 0), calendar=object()) is None
