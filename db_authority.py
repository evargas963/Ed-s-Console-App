"""
Canonical SQLite database authority — classification, env policy, CLI enforcement.

Policy (encoded here and in db.EdDB / db._resolve_console_db_path):

- **Canonical production file:** ``<project_root>/data/ed_console.db`` (resolved).
- **ED_CONSOLE_DB:** Optional absolute path to the single live DB for this deployment.
  If it does not resolve to the canonical file, ``ED_CONSOLE_ALLOW_NONCANONICAL_DB=1``
  is required (alternate volume / recovery).
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


def project_root() -> Path:
    return Path(__file__).resolve().parent


def canonical_console_db_path() -> Path:
    """The one intended canonical production database file on disk."""
    return (project_root() / "data" / "ed_console.db").resolve()


def is_canonical_db_path(p: Path | str) -> bool:
    try:
        return Path(p).resolve() == canonical_console_db_path()
    except OSError:
        return False


def classify_db_path(p: Path | str) -> Classification:
    """Best-effort classification for guardrails and error messages."""
    rp = Path(p).resolve()
    s = str(rp).replace("\\", "/")
    if is_canonical_db_path(rp):
        return "canonical"
    if "calibration_accumulation_validation.db" in s:
        return "harness"
    if "calibration_anchor_proof.db" in s:
        return "proof"
    if "/data/backups/" in s or "\\data\\backups\\" in s:
        return "backup"
    return "unknown"


def env_allows_noncanonical_db() -> bool:
    return os.environ.get("ED_CONSOLE_ALLOW_NONCANONICAL_DB", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def assert_ed_console_db_env_resolves_safely(resolved_path: Path) -> None:
    """
    When ED_CONSOLE_DB is set: path must exist. If not the canonical file,
    ED_CONSOLE_ALLOW_NONCANONICAL_DB must be set (alternate deployment / recovery).
    """
    if not resolved_path.exists():
        raise FileNotFoundError(f"ED_CONSOLE_DB path does not exist: {resolved_path}")
    if is_canonical_db_path(resolved_path):
        return
    if not env_allows_noncanonical_db():
        raise ValueError(
            f"ED_CONSOLE_DB={resolved_path!r} is not the canonical file "
            f"{canonical_console_db_path()!r} (classified: {classify_db_path(resolved_path)}). "
            "Set ED_CONSOLE_ALLOW_NONCANONICAL_DB=1 only for intentional alternate or recovery DBs."
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
