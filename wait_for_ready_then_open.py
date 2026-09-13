"""wait_for_ready_then_open.py -- coordinate browser opening with actual server
readiness, instead of a fixed sleep.

The launcher used to open Edge on a blind 2-second timer, independently of
whether the server had actually finished starting -- on a slow cold start
(Schwab auth, DB init, warmers) the browser would land on a connection-refused
page well before the server was listening. This polls the real endpoint until
it answers, then opens the browser -- native capability (Python's own
urllib + subprocess), no new service.

Operator finding (2026-09-11): the first version always opened the browser and
always exited 0, whether the server answered 200, answered something else, or
never answered at all within the timeout -- "browser opened" was being used as
proof of "app started successfully", which a timeout or an error response does
not establish. This version distinguishes the three outcomes and reports (via
both stdout and process exit code) which one happened; only a genuine timeout
skips opening the browser at all, since there is then nothing real to show.

Usage: python tools/wait_for_ready_then_open.py <url> <browser_exe> [timeout_sec]
Exit 0: the URL answered 200 -- opened the browser.
Exit 1: the URL answered, but not with 200 (server up, not healthy at this
        route) -- opened the browser anyway (something real to look at), but
        this is reported distinctly, not as clean success.
Exit 2: the URL never answered within the timeout -- did NOT open the browser.
"""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request

DEFAULT_TIMEOUT_SEC = 90.0
POLL_INTERVAL_SEC = 0.25


def wait_until_ready(url: str, timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> str:
    """Poll `url` until it answers or `timeout_sec` elapses.
    Returns "ready" (status == 200, exactly), "unhealthy" (answered with any
    other status, including other 2xx like 204), or "timeout" (never answered).

    Independent-review finding (2026-09-12): urllib.request.urlopen only raises
    HTTPError for 4xx/5xx -- ANY 2xx (200-299) returns normally without raising,
    so a bare `except HTTPError` treated every 2xx as "ready" including a 204
    (No Content), despite this function's own stated 200-only contract. Fixed by
    checking the actual status code on the non-raising path too.
    """
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            resp = urllib.request.urlopen(url, timeout=2)
            return "ready" if resp.status == 200 else "unhealthy"
        except urllib.error.HTTPError:
            # The server IS up and routing requests -- just not a 200 for this
            # exact path (4xx/5xx here). Worth reporting distinctly, not
            # silently equated with "ready".
            return "unhealthy"
        except Exception:
            time.sleep(POLL_INTERVAL_SEC)
    return "timeout"


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 4):
        print("usage: wait_for_ready_then_open.py <url> <browser_exe> [timeout_sec]", file=sys.stderr)
        return 2
    url, browser_exe = argv[1], argv[2]
    timeout_sec = float(argv[3]) if len(argv) == 4 else DEFAULT_TIMEOUT_SEC
    result = wait_until_ready(url, timeout_sec)
    if result == "ready":
        subprocess.Popen([browser_exe, url])
        return 0
    if result == "unhealthy":
        print(f"WARNING: {url} answered but not with 200 -- opening it anyway so you can see the actual response.")
        subprocess.Popen([browser_exe, url])
        return 1
    print(f"WARNING: {url} never answered within {timeout_sec}s -- NOT opening the browser. "
          f"Check the server's own console window for the actual failure.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
