"""Schwab import boundary — CI-safe module load without live auth or network."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def ci_schwab_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHWAB_API_KEY", "ci-test-key-not-live")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "ci-test-secret-not-live")
    monkeypatch.setenv("SCHWAB_TOKEN_PATH", str(REPO / "nonexistent_ci_schwab_token.json"))


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
    monkeypatch.setattr("config._load_dotenv_if_present", lambda: None)
    from config import build_config

    with pytest.raises(RuntimeError, match="SCHWAB_API_KEY"):
        build_config(str(tmp_path))


def test_server_imports_in_ci_without_live_credentials() -> None:
    """Importing server in a CI env must not build a client.

    Uses a fresh module load rather than whatever `server` the suite already imported:
    `_client` is a module-level global, so asserting on the shared instance made this
    test depend on suite order (observed 2026-07-19 inside the full run only). The
    reload tests the actual intent - a clean import builds no client.
    """
    srv = _reload_server_module()

    assert srv._client is None
    assert srv.app is not None


def test_server_import_does_not_build_client_or_run_login_flow() -> None:
    with patch("schwab_client.build_client_from_token") as mock_build, patch(
        "schwab_client.run_login_flow"
    ) as mock_login:
        srv = _reload_server_module()
        mock_build.assert_not_called()
        mock_login.assert_not_called()
        assert srv._client is None


def test_get_client_requires_token_only_when_called(monkeypatch: pytest.MonkeyPatch) -> None:
    from schwab_client import SchwabClientState

    import server

    monkeypatch.setattr(server, "_client", None)
    monkeypatch.setattr(
        server,
        "build_client_from_token",
        lambda **_: SchwabClientState(
            ok=False,
            message="Token file not found: ci-missing-token",
            client=None,
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        server.get_client(force_refresh=True)
    assert exc_info.value.status_code == 503
    assert "Schwab auth failed" in str(exc_info.value.detail)


def test_adversarial_tests_can_import_server() -> None:
    import server as srv

    assert hasattr(srv, "_finalize_production_decision")
    assert hasattr(srv, "app")


def test_ci_offline_blocks_live_schwab_client_and_api(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import is_schwab_ci_offline_mode, schwab_credentials_are_ci_placeholders, schwab_live_blocked_for
    from schwab_client import build_client_from_token, safe_get_quote

    monkeypatch.setenv("ED_CI_OFFLINE", "1")
    monkeypatch.setenv("SCHWAB_API_KEY", "ci-not-live-placeholder")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "ci-not-live-placeholder")

    assert is_schwab_ci_offline_mode() is True
    assert schwab_credentials_are_ci_placeholders() is True
    assert schwab_live_blocked_for() is True
    assert schwab_live_blocked_for(api_key="fake-key-not-ci-placeholder", app_secret="fake-secret-not-ci-placeholder") is False

    state = build_client_from_token("/tmp/missing.json", api_key="fake-key-not-ci-placeholder", app_secret="fake-secret-not-ci-placeholder")
    assert state.ok is False
    assert "not found" in state.message.lower()
    assert state.client is None

    state_placeholder = build_client_from_token(
        "/tmp/missing.json", api_key="ci-not-live-placeholder", app_secret="ci-not-live-placeholder"
    )
    assert state_placeholder.ok is False
    assert "offline" in state_placeholder.message.lower()

    class _FakeClient:
        def get_quote(self, _ticker: str):
            raise AssertionError("live Schwab API must not be called in CI offline mode")

    with pytest.raises(RuntimeError, match="offline"):
        safe_get_quote(_FakeClient(), "SPY")
