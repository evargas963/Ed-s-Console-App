"""The capture daemon's start, as its window runs it (start_capture_daemon.bat):

    pythonw -m app.market_data.schwab.streaming.capture_main

Under pythonw there is no error output. Until the daemon's log starts it is the day's log file,
opened here before the daemon's modules load, so a module that fails to load leaves its reason
there; capture.main closes it when the log starts."""

from __future__ import annotations

import os
import sys
import time
from datetime import date

import runtime_layout


def main() -> int:
    early_errors = None
    if sys.stderr is None:
        folder = runtime_layout.logs_dir()
        folder.mkdir(parents=True, exist_ok=True)
        early_errors = sys.stderr = open(
            runtime_layout.daemon_log_path(folder, date.today()), "a", encoding="utf-8", buffering=1
        )
        print(
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} capture daemon loading (pid {os.getpid()})",
            file=sys.stderr,
        )
    from app.market_data.schwab.streaming import capture

    return capture.main(early_errors)


if __name__ == "__main__":
    raise SystemExit(main())
