"""Behavioral reproduction: CI-offline contaminated launch must fail closed.

Proven production failure (2026-08-29, HEAD 9c195333): parent shell exported
ED_CI_OFFLINE=1 + SCHWAB_*='test'; analytics bg raised::

    RuntimeError: Schwab CI offline mode — live API call blocked (...)

while /api/health stayed 200. These tests lock the launcher preflight that
refuses that launch posture — without weakening the Schwab gate itself.

pytest-full 33283969383 (head c30d1543): apply_sanitize() on process env also
stripped ED_CONSOLE_ALLOW_NONCANONICAL_DB, leaking into xdist gw1 and failing
unrelated EdDB tests. Sanitize must never touch that harness flag, and tests
must not mutate process env without monkeypatch restore.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_LIVE_KEY = "live-desk-key-not-placeholder"
_LIVE_SECRET = "live-desk-secret-not-placeholder"
_TEST_SENTINEL = "test"


def _isolated_contaminated_parent() -> dict[str, str]:
    """Exact proven production contamination plus a harness flag that must survive."""
    return {
        "ED_CI_OFFLINE": "1",
        "CI": "true",
        "ED_CONSOLE_ALLOW_NONCANONICAL_DB": "1",
        "SCHWAB_API_KEY": _TEST_SENTINEL,
        "SCHWAB_APP_SECRET": _TEST_SENTINEL,
        "ED_OPS_RUNNER": "1",
        "PATH": "/usr/bin",
    }


def test_start_ed_console_bat_wires_live_schwab_env_preflight():
    bat = (ROOT / "start_ed_console.bat").read_text(encoding="utf-8")
    assert 'live_schwab_env.py --bat-unsets' in bat
    assert 'live_schwab_env.py --sanitize' in bat
    # RC-514: an unavailable Schwab capability is REPORTED, never a launch veto. The
    # sanitization asserted above is unchanged; only the consequence of a bad result changed,
    # because one vendor's credentials must not decide whether the application may exist
    # (docs/ARCHITECTURE.md §4).
    assert "SCHWAB CAPABILITY UNAVAILABLE" in bat
    assert "LAUNCH BLOCKED: live Schwab env" not in bat
    # preflight (unsets + sanitize) runs before uvicorn so the child inherits the sanitized env
    assert bat.index("live_schwab_env.py --bat-unsets") < bat.index(
        '"%VENV_PY%" -m uvicorn server:app'
    )
    assert bat.index("live_schwab_env.py --sanitize") < bat.index(
        '"%VENV_PY%" -m uvicorn server:app'
    )


def test_ed_ci_offline_inherited_is_sanitized_before_launch():
    from live_schwab_env import apply_sanitize

    env = _isolated_contaminated_parent()
    apply_sanitize(env)
    assert "ED_CI_OFFLINE" not in env
    assert env.get("ED_CI_OFFLINE") in (None, "")


def test_schwab_test_sentinel_inherited_is_sanitized_before_launch():
    from live_schwab_env import apply_sanitize, _is_non_live_schwab_value

    env = _isolated_contaminated_parent()
    apply_sanitize(env)
    assert "SCHWAB_API_KEY" not in env
    assert "SCHWAB_APP_SECRET" not in env
    assert not _is_non_live_schwab_value(env.get("SCHWAB_API_KEY"))
    assert not _is_non_live_schwab_value(env.get("SCHWAB_APP_SECRET"))


def test_sanitize_does_not_strip_db_harness_or_live_authority():
    """Regression lock for pytest-full 33283969383 / c30d1543."""
    from live_schwab_env import apply_sanitize, vars_to_unset

    env = _isolated_contaminated_parent()
    env["SCHWAB_TOKEN_PATH"] = "C:\\live\\schwab_token.json"
    cleared = vars_to_unset(env)
    assert "ED_CONSOLE_ALLOW_NONCANONICAL_DB" not in cleared
    assert "ED_OPS_RUNNER" not in cleared
    assert "SCHWAB_TOKEN_PATH" not in cleared
    apply_sanitize(env)
    assert env["ED_CONSOLE_ALLOW_NONCANONICAL_DB"] == "1"
    assert env["ED_OPS_RUNNER"] == "1"
    assert env["SCHWAB_TOKEN_PATH"] == "C:\\live\\schwab_token.json"
    assert "PATH" in env


def test_sanitize_does_not_erase_legitimate_live_schwab_credentials():
    from live_schwab_env import apply_sanitize

    env = {
        "SCHWAB_API_KEY": _LIVE_KEY,
        "SCHWAB_APP_SECRET": _LIVE_SECRET,
        "ED_OPS_RUNNER": "1",
    }
    apply_sanitize(env)
    assert env["SCHWAB_API_KEY"] == _LIVE_KEY
    assert env["SCHWAB_APP_SECRET"] == _LIVE_SECRET


def test_child_uvicorn_env_has_no_ci_test_contamination():
    """bat-unsets + sanitize are the parent env the uvicorn child inherits."""
    from live_schwab_env import apply_sanitize

    inherited = _isolated_contaminated_parent()
    apply_sanitize(inherited)
    assert inherited.get("ED_CI_OFFLINE") in (None, "")
    assert inherited.get("CI") in (None, "")
    assert inherited.get("SCHWAB_API_KEY") in (None, "")
    assert inherited.get("SCHWAB_APP_SECRET") in (None, "")
    # harness / ops flags survive so we did not wipe the parent indiscriminately
    assert inherited["ED_CONSOLE_ALLOW_NONCANONICAL_DB"] == "1"
    assert inherited["ED_OPS_RUNNER"] == "1"


def test_contamination_remaining_after_sanitize_blocks(monkeypatch):
    """Missing live replacement after sentinel strip → fail closed."""
    import live_schwab_env as mod

    monkeypatch.setattr("config._ensure_dotenv_loaded", lambda: None)
    monkeypatch.delenv("ED_CI_OFFLINE", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("SCHWAB_API_KEY", raising=False)
    monkeypatch.delenv("SCHWAB_APP_SECRET", raising=False)
    assert mod.main([]) == 1


def test_placeholder_credentials_remaining_block(monkeypatch):
    import live_schwab_env as mod

    monkeypatch.setattr("config._ensure_dotenv_loaded", lambda: None)
    monkeypatch.delenv("ED_CI_OFFLINE", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("SCHWAB_API_KEY", "ci-not-live-placeholder")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "ci-not-live-placeholder")
    assert mod.main([]) == 1


def test_legitimate_live_configuration_passes(monkeypatch):
    import live_schwab_env as mod

    monkeypatch.setattr("config._ensure_dotenv_loaded", lambda: None)
    monkeypatch.delenv("ED_CI_OFFLINE", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("SCHWAB_API_KEY", _LIVE_KEY)
    monkeypatch.setenv("SCHWAB_APP_SECRET", _LIVE_SECRET)
    harness_before = os.getenv("ED_CONSOLE_ALLOW_NONCANONICAL_DB")
    assert mod.main([]) == 0
    assert os.getenv("ED_CONSOLE_ALLOW_NONCANONICAL_DB") == harness_before


def test_preflight_never_emits_secret_values(monkeypatch, capsys):
    import live_schwab_env as mod

    secret = "super-secret-live-value-xyz-9f3"
    monkeypatch.setattr("config._ensure_dotenv_loaded", lambda: None)
    monkeypatch.setenv("ED_CI_OFFLINE", "1")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("SCHWAB_API_KEY", secret)
    monkeypatch.setenv("SCHWAB_APP_SECRET", secret)
    assert mod.main([]) == 1
    blocked = capsys.readouterr()
    assert secret not in blocked.out
    assert secret not in blocked.err
    assert mod.main(["--bat-unsets"]) == 0
    unsets = capsys.readouterr()
    assert secret not in unsets.out
    assert secret not in unsets.err
    assert "set ED_CI_OFFLINE=\n" in unsets.out
    assert "set SCHWAB_API_KEY=\n" not in unsets.out  # live value is not a sentinel


def test_block_live_schwab_raises_under_ci_offline_no_arg_call(monkeypatch):
    """Reproduce the exact RuntimeError analytics bg hit in production."""
    monkeypatch.setenv("ED_CI_OFFLINE", "1")
    monkeypatch.setenv("SCHWAB_API_KEY", _TEST_SENTINEL)
    monkeypatch.setenv("SCHWAB_APP_SECRET", _TEST_SENTINEL)
    import schwab_client as sc

    # RC-514: same refusal, message widened to name every reason the capability is unavailable.
    with pytest.raises(RuntimeError, match="UNAVAILABLE"):
        sc._block_live_schwab_in_ci_offline()


def test_preflight_refuses_contaminated_env_then_passes_after_isolated_sanitize(monkeypatch):
    """Same contract as the old process-env test, but sanitize a copy — no xdist leak."""
    import live_schwab_env as mod

    monkeypatch.setattr("config._ensure_dotenv_loaded", lambda: None)
    monkeypatch.setenv("ED_CI_OFFLINE", "1")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("SCHWAB_API_KEY", _TEST_SENTINEL)
    monkeypatch.setenv("SCHWAB_APP_SECRET", _TEST_SENTINEL)

    assert mod.main([]) == 1

    isolated = {
        "ED_CI_OFFLINE": "1",
        "CI": "true",
        "SCHWAB_API_KEY": _TEST_SENTINEL,
        "SCHWAB_APP_SECRET": _TEST_SENTINEL,
        "ED_CONSOLE_ALLOW_NONCANONICAL_DB": "1",
    }
    mod.apply_sanitize(isolated)
    assert "ED_CI_OFFLINE" not in isolated
    assert isolated["ED_CONSOLE_ALLOW_NONCANONICAL_DB"] == "1"

    monkeypatch.delenv("ED_CI_OFFLINE", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("SCHWAB_API_KEY", _LIVE_KEY)
    monkeypatch.setenv("SCHWAB_APP_SECRET", _LIVE_SECRET)
    assert os.getenv("ED_CI_OFFLINE") in (None, "")
    assert mod.main([]) == 0
    # process harness flag must still be present for later tests on this worker
    assert os.getenv("ED_CONSOLE_ALLOW_NONCANONICAL_DB") == "1"


def test_bat_unsets_emit_set_lines_for_cmd_contamination_only(monkeypatch, capsys):
    import live_schwab_env as mod

    monkeypatch.setenv("ED_CI_OFFLINE", "1")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("SCHWAB_API_KEY", _TEST_SENTINEL)
    monkeypatch.setenv("SCHWAB_APP_SECRET", _TEST_SENTINEL)
    monkeypatch.setenv("ED_CONSOLE_ALLOW_NONCANONICAL_DB", "1")
    assert mod.main(["--bat-unsets"]) == 0
    out = capsys.readouterr().out
    assert "set ED_CI_OFFLINE=\n" in out
    assert "set CI=\n" in out
    assert "set SCHWAB_API_KEY=\n" in out
    assert "set SCHWAB_APP_SECRET=\n" in out
    assert "ED_CONSOLE_ALLOW_NONCANONICAL_DB" not in out
