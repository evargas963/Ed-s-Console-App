"""
Pytest: allow EdDB against temp paths (non-canonical) without per-call flags.

Production processes must NOT set ED_CONSOLE_ALLOW_NONCANONICAL_DB globally.

Schwab placeholders (CI / adversarial): the Schwab client modules read the credentials from
the environment. Module-level setdefault here runs before test collection so no test needs
real GitHub secrets; these vars are not set outside pytest. Fail-closed without secrets is
locked by ``test_build_config_fail_closed_without_secrets``.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

# Every pytest process (serial runner, xdist controller, and each xdist worker) owns ONE
# deterministic, process-private runtime boundary before any application module imports
# (RC-523 runtime root + RC-515 explicit isolation, reconciled). Inherited production DB
# selectors are cleared first so a host/live value can never win; every mutable runtime path
# is then rooted under one directory, and Schwab is explicitly OFFLINE with a missing token
# so no test can reach the live account. Tests of live/offline semantics monkeypatch after
# this boundary and therefore state their own inputs.
os.environ.pop("ED_CONSOLE_DB", None)
os.environ.pop("ED_DB_PATH", None)
_PYTEST_RUNTIME_ROOT = Path(
    tempfile.mkdtemp(
        prefix=f"ed-pytest-{os.environ.get('PYTEST_XDIST_WORKER', 'serial')}-{os.getpid()}-"
    )
).resolve()
os.environ["ED_RUNTIME_ROOT"] = str(_PYTEST_RUNTIME_ROOT)
os.environ["ED_ARTIFACTS_ROOT"] = str(_PYTEST_RUNTIME_ROOT / "artifacts")
os.environ.setdefault("ED_CONSOLE_ALLOW_NONCANONICAL_DB", "1")
# The console DB and stream-capture DB are NOT set by env: RC-534 disabled ambient
# ED_CONSOLE_DB / STREAM_CAPTURE_DB_PATH overrides (db._resolve_console_db_path raises on
# them). Both resolve canonically under ED_RUNTIME_ROOT above, which is the one isolation
# knob — the _stream_spine_fallback fixture below still pins the stream reader default.

# Schwab hermetic AND explicitly offline: placeholder credentials in the environment;
# ED_CI_OFFLINE guarantees no test constructs a live Schwab client. SCHWAB_TOKEN_PATH is NOT
# set — RC-534 resolves the token canonically under ED_RUNTIME_ROOT (a path with no token in
# the private root, so still offline), and runtime_layout's own tests require it unset.
os.environ["ED_CI_OFFLINE"] = "1"
# No test console may connect to the real capture daemon's live push (it would ingest live
# market data): point the push at a port nothing listens on.
os.environ["ED_LIVE_PUSH_PORT"] = "1"
# ...and the browser price socket a test daemon would bind / a test page is told
os.environ["ED_LIVE_UI_PORT"] = "1"
os.environ["SCHWAB_API_KEY"] = "ci-placeholder-api-key"
os.environ["SCHWAB_APP_SECRET"] = "ci-placeholder-app-secret"
os.environ["SCHWAB_CALLBACK_URL"] = "https://127.0.0.1:8182"


def pytest_configure(config) -> None:
    """The import-time runtime boundary holds in the controller and every xdist worker."""
    assert Path(os.environ["ED_RUNTIME_ROOT"]) == _PYTEST_RUNTIME_ROOT
    assert "ED_CONSOLE_DB" not in os.environ  # RC-534: no ambient console-DB override
    from db_authority import canonical_console_db_path, canonical_stream_db_path

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
    """Every process holds what the daemon has asked Schwab's /markets (the console takes each
    answer as the daemon publishes it): each 200 answer captured 2026-10-07 is held through
    the one intake, time_et.record_markets."""
    import json

    from time_et import record_markets
    for a in json.loads(MARKETS_ANSWERS.read_text(encoding="utf-8"))["answers"].values():
        if a["status"] == 200:
            record_markets(json.loads(a["body"]))


@pytest.fixture(autouse=True)
def _live_feed_starts_down():
    """live_market_plane's feed state (the daemon heartbeat) is process-global: every test
    starts with NO live feed, so a heartbeat one test marks can never make another test's
    price live. Tests that need a live price mark it (tests/feed_live_helper.py)."""
    import live_market_plane as _lmp_feed
    _lmp_feed.record_feed_down()
    yield
    _lmp_feed.record_feed_down()


def most_recent_trading_day_et(*, on_or_before: date | None = None) -> date:
    """The newest ET date at or before `on_or_before` (today) that Schwab's /markets answers
    held say the market was open (the same answers the code reads, so the test cannot disagree
    with them)."""
    from time_et import ET, session

    day = on_or_before or datetime.now(ET).date()
    for _ in range(14):          # the longest market closure gap is far under two weeks
        s = session(day.isoformat())
        if s is not None and s.is_open:
            return day
        day -= timedelta(days=1)
    raise AssertionError(
        f"no open day in Schwab's /markets answers held in the 14 ET days before "
        f"{on_or_before or 'today'} ({MARKETS_ANSWERS.name} covers 2026-09-30 to 2027-10-07)")


@pytest.fixture(autouse=True)
def _clear_quote_memo_between_tests():
    """RC-314: `server._quote_memo` is process-global and outlives every pytest boundary.

    `test_rest_fast_quote_spot_fail_closed_not_zero` passed as a single node and FAILED as
    part of its own file, with `quote_attempts=0` in the log: a sibling had left SPY at
    501.25 in the memo, `_memoized_quote_response` served it, and the fail-closed path under
    test never ran. tmp_path, fresh DBs and monkeypatch all isolate what the TEST owns; a
    cache owned by the import is invisible to them.

    Guarded on `server` already being imported, so the tests that never touch it pay nothing
    and none of them triggers a server import it did not ask for.
    """
    srv = sys.modules.get("server")
    memo = getattr(srv, "_quote_memo", None) if srv is not None else None
    if isinstance(memo, dict):
        memo.clear()
    yield


@pytest.fixture(scope="session")
def tracked_files() -> list[str]:
    """Every path git tracks."""
    import subprocess
    out = subprocess.run(["git", "ls-files", "-z"], cwd=Path(__file__).resolve().parent.parent,
                         capture_output=True, text=True, check=True).stdout
    return sorted(p for p in out.split("\0") if p)


@pytest.fixture
def pin_clock(monkeypatch):
    """Value a test at a fixed instant: `pin_clock(2026, 9, 22, 12, 46)` (ET). A test built on a
    stored Schwab chain is valued at the chain's capture instant, so the chain's expiries passing
    can never empty the greeks the test compares (2026-09-27: six tests had been comparing None
    with None since their fixtures expired)."""
    import time_et
    from datetime import datetime as _dt

    real = time_et.now_et
    pinned: list = []                        # modules this test has pinned, so a second pin moves them

    def pin(*when):
        at = _dt(*when, tzinfo=time_et.ET)
        if not pinned:
            pinned.extend(m for m in list(sys.modules.values())
                          if m is not None and getattr(m, "now_et", None) is real)
        for mod in pinned:
            monkeypatch.setattr(mod, "now_et", lambda: at)
        return at
    return pin


@pytest.fixture
def view(monkeypatch):
    """Open the page on tickers: `view("SPY")` opens its /api/changes connection (the one viewing
    signal) as the page does; the test starts with no page open and ends with them closed. No
    event loop is bound, so a change is recorded for the page but not delivered (another test's
    loop may be closed)."""
    import push_changes
    monkeypatch.setattr(push_changes, "_open", [])
    monkeypatch.setattr(push_changes, "_loop", None)

    def open_(*tickers):
        return [push_changes.subscribe(tk) for tk in tickers]
    return open_
