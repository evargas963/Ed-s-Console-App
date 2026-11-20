"""The chart's newest bar moves with every trade until Schwab's own bar for its minute arrives.

Real data, read-only from production's data/ed.db: SPY's LEVELONE_EQUITIES messages received
2026-11-19 10:00:30-10:05:10 ET and its CHART_EQUITY bars received 09:56:00-10:05:10, in receive
order (tests/fixtures/real_spy_forming_minutes_2026_11_19.json), each taken by the program's own
intake: the price row (live_market_plane.record_from_level_one_equity) and the bar writer
(server._write_streamed_bar). SPY's pushed day fields of 2026-11-10
(tests/fixtures/real_spy_day_fields_and_daily_candles_2026_11_10.json) for the daily bar.
Every expected bar is worked out here from the raw messages: each minute's trades are the
messages whose held TRADE_TIME_MILLIS falls in it, the bar the held LAST_PRICE at its first and
last of them and the extremes between, its volume the held TOTAL_VOLUME at its last less at the
message before its first. INDUCED, each named where it is set: a LAST_PRICE not a number, a
TOTAL_VOLUME lower than held.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import live_market_plane as lmp
import server
from app.market_data.schwab.streaming.live_ui import Asked
from feed.connection import CHART_FIELDS
from push import bars as push_bars
from state import bar_store
from time_et import ET, ct_label

TK = "SPY"
_FX = Path(__file__).resolve().parent / "fixtures"
_MSGS: list[dict[str, Any]] = json.loads(
    (_FX / "real_spy_forming_minutes_2026_11_19.json").read_text(encoding="utf-8")
)["messages"]
#: the browser test's frames (tests/e2e/console-forming-bar.spec.js), the server's own answers
_E2E = Path(__file__).resolve().parent / "e2e" / "fixtures" / "forming_spy_2026_11_19.json"


def _at(h: int, m: int, s: float = 0) -> float:
    return datetime(2026, 11, 19, h, m, int(s), int(s % 1 * 1e6), tzinfo=ET).timestamp()


def _take(msg: dict[str, Any]) -> None:
    """Take one fixture message through the program's own intake."""
    n = msg["native"]
    if msg["service"] == "CHART_EQUITY":
        server._write_streamed_bar({"symbol": TK, **{v: n.get(k) for k, v in CHART_FIELDS.items()}})
    else:
        lmp.record_from_level_one_equity(TK, n, received_ts=msg["ts_recv"])


def _replay(until: float, since: float = 0.0) -> None:
    for msg in _MSGS:
        if since < msg["ts_recv"] <= until:
            _take(msg)


def _held(until: float) -> list[dict[str, Any]]:
    """Each LEVELONE message to `until` with the fields held after it: price, trade time, volume."""
    held: dict[str, Any] = {}
    out = []
    for msg in _MSGS:
        if msg["ts_recv"] > until or msg["service"] != "LEVELONE_EQUITIES":
            continue
        for f in ("LAST_PRICE", "TRADE_TIME_MILLIS", "TOTAL_VOLUME"):
            if f in msg["native"]:
                held[f] = msg["native"][f]
        out.append(dict(held))
    return out


def _expected(until: float) -> dict[float, dict[str, Any]]:
    """Every minute's bar from the trades held to `until`, but the first minute seen."""
    rows = [r for r in _held(until) if "LAST_PRICE" in r and "TRADE_TIME_MILLIS" in r]
    by_minute: dict[float, list[int]] = {}
    for i, r in enumerate(rows):
        by_minute.setdefault(r["TRADE_TIME_MILLIS"] // 60000 * 60.0, []).append(i)
    out = {}
    for minute, idx in list(by_minute.items())[1:]:
        prices = [rows[i]["LAST_PRICE"] for i in idx]
        out[minute] = {
            "t": minute,
            "o": prices[0],
            "h": max(prices),
            "l": min(prices),
            "c": prices[-1],
            "v": rows[idx[-1]]["TOTAL_VOLUME"] - rows[idx[0] - 1]["TOTAL_VOLUME"],
        }
    return out


def _schwab(minute: float) -> dict[str, Any]:
    """Schwab's CHART_EQUITY bar for `minute` as the fixture holds it."""
    n = next(
        m["native"]
        for m in _MSGS
        if m["service"] == "CHART_EQUITY" and m["native"]["CHART_TIME_MILLIS"] == minute * 1000
    )
    return {
        "t": minute,
        "o": n["OPEN_PRICE"],
        "h": n["HIGH_PRICE"],
        "l": n["LOW_PRICE"],
        "c": n["CLOSE_PRICE"],
        "v": n["VOLUME"],
    }


def _bar_arrived(minute: float) -> float:
    """When Schwab's bar for `minute` was received."""
    return next(
        m["ts_recv"]
        for m in _MSGS
        if m["service"] == "CHART_EQUITY" and m["native"]["CHART_TIME_MILLIS"] == minute * 1000
    )


def _first_trade_in(minute: float) -> float:
    """When the first message carrying a trade time in `minute` was received."""
    return next(
        m["ts_recv"]
        for m in _MSGS
        if m["service"] == "LEVELONE_EQUITIES"
        and "TRADE_TIME_MILLIS" in m["native"]
        and m["native"]["TRADE_TIME_MILLIS"] >= minute * 1000
    )


def _ohlcv(b: dict[str, Any]) -> tuple:
    return (b["t"], b["o"], b["h"], b["l"], b["c"], b["v"])


def _forming(now: float, tf: str = "1") -> dict[str, Any]:
    return push_bars.forming(TK, now, {"tf": tf})


M1, M2, M3, M4 = _at(10, 1), _at(10, 2), _at(10, 3), _at(10, 4)


def test_the_first_minute_seen_is_not_built():
    """Quotes start at 10:00:30: 10:00's earlier trades were not seen, so no bar is built for it.

    Until 10:01's first trade the panel serves no bar, never one opened mid-minute.
    """
    first_1001 = _first_trade_in(M1)
    _replay(first_1001 - 1e-6)
    assert _forming(first_1001)["bars"] == []
    _take(next(m for m in _MSGS if m["ts_recv"] == first_1001))
    assert [_ohlcv(b) for b in _forming(first_1001)["bars"]] == [_ohlcv(_expected(first_1001)[M1])]


def test_each_trade_inside_the_minute_moves_its_close_high_and_low():
    """Every message of 10:04 before Schwab's 10:04 bar: the served bar is its trades' bar so far.

    The minute's trades in this capture raise its high, lower its low and move its close.
    """
    end = _bar_arrived(M4)
    _replay(M4)
    moved = set()
    before = None
    for msg in _MSGS:
        if not M4 < msg["ts_recv"] < end or msg["service"] != "LEVELONE_EQUITIES":
            continue
        _take(msg)
        (bar,) = [b for b in _forming(msg["ts_recv"])["bars"] if b["t"] == M4] or [None]
        want = _expected(msg["ts_recv"]).get(M4)
        assert (bar and _ohlcv(bar)) == (want and _ohlcv(want))
        if before is not None and bar is not None:
            moved |= {k for k in "hlc" if bar[k] != before[k]}
        before = bar
    assert moved == {"h", "l", "c"}


def test_the_first_trade_of_a_new_minute_opens_a_new_bar_and_a_late_bar_replaces_its_own():
    """10:02's first trade opens its bar while 10:01's built bar stands: Schwab's came late.

    Schwab's 10:01 bar arrived at 10:02:02.6, after 10:02's first trades; once it arrives it is
    10:01's bar on the chart and the built one is dropped. The 10:02 bar goes on.
    """
    arrived = _bar_arrived(M1)
    first_1002 = _first_trade_in(M2)
    assert first_1002 < arrived  # the late bar, as captured
    _replay(first_1002)
    want = _expected(first_1002)
    served = _forming(first_1002)["bars"]
    assert [_ohlcv(b) for b in served] == [_ohlcv(want[M1]), _ohlcv(want[M2])]
    assert want[M2]["o"] == want[M2]["h"] == want[M2]["l"] == want[M2]["c"]
    _replay(arrived, first_1002)
    assert [_ohlcv(b) for b in _forming(arrived)["bars"]] == [_ohlcv(_expected(arrived)[M2])]
    newest = push_bars.bars(TK, arrived, {"tf": "1", "limit": 390})["bars"][-1]
    assert _ohlcv(newest) == _ohlcv(_schwab(M1))


def test_schwabs_bar_is_the_bar_once_it_arrives():
    """Schwab's 10:03 bar replaces the built one: the chart's 10:03 is Schwab's exactly.

    The built bar is what the stream showed (its trades, TOTAL_VOLUME's rise); Schwab's is the
    record. Both are worked out from the capture.
    """
    arrived = _bar_arrived(M3)
    _replay(arrived - 1e-6)
    built = {b["t"]: _ohlcv(b) for b in _forming(arrived)["bars"]}
    assert built[M3] == _ohlcv(_expected(arrived)[M3])
    _replay(arrived, arrived - 1e-6)
    assert M3 not in {b["t"] for b in _forming(arrived)["bars"]}
    bars = push_bars.bars(TK, arrived, {"tf": "1", "limit": 390})["bars"]
    assert _ohlcv(bars[-1]) == _ohlcv(_schwab(M3))


def test_a_message_without_a_trade_or_a_price_changes_nothing():
    """A quote-only message (no LAST_PRICE, no trade time, no volume) leaves the bar as it was.

    INDUCED (the capture holds none): 10:04:30's message with its bid and ask alone; and a
    LAST_PRICE sent not a number (-999), which clears the price row's price.
    """
    now = _at(10, 4, 30)
    _replay(now)
    before = _forming(now)
    assert before["bars"]
    sent = next(m["native"] for m in _MSGS if m["ts_recv"] > now)
    quote = {k: sent[k] for k in ("key", "BID_PRICE", "ASK_PRICE") if k in sent}
    assert lmp.record_from_level_one_equity(TK, quote, received_ts=now)
    assert _forming(now) == before
    lmp.record_from_level_one_equity(TK, {"key": TK, "LAST_PRICE": -999}, received_ts=now)
    assert lmp.get_quote(TK).spot is None
    assert _forming(now) == before


def test_a_stall_leaves_the_bar_as_it_was_with_its_last_trade_time():
    """No trade for a minute after 10:04:59: the bar stands, with its last trade's time."""
    end = _at(10, 4, 59)
    _replay(end)
    last_trade = _held(end)[-1]["TRADE_TIME_MILLIS"] / 1000
    now = _forming(end)
    later = _forming(end + 60)
    assert later == now
    assert later["trade_time_ct"] == ct_label(last_trade)
    assert _ohlcv(later["bars"][-1]) == _ohlcv(_expected(end)[M4])


def test_a_volume_lower_than_held_leaves_the_minute_s_volume_unknown():
    """INDUCED: TOTAL_VOLUME lower than held, as Schwab's zero at 7:28 ET (§3.1 field 8) is.

    The minute's volume is unknown ("-"), never a negative or a guess; its prices stand.
    """
    end = _at(10, 4, 59)
    _replay(end)
    (bar,) = [b for b in _forming(end)["bars"] if b["t"] == M4]
    assert bar["v"] == _expected(end)[M4]["v"] > 0
    lmp.record_from_level_one_equity(TK, {"key": TK, "TOTAL_VOLUME": 100}, received_ts=end)
    (bar,) = [b for b in _forming(end)["bars"] if b["t"] == M4]
    assert bar["v"] is None and bar["v_text"] is None
    assert _ohlcv(bar)[:5] == _ohlcv(_expected(end)[M4])[:5]


def test_a_five_minute_chart_s_forming_bar_is_its_minutes_rolled_up():
    """At 10:03:30 the 10:00 bar is Schwab's 10:00-10:02 bars and the built 10:03, rolled up.

    First open, highest high, lowest low, last close, the volumes added.
    """
    now = _at(10, 3, 30)
    _replay(now)
    minutes = [_schwab(M) for M in (_at(10, 0), M1, M2)] + [_expected(now)[M3]]
    (bar,) = _forming(now, "5")["bars"]
    assert _ohlcv(bar) == (
        _at(10, 0),
        minutes[0]["o"],
        max(m["h"] for m in minutes),
        min(m["l"] for m in minutes),
        minutes[-1]["c"],
        sum(m["v"] for m in minutes),
    )
    # the bars panel's 10:00 bar, without the built minute, is drawn over by it
    held = push_bars.bars(TK, now, {"tf": "5", "limit": 390})["bars"]
    assert held[-1]["t"] == bar["t"] and held[-1]["v"] == sum(m["v"] for m in minutes[:3])


_DAY = json.loads(
    (_FX / "real_spy_day_fields_and_daily_candles_2026_11_10.json").read_text(encoding="utf-8")
)


def test_the_daily_chart_s_forming_bar_is_today_s_pushed_candle():
    """The daily bar is today's candle as Schwab pushes it; none before the regular session.

    OPEN_PRICE, HIGH_PRICE, LOW_PRICE and REGULAR_MARKET_LAST_PRICE as last sent before 11:00.
    """
    early, now = datetime(2026, 11, 10, 8, 0, tzinfo=ET), datetime(2026, 11, 10, 11, 0, tzinfo=ET)
    held: dict[str, Any] = {}
    for q in _DAY["quotes"]:
        if q["ts_recv"] <= now.timestamp():
            lmp.record_from_level_one_equity(TK, q["native"], received_ts=q["ts_recv"])
            held.update(q["native"])
    assert _forming(early.timestamp(), "D")["bars"] == []
    (bar,) = _forming(now.timestamp(), "D")["bars"]
    assert (bar["o"], bar["h"], bar["l"], bar["c"]) == (
        held["OPEN_PRICE"],
        held["HIGH_PRICE"],
        held["LOW_PRICE"],
        held["REGULAR_MARKET_LAST_PRICE"],
    )
    assert bar["t"] == datetime(2026, 11, 10, 9, 30, tzinfo=ET).timestamp()


def test_the_page_s_socket_sends_the_forming_bars_with_each_price_row_and_each_new_bar():
    """The `forming` panel is the page's, sent again with each price row and each new bar.

    A new bar's panels go out in name order, so `forming` follows `bars` (live_ui._pump).
    """
    now = _at(10, 3, 30)
    _replay(now)
    asked = Asked(TK, now, {"tf": "5"})
    assert server.PAGE_PANELS["forming"](asked) == push_bars.forming(TK, now, {"tf": "5"})
    assert "forming" in server.PRICED_PANELS and "forming" in server.BARS_PANELS
    assert sorted(["forming:chart", "bars:chart"]) == ["bars:chart", "forming:chart"]


def build_e2e_frames() -> dict[str, Any]:
    """The browser test's frames: the 5-minute chart's bars and forming bars at three moments.

    10:04:30 (10:04 built over Schwab's 10:00-10:03), 10:04:59 (10:04's later trades) and
    10:05:10 (Schwab's 10:04 bar arrived; 10:05 built, a new 5-minute bar).
    """
    early, late, after = _at(10, 4, 30), _at(10, 4, 59), _MSGS[-1]["ts_recv"]
    params = {"tf": "5", "limit": 390}
    _replay(early)
    frames = {"bars": push_bars.bars(TK, early, params), "forming_early": _forming(early, "5")}
    _replay(late, early)
    frames["forming_late"] = _forming(late, "5")
    _replay(after, late)
    frames["bars_after"] = push_bars.bars(TK, after, params)
    frames["forming_after"] = _forming(after, "5")
    return frames


def write_e2e_frames() -> None:
    """Regeneration utility (never called by a test).

    python -c "import tests.conftest, tests.test_forming_bar_v1 as t; t.write_e2e_frames()"
    and then Prettier on the file (its JSON layout).
    """
    bar_store._bars.pop(TK, None)
    lmp._built.pop(TK, None)
    _E2E.write_text(json.dumps(build_e2e_frames(), indent=2) + "\n", encoding="utf-8")


def test_the_browser_test_s_frames_are_the_server_s_own():
    frames = build_e2e_frames()
    assert json.loads(_E2E.read_text(encoding="utf-8")) == json.loads(json.dumps(frames)), (
        "the browser test's file drifted from the server; regenerate with write_e2e_frames()"
    )
    # what the set is for: one bar redrawn as its trades come, then a new bar after Schwab's
    early, late = frames["forming_early"]["bars"][-1], frames["forming_late"]["bars"][-1]
    assert early["t"] == late["t"] == frames["bars"]["bars"][-1]["t"]
    assert early["c"] != late["c"]
    after = frames["forming_after"]["bars"]
    assert len(after) == 1 and after[0]["t"] > frames["bars_after"]["bars"][-1]["t"]
