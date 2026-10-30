"""Schwab -> the liquidity zones. A level at 0 is a level: a LAST_PRICE Schwab sends as 0 is the
live spot the zones are fused with (AGENTS.md rule 2: a reported 0 is 0), never dropped. Real data
and stand-ins as tests/test_liquidity_snapshot_spot_identity_v1.py: Schwab's SPY 1-minute bars of
2026-10-01 and 10-02 under the stand-in ticker ZZLIQ, valued on Friday at 15:00 ET; the LAST_PRICE
of 0 is a stand-in (no captured message carries one)."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

import liquidity_value_engine as lve
import live_market_plane as lmp
import live_price_rows
import server as srv
from app.options.order_flow import streaming as ofs
from micro_structure import Candle
from tests.test_liquidity_snapshot_spot_identity_v1 import _BARS, FRIDAY, TK, published as published
from time_et import ET

BEFORE_OPEN = FRIDAY.replace(hour=8)


def test_a_last_price_of_zero_is_the_live_spot_level_in_the_zones(published):
    at = FRIDAY.timestamp()
    lmp.record_feed_heartbeat(
        {"ts": at, "schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": [TK]}}
    )
    lmp.record_from_level_one_equity(TK, {"LAST_PRICE": 0}, received_ts=at)
    ofs._price_rows[TK] = live_price_rows.price_row(TK, at)
    resp = srv.liquidity_snapshot(TK, FRIDAY)
    body = json.loads(resp.body) if hasattr(resp, "body") else resp
    assert "spot_used_for_scoring" in body, body
    assert body["spot_used_for_scoring"] == 0
    tags = [t for z in body["zones"] for t in z["source_tags"]]
    assert "SPOT_LIVE" in tags, tags


def _low_of_zero() -> None:
    """A bar of Thursday's session reporting a low of 0 (a stand-in: no captured bar has one)."""
    bar = next(b for b in _BARS if datetime.fromtimestamp(b["timestamp"] / 1000, ET).hour == 10)
    srv._keep_bar(
        TK,
        Candle(
            ts=bar["timestamp"] / 1000,
            open=bar["open"],
            high=bar["high"],
            low=0,
            close=bar["close"],
            volume=bar["volume"],
        ),
    )


def test_a_prior_day_low_of_zero_is_the_pdl_level_in_the_zones(published):
    _low_of_zero()
    srv._publish_price_levels(TK, FRIDAY)
    resp = srv.liquidity_snapshot(TK, FRIDAY)
    body = json.loads(resp.body) if hasattr(resp, "body") else resp
    assert [z["zone_low"] for z in body["zones"] if "PDL" in z["source_tags"]] == [0]


@pytest.mark.parametrize(
    ("poc", "prior_poc", "vwap", "expected"),
    [
        (500.0, 0.0, None, ("shifted_higher", "at_value", "")),
        (0.0, 0.0, None, ("unchanged", "at_value", "")),
        (0.0, 500.0, None, ("shifted_lower", "at_value", "")),
        (0.0, None, 500.0, ("unchanged", "above_value", "")),
        (500.0, None, 0.0, ("unchanged", "below_value", "")),
    ],
)
def test_a_value_area_price_of_zero_is_compared_as_a_price(poc, prior_poc, vwap, expected):
    assert lve._classify_value_state_and_vwap_relation(poc, prior_poc, vwap) == expected


def test_a_prior_day_low_of_zero_is_the_pdl_level_before_the_open(published):
    """The pre-market snapshot, on the same stand-in bar: before Friday's open the level stands."""
    _low_of_zero()
    srv._publish_price_levels(TK, BEFORE_OPEN)
    resp = srv.liquidity_snapshot(TK, BEFORE_OPEN)
    body = json.loads(resp.body) if hasattr(resp, "body") else resp
    assert [z["zone_low"] for z in body["zones"] if "PDL" in z["source_tags"]] == [0]
