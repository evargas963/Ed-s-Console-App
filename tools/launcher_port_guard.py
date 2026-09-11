"""launcher_port_guard.py -- ownership-verified stop for start_ed_console.bat.

Operator finding (2026-09-11): the launcher used to `taskkill /F` whatever PID held
the target port, with no check on WHAT it was -- an unrelated process that happened
to be using that port would be killed too, silently. This script only stops a
process whose own command line names an Ed Console server entry point
(uvicorn ... server:app); anything else is left alone and reported so the operator
can decide, matching the adversarial requirement "an unrelated process occupying
the intended port -- leave that process intact".

Usage: python tools/launcher_port_guard.py <port>
Exit 0: the port was already free, or an Ed Console instance was found and
        stopped and the port is now free.
Exit 1: the port is held by something that is NOT an Ed Console server (left
        running), or an Ed Console instance was stopped but the port is still
        occupied after stopping it.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time


def listening_pid(port: int) -> str | None:
    """PID of the process LISTENING on 127.0.0.1:<port>, or None if nothing is."""
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        return None
    needle = f":{port} "
    for line in out.splitlines():
        if needle in line and "LISTENING" in line:
            parts = line.split()
            if parts:
                return parts[-1]
    return None


def command_line_for_pid(pid: str) -> str:
    """The full command line of `pid`, or '' if it cannot be read (e.g. already exited)."""
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


def is_ed_console_command_line(cmd: str) -> bool:
    """True only for an Ed Console uvicorn server process -- the one shape this
    launcher is ever allowed to stop on its own authority."""
    c = (cmd or "").lower()
    return "uvicorn" in c and "server:app" in c


def port_is_free(port: int) -> bool:
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", port)) != 0
    finally:
        s.close()


def ensure_port_free(port: int, *, out=print) -> int:
    """Stop a prior Ed Console instance on `port` if one is found; leave anything
    else alone. Returns a process exit code (0 = free / stopped, 1 = still held
    by something that should not be touched, or that failed to stop)."""
    pid = listening_pid(port)
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
