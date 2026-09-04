"""Keep the ONE Schwab streaming daemon alive.

The capture process is ``tools/run_stream_capture.py``. This module does not
open a Schwab session. It starts that daemon with ``--duration-min 0`` when
the producer heartbeat in stream_capture.db is missing or stale.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from stream_spine import (
    PRODUCER_CLAIM_TTL_SEC,
    STREAM_CAPTURE_DB_PATH_ENV,
    read_producer_heartbeat,
    resolve_stream_db_path,
)

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SYMBOLS = ("SPY", "QQQ", "IWM")


def heartbeat_age_sec(db_path: Path | str | None = None, *, now: float | None = None) -> float | None:
    """Seconds since the daemon last wrote its heartbeat, or None if unread."""
    path = resolve_stream_db_path(db_path)
    if not path.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = read_producer_heartbeat(con)
    finally:
        con.close()
    if not row or row.get("heartbeat_ts") is None:
        return None
    return float((now if now is not None else time.time()) - float(row["heartbeat_ts"]))


def daemon_is_fresh(db_path: Path | str | None = None, *, now: float | None = None) -> bool:
    age = heartbeat_age_sec(db_path, now=now)
    return age is not None and age <= PRODUCER_CLAIM_TTL_SEC


def start_durable_daemon(
    *,
    repo: Path | None = None,
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
    python: str | None = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Spawn the capture daemon with duration 0 (until process death), detached."""
    root = repo or REPO
    exe = python or sys.executable
    script = root / "tools" / "run_stream_capture.py"
    if not script.is_file():
        return {"started": False, "reason": "missing_daemon_script"}
    args = [
        exe,
        str(script),
        "--symbols",
        ",".join(symbols),
        "--duration-min",
        "0",
    ]
    resolved_db = resolve_stream_db_path(db_path)
    args.extend(["--db", str(resolved_db)])
    env = os.environ.copy()
    env[STREAM_CAPTURE_DB_PATH_ENV] = str(resolved_db)
    creation = 0
    if os.name == "nt":
        creation = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        args,
        cwd=str(root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creation,
        start_new_session=(os.name != "nt"),
    )
    return {"started": True, "pid": proc.pid, "duration_min": 0}


def ensure_stream_capture_running(
    *,
    repo: Path | None = None,
    db_path: Path | str | None = None,
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
    python: str | None = None,
) -> dict[str, Any]:
    """ONE faucet: start the daemon only when the heartbeat is absent or stale."""
    if daemon_is_fresh(db_path):
        return {"action": "already_running", "age_sec": heartbeat_age_sec(db_path)}
    started = start_durable_daemon(repo=repo, symbols=symbols, python=python, db_path=db_path)
    started["action"] = "started" if started.get("started") else "failed"
    started["age_sec"] = heartbeat_age_sec(db_path)
    return started
