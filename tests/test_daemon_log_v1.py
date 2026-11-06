"""The capture daemon's log (capture.DailyLog): every line, with its wall time, in the file of its
own day; the newest LOG_DAYS_KEPT days kept. No file is renamed, so the day changes while another
process holds the day's file open (Windows refuses to rename a file another process holds open).

STAND-IN: a second Python process holding the day's file open, as a log viewer or a second
daemon's start does.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import runtime_layout
from app.market_data.schwab.streaming import capture

REPO = Path(__file__).resolve().parent.parent


def _line(handler: logging.Handler, when: datetime, text: str) -> None:
    record = logging.LogRecord("capture", logging.INFO, __file__, 0, text, None, None)
    record.created = when.timestamp()
    handler.handle(record)


def test_the_day_changes_while_another_process_holds_the_log_open(tmp_path):
    before = datetime(2026, 10, 8, 23, 59, 59)
    handler = capture.DailyLog(tmp_path)
    _line(handler, before, "before midnight")
    handler.flush()
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time; f = open(sys.argv[1], 'a'); print('open', flush=True); "
            "time.sleep(60)",
            str(runtime_layout.daemon_log_path(tmp_path, before.date())),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "open"
        _line(handler, before + timedelta(seconds=2), "after midnight")
        handler.close()
    finally:
        holder.kill()
        holder.wait()
    assert (
        runtime_layout.daemon_log_path(tmp_path, before.date()).read_text(encoding="utf-8")
        == "before midnight\n"
    )
    assert (
        runtime_layout.daemon_log_path(tmp_path, date(2026, 10, 9)).read_text(encoding="utf-8")
        == "after midnight\n"
    ), "a line after midnight did not reach the new day's file"


def test_a_days_file_the_disk_will_not_open_never_raises_where_the_daemon_logs(tmp_path):
    """INDUCED CONDITION: a folder where the new day's file would be, so the disk will not open it.
    A line that day does not raise at the call that logged it (logging's own error report takes
    it); once the folder is gone the next line opens the day's file."""
    before = datetime(2026, 10, 8, 23, 59, 59)
    handler = capture.DailyLog(tmp_path)
    _line(handler, before, "before midnight")
    runtime_layout.daemon_log_path(tmp_path, date(2026, 10, 9)).mkdir()
    _line(handler, before + timedelta(seconds=2), "the file will not open")
    runtime_layout.daemon_log_path(tmp_path, date(2026, 10, 9)).rmdir()
    _line(handler, before + timedelta(seconds=3), "after midnight")
    handler.close()
    assert (
        runtime_layout.daemon_log_path(tmp_path, before.date()).read_text(encoding="utf-8")
        == "before midnight\n"
    )
    assert (
        runtime_layout.daemon_log_path(tmp_path, date(2026, 10, 9)).read_text(encoding="utf-8")
        == "after midnight\n"
    )


def test_the_newest_45_days_are_kept(tmp_path):
    """50 earlier days' files beside the log; at the next day's first line the 45 newest stay,
    the new day's among them."""
    days = [date(2026, 8, 1) + timedelta(days=i) for i in range(50)]
    for d in days:
        runtime_layout.daemon_log_path(tmp_path, d).write_text(f"{d}\n", encoding="utf-8")
    handler = capture.DailyLog(tmp_path)
    _line(handler, datetime(2026, 9, 20, 9, 0), "the next day")
    handler.close()
    kept = sorted(tmp_path.glob("stream_capture.*.log"))
    assert capture.LOG_DAYS_KEPT == 45
    assert kept == [runtime_layout.daemon_log_path(tmp_path, d) for d in days[6:]] + [
        runtime_layout.daemon_log_path(tmp_path, date(2026, 9, 20))
    ]


def test_the_daemons_log_has_every_line_with_its_wall_time(tmp_path):
    """The daemon's log as it starts it (_start_log), under a runtime root of its own: a line
    reaches the day's file under <runtime>/logs, beginning with its date and time."""
    script = (
        "from app.market_data.schwab.streaming import capture; capture._start_log(); "
        "capture.log.warning('schwab: connection ended (socket closed)')"
    )
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        env={**os.environ, "ED_RUNTIME_ROOT": str(tmp_path)},
        check=True,
        timeout=120,
    )
    (log,) = (tmp_path / "logs").glob("stream_capture.*.log")
    text = log.read_text(encoding="utf-8")
    assert "schwab: connection ended (socket closed)" in text
    datetime.strptime(text[:23], "%Y-%m-%d %H:%M:%S.%f")


def test_a_window_that_holds_its_writes_never_stops_the_daemon(tmp_path):
    """Measured 2026-11-05 05:17 to 07:07 CT: text selected in the daemon's window held every
    write to it, and the daemon stopped inside its next log line (its event loop and its chain
    thread, a token refresh with them). Here the window holds every write for good: each line is
    logged at once and reaches the day's file. STAND-IN: the window, an error output whose
    write never returns."""
    script = (
        "import os, sys, threading, time\n"
        "class Held:\n"
        "    def write(self, text):\n"
        "        threading.Event().wait()\n"
        "    def flush(self):\n"
        "        pass\n"
        "from app.market_data.schwab.streaming import capture\n"
        "sys.stderr = Held()\n"
        "capture._start_log()\n"
        "started = time.monotonic()\n"
        "for n in range(3):\n"
        "    capture.log.warning('line %d', n)\n"
        "print(time.monotonic() - started, flush=True)\n"
        "os._exit(0)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        env={**os.environ, "ED_RUNTIME_ROOT": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert float(done.stdout) < 1.0, "a log line waited on the window"
    (log,) = (tmp_path / "logs").glob("stream_capture.*.log")
    assert [line[24:] for line in log.read_text(encoding="utf-8").splitlines()] == [
        "line 0",
        "line 1",
        "line 2",
    ]


def test_a_window_line_reaches_the_window_and_not_the_days_file(tmp_path):
    """What Schwab streamed is recorded in stream_capture.db; the window's line of it is not
    written a second time in the day's file, and every other line still is."""
    script = (
        "import logging\n"
        "from app.market_data.schwab.streaming import capture\n"
        "capture._start_log()\n"
        "capture.WINDOW_ONLY.info('PUSH LEVELONE_EQUITIES: 1 messages')\n"
        "capture.log.warning('schwab: connected')\n"
        "logging.shutdown()\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        env={**os.environ, "ED_RUNTIME_ROOT": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert "PUSH LEVELONE_EQUITIES: 1 messages" in done.stderr
    (log,) = (tmp_path / "logs").glob("stream_capture.*.log")
    assert [line[24:] for line in log.read_text(encoding="utf-8").splitlines()] == [
        "schwab: connected"
    ]


def test_every_window_line_reaches_the_window_before_the_program_ends(tmp_path):
    """The window's lines are printed by a thread of their own from a queue: a program that
    ends the moment it has logged still prints every line it logged, in order (the last lines
    of a clean stop included)."""
    script = (
        "from app.market_data.schwab.streaming import capture\n"
        "capture._start_log()\n"
        "for i in range(2000):\n"
        "    capture.WINDOW_ONLY.info('PUSH line %d', i)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        env={**os.environ, "ED_RUNTIME_ROOT": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    shown = [line.split(" ", 2)[2] for line in done.stderr.splitlines() if " PUSH line " in line]
    assert shown == [f"PUSH line {i}" for i in range(2000)]


def test_the_window_shows_each_second_what_schwab_streamed(caplog):
    """Real LEVELONE and book messages Schwab sent (2026-10-05 14:00 CT) through the daemon's
    receive handler: the window's line per service gives the messages, the symbols they came
    for, and the newest message as Schwab sent it."""
    mix = json.loads((REPO / "tests/fixtures/real_stream_mix_2026_10_05_1400ct.json").read_text())
    messages = mix["messages"][:400]
    bus, health = capture.MessageBus(), capture.HealthRegistry()

    async def run():
        stop = asyncio.Event()
        window = asyncio.create_task(capture.show_stream(bus, stop, every=0.05))
        await asyncio.sleep(0)
        for m in messages:
            frame = {"timestamp": m["schwab_ts"], "content": [m["item"]]}
            capture._publisher(m["service"], bus, health)(frame)
        await asyncio.sleep(0.2)
        stop.set()
        await window

    with caplog.at_level(logging.INFO, logger="capture"):
        asyncio.run(run())
    shown = [r.getMessage() for r in caplog.records if r.getMessage().startswith("PUSH ")]
    for service in {m["service"] for m in messages}:
        sent = [m for m in messages if m["service"] == service]
        newest = sent[-1]["item"]
        fields = ", ".join(
            f"{k} [{len(v)}]" if isinstance(v, list) else f"{k} {v}"
            for k, v in newest.items()
            if k != "key"
        )
        assert (
            shown.count(
                f"PUSH {service}: {len(sent)} messages, "
                f"{len({m['item']['key'].upper() for m in sent})} symbols | "
                f"newest {newest['key'].upper()}: {fields}"
            )
            == 1
        ), service
