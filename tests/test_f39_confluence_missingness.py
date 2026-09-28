"""Index confluence retired: no weighted_push producer; /api/state keys stay withheld."""
from __future__ import annotations


def test_retired_roster_tables_are_gone():
    import market_context as mc

    for name in (
        "SPY_TOP",
        "QQQ_TOP",
        "IWM_TOP_HOLDINGS",
        "IWM_SECTORS",
        "_build_confluence",
        "_build_iwm_confluence",
        "weighted_push_from_constituents",
        "blend_iwm_weighted_push",
    ):
        assert not hasattr(mc, name), name
