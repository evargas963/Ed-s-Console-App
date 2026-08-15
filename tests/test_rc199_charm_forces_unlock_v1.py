"""RC-199: operator revoked Chart charm vote-lock — forces + Chart must not say LOCKED."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_chart_has_no_charm_vote_lock_literals():
    src = (REPO / "static" / "chart.html").read_text(encoding="utf-8")
    assert "gated on vote" not in src
    assert "renders after the operator charm vote" not in src
    assert "renders after operator vote" not in src
    # Bias theater removed
    assert '">LOCKED</span>' not in src
    assert "Bias:" in src and "WAIT" in src
    # Charm walls default ON
    i = src.find("['charmw'")
    assert i > 0
    row = src[i : i + 140]
    assert "'on'" in row


def test_get_forces_docstring_serves_charm():
    src = (REPO / "server.py").read_text(encoding="utf-8")
    # Find get_forces block
    i = src.find("def get_forces")
    assert i > 0
    block = src[i : i + 4500]
    assert "charm_below" in block and "charm_above" in block
    assert "compute_charm_by_strike" in block
    assert "deliberately NOT served" not in block
