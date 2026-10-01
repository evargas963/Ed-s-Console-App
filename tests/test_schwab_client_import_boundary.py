"""Schwab import boundary — CI-safe module load without live auth or network."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _restore_server_module_binding():
    """Put `sys.modules["server"]` back exactly as found.

    `_reload_server_module` below pops `server` and re-imports it, which is the point of
    these tests. It never restored the original, so every suite that ran afterwards in the
    same process saw a DIFFERENT module object than the one it had imported — its
    module-level caches and any references captured at import time belonged to the discarded
    copy. MEASURED: `test_server_quote_source_contract.py` passes alone (8 passed) and this
    file passes alone (9 passed), but run in this order two of its tests fail; that pair is
    exactly the failure the authoritative turn audit reported twice. A test may reload a
    module; it may not leave the interpreter holding a different one than it found.
    """
    had = "server" in sys.modules
    original = sys.modules.get("server")
    try:
        yield
    finally:
        if had:
            sys.modules["server"] = original
        else:
            sys.modules.pop("server", None)


def _reload_server_module() -> object:
    sys.modules.pop("server", None)
    return importlib.import_module("server")


def test_schwab_py_package_importable() -> None:
    import schwab.auth
    assert schwab.auth.__name__ == "schwab.auth"


def test_schwab_client_imports_without_constructing_live_client() -> None:
    import schwab_client

    assert callable(schwab_client.build_client_from_token)
    assert not hasattr(schwab_client, "_client")


def test_build_client_from_token_fails_closed_without_token_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from schwab_client import build_client_from_token

    monkeypatch.delenv("ED_CI_OFFLINE", raising=False)
    state = build_client_from_token(
        str(tmp_path / "missing_token.json"),
        api_key="fake-key-not-ci-placeholder",
        app_secret="fake-secret-not-ci-placeholder",
    )
    assert state.ok is False
    assert state.client is None
    assert "not found" in state.message.lower()


def test_build_config_fail_closed_without_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SCHWAB_API_KEY", raising=False)
    monkeypatch.delenv("SCHWAB_APP_SECRET", raising=False)
    from config import build_config

    # RC-514: this used to require build_config to RAISE without secrets. server.py calls
    # build_config at MODULE SCOPE, so that raise made `import server` — and therefore
    # `uvicorn server:app` — fail outright: the whole application refused to exist because one
    # vendor's credentials were absent, the boundary docs/ARCHITECTURE.md "Failure domains" rejects.
    #
    # Nothing is weakened. What the raise protected — no live Schwab without credentials — is
    # asserted here at `schwab_live_blocked_for`, the gate `schwab_client` refuses on, so the
    # capability fails closed while the application shell stays able to run.
    from config import schwab_live_blocked_for
    from schwab_client import build_client_from_token

    cfg = build_config()                         # the app shell builds ...
    assert cfg.api_key == "" and cfg.app_secret == ""

    assert schwab_live_blocked_for() is True     # ... the capability does not
    state = build_client_from_token(str(tmp_path / "token.json"), cfg.api_key, cfg.app_secret)
    assert state.ok is False and state.client is None, state
    assert "UNAVAILABLE" in state.message, state.message


def test_server_import_does_not_build_client_or_run_login_flow() -> None:
    with patch("schwab_client.build_client_from_token") as mock_build, patch(
        "schwab_client.run_login_flow"
    ) as mock_login:
        srv = _reload_server_module()
        mock_build.assert_not_called()
        mock_login.assert_not_called()
        assert srv.app is not None


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


def test_adversarial_tests_can_import_server() -> None:
    import server as srv

    assert hasattr(srv, "app")
