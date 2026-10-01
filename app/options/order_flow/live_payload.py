"""One option contract's book microstructure, from the console's live state."""
from __future__ import annotations

from typing import Any

from app.options.order_flow.engine import compute_book_microstructure
import live_market_plane as lmp
from app.options.order_flow.state import get_content_for_symbol, option_top


def options_live_payload(contract: str, now: float) -> dict[str, Any]:
    """The contract's book microstructure at `now`: the one producer
    (engine.compute_book_microstructure) on its live book and top of book."""
    top = option_top(contract) if lmp.feed_live_for(contract, "LEVELONE_OPTIONS", now) else None
    return dict(compute_book_microstructure(
        {"content": get_content_for_symbol(contract), "top": top,
         "book_live": lmp.book_is_live(contract, "OPTIONS_BOOK", now)},
        now_ts=now, ticker=contract))
