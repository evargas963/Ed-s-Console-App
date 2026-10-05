"""Batch-2: analytics background recompute fail-counter wiring."""

from __future__ import annotations

from pathlib import Path

import pytest












class _RevokedClient:
    """STAND-IN for a schwab-py client whose token refresh Schwab rejected: each chain request
    raises what authlib raises then."""

    def __init__(self):
        self.calls = 0

    def get_option_chain(self, *_a, **_k):
        from authlib.integrations.base_client.errors import OAuthError
        self.calls += 1
        raise OAuthError(error="invalid_grant", description="refresh token revoked")


class _AnsweringClient:
    """STAND-IN for a schwab-py client that reaches Schwab: each chain request is answered."""

    def __init__(self, error: "Exception | None" = None):
        self.calls, self.error = 0, error

    def get_option_chain(self, *_a, **_k):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return object()


def test_an_auth_failure_withholds_that_clients_next_chain_request():
    import schwab_client as sc

    client = _RevokedClient()
    with pytest.raises(sc.SchwabAuthError):
        sc.safe_get_chain(client, "SPY")
    with pytest.raises(sc.SchwabAuthError, match="latched"):
        sc.safe_get_chain(client, "SPY")
    assert client.calls == 1, "a latched client's request reached Schwab"


def test_a_non_auth_failure_is_not_an_auth_error():
    """A message that merely mentions a token or 401 is not an OAuth failure."""
    import schwab_client as sc

    client = _AnsweringClient(RuntimeError("token 401 invalid"))
    for _ in range(2):
        with pytest.raises(RuntimeError):
            sc.safe_get_chain(client, "SPY")
    assert client.calls == 2, "a non-auth failure latched the client"


def test_one_clients_auth_failure_never_withholds_another_clients_requests():
    """The latch was one module-wide value: one client's token failure withheld every other
    client's chains and quotes for 5 minutes (in CI, a test's revoked stand-in withheld a later
    test's chain on the same worker)."""
    import schwab_client as sc

    with pytest.raises(sc.SchwabAuthError):
        sc.safe_get_chain(_RevokedClient(), "SPY")
    other = _AnsweringClient()
    sc.safe_get_chain(other, "SPY")
    assert other.calls == 1








def test_api_build_exposes_git_sha(monkeypatch):
    """BUILD_IDENTITY semantics (operator-approved 2026-07-10): git_sha is the
    STARTUP process identity; request-time repo state lives only under
    repository_state_now.repo_head_now.

    TEST_SYSTEM_REHAB_V2 final remediation: api_build is a plain sync handler with
    no auth/middleware/serialization-shaping dependency -- the HTTP round trip added
    nothing a direct call doesn't already prove."""
    import server as srv

    monkeypatch.setattr(srv, "_repo_git_head_sha", lambda: "abc123deadbeef")
    body = srv.api_build()
    assert body["git_sha"] == body["process_identity"]["startup_git_sha"]
    assert body["repository_state_now"]["repo_head_now"] == "abc123deadbeef"
    assert body["git_sha_semantics"] == "startup_process_identity"
    assert body["contract"] == "meet_or_exceed_v1"




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
