"""RC-514 — a vendor outage degrades a capability; it does not decide whether the app exists.

docs/ARCHITECTURE.md "Failure domains" separates application availability from capability availability:

    Schwab unavailable
        -> app stays alive
        -> Schwab capability unavailable/degraded
        -> Schwab-dependent decision influence fails closed

The correction is narrow and adds no mechanism. `config.schwab_live_blocked_for()` — the gate
`schwab_client` already refuses on — now also blocks when credentials are ABSENT, which it did
not; and `/api/health` publishes the capability from the capture daemon's heartbeat (the daemon
is the only Schwab client), so health can never advertise a Schwab connection that is not open.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

LIVE_KEY = "LiveLookingKey1234567890"
LIVE_SECRET = "LiveLookingSecret098765"

SCHWAB_ENV = ("SCHWAB_API_KEY", "SCHWAB_APP_SECRET", "ED_CI_OFFLINE", "CI")


@pytest.fixture()
def clean_env(monkeypatch):
    """No inherited Schwab state — each test states the situation it is testing."""
    for key in SCHWAB_ENV:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


# ==================================================== the capability gate and fail-closed

def test_absent_credentials_block_live_schwab(clean_env):
    """PROOF 4a. The hole this closes: absent credentials used to NOT block.

    `schwab_credentials_are_ci_placeholders` returns False for an empty value, so with no
    credentials the gate said "not blocked", a client was built, and calls went out
    unauthenticated — the capability presenting itself as live.
    """
    from config import schwab_live_blocked_for

    assert schwab_live_blocked_for() is True, "no credentials must block live Schwab"
    assert schwab_live_blocked_for(api_key="", app_secret="") is True

    clean_env.setenv("SCHWAB_API_KEY", LIVE_KEY)
    clean_env.setenv("SCHWAB_APP_SECRET", LIVE_SECRET)
    assert schwab_live_blocked_for() is False, "PROOF 3: live credentials must NOT be blocked"

    clean_env.setenv("ED_CI_OFFLINE", "1")
    assert schwab_live_blocked_for() is True, "CI offline must still block"
    # explicit non-placeholder args stay usable for unit tests (unchanged contract)
    assert schwab_live_blocked_for(api_key=LIVE_KEY, app_secret=LIVE_SECRET) is False


def test_an_unavailable_capability_cannot_serve_live_data(clean_env):
    """PROOF 4b. Fail closed at the one refusal site — no client, so no call.

    Nothing may reach the money path from an unavailable capability: not a client, not a
    fabricated quote, not a stale substitute.
    """
    import schwab_client

    state = schwab_client.build_client_from_token("nonexistent.json", "", "")
    assert state.ok is False and state.client is None, state
    assert "UNAVAILABLE" in state.message, state.message




# ================================================================= app availability

def test_health_reports_the_daemons_schwab_socket_and_the_app_stays_ok():
    """PROOF 1c/2. The app is `ok` while Schwab is UNAVAILABLE, and health says which. Schwab is
    the capture daemon's (the console makes no Schwab call): its heartbeat says whether its Schwab
    socket is open; no current heartbeat is UNAVAILABLE, never AVAILABLE (RC-57)."""
    import time

    import live_market_plane as lmp
    import server

    payload = server.health()
    assert payload["status"] == "ok", "a vendor outage must not make the application unhealthy"
    assert payload["capabilities"] == {
        "schwab": "UNAVAILABLE", "schwab_reason": "the capture daemon's heartbeat is not current"}
    assert payload["logger_tickers"] is None

    now = time.time()
    lmp.record_feed_heartbeat({"ts": now, "schwab_socket_open": False, "board": ["SPY", "$SPX"]})
    payload = server.health()
    assert payload["capabilities"] == {
        "schwab": "UNAVAILABLE", "schwab_reason": "the capture daemon's Schwab socket is not open"}

    lmp.record_feed_heartbeat({"ts": now, "schwab_socket_open": True, "board": ["SPY", "$SPX"]})
    payload = server.health()
    assert payload["status"] == "ok"
    assert payload["capabilities"] == {"schwab": "AVAILABLE"}
    assert payload["logger_tickers"] == 2


