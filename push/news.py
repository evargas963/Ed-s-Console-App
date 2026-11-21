"""The header's news frame: Schwab's headlines as the line shows them, on every page."""

from __future__ import annotations

from typing import TypedDict

from instrument_identity import display_symbol
from numeric_contract import count_text
from state import news_store
from time_et import ct_dated


class NewsItem(TypedDict):
    """One story as the line draws it: each part a text, the source None when Schwab sent none."""

    time_ct: str
    symbols_text: str
    headline: str
    source: str | None


class NewsLine(TypedDict):
    """The header's news frame: the stories held, newest first, and what the line left out."""

    items: list[NewsItem]
    left_out: str


def news(now: float) -> NewsLine:
    """Return the header's news frame at `now`: the stories held, newest first.

    Each story of state.news_store (at most its STORIES_HELD): its own time as the line shows
    it (time_et.ct_dated: the time alone on today's Central day, the whole label on another),
    the display names of the symbols Schwab sent it under, the headline and its source.
    `left_out`: the line's rule and what it left out since the program started, the NEWS
    label's title. No story held: no item, and the page draws "-".
    """
    out = news_store.left_out()
    return {
        "items": [
            {
                "time_ct": ct_dated(s.story_ts, now),
                "symbols_text": " · ".join(display_symbol(k) for k in s.symbols),
                "headline": s.headline,
                "source": s.source,
            }
            for s in news_store.stories()
        ],
        "left_out": (
            f"English only, by Schwab's language field: {count_text(out.other_languages)} "
            f"messages in other languages and {count_text(out.unreadable)} unreadable left out "
            "since the program started"
        ),
    }
