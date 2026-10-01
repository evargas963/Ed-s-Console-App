from __future__ import annotations

from pathlib import Path

import pytest


def test_safe_get_chain_raises_schwab_auth_error_on_invalid_grant(monkeypatch: pytest.MonkeyPatch):
    import schwab_client as sc

    monkeypatch.setenv("SCHWAB_API_KEY", "unit-test-key-not-live")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "unit-test-secret-not-live")
    monkeypatch.delenv("ED_CI_OFFLINE", raising=False)
    sc._schwab_auth_failure_until_mono = 0.0

    from authlib.integrations.base_client.errors import OAuthError

    class _FakeClient:
        def get_option_chain(self, *_a, **_k):   # what authlib raises when a refresh is rejected
            raise OAuthError(error="invalid_grant", description="refresh token revoked")

    with pytest.raises(sc.SchwabAuthError):
        sc.safe_get_chain(_FakeClient(), "SPY")
    assert sc._schwab_auth_latched()


def test_a_non_auth_failure_is_not_an_auth_error(monkeypatch: pytest.MonkeyPatch):
    """A message that merely mentions a token or 401 is not an OAuth failure."""
    import schwab_client as sc

    monkeypatch.setenv("SCHWAB_API_KEY", "unit-test-key-not-live")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "unit-test-secret-not-live")
    monkeypatch.delenv("ED_CI_OFFLINE", raising=False)
    sc._schwab_auth_failure_until_mono = 0.0

    class _FakeClient:
        def get_option_chain(self, *_a, **_k):
            raise RuntimeError("token 401 invalid")

    with pytest.raises(RuntimeError):
        sc.safe_get_chain(_FakeClient(), "SPY")
    assert not sc._schwab_auth_latched()


def test_safe_get_chain_latched_skips_second_call(monkeypatch: pytest.MonkeyPatch):
    import schwab_client as sc

    monkeypatch.setenv("SCHWAB_API_KEY", "unit-test-key-not-live")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "unit-test-secret-not-live")
    monkeypatch.delenv("ED_CI_OFFLINE", raising=False)
    sc._schwab_auth_failure_until_mono = sc.time.monotonic() + 60.0
    calls = {"n": 0}

    class _FakeClient:
        def get_option_chain(self, *_a, **_k):
            calls["n"] += 1
            return object()

    with pytest.raises(sc.SchwabAuthError):
        sc.safe_get_chain(_FakeClient(), "SPY")
    assert calls["n"] == 0


def test_the_port_guard_refuses_an_occupied_port_and_passes_a_free_one():
    """The launcher's port guard, run as a subprocess against a bound port (an occupant that is
    not an Ed Console server -> exit 1, refuse) and a free port (-> exit 0, proceed)."""
    import socket
    import subprocess
    import sys

    root = Path(__file__).resolve().parent.parent
    guard = str(root / "launcher_port_guard.py")
    venv_py = sys.executable  # virtualenv-parity gate guarantees this is the repo .venv python

    busy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    busy_port = busy.getsockname()[1]
    try:
        occ = subprocess.run([venv_py, guard, str(busy_port)], capture_output=True, text=True)
    finally:
        busy.close()
    assert occ.returncode == 1, (
        f"launcher_port_guard must report an unrecognized occupant as exit 1: {occ.stdout}"
    )

    free = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    free.bind(("127.0.0.1", 0))
    free_port = free.getsockname()[1]
    free.close()
    fr = subprocess.run([venv_py, guard, str(free_port)], capture_output=True, text=True)
    assert fr.returncode == 0, f"launcher_port_guard must report a free port as exit 0: {fr.stdout}"
