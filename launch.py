"""Ed Console's launcher: start_ed_console.bat runs it with the project's .venv Python.

1. The settings both processes start from (environment): the shell's over .env's, without what a
   test shell leaves set that blocks every live Schwab call (TEST_SHELL, stand-in credentials).
2. The capture daemon, in its own window (start_capture_daemon.bat restarts it), unless one
   already serves its price socket. It holds the Schwab credentials and says on screen whether
   Schwab took them (the header's Schwab, from its heartbeat).
3. The console on port 8000, with the same settings but no Schwab credentials (it never calls
   Schwab and reads no .env of its own), unless one is
   already there: one that answers healthy within HEALTHY_WITHIN_SEC is opened and nothing is
   started; one that does not is stopped only when the operator says so here.
4. The browser, at URL, once the console answers healthy.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import psutil
from dotenv import dotenv_values

from app.market_data.schwab.streaming.live_ui import LIVE_UI_PORT as DAEMON_PORT
from config import ENV_FILE, schwab_credential_is_stand_in

ROOT = Path(__file__).resolve().parent
CONSOLE_PORT = 8000
URL = f"http://127.0.0.1:{CONSOLE_PORT}/"
HEALTHY_WITHIN_SEC = 10.0
#: --timeout-graceful-shutdown: Ctrl+C ends it while pages hold their change streams open
CONSOLE = [sys.executable, "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", str(CONSOLE_PORT),
           "--timeout-graceful-shutdown", "10"]
#: set by a test shell, it blocks every live Schwab call (config.schwab_live_blocked_for)
TEST_SHELL = ("ED_CI_OFFLINE",)
SCHWAB_CREDENTIALS = ("SCHWAB_API_KEY", "SCHWAB_APP_SECRET")
EDGE = [Path(os.environ[v]) / "Microsoft/Edge/Application/msedge.exe"
        for v in ("ProgramFiles(x86)", "ProgramFiles") if v in os.environ]


def daemon_environment(shell: "dict[str, str]", env_file: Path) -> "dict[str, str]":
    """The shell's settings over `env_file`'s (.env; the shell's value wins, as
    config.load_dotenv_file has it), without TEST_SHELL and without any Schwab credential that is
    a stand-in (config.schwab_credential_is_stand_in): .env's real one stands in its place."""
    def kept(settings: "dict[str, str]") -> "dict[str, str]":
        return {k: v for k, v in settings.items() if k not in TEST_SHELL
                and not (k in SCHWAB_CREDENTIALS and schwab_credential_is_stand_in(v))}
    from_file = {k: v for k, v in dotenv_values(env_file).items() if v is not None}
    return {**kept(from_file), **kept(shell)}


def console_environment(shell: "dict[str, str]", env_file: Path) -> "dict[str, str]":
    """The daemon's settings without any Schwab variable but the token's path (its age is shown)."""
    return {k: v for k, v in daemon_environment(shell, env_file).items()
            if not k.upper().startswith("SCHWAB_") or k.upper() == "SCHWAB_TOKEN_PATH"}


def listener(port: int) -> "psutil.Process | None":
    """The process listening on `port` on this machine, or None. A listener whose process cannot
    be read is refused: the port is taken, by whom is unknown."""
    for c in psutil.net_connections(kind="inet"):
        if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port:
            if not c.pid:
                raise PermissionError(f"port {port} is held by a process this user cannot see; nothing started")
            return psutil.Process(c.pid)
    return None


def unhealthy_for(port: int, seconds: float) -> "str | None":
    """None once the console on `port` answers /api/health with 200 within `seconds`; else the
    last answer it gave instead (an error status, a refused connection, a timeout)."""
    deadline = time.monotonic() + seconds
    why = f"no answer in {seconds:.0f} s"
    while (left := deadline - time.monotonic()) > 0:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=min(left, 2.0)) as r:
                if r.status == 200:
                    return None
                why = f"HTTP {r.status}"
        except OSError as e:
            why = f"{type(e).__name__}: {e}"
        time.sleep(min(0.25, max(deadline - time.monotonic(), 0)))
    return why


def console_on(port: int, ask, out=print) -> str:
    """What to do about the console on `port`: "open" (one answers healthy within
    HEALTHY_WITHIN_SEC), "start" (none, or the operator had the one that did not answer stopped)
    or "leave" (it did not answer and the operator kept it)."""
    proc = listener(port)
    if proc is None:
        return "start"
    why = unhealthy_for(port, HEALTHY_WITHIN_SEC)
    if why is None:
        out(f"Console: already running on port {port} (PID {proc.pid}) and healthy.")
        return "open"
    command = " ".join(proc.cmdline())
    reply = ask(f"Port {port} is held by PID {proc.pid} ({command}), which has not answered healthy in "
                f"{HEALTHY_WITHIN_SEC:.0f} s ({why}). Stop it and start a new console? [y/N] ")
    if reply.strip().lower() != "y":
        out(f"Left PID {proc.pid} running; nothing started.")
        return "leave"
    proc.kill()
    proc.wait(10)
    out(f"Stopped PID {proc.pid}.")
    return "start"


def open_browser(out=print) -> None:
    found = [p for p in EDGE if p.is_file()]
    if found:
        subprocess.Popen([str(found[0]), URL])
    else:
        out(f"Microsoft Edge not found; open {URL} yourself.")


def main() -> int:
    shell = dict(os.environ)
    if listener(DAEMON_PORT) is None:
        subprocess.Popen(["cmd", "/c", "start", "Ed Capture Daemon", "/min", str(ROOT / "start_capture_daemon.bat")],
                         env=daemon_environment(shell, ENV_FILE), cwd=ROOT)
        print('Capture daemon: started in its own window ("Ed Capture Daemon").')
    else:
        print(f"Capture daemon: already running (port {DAEMON_PORT} is serving).")
    action = console_on(CONSOLE_PORT, input)
    if action == "open":
        open_browser()
    if action != "start":
        return 0
    print(f"Console: starting on port {CONSOLE_PORT}; the browser opens at {URL} once it answers. Ctrl+C stops it.")
    console = subprocess.Popen(CONSOLE, env=console_environment(shell, ENV_FILE), cwd=ROOT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)   # Ctrl+C is the console's: it stops, then this ends
    started = time.monotonic()
    while console.poll() is None and unhealthy_for(CONSOLE_PORT, 1.0) is not None:
        pass
    if console.poll() is None:
        print(f"Console: healthy {time.monotonic() - started:.1f} s after its start.")
        open_browser()
    return console.wait()


if __name__ == "__main__":
    raise SystemExit(main())
