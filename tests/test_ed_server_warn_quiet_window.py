"""Unit tests for tools.ed_server_warn_quiet_window — no live server required."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.ed_server_warn_quiet_window import (  # noqa: E402
    collect_fail_lines_from_text,
    is_quiet_window_fail_line,
    monitor_quiet_window,
)


def test_fail_line_matches_any_logger_warning_error_critical_traceback():
    assert is_quiet_window_fail_line(
        "[WARN] WARNING:ed_server:L1 payload scope drift: ['quote_source_detail']"
    )
    assert is_quiet_window_fail_line(
        "WARNING:db:sqlite_bg_write_slow elapsed_ms=1234"
    )
    assert is_quiet_window_fail_line("WARNING:uvicorn.error:something")
    assert is_quiet_window_fail_line("[ERR ] ERROR:ed_server:boom")
    assert is_quiet_window_fail_line("ERROR:db:write failed")
    assert is_quiet_window_fail_line("[CRIT] CRITICAL:ed_server:dead")
    assert is_quiet_window_fail_line("CRITICAL:other:x")
    assert is_quiet_window_fail_line("Traceback (most recent call last):")
    # INFO/DEBUG never fail — even if text contains "fail"
    assert not is_quiet_window_fail_line("INFO:ed_server:steady")
    assert not is_quiet_window_fail_line("INFO:db:failed to parse optional field")
    assert not is_quiet_window_fail_line("DEBUG:ed_server:fail soft path")


def test_collect_fail_lines_from_text():
    text = (
        "INFO:ed_server:boot\n"
        "[WARN] WARNING:ed_server:L1 payload scope drift: ['quote_source_detail']\n"
        "WARNING:db:sqlite_bg_write_slow elapsed_ms=99\n"
        "INFO:db:failed to parse optional X\n"
        "Traceback (most recent call last):\n"
        "ERROR:uvicorn.error:worker\n"
    )
    got = collect_fail_lines_from_text(text)
    assert len(got) == 4
    assert "L1 payload scope drift" in got[0]
    assert "sqlite_bg_write_slow" in got[1]
    assert got[2].startswith("Traceback")
    assert "uvicorn.error" in got[3]


def test_monitor_quiet_window_pass_clean_growing_info(tmp_path: Path):
    log_path = tmp_path / "ed_server.log"
    # Preexisting WARNING before offset must not count:
    log_path.write_text(
        "[WARN] WARNING:ed_server:old spam before window\nINFO:ed_server:ready\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.json"
    clock = {"t": 1000.0}
    injected = {"done": False}

    def now():
        return clock["t"]

    def sleep(dt):
        clock["t"] += float(dt)
        if not injected["done"] and clock["t"] >= 1000.5:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write("INFO:ed_server:heartbeat during window\n")
            injected["done"] = True

    result = monitor_quiet_window(
        log_path=log_path,
        window_sec=2.0,
        poll_sec=0.5,
        skip_health=True,
        write_report=True,
        report_path=report,
        now_fn=now,
        sleep_fn=sleep,
    )
    assert result["verdict"] == "PASS"
    assert result["ok"] is True
    assert result["warn_count"] == 0
    assert result["log_progressed"] is True
    assert result["measurement_invalid"] is False
    assert report.is_file()
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert saved["verdict"] == "PASS"


def test_monitor_quiet_window_fail_on_db_warn(tmp_path: Path):
    log_path = tmp_path / "ed_server.log"
    log_path.write_text("INFO:ed_server:ready\n", encoding="utf-8")
    report = tmp_path / "report.json"
    clock = {"t": 0.0}
    injected = {"done": False}

    def now():
        return clock["t"]

    def sleep(dt):
        clock["t"] += float(dt)
        if not injected["done"] and clock["t"] >= 0.5:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write("WARNING:db:sqlite_bg_write_slow elapsed_ms=2500\n")
            injected["done"] = True

    result = monitor_quiet_window(
        log_path=log_path,
        window_sec=5.0,
        poll_sec=0.5,
        skip_health=True,
        write_report=True,
        report_path=report,
        now_fn=now,
        sleep_fn=sleep,
    )
    assert result["verdict"] == "FAIL"
    assert result["ok"] is False
    assert result["warn_count"] >= 1
    assert any("sqlite_bg_write_slow" in w for w in result["warns"])


def test_monitor_quiet_window_fail_on_ed_server_warn_marker(tmp_path: Path):
    log_path = tmp_path / "ed_server.log"
    log_path.write_text("INFO:ed_server:ready\n", encoding="utf-8")
    clock = {"t": 0.0}
    injected = {"done": False}

    def now():
        return clock["t"]

    def sleep(dt):
        clock["t"] += float(dt)
        if not injected["done"] and clock["t"] >= 0.5:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(
                    "[WARN] WARNING:ed_server:L1 payload scope drift: "
                    "['quote_source_detail']\n"
                )
            injected["done"] = True

    result = monitor_quiet_window(
        log_path=log_path,
        window_sec=5.0,
        poll_sec=0.5,
        skip_health=True,
        write_report=False,
        now_fn=now,
        sleep_fn=sleep,
    )
    assert result["verdict"] == "FAIL"
    assert any("L1 payload scope drift" in w for w in result["fails"])


def test_monitor_stale_log_fail_closed_measurement_invalid(tmp_path: Path):
    """Dead file sink must never PASS — prior false-green class."""
    log_path = tmp_path / "ed_server.log"
    log_path.write_text("INFO:ed_server:frozen\n", encoding="utf-8")
    report = tmp_path / "report.json"
    clock = {"t": 0.0}

    def now():
        return clock["t"]

    def sleep(dt):
        clock["t"] += float(dt)
        # Deliberately do NOT append — simulates dead FileHandler.

    result = monitor_quiet_window(
        log_path=log_path,
        window_sec=2.0,
        poll_sec=0.5,
        skip_health=True,
        write_report=True,
        report_path=report,
        now_fn=now,
        sleep_fn=sleep,
        require_log_progress=True,
    )
    assert result["ok"] is False
    assert result["verdict"] == "MEASUREMENT_INVALID"
    assert result["measurement_invalid"] is True
    assert result["log_progressed"] is False
    assert result["warn_count"] == 0


def test_install_ed_server_file_sink_captures_db_warning(tmp_path: Path):
    """Root FileHandler must record WARNING:db:... (not ed_server-only)."""
    # Import install helper without relying on live boot path side effects beyond
    # the function itself (server import is used elsewhere in this suite).
    import server as srv

    log_path = tmp_path / "ed_server.log"
    handler = srv.install_ed_server_file_sink(log_path, level=logging.INFO)
    try:
        logging.getLogger("db").warning("sqlite_bg_write_slow elapsed_ms=42")
        handler.flush()
        text = log_path.read_text(encoding="utf-8")
        assert "WARNING:db:sqlite_bg_write_slow" in text or (
            "[WARN]" in text and "db" in text and "sqlite_bg_write_slow" in text
        )
        assert is_quiet_window_fail_line(text.strip().splitlines()[-1])
    finally:
        root = logging.getLogger()
        root.removeHandler(handler)
        handler.close()


def test_fill_outcomes_latency_log_severity_honest_for_quiet_window():
    """5s+/10s+ stay WARNING (quiet FAIL). Cosmetics-only demote to INFO is banned."""
    from db import _fill_outcomes_latency_log

    assert _fill_outcomes_latency_log(999.0) == (None, None)
    assert _fill_outcomes_latency_log(1_500.0) == (logging.INFO, "1s+")
    assert _fill_outcomes_latency_log(5_500.0) == (logging.WARNING, "5s+")
    assert _fill_outcomes_latency_log(22_970.0) == (logging.WARNING, "10s+")
    assert _fill_outcomes_latency_log(60_000.0) == (logging.WARNING, "10s+")
    assert not is_quiet_window_fail_line(
        "INFO:db:sqlite_bg_write op=fill_outcomes exec_ms=1500.0"
    )
    assert is_quiet_window_fail_line(
        "WARNING:db:sqlite_bg_write_slow op=fill_outcomes tier=10s+ exec_ms=22970.0"
    )
    assert is_quiet_window_fail_line(
        "[WARN] WARNING:db:sqlite_bg_write_slow op=fill_outcomes tier=5s+ exec_ms=5500.0"
    )
