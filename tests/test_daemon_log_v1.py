"""The capture daemon's log (capture.DailyLog): every line, with its wall time, in the file of its
own day; the newest LOG_DAYS_KEPT days kept. No file is renamed, so the day changes while another
process holds the day's file open (Windows refuses to rename a file another process holds open).

STAND-IN: a second Python process holding the day's file open, as a log viewer or a second
daemon's start does.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

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
        [sys.executable, "-c", "import sys, time; f = open(sys.argv[1], 'a'); print('open', flush=True); "
         "time.sleep(60)", str(capture.log_path(tmp_path, before.date()))], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "open"
        _line(handler, before + timedelta(seconds=2), "after midnight")
        handler.close()
    finally:
        holder.kill()
        holder.wait()
    assert capture.log_path(tmp_path, before.date()).read_text(encoding="utf-8") == "before midnight\n"
    assert capture.log_path(tmp_path, date(2026, 10, 9)).read_text(encoding="utf-8") == "after midnight\n", \
        "a line after midnight did not reach the new day's file"


def test_a_days_file_the_disk_will_not_open_never_raises_where_the_daemon_logs(tmp_path):
    """INDUCED CONDITION: a folder where the new day's file would be, so the disk will not open it.
    A line that day does not raise at the call that logged it (logging's own error report takes
    it); once the folder is gone the next line opens the day's file."""
    before = datetime(2026, 10, 8, 23, 59, 59)
    handler = capture.DailyLog(tmp_path)
    _line(handler, before, "before midnight")
    capture.log_path(tmp_path, date(2026, 10, 9)).mkdir()
    _line(handler, before + timedelta(seconds=2), "the file will not open")
    capture.log_path(tmp_path, date(2026, 10, 9)).rmdir()
    _line(handler, before + timedelta(seconds=3), "after midnight")
    handler.close()
    assert capture.log_path(tmp_path, before.date()).read_text(encoding="utf-8") == "before midnight\n"
    assert capture.log_path(tmp_path, date(2026, 10, 9)).read_text(encoding="utf-8") == "after midnight\n"


def test_the_newest_45_days_are_kept(tmp_path):
    """50 earlier days' files beside the log; at the next day's first line the 45 newest stay,
    the new day's among them."""
    days = [date(2026, 8, 1) + timedelta(days=i) for i in range(50)]
    for d in days:
        capture.log_path(tmp_path, d).write_text(f"{d}\n", encoding="utf-8")
    handler = capture.DailyLog(tmp_path)
    _line(handler, datetime(2026, 9, 20, 9, 0), "the next day")
    handler.close()
    kept = sorted(tmp_path.glob("stream_capture.*.log"))
    assert capture.LOG_DAYS_KEPT == 45
    assert kept == [capture.log_path(tmp_path, d) for d in days[6:]] + [capture.log_path(tmp_path, date(2026, 9, 20))]


def test_the_daemons_log_has_every_line_with_its_wall_time(tmp_path):
    """The daemon's log as it starts it (_start_log), under a runtime root of its own: a line
    reaches the day's file under <runtime>/logs, beginning with its date and time."""
    script = ("from app.market_data.schwab.streaming import capture; capture._start_log(); "
              "capture.log.warning('schwab: connection ended (socket closed)')")
    subprocess.run([sys.executable, "-c", script], cwd=REPO, env={**os.environ, "ED_RUNTIME_ROOT": str(tmp_path)},
                   check=True, timeout=120)
    (log,) = (tmp_path / "logs").glob("stream_capture.*.log")
    text = log.read_text(encoding="utf-8")
    assert "schwab: connection ended (socket closed)" in text
    datetime.strptime(text[:23], "%Y-%m-%d %H:%M:%S.%f")
