"""No-fallback item 13: spread provenance used to collapse two independently-resolved bid
and ask sources into one hardcoded generic label ("schwab_bid_ask") instead of retaining
both. Fixed at three sites (live_market_plane.record_from_level_one_equity,
server._build_rest_fast_quote_payload, and order_flow.engine._compute_spread) to compose
the label FROM the actual bid/ask source facts already resolved at each site.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.options.order_flow.engine as ofe


def test_compute_spread_retains_both_bid_and_ask_leaves_when_they_differ():
    """MUTATION CONTROL: bid and ask resolved from DIFFERENT tiers (bid from the streaming
    book, ask from a REST quote) -- the old `bid_leaf or ask_leaf or 'schwab_bid_ask'`
    picked only bid_leaf, silently discarding that ask came from a different source."""
    data = {
        "content": [
            {
                "BIDS": [{"BID_PRICE": 10.0, "TOTAL_VOLUME": 5}],
                # Truthy (so _latest_book_snapshot treats this as a real snapshot) but an
                # invalid price -> _sorted_valid_levels filters it out, so the ASK side
                # falls through to the REST quote tier below instead of the book.
                "ASKS": [{"ASK_PRICE": -1.0, "TOTAL_VOLUME": 5}],
                "BOOK_TIME": 1,
            },
        ],
        "quote": {"askPrice": 10.5},
    }
    spread = ofe._compute_spread(data)
    assert spread["spread_bid_leaf"] == "streaming.BOOK.BID_PRICE"
    assert spread["spread_ask_leaf"] == "quotes.quote.askPrice"
    assert spread["spread_pts_source"] == "derived_bid_ask_pts_streaming.BOOK.BID_PRICE+quotes.quote.askPrice", (
        "MUTATION CONTROL FAILED TO BITE: spread_pts_source must retain BOTH leaves, not "
        f"silently pick one -- got {spread['spread_pts_source']!r}")


def test_compute_spread_no_generic_fallback_label_survives():
    data = {
        "content": [
            {"BIDS": [{"BID_PRICE": 10.0, "TOTAL_VOLUME": 5}],
             "ASKS": [{"ASK_PRICE": 10.5, "TOTAL_VOLUME": 3}], "BOOK_TIME": 1},
        ],
    }
    spread = ofe._compute_spread(data)
    assert "schwab_bid_ask" not in (spread["spread_pts_source"] or "")
