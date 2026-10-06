"""Schwab import boundary — CI-safe module load without live auth or network."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def test_schwab_py_package_importable() -> None:
    import schwab.auth
    assert schwab.auth.__name__ == "schwab.auth"


def test_schwab_client_imports_without_constructing_live_client() -> None:
    import schwab_client

    assert callable(schwab_client.build_client_from_token)
    assert not hasattr(schwab_client, "_client")


def test_build_client_from_token_fails_closed_without_token_file(tmp_path: Path) -> None:
    """Explicit live-looking credentials (ED_CI_OFFLINE does not block explicit ones) and no
    token file: no client, and the reason names the missing file."""
    from schwab_client import build_client_from_token

    state = build_client_from_token(
        str(tmp_path / "missing_token.json"),
        api_key="fake-key-not-ci-placeholder",
        app_secret="fake-secret-not-ci-placeholder",
    )
    assert state.ok is False
    assert state.client is None
    assert "not found" in state.message.lower()


def test_build_config_fail_closed_without_secrets(tmp_path: Path) -> None:
    """With no Schwab credentials the configuration still builds, and the one gate
    (`schwab_live_blocked_for`, which `build_client_from_token` refuses on) builds no client: no
    live Schwab without credentials (docs/ARCHITECTURE.md "Failure domains"). Run in a fresh
    interpreter whose environment has no Schwab credential."""
    code = ("import config, schwab_client\n"
            "cfg = config.build_config()\n"
            "assert cfg.api_key == '' and cfg.app_secret == '', cfg\n"
            "assert config.schwab_live_blocked_for() is True\n"
            f"state = schwab_client.build_client_from_token({str(tmp_path / 'token.json')!r}, cfg.api_key, cfg.app_secret)\n"
            "assert state.ok is False and state.client is None and 'UNAVAILABLE' in state.message, state\n")
    env = {k: v for k, v in os.environ.items() if k not in ("SCHWAB_API_KEY", "SCHWAB_APP_SECRET")}
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr


def test_server_import_does_not_build_client_or_run_login_flow() -> None:
    """`import server` in a fresh interpreter builds no client and runs no login flow."""
    code = (
        "from unittest.mock import patch\n"
        "with patch('schwab_client.build_client_from_token') as b, patch('schwab_client.run_login_flow') as lf:\n"
        "    import server\n"
        "    b.assert_not_called(); lf.assert_not_called()\n"
        "    assert server.app is not None\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_console_makes_no_schwab_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """The capture daemon is the only Schwab client (DATA_FLOW decision 1). The console started,
    every one of its GET routes asked for a ticker, and a chain the daemon fetched priced through
    it: no Schwab client is built and no chain or quote is asked of Schwab. Before this change the
    console fetched every board ticker's chain itself (the 429s of 2026-10-01 came from it and the
    daemon asking at once)."""
    import json as _json

    import schwab
    import schwab_client
    import server
    from app.options.order_flow import streaming as ofs
    from fastapi.testclient import TestClient

    calls: list = []

    def _schwab_call(name):
        def call(*_a, **_k):
            calls.append(name)
            raise AssertionError(f"the console called Schwab: {name}")
        return call

    for name in ("build_client_from_token", "client_from_token_file_atomic", "safe_get_chain",
                 "safe_get_quotes", "fetch_full_chain", "run_login_flow"):
        monkeypatch.setattr(schwab_client, name, _schwab_call(name))
    for name in ("client_from_token_file", "client_from_login_flow", "client_from_manual_flow",
                 "easy_client"):
        monkeypatch.setattr(schwab.auth, name, _schwab_call(name))

    fx = _json.loads((Path(__file__).resolve().parent / "fixtures"
                      / "real_spy_2026_11_20_chain_and_quotes.json").read_text(encoding="utf-8"))
    with TestClient(server.app) as client:
        ofs._on_chain_callback = server._on_chain
        ofs._ingest_pushed("chain.SPY", {"src": "schwab_chain", "ticker": "SPY",
                                         "ts_recv": fx["capture_ts_utc"], "part": 0, "parts": 1,
                                         "contracts": fx["chain"]})
        server._chain_pricing.submit(lambda: None).result(timeout=120)   # the chain is priced
        for route in server.app.routes:
            # /api/changes is an open-ended event stream (it reads only the push's own state)
            if ("GET" in (getattr(route, "methods", None) or ()) and "{" not in route.path
                    and route.path != "/api/changes"):
                client.get(route.path, params={"ticker": "SPY", "contract": "SPY   261120C00875000"})
    assert calls == []
    assert server.terrain_cache_get("SPY") is not None, "the daemon's chain was priced"
    with server._terrain_cache_lock:             # the levels this test priced leave with it
        server._terrain_cache.pop("SPY", None)


def test_adversarial_tests_can_import_server() -> None:
    import server as srv

    assert hasattr(srv, "app")
