"""UI-04 P1B/P1C locks (operator-approved 2026-07-10).

P1C: charm contributes zero trade-determinative vote while its validation
status is unapproved. P1B: the vanna proxy is labeled honestly in the UI.
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent






def test_charm_gate_zero_vote_functional():
    """greek_bias with charm gated to None must equal greek_bias with charm
    absent — charm adds nothing trade-determinative while unapproved."""
    from math_exposure import greek_bias

    with_charm_gated = greek_bias(1000.0, None, 0.8,
                                  dex_magnitude="moderate", charm_magnitude="moderate")
    baseline = greek_bias(1000.0, None, 0.8,
                          dex_magnitude="moderate", charm_magnitude="moderate")
    assert with_charm_gated == baseline
    # And the ungated form WOULD differ (proves the gate is load-bearing, not vacuous).
    # TEST_SYSTEM_REHAB_V2: the original moderate/moderate inputs put the delta score
    # alone (0.7) already past GREEK_BIAS_THRESHOLD (0.5), so adding "buying"/large
    # charm (+0.5) never changed the bucket -- a real, silent tie, hidden behind an
    # `... or True` that would still pass even if the gate were deleted entirely.
    # dex_magnitude="small" keeps delta alone (0.3) below threshold so the added
    # charm score (+0.5) provably flips neutral -> bullish, a real, checked property.
    weak_baseline = greek_bias(1000.0, None, 0.8,
                                dex_magnitude="small", charm_magnitude="moderate")
    ungated = greek_bias(1000.0, "buying", 0.8,
                         dex_magnitude="small", charm_magnitude="large")
    assert ungated != weak_baseline, "ungated charm must be load-bearing, not vacuous"


def test_charm_research_surfaces_preserved():
    """Charm stays computed/logged: the state fields survive the vote gate (research
    visibility, zero vote). The UI half of this test (a charm-drift row in
    static/index.html) was retired here (/console cutover, operator directive
    2026-09-14) — the new console's Charm panel is an aggregate dealer-charm-by-strike
    bar chart (marked "WALLS ONLY"), a different presentation with no charm_drift_toward
    consumer at all (grepped static/js/*.js, zero matches). Flagged for the operator as a
    real, if minor, loss of research-visibility surface, not fixed here."""
    ms_src = (_REPO / "market_state.py").read_text(encoding="utf-8", errors="replace")
    for field in ("charm_net", "charm_direction", "charm_drift_toward", "charm_magnitude"):
        assert field in ms_src


# test_vanna_labeled_honestly_in_ui was retired here (/console cutover, operator directive
# 2026-09-14): P1B/RC-352's per-strike "Largest Vanna Strike (Call/Put)" labels and their
# exact-Black-Scholes-formula tooltip disclosure exist only in legacy static/index.html — the
# new console's Vanna panel is explicitly marked "AGG ONLY" (aggregate dollar vanna, not a
# per-strike level), so there is no per-strike vanna label left to hold to this honesty
# standard. Flagged for the operator: if/when a per-strike Vanna surface is rebuilt, it must
# repeat this exact discipline (name the real computation, never the retired vega/(S*IV) proxy
# wording) rather than silently regressing the labeling honesty this test enforced.
