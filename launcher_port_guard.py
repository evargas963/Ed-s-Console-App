"""launcher_port_guard.py -- ownership-verified stop for start_ed_console.bat.

Operator finding (2026-09-11): the launcher used to `taskkill /F` whatever PID held
the target port, with no check on WHAT it was -- an unrelated process that happened
to be using that port would be killed too, silently. This script only stops a
process whose own command line matches the real Ed Console invocation shape
(python[.exe] -m uvicorn ... server:app); anything else is left alone and
reported so the operator can decide, matching the adversarial requirement "an
unrelated process occupying the intended port -- leave that process intact".

Usage: python tools/launcher_port_guard.py <port>
Exit 0: the port was CONFIRMED free, or an Ed Console instance was found and
        stopped and the port is now free.
Exit 1: the port is held by something that is NOT an Ed Console server (left
        running), or an Ed Console instance was stopped but the port is still
        occupied after stopping it.
Exit 2: port state could not be determined (netstat/process inspection
        failed) -- this is NOT treated as "the port is free"; the launcher
        must not guess and proceed into a possibly-occupied port.
"""
from __future__ import annotations

import re
import socket
import subprocess
import sys
import time


class PortInspectionError(Exception):
    """Raised when netstat/process inspection itself fails -- a genuinely UNKNOWN
    port state, never to be treated as 'confirmed free' (operator finding:
    a netstat failure used to fall through to `None`, which `ensure_port_free`
    read as 'nothing is listening' and launched anyway)."""


def listening_pid(port: int) -> str | None:
    """PID of the process LISTENING on 127.0.0.1:<port>, or None if netstat ran
    successfully and found no such listener. Raises PortInspectionError if
    netstat itself could not be run/parsed -- that is an unknown state, not
    a free port."""
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except Exception as e:
        raise PortInspectionError(f"netstat -ano failed: {e}") from e
    needle = f":{port} "
    for line in out.splitlines():
        if needle in line and "LISTENING" in line:
            parts = line.split()
            if parts:
                return parts[-1]
    return None


def command_line_for_pid(pid: str) -> str:
    """The full command line of `pid`, or '' if it cannot be read (e.g. already exited).
    Deliberately NOT a PortInspectionError: a process that exited between the netstat
    read and this lookup is a real, common race, not an inspection failure -- an empty
    command line correctly fails is_ed_console_command_line's check below and the
    caller reports it rather than guessing either way."""
    try:
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
            ],
            capture_output=True, text=True, timeout=10,
        ).stdout
        return (out or "").strip()
    except Exception:
        return ""


# Operator finding (2026-09-11): the previous check was `"uvicorn" in c and
# "server:app" in c` -- true for ANY command line containing both substrings
# ANYWHERE (e.g. a text editor with a file path mentioning both words), not
# just a real Ed Console invocation. This anchors the two tokens to the actual
# shape every launch entry in this repo (launch.json, start_ed_console.bat)
# uses: a python[.exe] interpreter, `-m uvicorn`, and `server:app` as the
# ASGI target, in that relative order.
_ED_CONSOLE_INVOCATION_RE = re.compile(
    r"python(?:\.exe)?\"?\s+-m\s+uvicorn\b[^\r\n]*\bserver:app\b", re.IGNORECASE,
)


def is_ed_console_command_line(cmd: str) -> bool:
    """True only for a command line matching the real Ed Console server
    invocation shape -- the one thing this launcher is ever allowed to stop
    on its own authority."""
    if not cmd:
        return False
    return bool(_ED_CONSOLE_INVOCATION_RE.search(cmd))


def port_is_free(port: int) -> bool:
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", port)) != 0
    finally:
        s.close()


def ensure_port_free(port: int, *, out=print) -> int:
    """Stop a prior Ed Console instance on `port` if one is found; leave anything
    else alone. Returns a process exit code: 0 = confirmed free / stopped,
    1 = held by something not to be touched (or failed to clear), 2 = port
    state could not be determined at all (fail closed -- never guess free)."""
    try:
        pid = listening_pid(port)
    except PortInspectionError as e:
        out(f"WARNING: could not determine whether port {port} is free ({e}).")
        out("Refusing to guess -- treating this as NOT confirmed free.")
        return 2
    if pid is None:
        out(f"Port {port} is free.")
        return 0
    cmd = command_line_for_pid(pid)
    if not is_ed_console_command_line(cmd):
        out(f"WARNING: port {port} is held by PID {pid}, which is NOT an Ed Console server:")
        out(f"  {cmd or '(command line unavailable -- process may already have exited)'}")
        out(f"Leaving it running -- free port {port} yourself if you want Ed Console there.")
        return 1
    out(f"Stopping prior Ed Console instance on port {port} (PID {pid})...")
    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
    for _ in range(10):
        if port_is_free(port):
            out(f"Port {port} is now free.")
            return 0
        time.sleep(0.5)
    out(f"WARNING: stopped PID {pid} but port {port} is still occupied.")
    return 1


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: launcher_port_guard.py <port>", file=sys.stderr)
        return 2
    return ensure_port_free(int(argv[1]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
