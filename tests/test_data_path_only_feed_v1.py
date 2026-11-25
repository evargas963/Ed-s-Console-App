"""The import contracts, as `locks` runs import-linter, on the repository's own files.

Only Feed talks to Schwab, and the Calculators read no State, Push, Feed, database or network.
"""

from __future__ import annotations

import shutil
import subprocess
import sysconfig
from pathlib import Path

import pytest

from feed import stream

pytestmark = pytest.mark.rail

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def head(tmp_path: Path) -> Path:
    """Return the tracked Python files, in a checkout named as `locks` names it."""
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
            Path(sysconfig.get_path("scripts")) / "lint-imports",
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
    assert "Only the daemon reaches Feed KEPT" in done.stdout
    assert "The Calculators read no State, Push, Feed, database or network KEPT" in done.stdout


def test_a_calculator_reaching_state_a_database_or_the_network_is_refused(head):
    """A Calculator importing State, the database or a socket is refused, each by its line."""
    reaches = {
        "calc/option_book.py": "import state.level_store\n",
        "calc/terrain_engine.py": "import sqlite3\n",
        "calc/liquidity_value_engine.py": "from push import spot\n",
        "calc/order_flow.py": "import socket\n",
    }
    for name, line in reaches.items():
        calculator = head / name
        calculator.write_text(line + calculator.read_text(encoding="utf-8"), encoding="utf-8")
    done = _lint(head)
    assert done.returncode != 0
    for importer in (
        "head.calc.option_book -> state",
        "head.calc.terrain_engine -> sqlite3",
        "head.calc.liquidity_value_engine -> push",
        "head.calc.order_flow -> socket",
    ):
        assert importer in done.stdout


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
    client = head / "feed" / "schwab_client.py"
    client.write_text("import requests\n" + client.read_text(encoding="utf-8"), encoding="utf-8")
    done = _lint(head)
    assert done.returncode != 0
    assert "head.feed.schwab_client -> requests" in done.stdout


def test_a_call_through_feeds_client_from_outside_feed_is_refused(head):
    """The page's server reaching Feed's Schwab client is refused, as importing schwab is."""
    server = head / "server.py"
    reach = "\n\ndef _call():\n    from feed import schwab_client\n"
    server.write_text(server.read_text(encoding="utf-8") + reach, encoding="utf-8")
    done = _lint(head)
    assert done.returncode != 0
    assert "head.server -> feed" in done.stdout


def test_schwab_fields_for_a_stream_service_come_from_feed():
    assert "BID_PRICE" in stream.streaming_fields()["LevelOneEquity"]
