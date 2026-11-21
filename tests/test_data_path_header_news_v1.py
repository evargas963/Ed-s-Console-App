"""The header's news line, from Schwab's messages to the page's socket.

Real data: every NEWS_HEADLINE message Schwab sent in three stretches of 2026-11-20, as the
daemon recorded them (tests/fixtures/real_schwab_news_headlines_2026_11_20.json, read-only from
ed.db): five headlines for $SPX in two frames at 08:30:57 CT; 11:07 to 11:18 CT, ten languages,
one story id sent again with another headline, stories sent again long after their own times
(the stream had just reconnected) and headlines carrying HTML entities; and 12:41 to 12:48 CT, a
story sent and withdrawn six minutes later. The expected values are worked out here from those
messages, as sent.

tests/e2e/console-header.spec.js draws tests/e2e/fixtures/header_news.json, GENERATED here by the
program's own producers, never hand written. Regenerate (from the repo root, project .venv), then
Prettier, which sets a JSON file's layout:
  python -c "import tests.conftest, tests.test_data_path_header_news_v1 as t
  t.write_e2e_fixture()"
"""

from __future__ import annotations

import asyncio
import html
import json
from itertools import groupby
from pathlib import Path

import pytest

import time_et
from app.market_data.schwab.streaming import capture
from push import news as push_news
from state import news_store
from stream_spine import HealthRegistry, MessageBus, held_key
from tests.feed_live_helper import forget_news, news_on_the_bus

_FX = Path(__file__).resolve().parent / "fixtures"
_E2E = Path(__file__).resolve().parent / "e2e" / "fixtures" / "header_news.json"
_MSGS = json.loads(
    (_FX / "real_schwab_news_headlines_2026_11_20.json").read_text(encoding="utf-8")
)["messages"]
#: the three stretches: the open's five $SPX headlines, late morning, and the withdrawn story
_OPEN, _MORNING, _WITHDRAWN = _MSGS[:5], _MSGS[5:114], _MSGS[114:]
_ENGLISH = "en-US"
#: the Associated Press story Schwab sent under one id all day, its headline rewritten
_AP = "202611192217AP______FINANCE__c4c3f4878b12989347f8a930ed813dad"
_LEFT_OUT = (
    "English only, by Schwab's language field: {} messages in other languages and {} unreadable "
    "left out since the program started"
)


@pytest.fixture(autouse=True)
def _no_news_before_or_after():
    forget_news()
    yield
    forget_news()


def _take(messages: list[dict]) -> list[bool]:
    """Give the store each message as the daemon's follower does; what each one changed."""
    return [news_store.take(m["symbol"], m["item"], m["schwab_ts"]) for m in messages]


def _english(messages: list[dict]) -> list[dict]:
    return [m for m in messages if m["item"]["11"] == _ENGLISH and m["item"]["3"] != "D"]


def _expected_order(messages: list[dict]) -> list[str]:
    """Each English story's id, newest first by its newest message's own time, as sent."""
    newest: dict[str, int] = {}
    for m in _english(messages):
        newest[m["item"]["2"]] = m["item"]["1"]
    return sorted(newest, key=lambda i: -newest[i])


def test_each_story_is_held_once_with_its_newest_wording_and_every_symbol_it_came_under():
    """Fifteen stories from 114 messages: one per headline id, whatever came how often.

    Schwab sent the Associated Press story with one headline at 11:07 and another at 11:17,
    under one id, for three symbols: the line holds it once, with the later headline and the
    three symbols in the order they came.
    """
    sent = _OPEN + _MORNING
    _take(sent)
    held = news_store.stories()
    assert len(sent) == 114 and len(_english(sent)) == 30
    assert [s.headline_id for s in held] == _expected_order(sent) and len(held) == 15
    wordings = [m["item"]["4"] for m in sent if m["item"]["2"] == _AP]
    assert len(wordings) == 8 and len(set(wordings)) == 2 and wordings[0] != wordings[-1]
    ap = next(s for s in held if s.headline_id == _AP)
    assert (
        ap.headline
        == wordings[-1]
        == ("US stocks tumble, and the S&P 500 drops as the sell-off for AI stocks accelerates")
    )
    assert ap.symbols == ("NVDA", "SPCX", "AMD")
    update = next(s for s in held if s.headline.startswith("UPDATE 4-Anthropic"))
    assert update.symbols == ("META", "NVDA", "AMD", "SPCX", "AMZN")


def test_the_line_is_served_newest_first_by_each_storys_own_time_with_its_texts():
    """What the page is sent: each story's time, symbols, headline and source, as the line shows.

    Schwab sent the 10:10 to 10:35 stories again at 11:10:12, after the 11:08 story: each lands
    by its own time, not by when it came. A story of today shows its time alone; the Associated
    Press story, written the evening before, shows its whole label. Schwab's "S&amp;P" reads
    "S&P", and its "$SPX" is named as the screen names it.
    """
    sent = _OPEN + _MORNING
    _take(sent)
    now = sent[-1]["ts_recv"]
    assert time_et.ct_label(now) == "Fri 11/20 11:17 AM CT"
    served = push_news.news(now)
    items, held = served["items"], news_store.stories()
    assert [s.headline_id for s in held] == _expected_order(sent)
    assert [i["headline"] for i in items] == [s.headline for s in held], "served in the held order"
    assert [i["time_ct"] for i in items] == [
        "11:15 AM CT",
        "11:11 AM CT",
        "11:08 AM CT",
        "11:00 AM CT",
        "10:35 AM CT",
        "10:32 AM CT",
        "10:25 AM CT",
        "10:15 AM CT",
        "10:10 AM CT",
        *["08:30 AM CT"] * 5,
        "Thu 11/19 09:17 PM CT",
    ]
    received = [m["item"]["2"] for m in _english(sent)]
    assert received.index(held[4].headline_id) > received.index(held[2].headline_id), (
        "it came later"
    )
    assert held[0].headline_id == "tag_reuters_com_2026_newsml_L2N4710OR"
    assert items[0] == {
        "time_ct": "11:15 AM CT",
        "symbols_text": "TSLA",
        "headline": "Tesla proposes $3.1 bln Texas polysilicon plant for solar manufacturing",
        "source": "Reuters",
    }
    assert (items[-1]["symbols_text"], items[-1]["source"]) == (
        "NVDA · SPCX · AMD",
        "Associated Press",
    )
    assert items[2]["symbols_text"] == "SPX"
    as_sent = [m["item"]["4"] for m in sent if m["symbol"] == "SPY"]
    assert as_sent == [
        "S&amp;P 500 slips into correction territory, with 10% drawdown from October 6 closing high"
    ]
    assert items[3]["headline"] == html.unescape(as_sent[0]) and "&amp;" not in items[3]["headline"]
    assert served["left_out"] == _LEFT_OUT.format(84, 0)


def test_only_english_is_shown_by_schwabs_own_field_and_the_rest_is_counted():
    """Ten languages arrived; the line holds the English stories and counts the other messages."""
    sent = _OPEN + _MORNING
    _take(sent)
    languages = {m["item"]["11"] for m in sent}
    assert len(languages) == 10 and _ENGLISH in languages
    others = [m for m in sent if m["item"]["11"] != _ENGLISH]
    assert news_store.left_out() == news_store.LeftOut(other_languages=len(others), unreadable=0)
    assert len(others) == 84
    english_ids = {m["item"]["2"] for m in _english(sent)}
    assert {s.headline_id for s in news_store.stories()} == english_ids
    assert not english_ids & {m["item"]["2"] for m in others}


def test_a_story_schwab_withdraws_leaves_the_line():
    """Sent at 12:41:21 CT with status A, withdrawn at 12:47:22 with status D, a corrected story
    in the same frame: the first story is the line's newest, then gone, the corrected one first.
    """
    _take(_OPEN + _MORNING)
    first, last = _WITHDRAWN[0], _WITHDRAWN[-1]
    assert (first["item"]["3"], last["item"]["3"]) == ("A", "D")
    assert first["item"]["2"] == last["item"]["2"] and last["item"]["11"] == _ENGLISH
    assert _take([first]) == [True]
    assert news_store.stories()[0].headline_id == first["item"]["2"]
    changed = _take(_WITHDRAWN[1:])
    assert changed[-1] is True
    held = news_store.stories()
    assert first["item"]["2"] not in {s.headline_id for s in held}
    assert held[0].headline.startswith("CORRECTED-US SENATOR TIM SCOTT'S AIDE")
    assert _take([last]) == [False], "a withdrawal of a story not held changes nothing"
    assert news_store.left_out().other_languages == 85


def test_a_message_arriving_twice_changes_nothing_and_an_older_frame_never_rewords_a_newer():
    """Every message of the morning given again changes no story (INDUCED: the second arrival).

    The store takes the newest wording by Schwab's frame time (docs/DATA_FLOW.md §2 D1): the
    Associated Press story's 11:07 message, given after its 11:17 one, adds its symbol and leaves
    the headline.
    """
    sent = _OPEN + _MORNING
    _take(sent)
    before = news_store.stories()
    assert not any(_take(sent))
    assert news_store.stories() == before
    forget_news()
    ap = [m for m in sent if m["item"]["2"] == _AP]
    newer, older = ap[-1], ap[0]
    assert older["schwab_ts"] < newer["schwab_ts"] and older["symbol"] != newer["symbol"]
    assert _take([newer, older]) == [True, True]
    (held,) = news_store.stories()
    assert held.headline == newer["item"]["4"] and held.symbols == ("AMD", "NVDA")


def test_the_line_holds_the_newest_fifteen_and_lets_the_oldest_go():
    """A sixteenth story takes the place of the oldest by its own time.

    The 12:41 story arrives with fifteen held: the Associated Press story, of the evening before,
    is let go. Schwab sending it again changes nothing while every story held is newer (INDUCED:
    the 11:17 message given again here; Schwab did send the story again that afternoon).
    """
    _take(_OPEN + _MORNING)
    assert news_store.STORIES_HELD == 15 and len(news_store.stories()) == 15
    assert news_store.stories()[-1].headline_id == _AP
    assert _take(_WITHDRAWN[:1]) == [True]
    held = news_store.stories()
    assert len(held) == 15 and _AP not in {s.headline_id for s in held}
    again = next(m for m in reversed(_MORNING) if m["item"]["2"] == _AP)
    assert _take([again]) == [False] and news_store.stories() == held


def test_no_story_received_serves_no_item_and_a_message_it_cannot_place_is_counted():
    """Before any message: no item (the page draws "-"). INDUCED: an English message with no
    headline (field 4 taken out of Schwab's own message) is counted and not held.
    """
    now = _OPEN[0]["ts_recv"]
    assert push_news.news(now) == {"items": [], "left_out": _LEFT_OUT.format(0, 0)}
    item = {k: v for k, v in _OPEN[0]["item"].items() if k != "4"}
    assert news_store.take("$SPX", item, _OPEN[0]["schwab_ts"]) is False
    assert news_store.stories() == []
    assert news_store.left_out() == news_store.LeftOut(other_languages=0, unreadable=1)


def _frames(messages: list[dict]) -> list[dict]:
    """The messages as Schwab framed them: one frame per frame time, its items in order."""
    return [
        {"timestamp": ts, "content": [m["item"] for m in group]}
        for ts, group in groupby(messages, key=lambda m: m["schwab_ts"])
    ]


def test_every_headline_reaches_the_line_though_the_bus_holds_one_record_per_symbol():
    """Schwab sent five headlines for $SPX in two frames within a quarter second.

    The bus keeps one current record per topic, so a reader of the newest alone would hold one
    of the five; the daemon's follower takes every message, and the line holds all five.
    """
    assert {m["symbol"] for m in _OPEN} == {"$SPX"} and len(_frames(_OPEN)) == 2

    async def go() -> list[news_store.Story]:
        bus, stop = MessageBus(), asyncio.Event()
        follower = asyncio.create_task(
            capture.Daemon(bus, HealthRegistry(), []).follow_market(stop)
        )
        # its readers subscribe before the first message, as in the program
        await asyncio.sleep(0.05)
        news_on_the_bus(bus, _OPEN)
        async with asyncio.timeout(5):
            while len(news_store.stories()) < 5:
                await asyncio.sleep(0.01)
        current = bus.current[held_key("NEWS_HEADLINE", "$SPX")][1]
        assert current["content"] == _OPEN[-1]["item"]
        stop.set()
        await asyncio.wait_for(follower, 5)
        return news_store.stories()

    held = asyncio.run(go())
    assert sorted(s.headline for s in held) == sorted(m["item"]["4"] for m in _OPEN)
    assert all(s.symbols == ("$SPX",) for s in held)


def build() -> dict:
    """Return the news the header test's socket sends: the line at three moments of the day.

    `morning`: after the open's and the morning's messages, at the last one's receive time;
    `story`: after the 12:41 story arrived; `withdrawn`: after Schwab withdrew it and sent the
    corrected one.
    """
    forget_news()
    try:
        _take(_OPEN + _MORNING)
        morning = push_news.news(_MORNING[-1]["ts_recv"])
        _take(_WITHDRAWN[:1])
        story = push_news.news(_WITHDRAWN[0]["ts_recv"])
        _take(_WITHDRAWN[1:])
        withdrawn = push_news.news(_WITHDRAWN[-1]["ts_recv"])
    finally:
        forget_news()
    return json.loads(json.dumps({"morning": morning, "story": story, "withdrawn": withdrawn}))


def write_e2e_fixture() -> None:
    """Regeneration utility (never called by a test): what the producers serve, to the fixture."""
    _E2E.write_text(
        json.dumps(build(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_the_header_tests_news_is_the_programs_own_for_schwabs_messages():
    """What the header test draws is the program's own, every key and value."""
    served = build()
    assert json.loads(_E2E.read_text(encoding="utf-8")) == served, (
        "E2E fixture drifted from the program's producers; regenerate with write_e2e_fixture()"
    )
    assert len(served["morning"]["items"]) == 15
    assert served["story"]["items"][0]["headline"].startswith("US SENATOR TIM SCOTT SAYS")
    assert served["story"]["items"][0]["headline"] not in {
        i["headline"] for i in served["withdrawn"]["items"]
    }
