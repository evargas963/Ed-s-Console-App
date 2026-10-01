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
    _rec("CARRY", {"key": "CARRY", "BID_PRICE": 9.95, "ASK_PRICE": 10.05}, received_ts=now)
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
    with Schwab's quote time, the prior close and the volume with their receive times -- Schwab's
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
    # the bid and ask Schwab sent in this session, with their quote time (they stayed blank until the
    # first trade: PCG 12.16 / 12.21 at 04:00:00), live for the computations
    assert (first["bid"], first["ask"], first["ask_size"], first["quote_live"]) == (12.16, 12.21, 4100.0, True)
    assert first["quote_as_of"] == "Wed 09/30 03:00:00 AM CT"
    # the prior close as Schwab sent it overnight (12.18 at 01:30 ET, adjusted to 12.13 at 03:45 ET)
    assert (first["prior_close"], first["prior_close_as_of"]) == (12.13, "Wed 09/30 02:45 AM CT")
    # Schwab's post-roll volume 0, shown as 0 at the time it came; its 0 open, high and low make no candle
    assert (first["day"]["volume"], first["day"]["volume_as_of"], first["day"]["bar"]) == (
        0.0, "Wed 09/30 02:45 AM CT", None)
    assert first["day"]["unavailable"] == (
        "No daily candle: Schwab's OPEN_PRICE, HIGH_PRICE and LOW_PRICE are 0 (at Wed 09/30 12:30 AM CT)")
    traded = at(4, 0, 10, 30)          # its first trade
    assert (traded["spot"], traded["spot_state"], traded["chg_pct"], traded["day"]["volume"]) == (
        12.18, "live", 0.412201, 3.0)
    assert traded["closed_last"] is None and traded["chg_pct_as_of"] == "Wed 09/30 03:00 AM CT"
    # Schwab's own change of the first trade is against that prior close: 12.18 - 12.13 = NET_CHANGE 0.05
    assert traded["prior_close"] == 12.13 and traded["net_change"] == 0.05


def test_a_resent_old_trade_is_not_live_and_the_quote_is_judged_by_its_own_fields():
    """Schwab re-sends the prior day's last trade in a new session: MTA at 2026-09-30 04:36:39 ET
    re-sent LAST_PRICE 9.59 with TRADE_TIME_MILLIS Tuesday 19:52:55 ET. It is shown with Schwab's
    trade time, never as a live price (judged by the trade's time, not the message's receive
    time). The quote is live for computations only when its bid and ask themselves came in this
    session: at 04:00:00 Schwab sent a new bid, but the ask was still Tuesday's, so it is not live;
    from 04:00:01 both are this session's. Real MTA messages, 2026-09-29 19:45 ET to 2026-09-30
    04:40 ET, read-only from production stream_capture.db
    (tests/fixtures/real_mta_l1_overnight_2026_09_29_30.json); the heartbeat a stand-in."""
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

    assert at(4, 0, 0, 500000)["quote_live"] is False             # the bid this session's, the ask Tuesday's
    assert at(4, 0, 2)["quote_live"] is True                       # both this session's
    row = at(4, 40, 0)                                              # after the 04:36:39 re-send
    assert row["spot"] is None and row["spot_state"] == "unavailable"
    assert row["closed_last"] == {"price": 9.59, "spot_disp": "9.59", "as_of": "Tue 09/29 06:52 PM CT"}
    assert row["unavailable_reason"] is None


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
