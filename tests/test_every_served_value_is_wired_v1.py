"""Every value key the console serves is a Schwab field (docs/schwab_fields.csv) or a row of the
derived register (docs/derived_register.csv), with its one producer (First gate). Each GET route,
walked over SPY's real chain and Schwab's recorded bars; a route with nothing to serve in that
state proves nothing about its keys."""

from __future__ import annotations

import csv
import pydoc
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from tests.feed_live_helper import daemon_bars, stream_daemon_bars
from tests.real_chains import SPY_0DTE

ROOT = Path(__file__).resolve().parent.parent
#: strikes, dates and option symbols: data used as a key, not a name
_DATA_KEY = re.compile(r"[\d.:\-]+|[A-Z]+\s+\d+[CP]\d+")
_PARAMS = {"ticker": "SPY", "venue": "NYSE_BOOK", "tf": "1", "timeframe": "1", "scope": "auto"}
_NOT_A_NAME = re.compile(r"[^a-z0-9]")


def _name(key: str) -> str:
    return _NOT_A_NAME.sub("", key.lower())


def _schwab_names() -> set[str]:
    with (ROOT / "docs" / "schwab_fields.csv").open(encoding="utf-8", newline="") as f:
        fields = [row["canonical_field"] for row in csv.DictReader(f)]
    return {_name(part) for field in fields for part in re.split(r"[.\[\]/ ]+", field)}


def _register() -> list[dict]:
    with (ROOT / "docs" / "derived_register.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _keys(node, into: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if not _DATA_KEY.fullmatch(str(key)):
                into.add(str(key))
            _keys(value, into)
    elif isinstance(node, list):
        for item in node:
            _keys(item, into)


@pytest.fixture
def served():
    """What the GET routes answer with SPY's levels and bars published, as {route: keys}."""
    held = SPY_0DTE
    server._publish_levels(
        "SPY",
        [dict(c) for c in held.chain],
        held.now.timestamp(),
        chain_spot=(held.spot, held.now.timestamp()),
        now=held.now,
    )
    stream_daemon_bars(daemon_bars("real_daemon_bars_spy_tsla_2026_10_01_02.json", "SPY"))
    client = TestClient(server.app, raise_server_exceptions=False)
    answers = {}
    try:
        for route, ops in sorted(server.app.openapi()["paths"].items()):
            if "get" not in ops or not route.startswith("/api/") or "{" in route:
                continue
            if route == "/api/changes":  # the long poll: it holds until a change
                continue
            query = {
                p["name"]: _PARAMS[p["name"]]
                for p in ops["get"].get("parameters", [])
                if p["name"] in _PARAMS
            }
            answer = client.get(route, params=query)
            if answer.status_code == 200 and "json" in answer.headers.get("content-type", ""):
                keys: set[str] = set()
                _keys(answer.json(), keys)
                answers[route] = keys
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop("SPY", None)
    return answers


def test_every_served_key_is_a_schwab_field_or_in_the_register(served):
    schwab, register = _schwab_names(), {row["key"] for row in _register()}
    assert {"/api/terrain", "/api/levels", "/api/health"} <= set(served)
    unwired = {
        route: sorted(k for k in keys if _name(k) not in schwab and k not in register)
        for route, keys in served.items()
    }
    named = [f"{route}: {' '.join(keys)}" for route, keys in unwired.items() if keys]
    assert not named, "\n".join(named)


def test_every_derived_row_says_why_schwab_does_not_send_it():
    assert [row["key"] for row in _register() if not row["why"] and row["kind"] != "schwab"] == []


def test_every_register_row_names_a_producer_that_exists():
    missing = [
        (row["key"], row["producer"])
        for row in _register()
        if not row["producer"].startswith("schwab:") and pydoc.locate(row["producer"]) is None
    ]
    assert not missing, "\n".join(f"{key}: {name}" for key, name in missing)
