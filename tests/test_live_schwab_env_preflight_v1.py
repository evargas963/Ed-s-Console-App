"""Behavioral reproduction: CI-offline contaminated launch must fail closed.

Proven production failure (2026-08-29, HEAD 9c195333): parent shell exported
ED_CI_OFFLINE=1 + SCHWAB_*='test'; analytics bg raised::

    RuntimeError: Schwab CI offline mode — live API call blocked (...)

while /api/health stayed 200. These tests lock the launcher preflight that
refuses that launch posture — without weakening the Schwab gate itself.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_start_ed_console_bat_wires_live_schwab_env_preflight():
    bat = (ROOT / "start_ed_console.bat").read_text(encoding="utf-8")
    assert r'tools\check_live_schwab_env.py --bat-unsets' in bat
    assert r'tools\check_live_schwab_env.py --sanitize' in bat
    assert "LAUNCH BLOCKED: live Schwab env is CI/test contaminated" in bat
    # preflight runs before uvicorn
    assert bat.index("check_live_schwab_env.py --sanitize") < bat.index(
        '"%VENV_PY%" -m uvicorn server:app'
    )


def test_vars_to_unset_matches_proven_contaminated_shell():
    from tools.check_live_schwab_env import vars_to_unset

    env = {
        "ED_CI_OFFLINE": "1",
        "CI": "true",
        "ED_CONSOLE_ALLOW_NONCANONICAL_DB": "1",
        "SCHWAB_API_KEY": "test",
        "SCHWAB_APP_SECRET": "test",
        "PATH": "/usr/bin",
    }
    cleared = vars_to_unset(env)
    assert "ED_CI_OFFLINE" in cleared
    assert "CI" in cleared
    assert "ED_CONSOLE_ALLOW_NONCANONICAL_DB" in cleared
    assert "SCHWAB_API_KEY" in cleared
    assert "SCHWAB_APP_SECRET" in cleared
    assert "PATH" not in cleared


def test_block_live_schwab_raises_under_ci_offline_no_arg_call(monkeypatch):
    """Reproduce the exact RuntimeError analytics bg hit in production."""
    monkeypatch.setenv("ED_CI_OFFLINE", "1")
    monkeypatch.setenv("SCHWAB_API_KEY", "test")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "test")
    # Import after env set so config reads current environ
    import schwab_client as sc

    with pytest.raises(RuntimeError, match="Schwab CI offline mode"):
        sc._block_live_schwab_in_ci_offline()


def test_preflight_refuses_contaminated_env_then_passes_after_sanitize(monkeypatch):
    monkeypatch.setenv("ED_CI_OFFLINE", "1")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("SCHWAB_API_KEY", "test")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "test")

    from tools import check_live_schwab_env as mod

    assert mod.main([]) == 1  # refuse while contaminated

    # After sanitize + live credentials, launch is allowed.
    mod.apply_sanitize()
    monkeypatch.setenv("SCHWAB_API_KEY", "live-desk-key-not-placeholder")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "live-desk-secret-not-placeholder")
    assert os.getenv("ED_CI_OFFLINE") in (None, "")
    assert mod.main([]) == 0


def test_bat_unsets_emit_set_lines_for_cmd(monkeypatch, capsys):
    monkeypatch.setenv("ED_CI_OFFLINE", "1")
    monkeypatch.setenv("SCHWAB_API_KEY", "test")
    from tools import check_live_schwab_env as mod

    assert mod.main(["--bat-unsets"]) == 0
    out = capsys.readouterr().out
    assert "set ED_CI_OFFLINE=\n" in out
    assert "set SCHWAB_API_KEY=\n" in out
