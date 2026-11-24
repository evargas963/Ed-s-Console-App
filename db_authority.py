"""
The one database: its path, and who may open another.

Policy (encoded here and in db.EdDB / stream_spine):

- **The production file:** exactly ``ed.db`` under ``runtime_layout.data_dir()``, the record
  of everything kept: the stream's messages, the chain history and the level crosses. Linked
  source worktrees resolve to the primary worktree's runtime root.
- **Ambient DB overrides:** never select the production file. Recovery and tests pass
  explicit paths to the owning API, with explicit non-canonical acknowledgement.
- **Tests:** ``tests/conftest.py`` sets ``ED_CONSOLE_ALLOW_NONCANONICAL_DB`` so ``EdDB``
  against temp paths works without per-call flags.
"""

from __future__ import annotations

import os
from pathlib import Path

from runtime_layout import data_dir


def canonical_db_path() -> Path:
    """Return the one production database file on disk.

    Rooted in the RUNTIME root, not the source checkout: with `ED_RUNTIME_ROOT` unset, a
    standalone checkout is its own runtime root and a linked worktree uses its primary's.
    """
    return (data_dir() / "ed.db").resolve()


def resolve_stream_db_path(default: Path | str | None = None) -> Path:
    """Return the one database's path (canonical_db_path). `default` is for tests."""
    if default is not None:
        return Path(default).resolve()
    return canonical_db_path()


def is_canonical_db_path(p: Path | str) -> bool:
    return Path(p).resolve() == canonical_db_path()


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
