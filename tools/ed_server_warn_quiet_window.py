#!/usr/bin/env python3
"""Live gate: zero WARNING+ / traceback lines in the quiet window after restart.

DONE bar (operator): after restart via start_ed_console.bat, this must PASS
for the default 5-minute window before LIVE closeout claims a clean console.

FAIL on ANY malfunction signal in the monitored log during the window:
  - logging levels WARNING / ERROR / CRITICAL (any logger — db, ed_server, uvicorn, …)
  - visual markers [WARN] / [ERR ] / [CRIT] from server.py _LevelMarkerFormatter
  - stdlib-style " WARNING:" / " ERROR:" / " CRITICAL:" (any logger name)
  - Python traceback headers: "Traceback (most recent call last):"

Primary rule: level >= WARNING OR traceback. INFO/DEBUG never fail the gate
even if the message text contains "fail".

MEASUREMENT INTEGRITY: if the log file does not progress during the window
while server health is ok, verdict is MEASUREMENT_INVALID (exit non-zero) —
never PASS on a dead/stale file sink. Prior PASS with a non-growing
logs/ed_server.log is VOID.

Usage:
  python -m tools.ed_server_warn_quiet_window
  python -m tools.ed_server_warn_quiet_window --minutes 5
  python -m tools.ed_server_warn_quiet_window --seconds 5   # smoke / unit
  python -m tools.ed_server_warn_quiet_window --log-path PATH --skip-health
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime_layout import logs_dir, reports_dir  # noqa: E402 — RC-523: runtime/artifacts roots

DEFAULT_HEALTH_URL = "http://127.0.0.1:8000/api/health"
DEFAULT_LOG_PATH = logs_dir() / "ed_server.log"
DEFAULT_REPORT = reports_dir() / "ed_server_warn_quiet_window_latest.json"
DEFAULT_WINDOW_SEC = 300

# Any logger. Level >= WARNING (markers + stdlib levelname) OR traceback.
# Do NOT bind logger names (ed_server / db / uvicorn all count).
_FAIL_LINE_RE = re.compile(
    r"(?:"
    r"\[(?:WARN|ERR\s|CRIT)\]"  # _LevelMarkerFormatter plain/ANSI-stripped markers
    r"|(?:^|\s)(?:WARNING|ERROR|CRITICAL):"  # stdlib "WARNING:name:msg"
    r"|Traceback \(most recent call last\):"
    r")",
    re.IGNORECASE,
)


def is_quiet_window_fail_line(line: str) -> bool:
    """True if *line* is WARNING+/ERROR/CRITICAL (any logger) or a traceback header."""
    return bool(_FAIL_LINE_RE.search(line))


def collect_fail_lines_from_text(text: str) -> list[str]:
    """Return matching failure-signal lines from a text blob."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip("\n\r")
        if is_quiet_window_fail_line(line):
            out.append(line)
    return out


def probe_health(url: str, *, timeout_sec: float = 5.0) -> dict[str, Any]:
    """GET health endpoint; raise RuntimeError if not reachable / not ok."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = int(resp.status)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"health probe failed: {url}: {exc}") from exc
    if status != 200:
        raise RuntimeError(f"health probe HTTP {status}: {url}")
    try:
        payload = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        payload = {"raw": body[:200]}
    if isinstance(payload, dict) and payload.get("status") not in (None, "ok"):
        raise RuntimeError(f"health status not ok: {payload!r}")
    return payload if isinstance(payload, dict) else {"raw": payload}


def _file_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def monitor_quiet_window(
    *,
    log_path: Path,
    window_sec: float,
    poll_sec: float = 0.5,
    health_url: str | None = DEFAULT_HEALTH_URL,
    skip_health: bool = False,
    write_report: bool = True,
    report_path: Path = DEFAULT_REPORT,
    now_fn=None,
    sleep_fn=None,
    require_log_progress: bool | None = None,
) -> dict[str, Any]:
    """Watch *log_path* for WARNING+/traceback lines for *window_sec*.

    PASS only if: (1) zero failure-signal matches, (2) full window elapsed, and
    (3) the log file progressed (grew) during the window when progress is
    required. Progress is required when health was probed OK, or when
    *require_log_progress* is True. Default: require progress unless
    skip_health and require_log_progress is not explicitly True — wait:
    operator: fail closed if no progress while health ok. Unit tests that
    skip health still need growing INFO for PASS — so default
    require_log_progress=True always (dead sink never PASSes).
    """
    now_fn = time.time if now_fn is None else now_fn
    sleep_fn = time.sleep if sleep_fn is None else sleep_fn
    if require_log_progress is None:
        require_log_progress = True

    health: dict[str, Any] | None = None
    if not skip_health:
        if not health_url:
            raise RuntimeError("health_url required unless --skip-health")
        health = probe_health(health_url)

    log_path = Path(log_path)
    if not log_path.parent.exists():
        log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.touch()

    start_offset = _file_size(log_path)
    started_at = float(now_fn())
    deadline = started_at + float(window_sec)
    fails: list[str] = []
    cursor = start_offset
    saw_new_bytes = False

    while True:
        size = _file_size(log_path)
        if size < cursor:
            # Rotation / truncate — rescan from start of new file.
            cursor = 0
            saw_new_bytes = True
        if size > cursor:
            with log_path.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(cursor)
                chunk = fh.read()
                cursor = fh.tell()
            saw_new_bytes = True
            for line in collect_fail_lines_from_text(chunk):
                fails.append(line)
        now = float(now_fn())
        if fails or now >= deadline:
            break
        remaining = deadline - now
        sleep_fn(min(poll_sec, max(0.01, remaining)))

    ended_at = float(now_fn())
    elapsed = max(0.0, ended_at - started_at)
    end_offset = cursor
    final_size = _file_size(log_path)
    log_progressed = bool(saw_new_bytes or final_size != start_offset)

    measurement_invalid = bool(require_log_progress) and (not log_progressed)
    passed = (
        len(fails) == 0
        and elapsed + 1e-9 >= float(window_sec)
        and not measurement_invalid
    )
    if fails:
        passed = False

    if measurement_invalid and not fails:
        verdict = "MEASUREMENT_INVALID"
    elif passed:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    result: dict[str, Any] = {
        "ok": passed,
        "verdict": verdict,
        "window_sec": float(window_sec),
        "elapsed_sec": round(elapsed, 3),
        "started_at_utc": datetime.fromtimestamp(started_at, tz=timezone.utc).isoformat(),
        "ended_at_utc": datetime.fromtimestamp(ended_at, tz=timezone.utc).isoformat(),
        "log_path": str(log_path),
        "start_offset": start_offset,
        "end_offset": end_offset,
        "log_progressed": bool(log_progressed),
        "measurement_invalid": bool(measurement_invalid),
        "fail_count": len(fails),
        "warn_count": len(fails),  # back-compat key
        "fails": fails[:50],
        "warns": fails[:50],  # back-compat
        "match_rule": "level>=WARNING (any logger) OR Traceback header; INFO/DEBUG ignored",
        "health": health,
        "health_url": health_url if not skip_health else None,
        "skip_health": bool(skip_health),
        "require_log_progress": bool(require_log_progress),
    }
    if write_report:
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        result["report_path"] = str(report_path)
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "PASS only if zero WARNING/ERROR/CRITICAL (any logger) and zero "
            "traceback lines in the quiet window, AND the log file progressed "
            "(fail-closed on a dead file sink)."
        )
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--minutes",
        type=float,
        default=None,
        help="Quiet window length in minutes (default: 5).",
    )
    g.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="Quiet window length in seconds (overrides minutes; use 5 for smoke).",
    )
    p.add_argument(
        "--log-path",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help=f"Monitored log file (default: {DEFAULT_LOG_PATH})",
    )
    p.add_argument(
        "--health-url",
        default=DEFAULT_HEALTH_URL,
        help=f"Health probe URL (default: {DEFAULT_HEALTH_URL})",
    )
    p.add_argument(
        "--skip-health",
        action="store_true",
        help="Skip live health probe (unit/smoke with a fake log only).",
    )
    p.add_argument(
        "--poll-sec",
        type=float,
        default=0.5,
        help="Poll interval while watching the log (default: 0.5).",
    )
    p.add_argument(
        "--no-report",
        action="store_true",
        help="Do not write reports/ed_server_warn_quiet_window_latest.json",
    )
    p.add_argument(
        "--report-path",
        type=Path,
        default=DEFAULT_REPORT,
        help="JSON report path",
    )
    args = p.parse_args(argv)

    if args.seconds is not None:
        window_sec = float(args.seconds)
    elif args.minutes is not None:
        window_sec = float(args.minutes) * 60.0
    else:
        window_sec = float(DEFAULT_WINDOW_SEC)

    try:
        result = monitor_quiet_window(
            log_path=args.log_path,
            window_sec=window_sec,
            poll_sec=float(args.poll_sec),
            health_url=None if args.skip_health else str(args.health_url),
            skip_health=bool(args.skip_health),
            write_report=not args.no_report,
            report_path=args.report_path,
        )
    except RuntimeError as exc:
        fail = {
            "ok": False,
            "verdict": "FAIL",
            "error": str(exc),
            "window_sec": window_sec,
        }
        print(json.dumps(fail, indent=2))
        if not args.no_report:
            args.report_path.parent.mkdir(parents=True, exist_ok=True)
            args.report_path.write_text(json.dumps(fail, indent=2) + "\n", encoding="utf-8")
        return 2

    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
