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
    an unknown state, not a free port.

    Independent-review finding (2026-09-12): psutil can report a LISTENING socket
    whose own `.pid` is None (a common, real shape -- Windows without elevated
    privilege, or a socket psutil cannot attribute to a process) -- REPRODUCED
    directly against this function. The old code returned that None straight
    through, which the caller read as "no listener" and reported the port FREE,
    even though something IS genuinely listening there. A socket found with an
    unreadable owner is the same "I cannot tell you whose this is" as a failed
    scan, and must fail the same way -- never silently promoted to 'nothing is
    here'."""
    if psutil is None:
        raise PortInspectionError("psutil is not available -- cannot inspect listening sockets")
    try:
        conns = psutil.net_connections(kind="inet")
    except Exception as e:
        raise PortInspectionError(f"psutil.net_connections failed: {e}") from e
    for conn in conns:
        if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port:
            if conn.pid is None:
                raise PortInspectionError(
                    f"port {port} has a LISTENING socket but psutil could not attribute it "
                    f"to a process (pid is None) -- ownership cannot be determined")
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


def is_actually_ed_console(port: int, *, pid: int | None = None, timeout: float = 2.0) -> bool:
    """Definitive ownership check: ask whatever is listening on `port` for its own
    identity via /api/build -- this app's existing identity endpoint -- and cross-validate
    the claim against real, hard-to-coincide-with evidence.

    Independent-review finding (2026-09-12), REPRODUCED directly against this function
    (round 1): a body of `{"git_sha": null, "release_id": null}` has both KEYS present and
    passed the old `"git_sha" in body` check, which tests key membership, not a real value.
    Fixed by requiring truthy string values.

    Independent-review finding (2026-09-12), REPRODUCED directly against this function
    (round 2): "an unrelated matching uvicorn process with ordinary nonempty build
    identifiers still passes." Truthy strings alone are still forgeable by any unrelated app
    that happens to expose SOME endpoint naming these two generic keys with SOME nonempty
    values -- neither "git_sha" nor "release_id" is unique to this codebase. Fixed with two
    independent, much harder to coincidentally satisfy checks:

      1. `contract == "meet_or_exceed_v1"` and `git_sha_semantics ==
         "startup_process_identity"` -- fixed, app-specific magic strings this exact
         /api/build route emits (server.py:api_build), not generic field names.
      2. THE definitive check, when `pid` is supplied (the psutil-observed OS pid actually
         LISTENING on `port`, from listening_pid): `process_identity.process_id` --
         captured via `os.getpid()` once at THIS process's own startup
         (server.py:_capture_process_identity) -- must equal that real OS pid. An unrelated
         process cannot produce this match without literally reporting ITS OWN real pid
         inside this exact nested response shape, which only server.py's own /api/build
         route does; a copy-pasted or coincidentally similar app reports a DIFFERENT pid
         (its own), not this one's.

    Both `contract`/`git_sha_semantics` and (when `pid` is given) the process_id cross-check
    must pass, on top of the truthy git_sha/release_id values, for ownership to be confirmed."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/build", timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read())
    except Exception:
        return False
    if not isinstance(body, dict):
        return False
    git_sha, release_id = body.get("git_sha"), body.get("release_id")
    if not (bool(git_sha) and bool(release_id) and isinstance(git_sha, str) and isinstance(release_id, str)):
        return False
    if body.get("contract") != "meet_or_exceed_v1":
        return False
    if body.get("git_sha_semantics") != "startup_process_identity":
        return False
    identity = body.get("process_identity")
    if not isinstance(identity, dict) or identity.get("startup_git_sha") != git_sha:
        return False
    if pid is not None and identity.get("process_id") != pid:
        return False
    return True


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
        identity_confirmed = is_actually_ed_console(port, pid=pid)
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
