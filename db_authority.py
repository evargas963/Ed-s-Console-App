"""
Canonical SQLite database authority — classification, env policy, CLI enforcement.

Policy (encoded here and in db.EdDB / stream_spine):

- **Permanent production files:** exactly ``ed_console.db`` and ``stream_capture.db``
  under ``runtime_layout.data_dir()``. Linked source worktrees resolve to the primary
  worktree's runtime root.
- **Ambient DB overrides:** never select a production authority. Recovery and tests pass
  explicit paths to the owning API, with explicit non-canonical acknowledgement.
- **Harness / proof:** Must never be targeted by mistake. CLI tools default
  to canonical; ``--allow-noncanonical-db`` opts in with explicit acknowledgement.
- **Tests:** ``tests/conftest.py`` sets ``ED_CONSOLE_ALLOW_NONCANONICAL_DB`` so ``EdDB``
  against temp paths works without per-call flags.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

Classification = Literal["canonical", "harness", "proof", "unknown"]
PermanentDatabaseIdentity = Literal["ed_console", "stream_capture"]


def canonical_console_db_path() -> Path:
    """The one intended canonical production database file on disk.

    Rooted in the RUNTIME root, not the source checkout: with `ED_RUNTIME_ROOT` unset, a
    standalone checkout is its own runtime root and a linked worktree uses its primary's.
    """
    from runtime_layout import data_dir

    return (data_dir() / "ed_console.db").resolve()


def canonical_stream_db_path() -> Path:
    """The one permanent raw receive-time market-event database."""
    from runtime_layout import data_dir

    return (data_dir() / "stream_capture.db").resolve()


def permanent_database_identity(p: Path | str) -> PermanentDatabaseIdentity | None:
    """Return the approved permanent identity for an exact canonical path."""
    resolved = Path(p).resolve()
    if resolved == canonical_console_db_path():
        return "ed_console"
    if resolved == canonical_stream_db_path():
        return "stream_capture"
    return None


def default_console_db_path() -> Path:
    """Resolved default DB for this process: the canonical one, for every process. No agent
    role or directory name selects another; ``EdDB.__init__`` admits only the canonical path
    unless its caller opts in (``allow_noncanonical``, ``ED_CONSOLE_ALLOW_NONCANONICAL_DB``)."""
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
