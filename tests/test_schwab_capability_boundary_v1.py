"""RC-514 — a vendor outage degrades a capability; it does not decide whether the app exists.

OBSERVED 2026-09-03. `start_ed_console.bat` ran `live_schwab_env.py --sanitize` and did
`exit /b 1` on a non-zero result, so whether Ed Console could run at all was decided by whether
one upstream vendor's credentials happened to resolve. A ghost `python-dotenv` distribution
made `.env` unloadable (RC-513) and the desk would not start — while the API, UI, health and
observability were all perfectly able to run.

docs/ARCHITECTURE.md §4 separates application availability from capability availability:

    Schwab unavailable
        -> app stays alive
        -> Schwab capability unavailable/degraded
        -> Schwab-dependent decision influence fails closed

The correction is narrow and adds no mechanism. `config.schwab_live_blocked_for()` — the gate
`schwab_client` already refuses on — now also blocks when credentials are ABSENT, which it did
not; the launcher reports instead of exiting; and `/api/health` publishes the capability from
that same gate, so health can never advertise what the call path is blocking.
"""
from __future__ import annotations

import os
import subprocess
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


def run_preflight(env_extra: dict) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in SCHWAB_ENV}
    env.update(env_extra)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(REPO / "live_schwab_env.py"), "--sanitize"],
        cwd=str(REPO), capture_output=True, text=True, env=env, timeout=300,
    )


# ============================================================ the boundary itself

def test_the_launcher_no_longer_exits_when_schwab_is_unavailable():
    """PROOF 1a. The `exit /b 1` on the Schwab preflight is gone.

    Read structurally: the Schwab preflight's `if errorlevel 1` block must not terminate the
    launcher, while the CORE-RUNTIME preflight above it still must.
    """
    bat = (REPO / "start_ed_console.bat").read_text(encoding="utf-8", errors="replace")
    lines = bat.splitlines()

    schwab_at = next(i for i, ln in enumerate(lines) if "live_schwab_env.py --sanitize" in ln)
    block, depth = [], 0
    for ln in lines[schwab_at:]:
        block.append(ln)
        depth += ln.count("(") - ln.count(")")
        if depth <= 0 and len(block) > 1:
            break
    body = "\n".join(block)
    assert "exit /b" not in body, (
        "the Schwab preflight still terminates the launcher — a vendor capability is deciding "
        f"whether the application may exist:\n{body}")
    assert "SCHWAB CAPABILITY UNAVAILABLE" in body, body

    # sanitization is NOT what was removed
    assert "live_schwab_env.py --bat-unsets" in bat
    assert bat.index("--bat-unsets") < bat.index("--sanitize")

    # core runtime provisioning still blocks the whole app (§4's reserved case)
    runtime_at = bat.index("runtime_preflight.py")
    assert "exit /b 1" in bat[runtime_at:bat.index("live_schwab_env.py")], (
        "the core-runtime preflight must still refuse startup")


@pytest.mark.parametrize("situation,env", [
    ("missing credentials", {}),
    ("CI placeholder credentials", {"SCHWAB_API_KEY": "ci-not-live-placeholder",
                                    "SCHWAB_APP_SECRET": "ci-not-live-placeholder"}),
    ("test sentinel credentials", {"SCHWAB_API_KEY": "test", "SCHWAB_APP_SECRET": "test"}),
    ("ED_CI_OFFLINE inherited", {"ED_CI_OFFLINE": "1"}),
])
def test_the_preflight_reports_a_capability_rather_than_a_launch_veto(situation, env):
    """PROOF 1b/2. Every unavailable situation reports the capability, never a launch verdict."""
    result = run_preflight(env)
    out = result.stdout + result.stderr
    assert result.returncode == 1, f"{situation}: expected UNAVAILABLE, got {result.returncode}"
    assert "LAUNCH BLOCKED" not in out, f"{situation}: still speaks as a launch veto:\n{out}"
    assert "SCHWAB CAPABILITY UNAVAILABLE" in out, f"{situation}:\n{out}"
    assert "fail closed" in out, f"{situation}: never states the money-path consequence:\n{out}"


def test_contamination_is_still_stripped(clean_env):
    """PROOF 2. The 2026-08-29 fix is intact: contamination never reaches uvicorn.

    This is the half that must NOT be relaxed by making the capability non-fatal.
    """
    import live_schwab_env

    clean_env.setenv("ED_CI_OFFLINE", "1")
    clean_env.setenv("SCHWAB_API_KEY", "test")
    clean_env.setenv("SCHWAB_APP_SECRET", "test")

    assert set(live_schwab_env.vars_to_unset()) >= {"ED_CI_OFFLINE", "SCHWAB_API_KEY",
                                                    "SCHWAB_APP_SECRET"}
    cleared = live_schwab_env.apply_sanitize()
    assert "ED_CI_OFFLINE" in cleared
    assert not os.getenv("ED_CI_OFFLINE")
    assert not os.getenv("SCHWAB_API_KEY")


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
    """PROOF 4b. Fail closed at both existing refusal sites — no client, no call.

    Nothing may reach the money path from an unavailable capability: not a client, not a
    fabricated quote, not a stale substitute.
    """
    import schwab_client

    state = schwab_client.build_client_from_token("nonexistent.json", "", "")
    assert state.ok is False and state.client is None, state
    assert "UNAVAILABLE" in state.message, state.message

    with pytest.raises(RuntimeError) as exc:
        schwab_client._block_live_schwab_in_ci_offline()
    assert "UNAVAILABLE" in str(exc.value)
    assert "No fabricated or stale substitute" in str(exc.value)


def test_the_shipped_decision_registry_authorizes_no_exposure():
    """PROOF 4c. Exposure needs an admitted component, and the SHIPPED registry admits none.

    Evaluated against the real `config/decision_path_admissions.json` by explicit path, not by
    the ambient default: a first cut of this test called the default and read `admitted=True`,
    because the pytest harness points the registry at a fixture that admits `the_call`. That
    measured the harness, not production, and would have certified the opposite of the truth.

    LIMIT, stated rather than implied: this proves no component is authorized to influence
    exposure at all, which subsumes the Schwab-dependent case. It does NOT prove what
    `compute_call` would do with a stale database if a component were later admitted while the
    Schwab capability was down. That is a decision-path question, not a capability-boundary
    one; the boundary guarantee proven here is upstream — no live Schwab value can enter
    (see `test_an_unavailable_capability_cannot_serve_live_data`).
    """
    import decision_gate

    real = (REPO / "config" / "decision_path_admissions.json").resolve()
    assert real.is_file(), real

    verdict = decision_gate.evaluate_decision_path_admission(path=real)
    assert verdict.admitted is False, verdict
    assert verdict.registry_state in ("empty", "missing", "invalid", "not_admitted"), verdict


# ================================================================= app availability

def test_health_reports_the_capability_and_the_app_stays_ok(clean_env):
    """PROOF 1c/2. The app is `ok` while Schwab is UNAVAILABLE, and health says which.

    Health reads the same gate `schwab_client` refuses on, so it can never advertise a
    capability the call path is blocking.
    """
    import server

    payload = server.health()
    assert payload["status"] == "ok", "a vendor outage must not make the application unhealthy"
    assert payload["capabilities"]["schwab"] == "UNAVAILABLE", payload

    clean_env.setenv("SCHWAB_API_KEY", LIVE_KEY)
    clean_env.setenv("SCHWAB_APP_SECRET", LIVE_SECRET)
    assert server.health()["capabilities"]["schwab"] == "AVAILABLE", "PROOF 3"


def test_health_answers_unavailable_when_the_gate_itself_cannot_be_read(clean_env, monkeypatch):
    """Unmeasurable is not ok (RC-57): a broken gate reports UNAVAILABLE, never AVAILABLE."""
    import config
    import server

    def boom():
        raise RuntimeError("gate unreadable")

    monkeypatch.setattr(config, "schwab_live_blocked_for", boom)
    payload = server.health()
    assert payload["status"] == "ok"
    assert payload["capabilities"]["schwab"] == "UNAVAILABLE", payload


def test_core_runtime_provisioning_still_blocks_startup():
    """PROOF 5. §4's reserved case is untouched: a broken venv still refuses to start.

    The narrow correction must not have turned every launch preflight into a warning.
    """
    result = subprocess.run([sys.executable, str(REPO / "runtime_preflight.py")],
                            cwd=str(REPO), capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr

    import runtime_preflight as rp

    assert hasattr(rp, "ghost_distributions") and hasattr(rp, "violations")
    bat = (REPO / "start_ed_console.bat").read_text(encoding="utf-8", errors="replace")
    tail = bat[bat.index("runtime_preflight.py"):bat.index("live_schwab_env.py")]
    assert "exit /b 1" in tail, "core-runtime failure must still stop the launch"
