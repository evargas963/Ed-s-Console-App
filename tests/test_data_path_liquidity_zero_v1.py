"""Schwab -> the liquidity zones. A level at 0 is a level: a LAST_PRICE or bar price Schwab sends
as 0 is a price (AGENTS.md rule 2: a reported 0 is 0), never dropped. Real data and stand-ins as
tests/test_liquidity_snapshot_spot_identity_v1.py: Schwab's SPY 1-minute bars of 2026-10-01 and
10-02 under the stand-in ticker ZZLIQ, valued on Friday at 15:00 ET. The prices of 0 are stand-ins
(no captured message carries one): those bars keep their real times and volumes."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

import live_market_plane as lmp
import live_price_rows
import server as srv
from app.options.order_flow import streaming as ofs
from micro_structure import Candle
from tests.test_liquidity_snapshot_spot_identity_v1 import _BARS, FRIDAY, TK, published as published
from time_et import ET

BEFORE_OPEN = FRIDAY.replace(hour=8)
THURSDAY_ON = {1}
FRIDAY_ON = {2}
BOTH = {1, 2}


def _snapshot(zero_days: set[int], at: datetime, keep: float | None = None) -> dict:
    """The route's answer at `at` on the bars before it, those of the October days in `zero_days`
    with every price 0 but the bar at `keep`."""
    srv._bars.pop(TK, None)
    for b in _BARS:
        ts = b["timestamp"] / 1000
        if ts >= at.timestamp():
            continue
        zero = datetime.fromtimestamp(ts, ET).day in zero_days and ts != keep
        o, h, lo, c = (0, 0, 0, 0) if zero else (b["open"], b["high"], b["low"], b["close"])
        srv._keep_bar(TK, Candle(ts=ts, open=o, high=h, low=lo, close=c, volume=b["volume"]))
    srv._publish_price_levels(TK, at)
    resp = srv.liquidity_snapshot(TK, at)
    return json.loads(resp.body) if hasattr(resp, "body") else resp


def _tags_at_zero(body: dict) -> set[str]:
    return {t for z in body["zones"] if z["zone_low"] == 0 for t in z["source_tags"]}


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


def test_every_level_at_zero_stands_in_the_live_zones(published):
    assert _tags_at_zero(_snapshot(BOTH, FRIDAY)) >= {
        "PDH",
        "PD_VAH",
        "PD_POC",
        "PD_VAL",
        "PDL",
        "ORB_HIGH",
        "ORB_MID",
        "ORB_LOW",
        "TODAY_VAH",
        "TODAY_POC",
        "TODAY_VAL",
        "VWAP",
        "VWAP_P1",
        "VWAP_M1",
        "OVERNIGHT_HIGH",
        "OVERNIGHT_LOW",
    }


def test_every_level_at_zero_stands_in_the_zones_before_the_open(published):
    assert _tags_at_zero(_snapshot(BOTH, BEFORE_OPEN)) >= {
        "PDH",
        "PD_VAH",
        "PD_POC",
        "PD_VAL",
        "PDL",
        "PDC",
        "OVERNIGHT_HIGH",
        "OVERNIGHT_LOW",
    }


@pytest.mark.parametrize(
    ("zero_days", "value_state", "vwap_relation"),
    [
        (THURSDAY_ON, "shifted_higher", "at_value"),
        (FRIDAY_ON, "shifted_lower", "at_value"),
        (BOTH, "unchanged", "at_value"),
    ],
)
def test_a_value_area_at_zero_is_compared_as_a_price(
    published, zero_days, value_state, vwap_relation
):
    summary = _snapshot(zero_days, FRIDAY)["summary"]
    assert (summary["value_state"], summary["vwap_relation"]) == (value_state, vwap_relation)


def test_a_poc_at_zero_under_a_vwap_above_it_reads_above_value(published):
    """Friday's bars at 0 but its last, which keeps its prices: the POC is 0, VWAP above it."""
    last = max(b["timestamp"] for b in _BARS) / 1000
    summary = _snapshot(FRIDAY_ON, FRIDAY, keep=last)["summary"]
    assert (summary["value_state"], summary["vwap_relation"]) == ("shifted_lower", "above_value")
