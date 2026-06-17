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


def _reload_server_module() -> object:
    sys.modules.pop("server", None)
    return importlib.import_module("server")


def test_schwab_py_package_importable() -> None:
    import schwab.auth  # noqa: F401


def test_schwab_client_imports_without_constructing_live_client() -> None:
    import schwab_client

    assert callable(schwab_client.build_client_from_token)
    assert not hasattr(schwab_client, "_client")


def test_build_client_from_token_fails_closed_without_token_file(tmp_path: Path) -> None:
    from schwab_client import build_client_from_token

    state = build_client_from_token(
        str(tmp_path / "missing_token.json"),
        api_key="fake-key",
        app_secret="fake-secret",
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
    import server

    assert server._client is None
    assert server.app is not None


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
