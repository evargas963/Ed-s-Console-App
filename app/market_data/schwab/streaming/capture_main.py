"""The capture daemon's start, as its window runs it (start_capture_daemon.bat).

    python -m app.market_data.schwab.streaming.capture_main

The window is the daemon's error output: a module that fails to load shows its reason there, and
from the log's start every line goes to the day's log file and to the window.
"""

from app.market_data.schwab.streaming import capture

if __name__ == "__main__":
    raise SystemExit(capture.main())
