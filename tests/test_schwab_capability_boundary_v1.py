"""A vendor outage degrades a capability; it does not decide whether the app exists.

docs/ARCHITECTURE.md "Failure domains" separates application availability from capability availability:

    Schwab unavailable
        -> app stays alive
        -> Schwab capability unavailable/degraded
        -> Schwab-dependent decision influence fails closed

`config.schwab_live_blocked_for()`, the gate `schwab_client` refuses on, blocks absent and
placeholder credentials; `/api/health` publishes the capability from the capture daemon's heartbeat
(the daemon is the only Schwab client), so health can never advertise a Schwab connection that is
not open.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import live_market_plane as lmp
import schwab_client
import server
from app.market_data.schwab.streaming import capture
from config import schwab_live_blocked_for
from stream_spine import HealthRegistry, MessageBus

REPO = Path(__file__).resolve().parent.parent

LIVE_KEY = "LiveLookingKey1234567890"
LIVE_SECRET = "LiveLookingSecret098765"

SCHWAB_ENV = ("SCHWAB_API_KEY", "SCHWAB_APP_SECRET", "ED_CI_OFFLINE")


def _blocked(**env: str) -> bool:
    """config.schwab_live_blocked_for() in a fresh interpreter whose environment holds exactly
    `env` of the Schwab settings (each test states the situation it is testing)."""
    base = {k: v for k, v in os.environ.items() if k not in SCHWAB_ENV}
    done = subprocess.run([sys.executable, "-c", "import config; print(config.schwab_live_blocked_for())"],
                          cwd=REPO, env={**base, **env}, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip() == "True"


# ==================================================== the capability gate and fail-closed

def test_absent_credentials_block_live_schwab():
    """PROOF 4a. Absent credentials block: with none, no client is built and no call goes out
    unauthenticated."""
    assert _blocked() is True, "no credentials must block live Schwab"
    assert schwab_live_blocked_for(api_key="", app_secret="") is True
    assert _blocked(SCHWAB_API_KEY=LIVE_KEY, SCHWAB_APP_SECRET=LIVE_SECRET) is False, \
        "PROOF 3: live credentials must NOT be blocked"
    assert _blocked(SCHWAB_API_KEY=LIVE_KEY, SCHWAB_APP_SECRET=LIVE_SECRET, ED_CI_OFFLINE="1") is True, \
        "CI offline must still block"
    # explicit non-placeholder args stay usable for unit tests (unchanged contract)
    assert schwab_live_blocked_for(api_key=LIVE_KEY, app_secret=LIVE_SECRET) is False


def test_an_unavailable_capability_cannot_serve_live_data():
    """PROOF 4b. Fail closed at the one refusal site — no client, so no call.

    Nothing may reach the money path from an unavailable capability: not a client, not a
    fabricated quote, not a stale substitute.
    """
    state = schwab_client.build_client_from_token("nonexistent.json", "", "")
    assert state.ok is False and state.client is None, state
    assert "UNAVAILABLE" in state.message, state.message




# ================================================================= app availability

def test_health_reports_the_daemons_schwab_socket_and_the_app_stays_ok():
    """PROOF 1c/2. The app is `ok` while Schwab is UNAVAILABLE, and health says which. Schwab is
    the capture daemon's (the console makes no Schwab call): its heartbeat says whether its Schwab
    socket is open and, when not, why, in its own words (the real daemon's status here); no
    current heartbeat is UNAVAILABLE, never AVAILABLE."""
    payload = server.health()
    assert payload["status"] == "ok", "a vendor outage must not make the application unhealthy"
    assert payload["capabilities"] == {
        "schwab": "UNAVAILABLE", "schwab_reason": "the capture daemon's heartbeat is not current"}
    assert payload["watchlist_tickers"] is None

    lmp.record_feed_heartbeat(capture.Daemon(MessageBus(), HealthRegistry(), ["SPY", "$SPX"]).status())
    payload = server.health()
    assert payload["capabilities"] == {
        "schwab": "UNAVAILABLE",
        "schwab_reason": "NOT CONNECTED: the stream is logging in, or its connection has just ended"}

    now = time.time()
    lmp.record_feed_heartbeat({"ts": now, "schwab_socket_open": True, "watchlist": ["SPY", "$SPX"]})
    payload = server.health()
    assert payload["status"] == "ok"
    assert payload["capabilities"] == {"schwab": "AVAILABLE"}
    assert payload["watchlist_tickers"] == 2


