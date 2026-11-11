"""
Pytest: allow EdDB against temp paths (non-canonical) without per-call flags.

Production processes must NOT set ED_CONSOLE_ALLOW_NONCANONICAL_DB globally.

Schwab placeholders (CI / adversarial): the Schwab client modules read the credentials from
the environment. Module-level setdefault here runs before test collection so no test needs
real GitHub secrets; these vars are not set outside pytest. Fail-closed without secrets is
locked by ``test_build_config_fail_closed_without_secrets``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane
import time_et
from db_authority import canonical_console_db_path, canonical_stream_db_path
from time_et import ET, now, record_markets, session

# Every pytest process (serial runner, xdist controller, and each xdist worker) owns ONE
# deterministic, process-private runtime boundary before any application module imports
# (RC-523 runtime root + RC-515 explicit isolation, reconciled). Every mutable runtime path
# is rooted under one directory, and Schwab is explicitly OFFLINE with a missing token
# so no test can reach the live account. Tests of live/offline semantics monkeypatch after
# this boundary and therefore state their own inputs.
_PYTEST_RUNTIME_ROOT = Path(
    tempfile.mkdtemp(prefix=f"ed-pytest-{os.getpid()}-")  # the process id names each worker's
).resolve()
os.environ["ED_RUNTIME_ROOT"] = str(_PYTEST_RUNTIME_ROOT)
os.environ["ED_CONSOLE_ALLOW_NONCANONICAL_DB"] = "1"
# The console DB and stream-capture DB are NOT set by env: both resolve canonically under
# ED_RUNTIME_ROOT above, which is the one isolation knob — the _stream_spine_fallback fixture
# below still pins the stream reader default.

# Schwab hermetic AND explicitly offline: placeholder credentials in the environment;
# ED_CI_OFFLINE guarantees no test constructs a live Schwab client. SCHWAB_TOKEN_PATH is NOT
# set — RC-534 resolves the token canonically under ED_RUNTIME_ROOT (a path with no token in
# the private root, so still offline), and runtime_layout's own tests require it unset.
os.environ["ED_CI_OFFLINE"] = "1"
# A test program's console pages (with the page's price socket, /ws) on a port the system picks,
# never production's 8000
os.environ["ED_CONSOLE_PORT"] = "0"
os.environ["SCHWAB_API_KEY"] = "ci-placeholder-api-key"
os.environ["SCHWAB_APP_SECRET"] = "ci-placeholder-app-secret"
os.environ["SCHWAB_CALLBACK_URL"] = "https://127.0.0.1:8182"

#: fixtures several test files share, loaded by pytest after this module has set the environment
pytest_plugins = ["tests.liquidity_friday"]


def pytest_configure() -> None:
    """Hold the import-time runtime boundary in the controller and every xdist worker."""
    assert Path(os.environ["ED_RUNTIME_ROOT"]) == _PYTEST_RUNTIME_ROOT
    assert _PYTEST_RUNTIME_ROOT in canonical_console_db_path().parents
    assert _PYTEST_RUNTIME_ROOT in canonical_stream_db_path().parents


@pytest.fixture(scope="session", autouse=True)
def _remove_pytest_runtime_after_session():
    yield
    shutil.rmtree(_PYTEST_RUNTIME_ROOT, ignore_errors=True)


#: Schwab's /markets answers for every date it would answer on 2026-10-07 (2026-09-30 to
#: 2027-10-07, and its 400 for each side), as sent
MARKETS_ANSWERS = Path(__file__).parent / "fixtures" / "real_schwab_markets_2026_10_07.json"


@pytest.fixture(scope="session", autouse=True)
def _markets_answers_held():
    """Every process holds what the daemon has asked Schwab's /markets.

    The console takes each answer as the daemon publishes it: each 200 answer captured
    2026-10-07 is held through the one intake, time_et.record_markets.
    """
    for a in json.loads(MARKETS_ANSWERS.read_text(encoding="utf-8"))["answers"].values():
        if a["status"] == 200:
            record_markets(json.loads(a["body"]))


@pytest.fixture(autouse=True)
def _live_feed_starts_down():
    """live_market_plane's feed state (the daemon heartbeat) is process-global.

    Every test starts with NO live feed and no remembered held set or watchlist, so a heartbeat
    one test marks can never make another test's price live. A down feed keeps that set and that
    list for the screen (record_feed_down); this fixture clears them. Tests that need a live
    price mark it (tests/feed_live_helper.py). The day's first streamed trade (time_et.record_trade)
    is process-global too: every test starts with none.
    """
    time_et._first_trade = {}
    live_market_plane.record_feed_down()
    with live_market_plane._lock:
        live_market_plane._feed["held"] = {}
        live_market_plane._feed["status"] = None
    yield
    live_market_plane.record_feed_down()
    with live_market_plane._lock:
        live_market_plane._feed["held"] = {}
        live_market_plane._feed["status"] = None


@pytest.fixture
def feed():
    """Clear the console's state before and after, and leave no daemon bound after."""
    ofs.stop_order_flow_stream()
    ofls.clear_all_live_state()
    live_market_plane._by_ticker.clear()
    yield
    ofs.stop_order_flow_stream()
    ofs.bind_daemon(None)
    live_market_plane._by_ticker.clear()
    live_market_plane.record_feed_down()


def most_recent_trading_day_et(*, on_or_before: date | None = None) -> date:
    """Return the newest ET date at or before `on_or_before` (today) the market was open.

    Open is what Schwab's /markets answers held say (the same answers the code reads, so the test
    cannot disagree with them).
    """
    start = on_or_before or datetime.fromtimestamp(now(), ET).date()
    day = start
    for _ in range(14):  # the longest market closure gap is far under two weeks
        s = session(day.isoformat())
        if s is not None and s.is_open:
            return day
        day -= timedelta(days=1)
    raise AssertionError(
        f"no open day in Schwab's /markets answers held in the 14 ET days before "
        f"{start} ({MARKETS_ANSWERS.name} covers 2026-09-30 to 2027-10-07)"
    )


@pytest.fixture(scope="session")
def tracked_files() -> list[str]:
    """Every path git tracks."""
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(p for p in out.split("\0") if p)
