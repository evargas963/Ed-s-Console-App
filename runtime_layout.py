"""RUNTIME LAYOUT — the ONE owner of where runtime state lives (docs/ARCHITECTURE.md §8).

Source, runtime state and generated artifacts are separate concerns:

    SOURCE      this checkout (code, tests, records)
    RUNTIME     the live database, logs, tokens            ED_RUNTIME_ROOT
    ARTIFACTS   generated reports and scorecards           ED_ARTIFACTS_ROOT (default: RUNTIME)

RC-523 (2026-09-06, bedrock step 7). Every runtime path was rooted in the source checkout
(`Path(__file__).parent / "data"`, `/ "logs"`, `/ "reports"`) with an override for the
database alone, so a source update could endanger the live database and runtime output
polluted the checkout — the two things §8 forbids — and the production checkout had to be
the desk's cwd. With the two variables below unset nothing changes: both roots ARE the source
root, so a fresh clone and every existing worktree behave exactly as before. Setting them
moves the state without touching code; the operator's move is an operations step, not a
merge.

This module imports nothing from `tools/` or `governance/`: it is on the runtime path and
governance does not decide whether the desk may run (RC-512). It reads `.env` at the source
root the same way `config.py` does, so the variables can live beside the other host settings.
"""
from __future__ import annotations

import os
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent


def _load_env_file() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = SOURCE_ROOT / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


def _dir_from_env(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return Path(raw).expanduser().resolve()


_load_env_file()
#: Live database, logs and tokens live under here. Default: the source checkout.
RUNTIME_ROOT: Path = _dir_from_env("ED_RUNTIME_ROOT", SOURCE_ROOT)
#: Generated reports and scorecards live under here. Default: the runtime root.
ARTIFACTS_ROOT: Path = _dir_from_env("ED_ARTIFACTS_ROOT", RUNTIME_ROOT)


def data_dir() -> Path:
    """`<runtime>/data` — the live SQLite database and its siblings."""
    return RUNTIME_ROOT / "data"


def logs_dir() -> Path:
    """`<runtime>/logs` — the server log sink and other process logs."""
    return RUNTIME_ROOT / "logs"


def reports_dir() -> Path:
    """`<artifacts>/reports` — runtime-written reports (terrain, operable surface, scoreboards)."""
    return ARTIFACTS_ROOT / "reports"


def describe() -> dict[str, str]:
    """The resolved layout, for a launch banner or a probe — never for a decision."""
    return {
        "source_root": str(SOURCE_ROOT),
        "runtime_root": str(RUNTIME_ROOT),
        "artifacts_root": str(ARTIFACTS_ROOT),
        "separated": str(RUNTIME_ROOT != SOURCE_ROOT),
    }
