"""launcher_port_guard.py -- ownership-verified stop for start_ed_console.bat.

Independent-review findings (2026-09-11/12), each verified against the actual
code before this rewrite:

1. The original check was `"uvicorn" in c and "server:app" in c` -- true for ANY
   command line containing both substrings anywhere. Tightened once to a regex
   anchored on the real invocation shape (python[.exe] -m uvicorn ... server:app) --
   but invocation SHAPE still does not prove OWNERSHIP: an unrelated FastAPI app
   using the same common `server.py` / `app = FastAPI()` naming convention would
   pass that regex too, with intercepted external calls proving it reaches
   taskkill. Fixed by adding a SECOND, independent check: the process must also
   answer its own /api/build identity endpoint (this app's existing identity
   mechanism, used throughout this project's own verification) with the expected
   shape. Both must agree before anything is stopped.
2. `netstat -ano` output and its "LISTENING" keyword are Windows-specific.
   CI runs this on Ubuntu, where the parse silently matched nothing and reported
   an OCCUPIED port as free. Replaced with psutil.net_connections() -- a native,
   already-installed, genuinely cross-platform capability -- for both listener
   discovery and command-line lookup (replacing a separate PowerShell subprocess
   too).

Usage: python launcher_port_guard.py <port>
Exit 0: the port was CONFIRMED free, or a verified Ed Console instance was found
        and stopped and the port is now free.
Exit 1: the port is held by something not CONFIRMED as an Ed Console server (left
        running), or a confirmed instance was stopped but the port is still
        occupied after stopping it.
Exit 2: port state could not be determined (inspection failed, e.g. psutil
        unavailable) -- never treated as "the port is free".
"""
from __future__ import annotations

import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request

try:
    import psutil
except ImportError:  # pragma: no cover -- exercised via PortInspectionError below
    psutil = None


class PortInspectionError(Exception):
    """Raised when process/socket inspection itself fails -- a genuinely UNKNOWN
    port state, never to be treated as 'confirmed free'."""


def listening_pid(port: int) -> int | None:
    """PID of the process LISTENING on <port> (any local interface), or None if
    the scan ran and found no such listener. Raises PortInspectionError if the
    scan itself could not run (e.g. psutil missing/unsupported here) -- that is
    an unknown state, not a free port."""
    if psutil is None:
        raise PortInspectionError("psutil is not available -- cannot inspect listening sockets")
    try:
        conns = psutil.net_connections(kind="inet")
    except Exception as e:
        raise PortInspectionError(f"psutil.net_connections failed: {e}") from e
    for conn in conns:
        if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port:
            return conn.pid
    return None


def command_line_for_pid(pid: int) -> str:
    """The full command line of `pid`, or '' if it cannot be read (already exited,
    or access denied -- both real, common races, not inspection failures: an
    empty command line correctly fails is_ed_console_command_line below)."""
    if psutil is None:
        return ""
    try:
        return " ".join(psutil.Process(pid).cmdline())
    except Exception:
        return ""


# A NECESSARY but NOT SUFFICIENT filter -- see is_actually_ed_console for the
# second, independent check that makes ownership verification real.
_ED_CONSOLE_INVOCATION_RE = re.compile(
    r"python(?:\.exe)?\"?\s+-m\s+uvicorn\b[^\r\n]*\bserver:app\b", re.IGNORECASE,
)


def is_ed_console_command_line(cmd: str) -> bool:
    """True only for a command line matching the Ed Console server invocation
    shape. On its own this is NOT proof of ownership (an unrelated app with the
    same common uvicorn/server.py naming would also match) -- always combined
    with is_actually_ed_console before anything is stopped."""
    if not cmd:
        return False
    return bool(_ED_CONSOLE_INVOCATION_RE.search(cmd))


def is_actually_ed_console(port: int, *, timeout: float = 2.0) -> bool:
    """Definitive ownership check: ask whatever is listening on `port` for its own
    identity via /api/build -- this app's existing identity endpoint (git_sha +
    release_id), already relied on throughout this project's own verification.
    A coincidentally command-line-matching but unrelated process will not answer
    this shape."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/build", timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read())
    except Exception:
        return False
    return isinstance(body, dict) and "git_sha" in body and "release_id" in body


def port_is_free(port: int) -> bool:
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", port)) != 0
    finally:
        s.close()


def ensure_port_free(port: int, *, out=print) -> int:
    """Stop a VERIFIED prior Ed Console instance on `port`; leave anything else
    alone. Returns 0 (confirmed free / stopped), 1 (held by something not
    confirmed as Ed Console, or failed to clear), or 2 (port state unknown --
    fail closed, never guess free)."""
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
    shape_matches = is_ed_console_command_line(cmd)
    # Only spend the HTTP round trip when the cheap filter already passed.
    identity_confirmed = False
    if shape_matches:
        identity_confirmed = is_actually_ed_console(port)
    if not (shape_matches and identity_confirmed):
        out(f"WARNING: port {port} is held by PID {pid}, NOT confirmed as an Ed Console server:")
        out(f"  {cmd or '(command line unavailable -- process may already have exited)'}")
        out(
            f"  invocation shape matches: {shape_matches}; "
            f"/api/build identity confirmed: {identity_confirmed}"
        )
        out(f"Leaving it running -- free port {port} yourself if you want Ed Console there.")
        return 1
    out(f"Stopping prior Ed Console instance on port {port} (PID {pid}, identity confirmed via /api/build)...")
    try:
        psutil.Process(pid).kill()
    except Exception as e:
        out(f"WARNING: could not stop PID {pid}: {e}")
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
