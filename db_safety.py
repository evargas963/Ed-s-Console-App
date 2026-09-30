"""
Canonical DB connections (``db_authority.is_canonical_db_path``) install an SQLite authorizer
that denies DROP / DETACH unless ``ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED=1``. Disable the hook
with ``ED_CONSOLE_SQL_EXECUTE_GUARD=0``.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from db_authority import (
    is_canonical_db_path,
)

DANGEROUS_SQL_UNRESTRICTED_ENV = "ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED"
SQL_EXECUTE_GUARD_ENV = "ED_CONSOLE_SQL_EXECUTE_GUARD"


def dangerous_sql_unrestricted() -> bool:
    return os.environ.get(DANGEROUS_SQL_UNRESTRICTED_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def sql_execute_guard_enabled() -> bool:
    v = os.environ.get(SQL_EXECUTE_GUARD_ENV, "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def install_production_sql_authorizer(conn: sqlite3.Connection) -> None:
    """SQLite authorizer hook: deny structural DROP / DETACH on guarded connections."""

    def _auth(action: int, arg1: str | None, arg2: str | None, db_name: str | None, inner: str | None) -> int:
        if dangerous_sql_unrestricted():
            return sqlite3.SQLITE_OK
        deny = {
            getattr(sqlite3, "SQLITE_DROP_TABLE", 10),
            getattr(sqlite3, "SQLITE_DROP_INDEX", 11),
            getattr(sqlite3, "SQLITE_DROP_VIEW", 12),
            getattr(sqlite3, "SQLITE_DROP_TRIGGER", 13),
            getattr(sqlite3, "SQLITE_DETACH", 23),
        }
        if action in deny:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(_auth)


def maybe_install_sql_guard_on_connection(conn: sqlite3.Connection, db_path: Path) -> None:
    """Install SQL authorizer on canonical production DB connections."""
    if not is_canonical_db_path(db_path):
        return
    if not sql_execute_guard_enabled():
        return
    if dangerous_sql_unrestricted():
        return
    install_production_sql_authorizer(conn)


