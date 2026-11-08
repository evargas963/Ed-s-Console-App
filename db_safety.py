"""A canonical database (``db_authority.is_canonical_db_path``) refuses DROP and DETACH."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from db_authority import is_canonical_db_path

#: the structural actions a canonical database refuses
DENIED = frozenset(
    {
        sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_DROP_INDEX,
        sqlite3.SQLITE_DROP_VIEW,
        sqlite3.SQLITE_DROP_TRIGGER,
        sqlite3.SQLITE_DETACH,
    }
)


def install_production_sql_authorizer(conn: sqlite3.Connection) -> None:
    """Refuse DROP and DETACH on `conn`."""

    def _auth(
        action: int, arg1: str | None, arg2: str | None, db_name: str | None, inner: str | None
    ) -> int:
        return sqlite3.SQLITE_DENY if action in DENIED else sqlite3.SQLITE_OK

    conn.set_authorizer(_auth)


def maybe_install_sql_guard_on_connection(conn: sqlite3.Connection, db_path: Path) -> None:
    """Install the authorizer on a connection to a canonical database."""
    if is_canonical_db_path(db_path):
        install_production_sql_authorizer(conn)
