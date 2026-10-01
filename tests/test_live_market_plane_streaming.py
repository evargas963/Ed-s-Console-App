"""live_market_plane: streaming Level One ingestion vs REST."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import time

import live_market_plane as lmp


def _rec(ticker, item, received_ts=None):
    """One streamed message, received now unless the test says when."""
    return lmp.record_from_level_one_equity(
        ticker, item, received_ts=time.time() if received_ts is None else received_ts)


def test_record_from_level_one_equity_updates_plane():
    _rec("ZZZ", {"key": "ZZZ", "LAST_PRICE": 1.0, "BID_PRICE": 0.9, "ASK_PRICE": 1.1})
    ok = _rec(
        "ZZZ",
        {"key": "ZZZ", "LAST_PRICE": 101.0, "BID_PRICE": 100.9, "ASK_PRICE": 101.1},
    )
    assert ok is True
    row = lmp.get_quote("ZZZ")
    assert row is not None
    assert row["quote_ingestion"] == "schwab_streaming_level_one"
    assert abs(row["spot"] - 101.0) < 1e-6
    assert row["quote_source_detail"]["spot"] == "LAST_PRICE"
    assert row["bid"] == 100.9 and row["ask"] == 101.1


def test_record_from_level_one_uses_schwab_quote_timestamp_for_fast_ts():
    ok = _rec(
        "TIMEAUTH",
        {
            "key": "TIMEAUTH",
            "LAST_PRICE": 101.0,
            "BID_PRICE": 100.9,
            "ASK_PRICE": 101.1,
            "QUOTE_TIME_MILLIS": 1_778_018_399_000,
        },
    )

    assert ok is True
    row = lmp.get_quote("TIMEAUTH")
    assert row is not None
    assert row["exchange_quote_ts"] == 1_778_018_399.0
    assert row["quote_time_source"] == "schwab_streaming_level_one"
    assert isinstance(row["server_received_ts"], float)
    # M6: exchange_quote_ts is the exchange QUOTE clock, and the row records WHICH clock —
    # never a silent quote/trade conflation. server_received_ts is the distinct wall clock.
    assert row["quote_source_detail"]["quote_ts"] == "QUOTE_TIME_MILLIS"
    assert row["exchange_quote_ts"] != row["server_received_ts"]


def test_record_from_level_one_never_uses_trade_time_as_the_quote_time():
    """TRADE_TIME_MILLIS is a different clock. With
    no QUOTE_TIME_MILLIS the quote time is unavailable -- never the trade time relabeled."""
    ok = _rec(
        "TRADEPROXY",
        {
            "key": "TRADEPROXY",
            "LAST_PRICE": 77.0,
            "BID_PRICE": 76.9,
            "ASK_PRICE": 77.1,
            "TRADE_TIME_MILLIS": 1_778_018_500_000,
            # no QUOTE_TIME_MILLIS
        },
    )
    assert ok is True
    row = lmp.get_quote("TRADEPROXY")
    assert row["exchange_quote_ts"] is None
    assert row["quote_source_detail"]["quote_ts"] == "unavailable"


def test_received_ts_is_required_and_is_what_freshness_judges():
    import inspect
    import pytest

    param = inspect.signature(lmp.record_from_level_one_equity).parameters["received_ts"]
    assert param.default is inspect.Parameter.empty, "no wall-clock default"
    with pytest.raises(TypeError):
        lmp.record_from_level_one_equity("RQD", {"key": "RQD", "LAST_PRICE": 1.0})
    old = time.time() - 100.0
    assert _rec("RQD", {"key": "RQD", "LAST_PRICE": 1.0}, received_ts=old)
    row = lmp.get_quote("RQD")
    assert row["server_received_ts"] == old and row["spot_received_ts"] == old
    assert not lmp.quote_is_fresh(row, time.time()) and not lmp.spot_is_fresh(row, time.time())


def test_a_carried_last_price_keeps_the_age_of_its_own_trade():
    """The unchanged LAST_PRICE keeps its own trade's time (information) and is live exactly
    while the feed is live for the symbol -- never judged by how long ago it arrived."""
    from tests.feed_live_helper import SESSION_NOW, mark_feed_down, mark_feed_live
    now = SESSION_NOW                     # judged in session, 45 s after the trade
    t_trade = now - 45.0
    _rec("CARRY", {"key": "CARRY", "LAST_PRICE": 10.0, "BID_PRICE": 9.9, "ASK_PRICE": 10.1},
         received_ts=t_trade)
    _rec("CARRY", {"key": "CARRY", "BID_PRICE": 9.95, "ASK_PRICE": 10.05, "BID_TIME_MILLIS": now * 1000,
                   "ASK_TIME_MILLIS": now * 1000}, received_ts=now)
    row = lmp.get_quote("CARRY")
    assert row["spot"] == 10.0
    assert row["spot_received_ts"] == t_trade
    assert not lmp.quote_is_fresh(row, now) and not lmp.spot_is_fresh(row, now)   # no heartbeat yet
    mark_feed_live("CARRY", now=now)
    assert lmp.quote_is_fresh(row, now) and lmp.spot_is_fresh(row, now)           # quiet, and live
    mark_feed_live("OTHER", now=now)
    assert not lmp.spot_is_fresh(row, now)                                         # not held
    mark_feed_down()
    assert not lmp.spot_is_fresh(row, now)


def test_record_from_level_one_new_schwab_timestamp_not_suppressed_as_duplicate():
    _rec(
        "TIMEDUP",
        {
            "key": "TIMEDUP",
            "LAST_PRICE": 50.0,
            "BID_PRICE": 49.9,
            "ASK_PRICE": 50.1,
            "QUOTE_TIME_MILLIS": 1_778_018_399_000,
        },
    )

    ok = _rec(
        "TIMEDUP",
        {
            "key": "TIMEDUP",
            "LAST_PRICE": 50.0,
            "BID_PRICE": 49.9,
            "ASK_PRICE": 50.1,
            "QUOTE_TIME_MILLIS": 1_778_018_400_000,
        },
    )

    assert ok is True
    row = lmp.get_quote("TIMEDUP")
    assert row["exchange_quote_ts"] == 1_778_018_400.0


def test_unchanged_bid_ask_stand_with_their_own_age():
    """Schwab LEVELONE sends only CHANGED fields (measured 2026-09-24 on 4,039 captured
    messages: 11% carried bid+ask+last together, 17% ask-only, 15% bid-only). A message with
    no BID_PRICE means the bid is unchanged -- it used to blank the bid and ask."""
    t0 = time.time() - 5.0
    _rec("NOCARRY", {"key": "NOCARRY", "LAST_PRICE": 10.0, "BID_PRICE": 9.9, "ASK_PRICE": 10.1},
         received_ts=t0)
    assert _rec("NOCARRY", {"key": "NOCARRY", "LAST_PRICE": 11.0}) is True
    row = lmp.get_quote("NOCARRY")
    assert row["spot"] == 11.0 and row["bid"] == 9.9 and row["ask"] == 10.1
    assert row["spot_received_ts"] > t0


def test_a_zero_price_is_taken_as_sent():
    """A price Schwab reports as 0 is 0."""
    _rec("ZRO", {"key": "ZRO", "LAST_PRICE": 10.0, "BID_PRICE": 9.9, "ASK_PRICE": 10.1})
    _rec("ZRO", {"key": "ZRO", "BID_PRICE": 0})
    row = lmp.get_quote("ZRO")
    assert row["bid"] == 0.0 and row["ask"] == 10.1


def test_a_value_that_is_not_a_number_clears_the_field():
    """A Schwab field sent as -999 or text is not a number."""
    for bad in (-999, "9.9"):
        _rec("CLR", {"key": "CLR", "LAST_PRICE": 10.0, "BID_PRICE": 9.9, "ASK_PRICE": 10.1})
        _rec("CLR", {"key": "CLR", "BID_PRICE": bad})
        row = lmp.get_quote("CLR")
        assert row["bid"] is None and row["ask"] == 10.1, bad

def test_a_new_session_shows_the_last_ones_values_with_their_times_until_schwab_sends_new_ones():
    """The daemon runs for days: at 04:00 ET yesterday's last price read LIVE (measured: PCG 12.14
    from 19:56 ET, 'live' at 04:00:05). What Schwab sent is shown, whatever the hour, with the
    time Schwab sent it, never as a live price (operator 2026-10-01: "we use what schwab gives us
    and we display it, regardless of the time. if we have it we display it"; display what Schwab
    sent with the time Schwab sent it): the last trade with Schwab's trade time, the bid and ask
    with Schwab's own times of each, the change percents and the volume with their Schwab time
    fields (live_market_plane.VALUE_TIME), the prior close with its receive time (Schwab sends
    none for it), each exactly as sent -- Schwab's
    post-roll volume 0 as 0, at the time it came. Real PCG messages, 2026-09-29 19:55 ET to
    2026-09-30 04:01 ET, including Schwab's overnight snapshots and day roll. Stand-in (named):
    the daemon's heartbeat, live and holding PCG at each instant judged."""
    import json
    from datetime import datetime

    import live_price_rows
    from time_et import ET
    fx = json.loads((ROOT / "tests" / "fixtures" / "real_pcg_l1_session_roll_2026_09_29_30.json")
                    .read_text(encoding="utf-8"))["messages"]
    with lmp._lock:
        lmp._by_ticker.pop("PCG", None)
        lmp._fields_by_ticker.pop("PCG", None)

    def at(h, m, s, day):
        now = datetime(2026, 9, day, h, m, s, tzinfo=ET).timestamp()
        for msg in [x for x in fx if x["ts_recv"] <= now and not x.get("_done")]:
            lmp.record_from_level_one_equity("PCG", msg["content"], received_ts=msg["ts_recv"])
            msg["_done"] = True
        lmp.record_feed_heartbeat({"schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": ["PCG"]}}, now)
        return live_price_rows.price_row("PCG", now)

    evening = at(19, 59, 0, 29)
    assert (evening["spot"], evening["spot_state"], evening["chg_pct"]) == (12.14, "live", 1.589958)
    first = at(4, 0, 5, 30)            # a new session: Schwab has sent a bid and ask, no trade yet
    # no live price: yesterday's last trade is shown with Schwab's trade time
    assert (first["spot"], first["spot_state"]) == (None, "unavailable")
    assert first["closed_last"] == {"price": 12.14, "spot_disp": "12.14", "as_of": "Tue 09/29 06:56 PM CT"}
    # the bid and ask Schwab sent in this session, exactly as sent, each with Schwab's own time of it
    # (BID_TIME_MILLIS 1790755200036, ASK_TIME_MILLIS 1790755200161: 04:00:00 ET), live for the
    # computations
    assert (first["bid"], first["ask"], first["ask_size"], first["quote_live"]) == (12.16, 12.21, 4100.0, True)
    assert (first["bid_text"], first["ask_text"], first["ask_size_text"]) == ("12.16", "12.21", "4,100")
    assert first["bid_as_of"] == first["ask_as_of"] == "as of Wed 09/30 03:00:00 AM CT"
    # the prior close as Schwab sent it overnight (12.18 at 01:30 ET, adjusted to 12.13 at 03:45 ET),
    # with our receive time, said so (Schwab sends no time for it)
    assert (first["prior_close_text"], first["prior_close_as_of"]) == ("12.13", "received Wed 09/30 02:45 AM CT")
    # Schwab's post-roll volume 0 (03:45:01 ET) and 0 open, high and low (01:30:10 ET) came without
    # their time fields (TRADE_TIME_MILLIS, REGULAR_MARKET_TRADE_MILLIS): each with the time it was
    # received, never with the field's value from another message (it read as Tuesday's volume 0)
    assert (first["day"]["volume_text"], first["day"]["volume_as_of"], first["day"]["bar"]) == (
        "0", "received Wed 09/30 02:45 AM CT", None)
    assert first["day"]["unavailable"] == (
        "No daily candle: Schwab's OPEN_PRICE, HIGH_PRICE and LOW_PRICE are 0 (received Wed 09/30 12:30 AM CT)")
    traded = at(4, 0, 10, 30)          # its first trade
    assert (traded["spot"], traded["spot_state"], traded["chg_pct"], traded["day"]["volume"]) == (
        12.18, "live", 0.412201, 3.0)
    # each change percent exactly as sent, with its direction and its own Schwab time field:
    # NET_CHANGE_PERCENT with TRADE_TIME_MILLIS (this trade, 04:00:07 ET), REGULAR_MARKET_CHANGE_
    # PERCENT with REGULAR_MARKET_TRADE_MILLIS (Tuesday 19:00:00 ET)
    assert traded["closed_last"] is None
    assert (traded["chg_pct_text"], traded["chg_pct_sign"], traded["chg_pct_as_of"]) == (
        "+0.412201%", "pos", "as of Wed 09/30 03:00:07 AM CT")
    assert (traded["chg_pct_regular_text"], traded["chg_pct_regular_sign"], traded["chg_pct_regular_as_of"]) == (
        "+1.924686%", "pos", "as of Tue 09/29 06:00:00 PM CT")
    # Schwab's own change of the first trade is against that prior close: 12.18 - 12.13 = NET_CHANGE 0.05
    assert traded["prior_close"] == 12.13 and traded["net_change"] == 0.05


def test_a_resent_old_trade_is_not_live_and_the_quote_is_judged_by_its_own_fields():
    """Schwab re-sends the prior day's last trade in a new session: MTA at 2026-09-30 04:36:39 ET
    re-sent LAST_PRICE 9.59 with TRADE_TIME_MILLIS Tuesday 19:52:55 ET. It is shown with Schwab's
    trade time, never as a live price (judged by the trade's time, not the message's receive
    time). The quote is live for computations when Schwab's own times of its bid and its ask
    (BID_TIME_MILLIS, ASK_TIME_MILLIS) are this session's -- the times the screen shows them with,
    never our receive times: until the 04:00:00.101 message both were Tuesday's; that message
    carried a new bid only, yet Schwab stamped both BID_TIME_MILLIS and ASK_TIME_MILLIS
    1790755200042 (04:00:00.042 ET), so from then the quote is live (by the ask's receive time it
    read Tuesday's). Real MTA messages, 2026-09-29 19:45 ET to 2026-09-30 04:40 ET, read-only from
    production stream_capture.db (tests/fixtures/real_mta_l1_overnight_2026_09_29_30.json); the
    heartbeat a stand-in."""
    import json
    from datetime import datetime

    import live_price_rows
    from time_et import ET
    fx = json.loads((ROOT / "tests" / "fixtures" / "real_mta_l1_overnight_2026_09_29_30.json")
                    .read_text(encoding="utf-8"))["messages"]
    with lmp._lock:
        lmp._by_ticker.pop("MTA", None)
        lmp._fields_by_ticker.pop("MTA", None)

    def at(h, m, s, us=0):
        now = datetime(2026, 9, 30, h, m, s, us, tzinfo=ET).timestamp()
        for msg in [x for x in fx if x["ts_recv"] <= now and not x.get("_done")]:
            lmp.record_from_level_one_equity("MTA", msg["content"], received_ts=msg["ts_recv"])
            msg["_done"] = True
        lmp.record_feed_heartbeat({"schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": ["MTA"]}}, now)
        return live_price_rows.price_row("MTA", now)

    assert at(4, 0, 0, 50000)["quote_live"] is False               # Schwab's bid and ask times Tuesday's
    first = at(4, 0, 0, 500000)                                     # both stamped 04:00:00.042 by Schwab
    assert first["quote_live"] is True
    assert (first["bid_text"], first["bid_as_of"]) == ("8.7", "as of Wed 09/30 03:00:00 AM CT")
    assert (first["ask_text"], first["ask_as_of"]) == ("10.5", "as of Wed 09/30 03:00:00 AM CT")
    row = at(4, 40, 0)                                              # after the 04:36:39 re-send
    assert row["spot"] is None and row["spot_state"] == "unavailable"
    assert row["closed_last"] == {"price": 9.59, "spot_disp": "9.59", "as_of": "Tue 09/29 06:52 PM CT"}
    assert row["unavailable_reason"] is None
    # the browser tests paint this row as served (tests/e2e/fixtures/served_price_row_mta_2026_09_30_0440.json)
    served = json.loads((ROOT / "tests" / "e2e" / "fixtures" / "served_price_row_mta_2026_09_30_0440.json")
                        .read_text(encoding="utf-8"))
    assert {k: v for k, v in row.items() if k not in ("day", "server_ts")} == served


def test_each_bid_and_ask_carries_the_time_schwab_sent_with_it():
    """A bid or an ask is shown with, and judged by, the time Schwab sent with it, by which fields
    Schwab sends for the instrument (no ticker list): its BID_TIME_MILLIS / ASK_TIME_MILLIS; where a
    price comes without one, the same message's QUOTE_TIME_MILLIS; with neither, our receive time,
    said so. On 2026-09-30 09:30-10:00 ET 1,711 of $SPX's bid messages had no BID_TIME_MILLIS, so
    judged by it alone its quote read not live all session. Real messages, read-only from
    production stream_capture.db (tests/fixtures/real_l1_quote_times_2026_09_30.json); the
    heartbeat a stand-in."""
    import json
    from datetime import datetime

    import live_price_rows
    from time_et import ET
    fx = json.loads((ROOT / "tests" / "fixtures" / "real_l1_quote_times_2026_09_30.json")
                    .read_text(encoding="utf-8"))["symbols"]

    def at(sym, h, m, s, us=0):
        now = datetime(2026, 9, 30, h, m, s, us, tzinfo=ET).timestamp()
        with lmp._lock:
            lmp._by_ticker.pop(sym, None)
            lmp._fields_by_ticker.pop(sym, None)
        for msg in fx[sym]:
            if msg["ts_recv"] <= now:
                lmp.record_from_level_one_equity(sym, msg["content"], received_ts=msg["ts_recv"])
        lmp.record_feed_heartbeat({"schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": [sym]}}, now)
        return live_price_rows.price_row(sym, now)

    # $SPX, an index (Schwab's assetMainType INDEX): its full refreshes at 04:36:39 and 05:23:00 sent
    # BID_TIME_MILLIS and ASK_TIME_MILLIS 74996850 (20:49:56.850 as milliseconds of a day, not epoch
    # milliseconds) with QUOTE_TIME_MILLIS 1790714323636 (Tue 16:38:43.636 ET): the quote is as of
    # its QUOTE_TIME, Tuesday's, so not live -- never "as of 01/01/1970"
    for h, m in ((4, 37), (5, 24)):
        refreshed = at("$SPX", h, m, 0)
        assert (refreshed["bid_text"], refreshed["quote_live"]) == ("7,643.12", False)
        assert refreshed["bid_as_of"] == refreshed["ask_as_of"] == "as of Tue 09/29 03:38:43 PM CT"
    # $SPX: its 09:30:01 bid 7670.92 / ask 7714.41 came with QUOTE_TIME_MILLIS 1790775001065 and no
    # bid or ask time: live, as of that time
    spx = at("$SPX", 9, 30, 2)
    assert (spx["bid_text"], spx["ask_text"], spx["quote_live"]) == ("7,670.92", "7,714.41", True)
    assert spx["bid_as_of"] == spx["ask_as_of"] == "as of Wed 09/30 08:30:01 AM CT"
    # CRWD 09:53:26: a new bid 265.72 with QUOTE_TIME_MILLIS 1790776405731 (= its ASK_TIME_MILLIS)
    # and no BID_TIME_MILLIS: the bid is as of the message's QUOTE_TIME, not the held BID_TIME
    # (1790776405631, the previous bid 265.83's)
    crwd = at("CRWD", 9, 53, 27)
    assert (crwd["bid_text"], crwd["bid_as_of"]) == ("265.72", "as of Wed 09/30 08:53:25 AM CT")
    assert lmp.get_quote("CRWD")["bid_ts"] == 1790776405.731
    # RKLB 09:44:08: a new bid 71.85 with neither BID_TIME_MILLIS nor QUOTE_TIME_MILLIS (the held
    # ones, 1790775846820, are the previous bid 71.84's): Schwab sent no time for it, so it is
    # shown with our receive time, said so
    rklb = at("RKLB", 9, 44, 9)
    assert (rklb["bid_text"], rklb["bid_as_of"]) == ("71.85", "received Wed 09/30 08:44 AM CT")
    assert rklb["ask_as_of"] == "as of Wed 09/30 08:44:06 AM CT"   # the ask 71.89's own ASK_TIME


def _replay_value_times(sym, h, m, s=0):
    """`sym`'s real messages of tests/fixtures/real_l1_value_times_2026_09_30.json received by
    2026-09-30 h:m:s ET (read-only from production stream_capture.db), and its price row then; the
    heartbeat a stand-in."""
    import json
    from datetime import datetime

    import live_price_rows
    from time_et import ET
    fx = json.loads((ROOT / "tests" / "fixtures" / "real_l1_value_times_2026_09_30.json")
                    .read_text(encoding="utf-8"))["symbols"][sym]
    now = datetime(2026, 9, 30, h, m, s, tzinfo=ET).timestamp()
    with lmp._lock:
        lmp._by_ticker.pop(sym, None)
        lmp._fields_by_ticker.pop(sym, None)
    for msg in fx:
        if msg["ts_recv"] <= now:
            lmp.record_from_level_one_equity(sym, msg["content"], received_ts=msg["ts_recv"])
    lmp.record_feed_heartbeat({"schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": [sym]}}, now)
    return live_price_rows.price_row(sym, now)


def test_each_value_is_shown_with_the_schwab_time_field_that_belongs_to_it():
    """One table pairs each value with its Schwab time field (live_market_plane.VALUE_TIME): field
    35 TRADE_TIME_MILLIS for the last price, its size, the change and the volume; field 36
    REGULAR_MARKET_TRADE_MILLIS for the regular-session fields; the bid and ask their own (37, 38).
    SPY's 04:36:39 ET full refresh of 2026-09-30: LAST 766.289 with TRADE_TIME_MILLIS
    1790757398710 (04:36:38.710 ET, pre-market), the REG change -0.184167% with
    REGULAR_MARKET_TRADE_MILLIS 1790712000012 (Tue 20:00:00.012 ET), bid 766.25 with BID_TIME_MILLIS
    1790757398711, ask 766.29 with ASK_TIME_MILLIS 1790757398080."""
    row = _replay_value_times("SPY", 4, 37)
    assert (row["spot_disp"], row["trade_ts"]) == ("766.289", 1790757398.71)
    assert (row["chg_pct_text"], row["chg_pct_as_of"]) == ("+0.273358%", "as of Wed 09/30 03:36:38 AM CT")
    assert (row["chg_pct_regular_text"], row["chg_pct_regular_as_of"]) == (
        "-0.184167%", "as of Tue 09/29 07:00:00 PM CT")
    assert (row["last_size_text"], row["last_size_as_of"]) == ("0", "as of Wed 09/30 03:36:38 AM CT")
    assert row["day"]["volume_as_of"] == "as of Wed 09/30 03:36:38 AM CT"
    assert (row["bid_text"], row["bid_as_of"]) == ("766.25", "as of Wed 09/30 03:36:38 AM CT")
    assert lmp.get_quote("SPY")["ask_ts"] == 1790757398.08 and row["quote_text"] is None


def test_an_index_schwab_sends_no_bid_or_ask_for_says_so_and_its_price_has_its_trade_time():
    """$VIX: Schwab sends no bid or ask in session, only 0s on its overnight refreshes with every
    time field 0 (BID_TIME_MILLIS, ASK_TIME_MILLIS, QUOTE_TIME_MILLIS), which is no time -- never
    a 1969 date; the bid x ask place says so, not 0 x 0. Its price is shown with its
    TRADE_TIME_MILLIS. Real $VIX messages 2026-09-29 20:00 to 2026-09-30 04:40 ET."""
    row = _replay_value_times("$VIX", 4, 40)
    assert row["quote_text"] == "Schwab sends no bid/ask for this index"
    assert row["bid_as_of"] == row["ask_as_of"] == "Schwab sent no time for it"
    # 15.9 (sent last at 04:36:39), its trade time Schwab's latest TRADE_TIME_MILLIS 1790757586390
    # (04:39:46.390 ET), sent alone as the price stood
    assert (row["spot_disp"], row["spot_state"]) == ("15.9", "live")
    assert row["trade_ts"] == 1790757586.39


def test_a_price_with_no_trade_time_or_not_a_number_says_which():
    """With no price shown the reason said Schwab sent no trade even when it sent one without its
    trade time, or sent the price as not a number. Each says what Schwab sent. Stand-in quotes."""
    import live_price_rows
    from tests.feed_live_helper import SESSION_NOW
    _rec("NOTIME", {"key": "NOTIME", "LAST_PRICE": 10.0}, received_ts=SESSION_NOW)
    assert live_price_rows.price_row("NOTIME", SESSION_NOW)["unavailable_reason"] == (
        "Schwab sent LAST_PRICE without its trade time (TRADE_TIME_MILLIS)")
    _rec("NOTNUM", {"key": "NOTNUM", "LAST_PRICE": -999, "BID_PRICE": 9.9}, received_ts=SESSION_NOW)
    assert live_price_rows.price_row("NOTNUM", SESSION_NOW)["unavailable_reason"] == (
        "Schwab sent LAST_PRICE as a value that is not a number")


def test_record_from_level_one_rejects_mark_as_current_spot():
    """A quote with no trade publishes its row (its bid and ask are the session's quote; 2026-10-01:
    they stayed blank until the first trade), but MARK never stands in for the spot."""
    ok = _rec(
        "MARKONLY",
        {"key": "MARKONLY", "MARK": 20.95, "BID_PRICE": 20.9, "ASK_PRICE": 21.1},
    )

    assert ok is True
    row = lmp.get_quote("MARKONLY")
    assert row["spot"] is None and row["quote_source_detail"]["spot"] is None and row["spot_received_ts"] is None
    assert (row["bid"], row["ask"], row["mark"]) == (20.9, 21.1, 20.95)


def test_record_from_level_one_rejects_midpoint_spot_fabrication():
    ok = _rec(
        "MIDONLY",
        {"key": "MIDONLY", "BID_PRICE": 30.0, "ASK_PRICE": 30.2},
    )

    assert ok is True
    row = lmp.get_quote("MIDONLY")
    assert row["spot"] is None and (row["bid"], row["ask"]) == (30.0, 30.2)       # no midpoint spot


def test_a_resent_identical_last_price_refreshes_its_age():
    """A LAST_PRICE message is a trade report: the same price resent is a NEW trade at that
    price, so its age refreshes (it used to be suppressed as a duplicate, aging the spot)."""
    t0 = time.time() - 20.0
    _rec("AAA", {"key": "AAA", "LAST_PRICE": 50.0, "BID_PRICE": 49.9, "ASK_PRICE": 50.1},
         received_ts=t0)
    assert _rec("AAA", {"key": "AAA", "LAST_PRICE": 50.0}) is True
    assert lmp.get_quote("AAA")["spot_received_ts"] > t0

def test_record_from_level_one_ignores_non_canonical_bid_ask_keys():
    """Schwab streaming dictionary uses BID_PRICE/ASK_PRICE only — bare BID/ASK are not wire leaves."""
    ok = _rec(
        "NOCANON",
        {"key": "NOCANON", "LAST_PRICE": 100.0, "BID": 99.5, "ASK": 100.5},
    )
    assert ok is True
    row = lmp.get_quote("NOCANON")
    assert row is not None
    assert row["bid"] is None
    assert row["ask"] is None
    assert row["quote_source_detail"]["bid"] is None
    assert row["quote_source_detail"]["ask"] is None


def test_prior_close_is_the_streamed_close_price_and_stands_between_sends():
    _rec("PCLOSE", {"key": "PCLOSE", "LAST_PRICE": 10.0, "CLOSE_PRICE": 9.5})
    assert lmp.get_quote("PCLOSE")["prior_close"] == 9.5
    _rec("PCLOSE", {"key": "PCLOSE", "LAST_PRICE": 10.1})          # CLOSE_PRICE not resent
    assert lmp.get_quote("PCLOSE")["prior_close"] == 9.5
    _rec("NOCLOSE", {"key": "NOCLOSE", "LAST_PRICE": 5.0})
    assert lmp.get_quote("NOCLOSE")["prior_close"] is None          # never sent: unknown


def test_last_price_is_carried_forward_only_from_a_streamed_row():
    """Independent audit (2026-09-24): a bid/ask-only tick used to keep the prior row's
    LAST_PRICE whenever that row's spot was tagged LAST_PRICE -- even a REST-written row --
    and stamp the result schwab_streaming_level_one. Only a streamed LAST_PRICE may carry."""
    assert not hasattr(lmp, "record_quote"), "the plane has ONE writer: the stream"
    with lmp._lock:
        lmp._by_ticker["RESTROW"] = {
            "ticker": "RESTROW", "spot": 50.0, "quote_ingestion": "rest_fast_quote",
            "quote_source_detail": {"spot": "LAST_PRICE"},
        }
    assert _rec("RESTROW", {"key": "RESTROW", "BID_PRICE": 49.9}) is True
    rest = lmp.get_quote("RESTROW")                     # the stream's row: the REST spot never carried
    assert rest["spot"] is None and rest["bid"] == 49.9 and rest["quote_ingestion"] == "schwab_streaming_level_one"
    _rec("STREAMROW", {"key": "STREAMROW", "LAST_PRICE": 50.0})
    assert _rec("STREAMROW", {"key": "STREAMROW", "BID_PRICE": 49.9}) is True
    row = lmp.get_quote("STREAMROW")
    assert row["spot"] == 50.0 and row["bid"] == 49.9
