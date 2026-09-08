"""
Canonical SQLite database authority — classification, env policy, CLI enforcement.

Policy (encoded here and in db.EdDB / stream_spine):

- **Permanent production files:** exactly ``ed_console.db`` and ``stream_capture.db``
  under ``runtime_layout.data_dir()``. Linked source worktrees resolve to the primary
  worktree's runtime root (RC-534).
- **Ambient DB overrides:** never select a production authority. Recovery and tests pass
  explicit paths to the owning API, with explicit non-canonical acknowledgement.
- **Harness / proof / backup:** Must never be targeted by mistake. CLI tools default
  to canonical; ``--allow-noncanonical-db`` opts in with explicit acknowledgement.
- **Tests:** ``tests/conftest.py`` sets ``ED_CONSOLE_ALLOW_NONCANONICAL_DB`` so ``EdDB``
  against temp paths works without per-call flags.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Literal

Classification = Literal["canonical", "harness", "proof", "backup", "unknown"]
PermanentDatabaseIdentity = Literal["ed_console", "stream_capture"]


def project_root() -> Path:
    return Path(__file__).resolve().parent


def canonical_console_db_path() -> Path:
    """The one intended canonical production database file on disk.

    Rooted in the RUNTIME root (RC-523), not the source checkout: with `ED_RUNTIME_ROOT`
    unset the two are the same directory, so nothing moves until the operator moves it.
    """
    from runtime_layout import data_dir

    return (data_dir() / "ed_console.db").resolve()


def canonical_stream_db_path() -> Path:
    """The one permanent raw receive-time market-event database."""
    from runtime_layout import data_dir

    return (data_dir() / "stream_capture.db").resolve()


def canonical_permanent_db_paths() -> tuple[Path, Path]:
    """The complete permanent SQLite population, in stable backup order."""
    return canonical_console_db_path(), canonical_stream_db_path()


def permanent_database_identity(p: Path | str) -> PermanentDatabaseIdentity | None:
    """Return the approved permanent identity for an exact canonical path."""
    resolved = Path(p).resolve()
    if resolved == canonical_console_db_path():
        return "ed_console"
    if resolved == canonical_stream_db_path():
        return "stream_capture"
    return None


def default_console_db_path() -> Path:
    """Resolved default DB for this process. ONE APP, ONE MAIN, ONE DB (RC-401).

    This used to fork on ``ED_AGENT_ROLE`` / a ``*-Claude`` directory name and return
    ``data/ed_console_claude.db``. The split was written when two agents ran two desks;
    it outlived that premise and what it produced was a SECOND money-path data source.
    MEASURED 2026-08-18: canonical ``EdWebConsole/data/ed_console.db`` = 34.28 GB, while
    the split had scattered ``EdWebConsole/data/ed_console_claude.db`` = 35.78 MB (503
    snapshots, 954 decision_persistence_ledger rows, 49,173 confluence_quote_ticks),
    ``_stack125/data/ed_console_claude.db`` = 0.21 MB and
    ``_runtime_main/data/ed_console_claude.db`` = 0 bytes.

    The routing also contradicted itself: ``EdDB.__init__`` admits only
    ``is_canonical_db_path``, so the path this function returned was refused by the only
    class that opens it. A desk started from ``_runtime_main`` died on exactly that.
    Honouring the fork would have been worse than the crash — the desk would have come up
    serving an empty history as if it were the record.

    Existing ``ed_console_claude.db`` files are left on disk untouched; merging or
    removing operator data is not this call to make.
    """
    return canonical_console_db_path()


def is_canonical_db_path(p: Path | str) -> bool:
    try:
        return Path(p).resolve() == canonical_console_db_path()
    except OSError:
        return False


def classify_db_path(p: Path | str) -> Classification:
    """Best-effort classification for guardrails and error messages."""
    rp = Path(p).resolve()
    s = str(rp).replace("\\", "/")
    if permanent_database_identity(rp) is not None:
        return "canonical"
    if "calibration_accumulation_validation.db" in s:
        return "harness"
    if "calibration_anchor_proof.db" in s:
        return "proof"
    if "/data/backups/" in s or "/backups/db/" in s:
        return "backup"
    return "unknown"


def env_allows_noncanonical_db() -> bool:
    return os.environ.get("ED_CONSOLE_ALLOW_NONCANONICAL_DB", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def eddb_allow_noncanonical_path(explicit: bool | None) -> bool:
    if explicit is not None:
        return explicit
    return env_allows_noncanonical_db()


def cli_require_canonical_or_ack(
    db_path: Path,
    *,
    allow_noncanonical: bool,
    tool_name: str,
    write_capable: bool,
) -> None:
    """
    Exit with code 2 if db_path is not canonical and user did not pass --allow-noncanonical-db.
    write_capable is for messaging only (both validators and writers use the same gate).
    """
    if is_canonical_db_path(db_path):
        return
    if allow_noncanonical:
        return
    cat = classify_db_path(db_path)
    kind = "write" if write_capable else "read"
    print(
        f"{tool_name}: refusing {kind} on non-canonical DB:\n"
        f"  path: {db_path.resolve()}\n"
        f"  classified: {cat}\n"
        f"  canonical: {canonical_console_db_path()}\n"
        "Pass --allow-noncanonical-db to proceed (explicit opt-in).",
        file=sys.stderr,
    )
    raise SystemExit(2)
