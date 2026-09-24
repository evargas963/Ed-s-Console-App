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
    assert row["quote_source_detail"]["spread"] == "schwab_bid_ask"
    assert row["quote_source_detail"]["carried_forward"] is False


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
    """No fallbacks (operator rule 2026-09-23): TRADE_TIME_MILLIS is a different clock. With
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
    assert not lmp.quote_is_fresh(row) and not lmp.spot_is_fresh(row)


def test_a_carried_last_price_keeps_the_age_of_its_own_trade():
    t_trade = time.time() - 45.0
    _rec("CARRY", {"key": "CARRY", "LAST_PRICE": 10.0, "BID_PRICE": 9.9, "ASK_PRICE": 10.1},
         received_ts=t_trade)
    _rec("CARRY", {"key": "CARRY", "BID_PRICE": 9.95, "ASK_PRICE": 10.05})
    row = lmp.get_quote("CARRY")
    assert row["spot"] == 10.0
    assert row["quote_source_detail"]["carried_forward"] is True
    assert row["spot_received_ts"] == t_trade
    assert lmp.quote_is_fresh(row) and not lmp.spot_is_fresh(row)


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
    g0 = lmp.get_quote("TIMEDUP")["fast_generation_id"]

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
    assert row["fast_generation_id"] > g0
    assert row["exchange_quote_ts"] == 1_778_018_400.0


def test_record_from_level_one_does_not_carry_forward_missing_bid_ask():
    _rec("NOCARRY", {"key": "NOCARRY", "LAST_PRICE": 10.0, "BID_PRICE": 9.9, "ASK_PRICE": 10.1})

    ok = _rec(
        "NOCARRY",
        {"key": "NOCARRY", "LAST_PRICE": 11.0},
    )

    assert ok is True
    row = lmp.get_quote("NOCARRY")
    assert row is not None
    assert row["spot"] == 11.0
    assert row["bid"] is None
    assert row["ask"] is None
    assert row["spread"] is None
    assert row["spread_pts"] is None
    assert row["quote_source_detail"]["spread"] == "unavailable_missing_bid_or_ask"
    assert row["quote_source_detail"]["previous_bid_available"] is True
    assert row["quote_source_detail"]["carried_forward"] is False


def test_record_from_level_one_rejects_mark_as_current_spot():
    ok = _rec(
        "MARKONLY",
        {"key": "MARKONLY", "MARK": 20.95, "BID_PRICE": 20.9, "ASK_PRICE": 21.1},
    )

    assert ok is False
    assert lmp.get_quote("MARKONLY") is None


def test_record_from_level_one_rejects_midpoint_spot_fabrication():
    ok = _rec(
        "MIDONLY",
        {"key": "MIDONLY", "BID_PRICE": 30.0, "ASK_PRICE": 30.2},
    )

    assert ok is False
    assert lmp.get_quote("MIDONLY") is None


def test_record_from_level_one_skips_duplicate_sig():
    _rec(
        "AAA",
        {"key": "AAA", "LAST_PRICE": 50.0, "BID_PRICE": 49.9, "ASK_PRICE": 50.1},
    )
    g0 = lmp.get_quote("AAA")["fast_generation_id"]
    ok = _rec(
        "AAA",
        {"key": "AAA", "LAST_PRICE": 50.0, "BID_PRICE": 49.9, "ASK_PRICE": 50.1},
    )
    assert ok is False
    g1 = lmp.get_quote("AAA")["fast_generation_id"]
    assert g0 == g1


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
    assert row["quote_source_detail"]["spread"] == "unavailable_missing_bid_or_ask"


def test_next_fast_generation_monotonic():
    a = lmp.next_fast_generation("M")
    b = lmp.next_fast_generation("M")
    assert b > a


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
    assert _rec("RESTROW", {"key": "RESTROW", "BID_PRICE": 49.9}) is False
    assert lmp.get_quote("RESTROW")["quote_ingestion"] == "rest_fast_quote"   # untouched
    _rec("STREAMROW", {"key": "STREAMROW", "LAST_PRICE": 50.0})
    assert _rec("STREAMROW", {"key": "STREAMROW", "BID_PRICE": 49.9}) is True
    row = lmp.get_quote("STREAMROW")
    assert row["spot"] == 50.0 and row["quote_source_detail"]["carried_forward"] is True
