"""Atomic file writes for arch_competition governance artifacts."""

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
        # newline="\n": os.fdopen's text mode otherwise applies the PLATFORM default (Windows:
        # every "\n" json.dump emits becomes "\r\n"), silently violating .gitattributes' `eol: lf`
        # for every tracked artifact this writes -- the exact bug found 2026-09-15 in
        # arch_competition/stack_bundle_eval_v1.py's own (non-atomic) write_text calls, which
        # predate this module's adoption there. read_text()'s universal-newline translation hides
        # the flip on a round trip, which is why no existing test caught it -- only inspecting the
        # raw bytes on disk (or `git diff`) shows it.
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=indent, default=default, sort_keys=sort_keys)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def write_text_atomically(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Write text via temp file + fsync + os.replace (no partial destination on crash)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        # newline="\n": see write_json_file_atomically's comment above -- this sibling function
        # was missed when that fix landed (2026-09-15), leaving this one write_text_atomically
        # call site (calibration/edge_discovery.py) still exposed to the same platform-default
        # CRLF flip on Windows.
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
