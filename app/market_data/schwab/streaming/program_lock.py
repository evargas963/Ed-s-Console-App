"""The program's lock: one program at a time, and where it listens.

The lock file sits beside the stream database. Its first line is the program's pid, written when
the program takes the lock; its second, written once the program has opened its socket, is the
port it holds (record_ports). The launcher reads it there (program_ports), so the port a page or a
stop goes to is the one the program holds, never one chosen before it bound.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import psutil

from stream_spine import resolve_stream_db_path

#: Exit code when another program already holds the lock (start_capture_daemon.bat stops its
#: restart loop on it). 2 is the live-binding refusal (runtime_layout).
EXIT_OWNER_LOCK_HELD = 3


@dataclass(frozen=True)
class Ports:
    """The port the program's socket holds: the console's pages and routes, the page's price
    socket (/ws) and the control route (/control, launch.py's stop).
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
