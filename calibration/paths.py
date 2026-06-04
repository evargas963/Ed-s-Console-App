"""Output paths for calibration artifacts."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from db_authority import canonical_console_db_path  # noqa: E402

# Same resolved path as db.DB_PATH (honors ED_CONSOLE_DB). Use for validators / repairs.
from db import DB_PATH as DEFAULT_DB  # noqa: F401,E402  (intentional re-export for validators/repairs)

CANONICAL_CONSOLE_DB_FILE = canonical_console_db_path()

ARTIFACTS_DIR = PROJECT_ROOT / "models" / "calibration_runs"
DOCS_DIR = PROJECT_ROOT / "docs"


def ensure_artifacts_dir() -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_DIR
