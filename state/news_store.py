"""The header's news line: Schwab's NEWS_HEADLINE stories, each once, with its newest wording.

Schwab sends a story once for every subscribed symbol it concerns, and again under the same
headline id whenever its wording or its time changes; it withdraws one with status "D". Held here
are the newest STORIES_HELD English stories by the story's own time, each with the wording of its
newest message (by Schwab's frame time, docs/DATA_FLOW.md §2 D1) and every symbol it arrived
under, and the count of the messages left out since the program started. Fed with every news
message Schwab sends (capture.Daemon._took_news) and read by the header's news frame (push.news),
both on the program's loop. The Recorder keeps every message, whatever is held here (D4).

A message comes as Feed read it (NewsHeadline): its fields are read once, where the item arrives
(feed.connection.news_headline), and nowhere else.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, replace

#: the stories the header's news line carries: the newest by the story's own time
STORIES_HELD = 15
#: Schwab's language of an English story: the only English value it has sent
ENGLISH = "en-US"
#: Schwab's status of a story it withdraws
WITHDRAWN = "D"


@dataclass(frozen=True)
class NewsHeadline:
    """One NEWS_HEADLINE item as Schwab sent it for a symbol, read once by Feed.

    Each field as sent: None where Schwab sent none, or a value of another kind than the field's
    (AGENTS.md rule 2).
    """

    #: the story's own time, in milliseconds since the epoch
    story_ms: float | None
    headline_id: str | None
    #: "A"; WITHDRAWN when Schwab withdraws the story
    status: str | None
    headline: str | None
    source: str | None
    #: ENGLISH for an English story
    language: str | None


@dataclass(frozen=True)
class Story:
    """One story as the line shows it: its newest wording and every symbol it arrived under.

    `story_ts` is the story's own time (epoch seconds, NewsHeadline.story_ms); `schwab_ts`
    Schwab's frame time of the message its wording is from, None when that frame carried none.
    """

    headline_id: str
    story_ts: float
    headline: str
    source: str | None
    symbols: tuple[str, ...]
    schwab_ts: int | None


@dataclass(frozen=True)
class LeftOut:
    """The messages the line left out since the program started, by why.

    `other_languages`: a message whose language is not ENGLISH; `unreadable`: an English message
    without a headline id, a headline or a story time the line can place.
    """

    other_languages: int
    unreadable: int


#: headline id -> the story held
_stories: dict[str, Story] = {}
#: the messages left out since the program started, by why (LeftOut's fields)
_left_out = {"other_languages": 0, "unreadable": 0}


def take(symbol: str, sent: NewsHeadline, schwab_ts: int | None) -> bool:
    """Take one NEWS_HEADLINE message Schwab sent for `symbol`; return whether the line changed.

    A withdrawal removes the story it names, whatever its language. A message in another
    language, or one the line cannot place (no headline, id or time), is counted and left out.
    A story's first message adds it; a later one adds its symbol, and replaces the wording, time
    and source when its frame is not older than the frame the held wording came from (a message
    arriving twice changes nothing). The oldest stories past STORIES_HELD are let go, so a story
    older than every one held, when the line is full, is not taken.
    """
    story_id = sent.headline_id
    if sent.status == WITHDRAWN:
        return story_id is not None and _stories.pop(story_id, None) is not None
    if sent.language != ENGLISH:
        _left_out["other_languages"] += 1
        return False
    if story_id is None or not sent.headline or sent.story_ms is None:
        _left_out["unreadable"] += 1
        return False
    story = Story(
        headline_id=story_id,
        story_ts=sent.story_ms / 1000.0,
        headline=html.unescape(sent.headline),
        source=sent.source,
        symbols=(symbol,),
        schwab_ts=schwab_ts,
    )
    if story_id in _stories:
        held = _stories[story_id]
        symbols = held.symbols if symbol in held.symbols else (*held.symbols, symbol)
        older = schwab_ts is not None and held.schwab_ts is not None and schwab_ts < held.schwab_ts
        story = replace(held if older else story, symbols=symbols)
        if story == held:
            return False
    before = stories()
    _stories[story_id] = story
    for gone in sorted(_stories.values(), key=lambda s: s.story_ts, reverse=True)[STORIES_HELD:]:
        del _stories[gone.headline_id]
    return stories() != before


def stories() -> list[Story]:
    """Return the stories held, newest first by the story's own time."""
    return sorted(_stories.values(), key=lambda s: s.story_ts, reverse=True)


def left_out() -> LeftOut:
    """Return the count of the messages left out since the program started."""
    return LeftOut(**_left_out)
