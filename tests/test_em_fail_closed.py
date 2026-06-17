"""DFR-008 / DFR-022: no synthetic 6.5h EM fallback in server KEY LEVELS path."""

from __future__ import annotations

from pathlib import Path


def test_server_fetch_state_has_no_synthetic_65_hour_em_fallback():
    source = Path("server.py").read_text(encoding="utf-8")
    assert "_fallback_hours = max(_hours_rem, 6.5)" not in source
    assert "MC_FALLBACK" not in source


def test_iv_em_requires_positive_hours_remaining():
    from math_volatility import compute_expected_move_iv

    em = compute_expected_move_iv(500.0, 25.0, 0.0)
    assert em.get("upper") is None
    assert em.get("lower") is None
    assert "session_hours_unavailable" in (em.get("error") or "")
