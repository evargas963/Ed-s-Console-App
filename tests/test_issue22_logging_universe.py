"""
Issue 22 — durable logging_universe enrollment (EdDB) and bounded user cap semantics.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_db_write_path_d_import_does_not_trigger_db_universe_load():
    """`import server` does not read the board from the database; the FastAPI lifespan does
    (start_logger -> _hydrate_logger_tickers_from_db). Run in a clean subprocess so earlier
    in-process reads cannot fill the board."""
    code = (
        "import server;"
        "assert server._logger_tickers == [], server._logger_tickers;"
        "print('IMPORT_DEFER_OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    assert "IMPORT_DEFER_OK" in proc.stdout
