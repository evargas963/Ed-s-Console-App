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

    cfg = build_config(str(tmp_path))            # the app shell builds ...
    assert cfg.api_key == "" and cfg.app_secret == ""

    assert schwab_live_blocked_for() is True     # ... the capability does not
    state = build_client_from_token(str(tmp_path / "token.json"), cfg.api_key, cfg.app_secret)
    assert state.ok is False and state.client is None, state
    assert "UNAVAILABLE" in state.message, state.message


def test_server_imports_in_ci_without_live_credentials() -> None:
    """Importing server builds no Schwab client and runs no login flow (it holds none: P2-1)."""
    with patch("schwab_client.build_client_from_token") as mock_build, patch(
        "schwab_client.run_login_flow"
    ) as mock_login:
        srv = _reload_server_module()
        mock_build.assert_not_called()
        mock_login.assert_not_called()
    assert srv.app is not None and not hasattr(srv, "get_client")


# P2-1 (DATA_FLOW 4.1): the capture daemon holds the one Schwab connection. A Schwab call is one
# of the repo's entry points or a Schwab client method; only these files may make one.
SCHWAB_ENTRY_POINTS = {"build_client_from_token", "safe_get_chain", "fetch_full_chain"}
SCHWAB_CLIENT_METHODS = {"get_option_chain", "get_option_expiration_chain", "get_price_history",
                         "get_price_history_every_minute", "get_price_history_every_day", "get_quote",
                         "get_quotes", "get_movers", "get_market_hours", "get_instruments"}
SCHWAB_CALLERS = {"schwab_client.py", "app/market_data/schwab/streaming/capture.py",
                  "calibration/complete_chain_capture.py"}


def schwab_calls(src: str) -> list[str]:
    import ast
    out = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call):
            fn = n.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
            recv = ast.unparse(fn.value) if isinstance(fn, ast.Attribute) else ""
            if name in SCHWAB_ENTRY_POINTS or (name in SCHWAB_CLIENT_METHODS and "client" in recv.lower()):
                out.append(f"{n.lineno} {name}")
    return out


def test_only_the_daemon_calls_schwab(repo_index) -> None:
    bad = {rel.as_posix(): hits for rel, text, _t in repo_index.items()
           if rel.suffix == ".py" and not rel.as_posix().startswith(("tests/", "tools/", "research/"))
           and rel.as_posix() not in SCHWAB_CALLERS and (hits := schwab_calls(text))}
    assert not bad, f"Schwab called outside the capture daemon: {bad}"


def test_the_check_catches_the_consoles_old_calls() -> None:
    old = "; ".join([
        "resp = fetch_full_chain(client, tk, lambda **d: _gated_safe_get_chain(client, tk, **d)[0])",
        "state = build_client_from_token(api_key=k, app_secret=s, token_path=p)",
        "r = client.get_quote('SPY')",
        "row = _lmp.get_quote(tk)",                      # the live plane's own reader: not Schwab
    ])
    assert [h.split()[1] for h in schwab_calls(old)] == ["fetch_full_chain", "build_client_from_token", "get_quote"]


def test_adversarial_tests_can_import_server() -> None:
    import server as srv

    assert hasattr(srv, "app")
