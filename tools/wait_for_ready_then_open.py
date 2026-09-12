"""wait_for_ready_then_open.py -- coordinate browser opening with actual server
readiness, instead of a fixed sleep.

The launcher used to open Edge on a blind 2-second timer, independently of
whether the server had actually finished starting -- on a slow cold start
(Schwab auth, DB init, warmers) the browser would land on a connection-refused
page well before the server was listening. This polls the real endpoint until
it answers, then opens the browser -- native capability (Python's own
urllib + subprocess), no new service.

Usage: python tools/wait_for_ready_then_open.py <url> <browser_exe> [timeout_sec]
"""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request

DEFAULT_TIMEOUT_SEC = 90.0
POLL_INTERVAL_SEC = 0.25


def wait_until_ready(url: str, timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> bool:
    """Poll `url` until it returns any HTTP response (readiness proxy: the ASGI
    app is accepting requests), or `timeout_sec` elapses. Returns whether it
    became ready."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except urllib.error.HTTPError:
            # Any HTTP status (even 404/500) proves the server is accepting
            # connections and routing requests -- that is what "ready to open
            # a browser at" means here, not "every subsystem is warm".
            return True
        except Exception:
            time.sleep(POLL_INTERVAL_SEC)
    return False


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 4):
        print("usage: wait_for_ready_then_open.py <url> <browser_exe> [timeout_sec]", file=sys.stderr)
        return 2
    url, browser_exe = argv[1], argv[2]
    timeout_sec = float(argv[3]) if len(argv) == 4 else DEFAULT_TIMEOUT_SEC
    ready = wait_until_ready(url, timeout_sec)
    if not ready:
        print(f"wait_for_ready_then_open: {url} did not answer within {timeout_sec}s -- opening anyway.")
    subprocess.Popen([browser_exe, url])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
