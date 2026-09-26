"""Greek-vote magnitudes are never guessed (audit P0, 2026-09-23).

No producer computes a DEX magnitude, so it defaulted to "negligible" -- the Greeks vote's
net-delta leg never counted, silently. The Call also turned a missing magnitude into
"moderate", greek_bias scored any unknown label 0.7, and a missing net GEX was labelled
"negligible". Unknown now stays unknown and contributes nothing.
"""
from __future__ import annotations

import inspect







def test_no_default_magnitude_is_substituted_anywhere():
    import call_engine
    import market_state
    assert 'or "moderate"' not in inspect.getsource(call_engine)
    src = inspect.getsource(market_state)
    assert 'getattr(consensus_summary, "dex_magnitude"' not in src
    assert market_state.MarketState.__dataclass_fields__["dex_magnitude"].default is None
