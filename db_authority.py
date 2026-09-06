"""
Canonical SQLite database authority — classification, env policy, CLI enforcement.

Policy (encoded here and in db.EdDB / db._resolve_console_db_path):

- **Canonical production file:** ``<runtime_root>/data/ed_console.db`` (resolved), where
  the runtime root is ``runtime_layout.RUNTIME_ROOT`` — the source checkout unless
  ``ED_RUNTIME_ROOT`` moves it (RC-523, ARCHITECTURE §8).
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
    """The one intended canonical production database file on disk.

    Rooted in the RUNTIME root (RC-523), not the source checkout: with `ED_RUNTIME_ROOT`
    unset the two are the same directory, so nothing moves until the operator moves it.
    """
    from runtime_layout import data_dir

    return (data_dir() / "ed_console.db").resolve()


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

    Explicit ``ED_CONSOLE_DB`` / ``ED_DB_PATH`` overrides are unaffected and still require
    ``ED_CONSOLE_ALLOW_NONCANONICAL_DB=1``. Existing ``ed_console_claude.db`` files are
    left on disk untouched; merging or removing operator data is not this call to make.
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
    When ED_CONSOLE_DB / ED_DB_PATH is set: path must exist. If it is not the canonical
    file, ED_CONSOLE_ALLOW_NONCANONICAL_DB must be set (alternate deployment / recovery).

    RC-401 removed a silent exemption here for any ``data/ed_console*.db`` under this
    project root. That exemption let a sibling database be selected without the operator
    ever acknowledging a non-canonical target, which is the same fork this module now
    refuses to produce by default.
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
