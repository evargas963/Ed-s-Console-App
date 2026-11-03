"""Only Feed talks to Schwab: import-linter, as `locks` runs it, on the repository's own files."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.market_data.schwab.streaming import capture

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def head(tmp_path: Path) -> Path:
    """The tracked Python files, in a checkout named as `locks` names it."""
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "*.py"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    for name in filter(None, tracked.stdout.split("\0")):
        copied = tmp_path / "head" / name
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, copied)
    return tmp_path / "head"


def _lint(head: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            Path(sys.executable).with_name("lint-imports"),
            "--config",
            str(ROOT / "locks.imports.toml"),
            "--no-cache",
        ],
        cwd=head.parent,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def test_every_module_of_the_repository_keeps_the_contract(head):
    done = _lint(head)
    assert done.returncode == 0, done.stdout
    assert "Only Feed talks to Schwab KEPT" in done.stdout
    assert "Feed has one HTTP client KEPT" in done.stdout


def test_a_schwab_client_outside_feed_is_refused_wherever_it_is_imported(head):
    (head / "new_root_module.py").write_text("import schwab\n", encoding="utf-8")
    (head / "app" / "options" / "new_module.py").write_text(
        "from schwab.client import Client\n", encoding="utf-8"
    )
    (head / "tools" / "new_tool.py").write_text("import authlib.jose\n", encoding="utf-8")
    server = head / "server.py"
    server.write_text(
        server.read_text(encoding="utf-8") + "\n\ndef _call():\n    import httpx\n",
        encoding="utf-8",
    )
    done = _lint(head)
    assert done.returncode != 0
    for importer in (
        "head.new_root_module -> schwab",
        "head.app.options.new_module -> schwab",
        "head.tools.new_tool -> authlib",
        "head.server -> httpx",
    ):
        assert importer in done.stdout


def test_a_second_http_client_is_refused_in_feed_too(head):
    client = head / "schwab_client.py"
    client.write_text("import requests\n" + client.read_text(encoding="utf-8"), encoding="utf-8")
    done = _lint(head)
    assert done.returncode != 0
    assert "head.schwab_client -> requests" in done.stdout


def test_feed_may_move_into_its_folder_under_the_contract_it_has_today(head):
    (head / "feed").mkdir()
    (head / "feed" / "__init__.py").write_text("", encoding="utf-8")
    (head / "schwab_client.py").rename(head / "feed" / "schwab_client.py")
    done = _lint(head)
    assert done.returncode == 0, done.stdout


def test_schwab_fields_for_a_stream_service_come_from_feed():
    assert "BID_PRICE" in capture.streaming_fields()["LevelOneEquity"]
