"""Schwab's option stream -> the matrix's look-back, on SPY's recorded messages of 2026-11-23.

tests/fixtures/real_spy_option_stream_two_strikes_2026_11_23.json: every LEVELONE_OPTIONS item
the record kept of SPY's 0DTE calls and puts at 721 and 722, received 09:59:00-10:10:00 ET, put
on a bus as the daemon's stream handler does and applied as the console does. Each expected value
is worked out here from the raw items, outside the code: the values in force at the window's
start, and each rise of TOTAL_VOLUME read by its last trade against the quote in force.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.options.order_flow.state import OrderFlowState
from calc.confluence_composite import family_votes
from calc.option_window import strike_look_back
from option_contract import read_chain
from stream_spine import MessageBus
from tests.feed_live_helper import apply_record, on_the_bus
from tests.shared_helpers import fixture_json
from time_et import ET

FX = fixture_json("real_spy_option_stream_two_strikes_2026_11_23.json")
DAY = "2026-11-23"
#: the window starts at 10:04 ET; the record began 09:59, before it
START = int(datetime(2026, 11, 23, 10, 4, tzinfo=ET).timestamp() // 60)
QUOTE = ("BID_PRICE", "ASK_PRICE", "BID_SIZE", "ASK_SIZE", "QUOTE_TIME_MILLIS")


def _replayed() -> OrderFlowState:
    """The fixture's items on a bus as the daemon puts them, applied as the console applies them."""
    bus = MessageBus()
    state = OrderFlowState()
    state.current = bus.current
    for m in FX["messages"]:
        record = on_the_bus(bus, "LEVELONE_OPTIONS", m["item"], m["ts_recv"], m["schwab_ts"])
        apply_record(state, "LEVELONE_OPTIONS", record)
    return state


def _number(v):
    return None if v is None or v == -999 else float(v)


def _worked_out(start_ts: float) -> dict:
    """Each contract over the window from `start_ts`, worked out from the raw items.

    The values in force at the start: the last each field was sent before it. Each rise of
    TOTAL_VOLUME received from the start on: its last trade (LAST_PRICE, TRADE_TIME_MILLIS as
    held then) against the newest of the quote held then and the one it replaced (a quote is
    replaced when a quote field already held changes value) that Schwab timed at or before the
    trade (same ET day); above their middle bought, below sold, else unknown; its flow the signed
    step x DELTA x 100 x UNDERLYING_PRICE as held then.
    """
    held: dict[str, dict] = {}
    replaced: dict[str, dict] = {}
    at_start: dict[str, tuple] = {}
    sums: dict[str, list[float]] = {}
    for m in FX["messages"]:
        item, ts = m["item"], m["ts_recv"]
        sym = item["key"]
        was = held.setdefault(sym, {})
        if ts >= start_ts and sym not in at_start:
            at_start[sym] = (_number(was.get("TOTAL_VOLUME")), _number(was.get("VOLATILITY")))
        before_volume = _number(was.get("TOTAL_VOLUME"))
        if any(f in item and f in was and item[f] != was[f] for f in QUOTE):
            replaced[sym] = {f: was[f] for f in QUOTE if f in was}
        was.update(item)
        quotes = ({f: was.get(f) for f in QUOTE}, replaced.get(sym, {}))
        volume = _number(was.get("TOTAL_VOLUME"))
        if ts < start_ts or volume is None or before_volume is None or volume <= before_volume:
            continue
        step = volume - before_volume
        trade_ms = was.get("TRADE_TIME_MILLIS")
        bid = ask = None
        for q in quotes:
            t = q.get("QUOTE_TIME_MILLIS")
            same_day = (
                t is not None
                and trade_ms is not None
                and datetime.fromtimestamp(t / 1000, ET).date()
                == datetime.fromtimestamp(trade_ms / 1000, ET).date()
            )
            if same_day and t <= trade_ms:
                bid, ask = _number(q.get("BID_PRICE")), _number(q.get("ASK_PRICE"))
                break
        price = _number(was.get("LAST_PRICE"))
        side = None
        if price is not None and bid is not None and ask is not None:
            mid = (bid + ask) / 2
            side = 1 if price > mid else -1 if price < mid else None
        delta, under = _number(was.get("DELTA")), _number(was.get("UNDERLYING_PRICE"))
        s = sums.setdefault(sym, [0.0] * 5)
        s[0] += step if side == 1 else 0.0
        s[1] += step if side == -1 else 0.0
        s[2] += step if side is None else 0.0
        if side is None or delta is None or under is None:
            s[4] += step
        else:
            s[3] += side * step * delta * 100 * under
    return {
        sym: {
            "start": at_start[sym],
            "now": (_number(v.get("TOTAL_VOLUME")), _number(v.get("VOLATILITY"))),
            "totals": tuple(sums.get(sym, [0.0] * 5)),
        }
        for sym, v in held.items()
    }


def test_each_contract_over_the_window_is_schwabs_values_and_its_steps():
    """The record's look-back from 10:04 ET of each of the four contracts.

    Its volume and volatility at the start are the last Schwab sent before 10:04:00, its newest
    the last overall, and its bought, sold, unknown and flow the sum over its steps from 10:04
    on, each worked out from the raw items.
    """
    looks = _replayed().look_back(FX["symbols"], DAY, START)
    expected = _worked_out(START * 60.0)
    assert sorted(looks) == sorted(FX["symbols"])
    traded = 0.0
    for sym, look in looks.items():
        want = expected[sym]
        assert look.volume == want["start"][:1] + want["now"][:1], sym
        assert look.iv == (want["start"][1], want["now"][1]), sym
        assert look.totals == pytest.approx(want["totals"], rel=1e-12, abs=1e-9), sym
        traded += want["now"][0] - want["start"][0]
    # a window with trades, read on both sides of the middle: not vacuous
    assert traded > 0
    assert sum(e["totals"][0] for e in expected.values()) > 0
    assert sum(e["totals"][1] for e in expected.values()) > 0


def test_a_window_begun_before_the_record_is_not_held():
    """A window from 09:58 ET began before the record (09:59): no contract is read over it."""
    early = int(datetime(2026, 11, 23, 9, 58, tzinfo=ET).timestamp() // 60)
    assert _replayed().look_back(FX["symbols"], DAY, early) == {}


def test_a_record_of_another_day_is_not_read():
    """The record is of 2026-11-23: asked for another day's window, it reads nothing."""
    assert _replayed().look_back(FX["symbols"], "2026-11-24", START) == {}


def test_a_strike_is_its_calls_and_its_puts_or_nothing():
    """Each strike's readings are its call's and its put's look-backs, summed.

    The volume calls and puts apart; bought, sold, unknown and flow summed; the volatility change
    iv_by_strike's blend on each contract's volume and volatility at each end, with the chain's
    open interest (the contracts' rows of SPY's newest stored capture of the expiry). A strike
    with a contract not held over the window is nothing.
    """
    state = _replayed()
    looks = state.look_back(FX["symbols"], DAY, START)
    expected = _worked_out(START * 60.0)
    chain = read_chain(FX["chain_rows"])
    for strike in (721.0, 722.0):
        legs = [c for c in chain if c.strike == strike]
        got = strike_look_back(legs, looks)
        call = next(c.symbol for c in legs if c.side == "CALL")
        put = next(c.symbol for c in legs if c.side == "PUT")
        assert got.volume == (
            expected[call]["now"][0] - expected[call]["start"][0],
            expected[put]["now"][0] - expected[put]["start"][0],
        )
        for k, name in enumerate(("bought", "sold", "unknown", "flow", "unpriced")):
            want = expected[call]["totals"][k] + expected[put]["totals"][k]
            assert getattr(got, name) == pytest.approx(want, rel=1e-12, abs=1e-9), name

        def blend(end: str, call=call, put=put, legs=legs) -> float:
            oi = {c.symbol: c.open_interest for c in legs}
            parts = [(oi[s] + expected[s][end][0], expected[s][end][1]) for s in (call, put)]
            return sum(w * iv for w, iv in parts) / sum(w for w, _iv in parts)

        assert got.iv_change == pytest.approx(blend("now") - blend("start"), rel=1e-12)
        missing = strike_look_back(legs, {call: looks[call]})
        assert missing.volume is None and missing.flow is None and missing.iv_change is None


def _underlying(before_ts: float | None) -> float:
    """The stock price the last item received before `before_ts` (None: of all) carried."""
    held = [
        m["item"]["UNDERLYING_PRICE"]
        for m in FX["messages"]
        if "UNDERLYING_PRICE" in m["item"] and (before_ts is None or m["ts_recv"] < before_ts)
    ]
    return held[-1]


def test_each_family_votes_on_the_kind_of_move_by_its_definition():
    """The headline's votes over the window from 10:04 ET, from the record's own readings.

    Option trades: the two strikes' hedging flow (worked out from the raw items) with the
    stock's move over the window (the price the items carried at its start and at its end)
    votes continuing, against it reverting; volatility: rising wider, falling calmer;
    positioning: negative gamma wider. The stock's book casts no vote; a zero casts none. The
    gamma at the price and the volatility change are INDUCED, each sign in turn (their own
    producers are tested on captured chains), as is a zero flow.
    """
    expected = _worked_out(START * 60.0)
    flow = sum(e["totals"][3] for e in expected.values())
    start, end = _underlying(START * 60.0), _underlying(None)
    votes = family_votes(-1.0e9, flow, (start, end), 0.5)
    move_sign = 1 if end > start else -1
    assert flow != 0 and end != start
    assert [v.vote for v in votes] == [1, (1 if flow > 0 else -1) * move_sign, 1, None]
    assert [v.family for v in votes] == ["positioning", "option trades", "volatility", "stock book"]
    calm = family_votes(2.0e9, 0.0, (start, end), -0.5)
    assert [v.vote for v in calm] == [-1, None, -1, None]
    unknown = family_votes(None, flow, (None, end), None)
    assert [v.vote for v in unknown] == [None, None, None, None]
