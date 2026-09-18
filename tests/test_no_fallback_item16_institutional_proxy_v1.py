"""No-fallback item 16: `_compute_institutional_flow_proxy`'s `book_imbalance_5` parameter
used to conflate two different facts under one `None` value -- "the caller never had a
canonical value to pass" (the standalone/test usage its fallback exists for) and "the
engine's canonical compute_book_microstructure ran and the imbalance genuinely IS
unavailable" (e.g. no book). Both collapsed into the same `is not None` check, so when the
main engine explicitly passed `book_imbalance_5=None` because the canonical answer was
unavailable, this function silently recomputed a DIFFERENT, independent answer from the
same raw `data` instead of propagating the canonical unavailability.

A sentinel now distinguishes "not supplied" from "supplied as None": only the former
triggers the standalone fallback recomputation.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.options.order_flow.engine as ofe


def _book_snapshot() -> dict:
    # A genuinely computable book -- if this function ever falls back to recomputing from
    # raw `data`, this fixture produces a REAL, non-None imbalance, making the mutation
    # visible rather than accidentally matching by both sides being None.
    return {
        "BIDS": [{"BID_PRICE": 100.0, "TOTAL_VOLUME": 1000}],
        "ASKS": [{"ASK_PRICE": 100.5, "TOTAL_VOLUME": 100}],
        "BOOK_TIME": 1787233769563,
    }


def _data() -> dict:
    return {"content": [_book_snapshot()], "exchange_quote_ts": 1787233769.0}


def test_not_supplied_falls_back_to_the_canonical_helper():
    """Standalone usage (no canonical value available to pass at all) still computes a
    real answer via the SAME canonical helper -- this is the legitimate default case."""
    data = _data()
    direct = ofe._compute_book_imbalance(data, ofe.OF_BOOK_DEPTH_DEEP)
    assert direct is not None, "fixture must produce a real imbalance for this test to prove anything"

    # book_imb (== direct) is the only present component for this fixture (no tape/options
    # signal), so the result must equal it exactly.
    only_book = ofe._compute_institutional_flow_proxy(data)
    assert only_book is not None
    assert abs(only_book - direct) < 1e-9, (
        "the standalone fallback must equal the SAME canonical helper's own answer, "
        f"got {only_book} vs canonical {direct}")


def test_explicit_none_from_the_engine_propagates_never_recomputes():
    """MUTATION CONTROL: the main engine explicitly passes book_imbalance_5=None when its
    own canonical compute_book_microstructure says the imbalance is unavailable. This
    function must NOT then independently recompute a different answer from raw `data` --
    that would silently disagree with the engine's own canonical verdict using the exact
    same book data this test's fixture makes non-trivially computable."""
    data = _data()   # genuinely contains a computable book -- content otherwise carries no
    # tape/options-flow signal, so the book component is the ONLY thing that could make
    # the averaged result non-None. If this leaked into a fallback recomputation, the
    # result below would be a real number instead of None.
    direct = ofe._compute_book_imbalance(data, ofe.OF_BOOK_DEPTH_DEEP)
    assert direct is not None, "fixture must produce a real imbalance for this test to prove anything"

    result = ofe._compute_institutional_flow_proxy(data, book_imbalance_5=None)
    assert result is None, (
        "MUTATION CONTROL FAILED TO BITE: an explicit book_imbalance_5=None (the "
        f"engine's own canonical 'unavailable' verdict) must propagate as None, not "
        f"recompute a substitute from the same raw data -- got {result!r}")
