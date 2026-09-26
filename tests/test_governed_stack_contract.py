"""governed_stack_contract: stack-health classification, MC-team fail-closed
authorization, and wall-clock-to-bars conversion must fail closed on a degraded or
malformed stack, never authorize a decision on incomplete inputs."""

import pytest







# ── BAR_MINUTES sizing alignment (minimal-guidance lane, 2026-07-08) ─────────








def test_default_horizon_removed_and_horizon_bars_required():
    """DEFAULT_HORIZON=13 was dead (every live caller passes horizon_bars) and
    misleading (commented '~1hr' under the 5-minute reading; 13 minutes under
    the aligned reading). Removed: a silent default cannot reintroduce a unit
    mistake — omitting horizon_bars is now a loud TypeError."""
    import inspect

    import monte_carlo

    assert not hasattr(monte_carlo, "DEFAULT_HORIZON")
    sig = inspect.signature(monte_carlo.simulate)
    assert sig.parameters["horizon_bars"].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        monte_carlo.simulate(spot=500.0, iv=0.2)  # no horizon_bars -> loud failure


















