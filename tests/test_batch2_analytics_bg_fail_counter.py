"""Batch-2: analytics background recompute fail-counter wiring."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def _bg_fail_spy():
    import server as srv

    ticker = "ZZZ_BG_FAIL"
    expiry = "2099-03-01"
    cache_key = (ticker, expiry)
    inflight_key = srv._tier_c_inflight_key(ticker, expiry)
    srv._state_cache[cache_key] = {"ms_dict": {"ticker": ticker}, "ts": 1.0}
    srv._analytics_bg_fail_counts.pop(inflight_key, None)
    srv._analytics_bg_last_error.pop(inflight_key, None)
    with srv._analytics_bg_lock:
        srv._analytics_inflight.discard(inflight_key)
    yield ticker, expiry, cache_key, inflight_key, srv
    srv._state_cache.pop(cache_key, None)
    srv._analytics_bg_fail_counts.pop(inflight_key, None)
    srv._analytics_bg_last_error.pop(inflight_key, None)
    with srv._analytics_bg_lock:
        srv._analytics_inflight.discard(inflight_key)










def test_safe_get_chain_raises_schwab_auth_error_on_invalid_grant(monkeypatch: pytest.MonkeyPatch):
    import schwab_client as sc

    monkeypatch.setenv("SCHWAB_API_KEY", "unit-test-key-not-live")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "unit-test-secret-not-live")
    monkeypatch.delenv("ED_CI_OFFLINE", raising=False)
    sc._schwab_auth_failure_until_mono = 0.0

    class _FakeClient:
        def get_option_chain(self, *_a, **_k):
            raise RuntimeError(
                'unsupported_token_type: 400 Bad Request: "invalid_grant refresh token revoked"'
            )

    with pytest.raises(sc.SchwabAuthError):
        sc.safe_get_chain(_FakeClient(), "SPY")
    assert sc._schwab_auth_latched()


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


def test_publish_progressive_tier_c_cache_non_pending_shell():
    import time

    import server as srv
    from math_levels import ExposureRow, WallsRow, TotalsRow

    ticker = "ZZZ_PROG"
    exp = "2099-06-01"
    cache_key = (ticker, exp)
    inflight_key = srv._tier_c_inflight_key(ticker, None)
    srv._state_cache.pop(cache_key, None)
    # RC-128/134: kl_* walls come only from terrain overlay — seed a fresh terrain row
    # so the progressive shell proves carriage, not a resurrected analytics wall book.
    with srv._terrain_cache_lock:
        srv._terrain_cache[(ticker.upper())] = {
            "call_wall": 510.0,
            "put_wall": 490.0,
            "computed_ts_utc": time.time(),
        }

    row = ExposureRow("CONSENSUS", None, 1.0, -1.0, 500.0, None, None, None, "Low", "Neutral")
    wall = WallsRow(
        "CONSENSUS",
        None,
        510.0,
        100.0,
        490.0,
        90.0,
        "CALL",
        510.0,
        100.0,
        505.0,
        80.0,
        495.0,
        70.0,
        "PUT",
        495.0,
        70.0,
        500.0,
        60.0,
        490.0,
        50.0,
        "CALL",
        500.0,
        60.0,
        490.0,
        50.0,
    )
    total = TotalsRow(
        "CONSENSUS",
        None,
        1.0,
        -1.0,
        0.0,
        1.0,
        -1.0,
        0.0,
        1000.0,
        900.0,
        100.0,
        0.9,
        0.2,
        0.1,
    )

    srv._publish_progressive_tier_c_cache(
        ticker=ticker,
        cache_key=cache_key,
        inflight_key=inflight_key,
        selected_exp=exp,
        expiries=[exp, "2099-06-08"],
        today_str="2099-01-01",
        spot_f=500.0,
        bid=499.9,
        ask=500.1,
        session_label="RTH",
        rows=[row],
        walls=[wall],
        totals=[total],
        consensus_summary=row,
        exposures={500.0: {"net_gex_1pct": 1.0}},
        gamma_flip=501.0,
        gamma_voids=[],
        charm_net=100.0,
        charm_dir="buying",
        charm_toward=500.0,
        pcr_val=0.9,
        kl_expiry_source="default_expiry",
        quote_spread_pts=0.2,
        quote_spread_source="schwab_bid_ask_live",
        update_source="test_progressive",
    )

    ent = srv._state_cache.get(cache_key)
    assert ent is not None
    md = ent["ms_dict"]
    assert md.get("analytics_pending_shell") is False
    assert md.get("analytics_partial_tier_c") is True
    assert md.get("analytics_refresh_in_progress") is True
    assert md.get("expiries") == [exp, "2099-06-08"]
    assert md.get("selected_exp") == exp
    assert md.get("kl_call_gamma_wall") == 510.0
    assert len(md.get("summary_rows") or []) == 1
    srv._state_cache.pop(cache_key, None)
    with srv._terrain_cache_lock:
        srv._terrain_cache.pop(ticker.upper(), None)


def test_api_build_exposes_ui_maximize_sla(monkeypatch):
    """TEST_SYSTEM_REHAB_V2 final remediation: api_build is a plain sync handler
    with no auth/middleware/serialization-shaping dependency -- the HTTP round trip
    added nothing a direct call doesn't already prove. The warm list is what the operator
    is viewing (universality), reported as-is."""
    import app.options.order_flow.streaming as ofs
    import server as srv

    monkeypatch.setattr(ofs, "viewed_equity_symbols", lambda: ["NFLX", "SPY"])

    body = srv.api_build()
    sla = body.get("ui_maximize_sla_ms") or {}
    assert sla.get("first_quote") == srv.UI_MAXIMIZE_SLA_MS["first_quote"]
    assert sla.get("fusion_cards_panel_warm") == srv.UI_MAXIMIZE_SLA_MS["fusion_cards_panel_warm"]
    assert body.get("ui_maximize_panel_warm_tickers") == ["NFLX", "SPY"]


def test_start_ed_console_bat_opens_edge_not_chrome():
    bat = (Path(__file__).resolve().parent.parent / "start_ed_console.bat").read_text(encoding="utf-8")
    assert "msedge.exe" in bat.lower()
    assert "chrome.exe" not in bat.lower()
    assert ">>>" not in bat
    assert 'set "PF86=%ProgramFiles(x86)%"' in bat
    # Operator finding (2026-09-11): a blind fixed 2s delay opened the browser whether or
    # not the server was actually ready yet. Replaced with wait_for_ready_then_open.py,
    # which polls the real URL and only opens once it answers (or reports a timeout
    # distinctly -- see test_wait_for_ready_then_open_v1.py for that script's own
    # behavioral proof). The launcher just needs to actually wire it in.
    assert "timeout /t 2 /nobreak" not in bat, "the old blind fixed-delay browser-open must not return"
    assert "wait_for_ready_then_open.py" in bat
    assert "ED_LIVE_ABLATION_EXPERIMENT" not in bat


def test_start_ed_console_bat_uses_repo_venv_python_not_bare_path_rc497():
    """RC-497: the launcher must drive its preflight and uvicorn through the repo
    .venv interpreter, never bare PATH python/pip. In a spawned/scheduled context
    (Start-Process, Task Scheduler) bare `python` resolves to a uvicorn-less
    interpreter and the launch silently no-ops (proven 2026-08-27).

    RC-512: the pinned statement was the RC-350 repository check, which is no longer on
    the launch path at all. The interpreter rule is unchanged and is now pinned on the
    live-Schwab preflight, the one preflight the launcher still runs."""
    bat = (Path(__file__).resolve().parent.parent / "start_ed_console.bat").read_text(encoding="utf-8")
    # the pinned repo interpreter is defined, and both the check and the launch go through it
    assert r'set "VENV_PY=%~dp0.venv\Scripts\python.exe"' in bat
    assert '"%VENV_PY%" -m uvicorn server:app' in bat
    assert '"%VENV_PY%" live_schwab_env.py --sanitize' in bat
    # no EXECUTED statement runs a bare-PATH python/pip, and there is no launch-time install
    for raw in bat.splitlines():
        ln = raw.strip().lower()
        assert not ln.startswith("python "), f"bare PATH python executed: {raw!r}"
        assert not ln.startswith("python.exe "), f"bare PATH python executed: {raw!r}"
        assert not ln.startswith("python\t"), f"bare PATH python executed: {raw!r}"
        assert not ln.startswith("pip "), f"bare PATH pip executed: {raw!r}"


def test_start_ed_console_bat_fails_closed_when_port_8000_stays_occupied_rc497():
    """RC-497: the launcher refuses to launch a second uvicorn into an occupied port.

    Operator finding (2026-09-11): the original mechanism (this same test, previously)
    taskkill'd whatever PID held port 8000 with no ownership check, then merely reproved
    the raw socket was free. Replaced with launcher_port_guard.py, which additionally
    verifies the occupant IS an Ed Console server before ever touching it (see
    test_launcher_port_guard_v1.py for that script's own unit-level negative controls).
    This test proves the .bat actually WIRES that script in with a fail-closed refusal,
    and runs the REAL script as a subprocess against a bound port (occupied by something
    with no Ed Console command line -> exit 1, refuse) and a free port (-> exit 0,
    proceed) -- behavioral proof at the process boundary, not a mock.
    """
    import socket
    import subprocess
    import sys

    root = Path(__file__).resolve().parent.parent
    bat = (root / "start_ed_console.bat").read_text(encoding="utf-8")

    # (a) the fail-closed guard is wired in for port 8000, immediately followed by an
    #     errorlevel refusal that exits non-zero, plus the operator-facing block message.
    assert "launcher_port_guard.py" in bat
    idx = bat.index('launcher_port_guard.py" 8000')
    tail = bat[idx:][:400]
    assert "if errorlevel 1" in tail
    assert "exit /b 1" in tail
    assert "LAUNCH BLOCKED: port 8000 is occupied" in bat

    # (b) behavioral: the real script, run as a subprocess (not imported/mocked), against
    #     a bound port and a free port. The hard-wired 8000 is swapped for the test's own
    #     port so the proof is independent of whatever the live desk is doing on 8000.
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
