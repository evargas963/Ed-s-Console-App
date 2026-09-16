"""Unit tests for arch_competition.atomic_io."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arch_competition.atomic_io import write_json_file_atomically, write_text_atomically


def test_write_text_atomically_writes_content(tmp_path: Path):
    target = tmp_path / "nested" / "artifact.md"
    write_text_atomically(target, "# hello\n\nbody")
    assert target.read_text(encoding="utf-8") == "# hello\n\nbody"


def test_write_text_atomically_preserves_prior_on_replace_failure(tmp_path: Path, monkeypatch):
    target = tmp_path / "artifact.md"
    target.write_text("prior", encoding="utf-8")

    def _fail_replace(*_args, **_kwargs):
        raise OSError("simulated crash before replace")

    monkeypatch.setattr("arch_competition.atomic_io.os.replace", _fail_replace)
    with pytest.raises(OSError, match="simulated crash"):
        write_text_atomically(target, "new")
    assert target.read_text(encoding="utf-8") == "prior"


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


def test_write_text_atomically_writes_lf_not_crlf(tmp_path: Path):
    """Sibling of the JSON writer's LF fix -- was missed when that fix first landed,
    leaving calibration/edge_discovery.py's write_text_atomically call still CRLF-exposed
    on Windows. Regression test for that gap."""
    target = tmp_path / "artifact.md"
    write_text_atomically(target, "# hello\n\nbody\n")
    raw = target.read_bytes()
    assert b"\r\n" not in raw
    assert b"\n" in raw
