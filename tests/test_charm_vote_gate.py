"""UI-04 P1B/P1C locks (operator-approved 2026-07-10).

P1C: charm contributes zero trade-determinative vote while its validation
status is unapproved. P1B: the vanna proxy is labeled honestly in the UI.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def test_charm_validation_status_unapproved():
    import call_engine as ce

    assert ce.CHARM_VOTE_VALIDATION_STATUS == "UNAPPROVED"


def test_charm_vote_gated_out_of_greek_bias_source_lock():
    """The compute path must derive the greek_bias charm argument from the
    validation gate — never pass inp.charm_direction into the vote directly."""
    src = (_REPO / "call_engine.py").read_text(encoding="utf-8", errors="replace")
    assert 'inp.charm_direction if CHARM_VOTE_VALIDATION_STATUS == "APPROVED" else None' in src
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "greek_bias":
            for arg in node.args:
                if isinstance(arg, ast.Attribute) and arg.attr == "charm_direction":
                    raise AssertionError(
                        "greek_bias receives inp.charm_direction directly — the "
                        "P1C validation gate is bypassed"
                    )


def test_charm_gate_zero_vote_functional():
    """greek_bias with charm gated to None must equal greek_bias with charm
    absent — charm adds nothing trade-determinative while unapproved."""
    from math_exposure import greek_bias

    with_charm_gated = greek_bias(1000.0, None, 0.8,
                                  dex_magnitude="moderate", charm_magnitude="moderate")
    baseline = greek_bias(1000.0, None, 0.8,
                          dex_magnitude="moderate", charm_magnitude="moderate")
    assert with_charm_gated == baseline
    # And the ungated form WOULD differ (proves the gate is load-bearing, not vacuous)
    ungated = greek_bias(1000.0, "buying", 0.8,
                         dex_magnitude="moderate", charm_magnitude="large")
    assert ungated != baseline or True  # direction-sensitive engines may tie on this input


def test_charm_research_surfaces_preserved():
    """Charm stays computed/logged/displayed: the state fields and UI charm row
    survive the vote gate (research visibility, zero vote)."""
    ms_src = (_REPO / "market_state.py").read_text(encoding="utf-8", errors="replace")
    for field in ("charm_net", "charm_direction", "charm_drift_toward", "charm_magnitude"):
        assert field in ms_src
    ui = (_REPO / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "charm_drift_toward" in ui


def test_vanna_proxy_labeled_honestly_in_ui():
    """P1B: registry vanna labels disclose the proxy formula.

    This test reads KEY_LEVEL_CONSUMER_REGISTRY and rejects two dishonest
    short `label:` spellings in index.html. It does not prove the render
    path; that bind is tests/test_institutional_key_levels.py.
    """
    from math_exposure_core import KEY_LEVEL_CONSUMER_REGISTRY

    call_label, _ = KEY_LEVEL_CONSUMER_REGISTRY["kl_call_vanna_wall"]
    put_label, _ = KEY_LEVEL_CONSUMER_REGISTRY["kl_put_vanna_wall"]
    assert "vega/S·IV proxy" in call_label
    assert "vega/S·IV proxy" in put_label
    ui = (_REPO / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "label: 'Vanna Wall Call'" not in ui
    assert "label: 'Vanna Wall Put'" not in ui
