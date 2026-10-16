"""The daemon's status is current at a time only when its stamp is not older than the live
limit (live_market_plane.daemon_status). A stamp after that time is a later moment.

End to end through the real code: the daemon's status (record_feed_heartbeat), Schwab's SPY quote
through the daemon's plane and its price row (record_from_level_one_equity, live_price_rows.price_row),
the pushed option message (streaming._ingest_pushed), the levels producer (server._publish_levels)
and the heatmap route (server.gamma_surface_payload).
Real data: SPY's 2026-11-20 chain captured 2026-09-30 15:31:57 ET
(tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json, fetched at its capture), and
Schwab's LEVELONE_EQUITIES SPY quote and LEVELONE_OPTIONS message for one of the chain's
contracts received 2026-10-05 14:00 CT (tests/fixtures/real_stream_mix_2026_10_05_1400ct.json),
priced and judged a second after that message. The daemon's status is the console's own message, built here
in its shape (no status is captured).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import live_price_rows
import server
from stream_spine import options_quote_msg
from time_et import ET

_FX = Path(__file__).resolve().parent / "fixtures"
_CAPTURE = json.loads((_FX / "real_spy_2026_11_20_chain_and_quotes.json").read_text(encoding="utf-8"))
_LISTED = {c["symbol"] for c in _CAPTURE["chain"]}
_MIX = json.loads((_FX / "real_stream_mix_2026_10_05_1400ct.json").read_text(encoding="utf-8"))["messages"]
_MSG = next(m for m in _MIX if m["service"] == "LEVELONE_OPTIONS" and m["item"]["key"] in _LISTED
            and {"GAMMA", "DELTA", "OPEN_INTEREST", "TOTAL_VOLUME"} & set(m["item"]))
_QUOTE = next(m for m in _MIX if m["service"] == "LEVELONE_EQUITIES" and m["item"]["key"] == "SPY"
              and "LAST_PRICE" in m["item"])
SYM = _MSG["item"]["key"]
TK = server.ticker_storage_key("SPY")
_AT = _MSG["ts_recv"] + 1.0


@pytest.fixture(autouse=True)
def _clean():
    ofls.clear_all_live_state()
    lmp.record_feed_down()
    yield
    ofls.clear_all_live_state()
    lmp.record_feed_down()
    for kept in (lmp._by_ticker, lmp._fields_by_ticker, ofs._price_rows):
        kept.pop(TK, None)
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    server._last_feed_stamp = None
    ofs._held_options.clear()


def _beat(ts: float, *, socket_open: bool = True, options: "list[str] | None" = None) -> None:
    lmp.record_feed_heartbeat({"ts": ts, "schwab_socket_open": socket_open,
                               "held": {"LEVELONE_EQUITIES": [TK],
                                        "LEVELONE_OPTIONS": [SYM] if options is None else options}})


def _states_when_the_status_was_sent(offset: float) -> list[str]:
    """SPY's chain priced and its heatmap served at `_AT`, the daemon's status stamped `offset`
    seconds from `_AT` (negative: earlier). The states of SYM's heatmap legs."""
    _beat(_AT + offset)
    lmp.record_from_level_one_equity(TK, _QUOTE["item"], received_ts=_QUOTE["ts_recv"])
    ofs._price_rows[TK] = live_price_rows.price_row(TK, _AT)
    ofs._ingest_pushed(f"optquote.{SYM}", options_quote_msg(
        symbol=SYM, content=_MSG["item"], src="schwab_options_l1", ts_recv=_MSG["ts_recv"]))
    at = datetime.fromtimestamp(_AT, ET)
    server._publish_levels(TK, [dict(c) for c in _CAPTURE["chain"]], _CAPTURE["capture_ts_utc"], now=at)
    body = server.gamma_surface_payload(TK, "all", None, 0, None, None, at)
    return [col[side]["state"] for cell in body["cells"] for col, pair in zip(cell["stream"], cell["contracts"])
            for side in ("call", "put") if col and pair.get(side) == SYM]


@pytest.mark.parametrize("before", [0.001, 0.5, 2.9])
def test_a_status_stamped_before_the_time_judged_keeps_the_streamed_cell_live(before):
    assert _states_when_the_status_was_sent(-before) == ["live"]


@pytest.mark.parametrize("after", [0.001, 0.5, 2.9])
def test_a_status_stamped_after_the_time_judged_is_not_that_time(after):
    """A stamp after `_AT` is not `_AT`. The last price still stands, and the cell is not live."""
    _beat(_AT + after)
    lmp.record_from_level_one_equity(TK, _QUOTE["item"], received_ts=_QUOTE["ts_recv"])
    ofs._price_rows[TK] = live_price_rows.price_row(TK, _AT)
    ofs._ingest_pushed(f"optquote.{SYM}", options_quote_msg(
        symbol=SYM, content=_MSG["item"], src="schwab_options_l1", ts_recv=_MSG["ts_recv"]))
    at = datetime.fromtimestamp(_AT, ET)
    server._publish_levels(TK, [dict(c) for c in _CAPTURE["chain"]], _CAPTURE["capture_ts_utc"], now=at)
    body = server.gamma_surface_payload(TK, "all", None, 0, None, None, at)
    states = [col[side]["state"] for cell in body["cells"]
              for col, pair in zip(cell["stream"], cell["contracts"])
              for side in ("call", "put") if col and pair.get(side) == SYM]
    assert lmp.daemon_status(_AT) is None
    assert states and "live" not in states


def test_a_status_sent_past_the_live_limit_is_not_current():
    _beat(_AT - lmp.FEED_HEARTBEAT_MAX_AGE_SEC)
    assert lmp.daemon_status(_AT) is None and not lmp.feed_live_for(SYM, "LEVELONE_OPTIONS", _AT)
    _beat(_AT - 1.0)
    assert lmp.feed_live_for(SYM, "LEVELONE_OPTIONS", _AT)


def test_a_closed_socket_keeps_the_last_option_value_and_names_its_time():
    """Schwab's socket drops and the daemon's held set empties: the last streamed gamma stays,
    the cell is stale, and its tooltip carries Schwab's time and the age."""
    _beat(_AT - 0.5)
    lmp.record_from_level_one_equity(TK, _QUOTE["item"], received_ts=_QUOTE["ts_recv"])
    ofs._price_rows[TK] = live_price_rows.price_row(TK, _AT)
    ofs._ingest_pushed(f"optquote.{SYM}", options_quote_msg(
        symbol=SYM, content=_MSG["item"], src="schwab_options_l1", ts_recv=_MSG["ts_recv"]))
    ofs._drop_released_options(_AT)
    at = datetime.fromtimestamp(_AT, ET)
    server._publish_levels(TK, [dict(c) for c in _CAPTURE["chain"]], _CAPTURE["capture_ts_utc"], now=at)
    with server._terrain_cache_lock:
        gex = [cell["gex"] for cell in server._terrain_cache[TK]["_gamma_surface"]["cells"]]
    kept = ofls.get_stream_greeks(SYM)
    _beat(_AT, socket_open=False, options=[])
    ofs._drop_released_options(_AT)
    server.restamp_open_surfaces(_AT)
    body = server.gamma_surface_payload(TK, "all", None, 0, None, None, at)
    cells = [col for cell in body["cells"] for col, pair in zip(cell["stream"], cell["contracts"])
             if col and (pair.get("call") == SYM or pair.get("put") == SYM)]
    with server._terrain_cache_lock:
        after = [cell["gex"] for cell in server._terrain_cache[TK]["_gamma_surface"]["cells"]]
    assert kept and ofls.get_stream_greeks(SYM) == kept
    assert after == gex
    assert cells and all(col["state"] == "stale" for col in cells)
    title = cells[0]["title"]
    assert title.startswith("this cell has stopped streaming")
    assert "CT" in title and title.endswith("s")
