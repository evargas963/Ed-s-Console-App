"""Unit tests for arch_competition.atomic_io."""

from __future__ import annotations

import json
from pathlib import Path


from arch_competition.atomic_io import (
    write_json_file_atomically,
)






def test_write_json_file_atomically_still_round_trips(tmp_path: Path):
    target = tmp_path / "artifact.json"
    write_json_file_atomically(target, {"ok": True, "n": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True, "n": 1}


def test_write_json_file_atomically_writes_lf_not_crlf(tmp_path: Path):
    """The 2026-09-15 fix: os.fdopen's text mode must not apply the platform (Windows: CRLF)
    default. read_text()'s universal-newline translation would mask this on a round trip --
    only raw bytes on disk reveal it."""
    target = tmp_path / "artifact.json"
    write_json_file_atomically(target, {"a": 1, "b": 2}, indent=2)
    raw = target.read_bytes()
    assert b"\r\n" not in raw
    assert b"\n" in raw


