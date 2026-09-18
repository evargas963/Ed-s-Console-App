"""live_market_plane: streaming Level One ingestion vs REST."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import live_market_plane as lmp


def test_record_from_level_one_equity_updates_plane():
    lmp.record_quote(
        "ZZZ",
        {
            "ticker": "ZZZ",
            "spot": 1.0,
            "bid": 0.9,
            "ask": 1.1,
            "spot_disp": "1.00",
            "bid_disp": "0.90",
            "ask_disp": "1.10",
            "spread": 0.2,
            "fast_generation_id": lmp.next_fast_generation("ZZZ"),
            "exchange_quote_ts": 100.0,
            "quote_ingestion": "rest_fast_quote",
        },
    )
    ok = lmp.record_from_level_one_equity(
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
    ok = lmp.record_from_level_one_equity(
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


def test_record_from_level_one_trade_time_fallback_is_labeled_proxy_not_silent():
    """M6: when QUOTE_TIME_MILLIS is absent, TRADE_TIME_MILLIS carries exchange_quote_ts but is
    stamped a labeled PROXY, so a trade-time value is never aged as a quote time unmarked."""
    ok = lmp.record_from_level_one_equity(
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
    assert row["exchange_quote_ts"] == 1_778_018_500.0
    assert row["quote_source_detail"]["quote_ts"] == "TRADE_TIME_MILLIS_proxy"


def test_record_from_level_one_new_schwab_timestamp_not_suppressed_as_duplicate():
    lmp.record_from_level_one_equity(
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

    ok = lmp.record_from_level_one_equity(
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
    lmp.record_quote(
        "NOCARRY",
        {
            "ticker": "NOCARRY",
            "spot": 10.0,
            "bid": 9.9,
            "ask": 10.1,
            "spot_disp": "10.00",
            "bid_disp": "9.90",
            "ask_disp": "10.10",
            "spread": 0.02,
            "fast_generation_id": lmp.next_fast_generation("NOCARRY"),
            "exchange_quote_ts": 100.0,
            "quote_ingestion": "rest_fast_quote",
        },
    )

    ok = lmp.record_from_level_one_equity(
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
    ok = lmp.record_from_level_one_equity(
        "MARKONLY",
        {"key": "MARKONLY", "MARK": 20.95, "BID_PRICE": 20.9, "ASK_PRICE": 21.1},
    )

    assert ok is False
    assert lmp.get_quote("MARKONLY") is None


def test_record_from_level_one_rejects_midpoint_spot_fabrication():
    ok = lmp.record_from_level_one_equity(
        "MIDONLY",
        {"key": "MIDONLY", "BID_PRICE": 30.0, "ASK_PRICE": 30.2},
    )

    assert ok is False
    assert lmp.get_quote("MIDONLY") is None


def test_record_from_level_one_skips_duplicate_sig():
    lmp.record_from_level_one_equity(
        "AAA",
        {"key": "AAA", "LAST_PRICE": 50.0, "BID_PRICE": 49.9, "ASK_PRICE": 50.1},
    )
    g0 = lmp.get_quote("AAA")["fast_generation_id"]
    ok = lmp.record_from_level_one_equity(
        "AAA",
        {"key": "AAA", "LAST_PRICE": 50.0, "BID_PRICE": 49.9, "ASK_PRICE": 50.1},
    )
    assert ok is False
    g1 = lmp.get_quote("AAA")["fast_generation_id"]
    assert g0 == g1


def test_record_from_level_one_ignores_non_canonical_bid_ask_keys():
    """Schwab streaming dictionary uses BID_PRICE/ASK_PRICE only — bare BID/ASK are not wire leaves."""
    ok = lmp.record_from_level_one_equity(
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


def test_record_from_level_one_marks_a_genuinely_carried_spot_as_stale(monkeypatch):
    """RC-REHAB-1 mutation test: this branch (bid/ask-only tick, spot reused from the prior
    LAST_PRICE tick) previously hardcoded quote_source_detail["carried_forward"] = False no
    matter what, silently telling every consumer -- including server.py's
    card_freshness_v1 actionability verdict -- that a carried print was a fresh one. A tick
    that reuses the prior spot MUST be marked carried_forward=True; a tick with its own
    LAST_PRICE MUST NOT be. The exchange clock (exchange_quote_ts) must keep advancing on
    the carried tick exactly as it does on a fresh one -- it is a quote-level fact, resolved
    from this tick's own payload, independent of whether spot itself was carried forward.
    """
    ok1 = lmp.record_from_level_one_equity(
        "CARRYCHECK",
        {
            "key": "CARRYCHECK",
            "LAST_PRICE": 200.0,
            "BID_PRICE": 199.9,
            "ASK_PRICE": 200.1,
            "QUOTE_TIME_MILLIS": 1_778_018_400_000,
        },
    )
    assert ok1 is True
    row1 = lmp.get_quote("CARRYCHECK")
    assert row1["quote_source_detail"]["carried_forward"] is False
    ts1 = row1["exchange_quote_ts"]
    assert ts1 == 1_778_018_400.0

    # Tick 2: bid/ask-only update (no LAST_PRICE) — spot must be reused from tick 1 and
    # explicitly marked stale/carried, while the exchange clock advances to this tick's own
    # (later) QUOTE_TIME_MILLIS.
    ok2 = lmp.record_from_level_one_equity(
        "CARRYCHECK",
        {
            "key": "CARRYCHECK",
            "BID_PRICE": 199.8,
            "ASK_PRICE": 200.2,
            "QUOTE_TIME_MILLIS": 1_778_018_405_000,
        },
    )
    assert ok2 is True
    row2 = lmp.get_quote("CARRYCHECK")
    assert row2["spot"] == 200.0, "carried spot must be the prior LAST_PRICE, not fabricated"
    assert row2["quote_source_detail"]["carried_forward"] is True, (
        "a spot reused from the prior tick must be disclosed as carried, not silently "
        "presented as a fresh LAST_PRICE read"
    )
    ts2 = row2["exchange_quote_ts"]
    assert ts2 == 1_778_018_405.0, "the exchange clock must advance on this tick regardless of the spot carry"
    assert ts2 != ts1, "REGRESSION: exchange_quote_ts frozen together with the carried spot"
