"""Atomic JSON file writes for arch_competition governance artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_file_atomically(
    path: Path,
    payload: Any,
    *,
    indent: int | None = 2,
    default: Any = str,
    sort_keys: bool = False,
) -> None:
    """Write JSON via temp file + fsync + os.replace (no partial destination on crash)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=indent, default=default, sort_keys=sort_keys)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
