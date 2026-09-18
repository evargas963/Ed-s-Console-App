"""RC-REHAB-1 (Phase 2) — server._stream_spot_and_of_regime's dead get_top_of_book import.

`app.options.order_flow.state` has never defined `get_top_of_book`. `from X import a, b`
fails atomically in Python, so importing it alongside the real `get_content_for_symbol`
raised ImportError on every call; the bare `except ImportError: return None, None` silently
swallowed it, making the ENTIRE function always return (None, None), every call, with no
error surfaced anywhere. Its only caller, `tick_triggers_coherent_refresh`
(`live_decision_bundle.py`), only acts on a non-None stream_spot/stream_of_regime, so this
silently disabled two real tick-trigger checks (stream spot moved; order-flow regime
changed) -- a genuinely broken import hiding behind a plausible-looking except clause.
"""
from __future__ import annotations

import server


def test_stream_spot_and_of_regime_no_longer_always_returns_none(monkeypatch):
    """Mutation test: with real streamed content present, stream_spot must resolve to the
    latest LAST_PRICE, not (None, None) -- proving the dead get_top_of_book import is gone
    and the raw-content fallback is actually reachable."""
    import app.options.order_flow.state as ofls

    ofls.clear_symbol("REHAB_STREAM_TICK")
    try:
        ofls.push_level_one("REHAB_STREAM_TICK", {"LAST_PRICE": 123.45}, ts_recv=1_000_000.0)
        spot, regime = server._stream_spot_and_of_regime("REHAB_STREAM_TICK")
        assert spot == 123.45, "a real streamed LAST_PRICE must resolve, not silently None"
    finally:
        ofls.clear_symbol("REHAB_STREAM_TICK")


def test_stream_spot_and_of_regime_returns_none_none_only_when_content_is_genuinely_absent():
    """The (None, None) fail-closed path must still work when there is truly no content for
    the symbol -- this is the ONE legitimate reason for that return value now, not a bug in
    the import."""
    import app.options.order_flow.state as ofls

    ofls.clear_symbol("REHAB_STREAM_TICK_EMPTY")
    try:
        spot, regime = server._stream_spot_and_of_regime("REHAB_STREAM_TICK_EMPTY")
        assert (spot, regime) == (None, None)
    finally:
        ofls.clear_symbol("REHAB_STREAM_TICK_EMPTY")


def test_get_top_of_book_does_not_exist_documenting_why_it_must_not_be_reimported():
    """Guards against the exact regression this rehab item fixed: if a future edit adds
    get_top_of_book back to state.py, this test should be revisited (it would then be safe
    to import) -- but as long as it does not exist, no code may import it, on pain of the
    same silent atomic-import failure this file exists to prevent."""
    import app.options.order_flow.state as ofls

    assert not hasattr(ofls, "get_top_of_book"), (
        "get_top_of_book now exists in state.py -- if server.py should use it, that is a "
        "deliberate design decision to make explicitly, not something to import back in "
        "silently under the assumption it always worked"
    )
