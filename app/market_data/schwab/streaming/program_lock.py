"""The program's lock: one program at a time, where it listens, and how it is asked to stop.

The lock file sits beside the stream database. Its first line is the program's pid, written when
the program takes the lock; its second, written once the program has opened its socket, is the
port it holds (record_ports). The launcher reads it there (program_ports), so the port a page goes
to is the one the program holds, never one chosen before it bound.

The clean stop (launch.py stop) is asked by name, not over a socket (StopRequest, ask_to_stop):
the name is derived from the lock's path (stop_event_name), so each runtime -- production's, a
test's -- has its own and a stop never reaches another runtime's program.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import signal
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

import psutil

from stream_spine import resolve_stream_db_path

#: Exit code when another program already holds the lock (start_capture_daemon.bat stops its
#: restart loop on it). 2 is the live-binding refusal (runtime_layout).
EXIT_OWNER_LOCK_HELD = 3

#: Windows' kernel32, for the stop event; None elsewhere (Linux CI), where the stop request is
#: SIGTERM
_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None
if _KERNEL32 is not None:
    _KERNEL32.CreateEventW.restype = _KERNEL32.OpenEventW.restype = ctypes.c_void_p
    _KERNEL32.CreateEventW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_wchar_p,
    )
    _KERNEL32.OpenEventW.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p)
    _KERNEL32.SetEvent.argtypes = _KERNEL32.CloseHandle.argtypes = (ctypes.c_void_p,)
    _KERNEL32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    _KERNEL32.WaitForSingleObject.restype = ctypes.c_uint32
#: OpenEventW's right to set an event; WaitForSingleObject's answer for a set one
EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0


@dataclass(frozen=True)
class Ports:
    """The port the program's socket holds: the console's pages and routes and the page's price
    socket (/ws).
    """

    console: int


def owner_lock_path(db_path: str | Path | None = None) -> Path:
    """Beside the stream database, so a worktree and production can never both stream."""
    return resolve_stream_db_path(db_path).with_name("stream_capture.lock")


def acquire_owner_lock(db_path: str | Path | None = None) -> tuple[int, Path]:
    """Exclusive pidfile: one program at a time; a lock left by a dead process is reclaimed."""
    lock = owner_lock_path(db_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pid = _holder(lock.read_text())
            if pid is not None:
                print(f"FATAL: another capture daemon holds {lock} (pid {pid}).", file=sys.stderr)
                raise SystemExit(EXIT_OWNER_LOCK_HELD) from None
            if attempt == 1:
                lock.unlink(missing_ok=True)
        else:
            os.write(fd, f"{os.getpid()}\n".encode())
            return fd, lock
    raise SystemExit(f"FATAL: could not acquire {lock}")


def record_ports(fd: int, ports: Ports) -> None:
    """Write the port the program's socket holds as the lock's second line (program_ports)."""
    os.write(fd, f"{json.dumps(asdict(ports))}\n".encode())


def release_owner_lock(fd: int, lock: Path) -> None:
    try:
        os.close(fd)
    finally:
        lock.unlink(missing_ok=True)


def program_ports(db_path: str | Path | None = None) -> Ports | None:
    """Return the port the running program holds (record_ports).

    None while no running program holds the lock, or while it has not opened its socket yet.
    """
    try:
        text = owner_lock_path(db_path).read_text()
    except FileNotFoundError:  # no program holds the lock
        return None
    head, _, ports = text.partition("\n")
    if _holder(head) is None or not ports.endswith("\n"):  # a line is whole once it ends
        return None
    return Ports(**json.loads(ports))


def _holder(text: str) -> int | None:
    """Return the pid on the lock's first line while that process runs.

    None when the line holds no pid (a program ended between creating the lock and writing it)
    or its process has ended.
    """
    head = text.partition("\n")[0]
    return int(head) if head.isdigit() and psutil.pid_exists(int(head)) else None


def stop_event_name(db_path: str | Path | None = None) -> str:
    """The name of the stop event of the program whose lock is at owner_lock_path(`db_path`).

    In the session namespace (Local\\); the rest is a hash of the lock's whole path, so two
    runtimes never share a name.
    """
    lock = os.path.normcase(str(owner_lock_path(db_path).resolve()))
    return "Local\\EdConsoleStop-" + hashlib.sha256(lock.encode("utf-8")).hexdigest()[:32]


class StopRequest:
    """The program's stop request, made before it takes its lock (capture.main), so a program
    whose pid the lock holds can always be asked; launch.py stop sets it (ask_to_stop).

    On Windows it is a named manual-reset event (stop_event_name), made by kernel32's
    CreateEventW with default security: only processes of this user's logon session can open it.
    It needs no port and no secret, and set twice it stays set. Elsewhere (Linux CI) the request
    is SIGTERM to the process holding the lock, the platform's own ask to stop, taken by this
    request's handler; close restores the handler it replaced.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._handle = self._sigterm = None
        self._asked = threading.Event()
        if _KERNEL32 is None:
            self._sigterm = signal.signal(signal.SIGTERM, lambda _sig, _frame: self._asked.set())
            return
        self._handle = _KERNEL32.CreateEventW(None, True, False, stop_event_name(db_path))
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def wait(self, seconds: float) -> bool:
        """Whether the stop was asked for, waiting up to `seconds` for it."""
        if self._handle is None:
            return self._asked.wait(seconds)
        return _KERNEL32.WaitForSingleObject(self._handle, round(seconds * 1000)) == WAIT_OBJECT_0

    def close(self) -> None:
        if self._handle is None:
            signal.signal(signal.SIGTERM, self._sigterm)
        else:
            _KERNEL32.CloseHandle(self._handle)


def ask_to_stop(db_path: str | Path | None = None) -> None:
    """Set the stop request (StopRequest) of the program whose lock is at owner_lock_path(
    `db_path`). Raises OSError when there is none to set: no program runs there, or it has not
    made its request yet.
    """
    if _KERNEL32 is None:
        pid = _holder(owner_lock_path(db_path).read_text())  # FileNotFoundError: no lock
        if pid is None:
            raise ProcessLookupError("no running program holds the lock")
        os.kill(pid, signal.SIGTERM)
        return
    name = stop_event_name(db_path)
    handle = _KERNEL32.OpenEventW(EVENT_MODIFY_STATE, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error(), f"no stop event {name} to open")
    try:
        if not _KERNEL32.SetEvent(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        _KERNEL32.CloseHandle(handle)
