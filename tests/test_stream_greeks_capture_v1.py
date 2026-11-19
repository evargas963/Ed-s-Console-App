"""A contract's streamed Greeks, volatility and volume, as its record on the bus holds them.

Schwab's LEVELONE_OPTIONS sends only the fields that changed (Change delivery), so the bus merges
each message into the contract's record field by field, each field with its own receive time
(stream_spine.MessageBus), and the console reads them from that record
(app.options.order_flow.state.streamed_record). GAMMA, DELTA and OPEN_INTEREST are in schwab-py's
LEVELONE_OPTIONS field enum (LevelOneOptionFields: DELTA=28, GAMMA=29, OPEN_INTEREST=9); open
interest is the chain's, never the stream's.
"""

from __future__ import annotations

import time_et
from app.options.order_flow.state import streamed_record
from option_contract import NO_GREEKS, Received, StreamedGreeks
from stream_spine import MessageBus, held_key
from tests.feed_live_helper import on_the_bus

SYM = "SPY   260116C00580000"
OPT = "LEVELONE_OPTIONS"


def _sent(bus: MessageBus, fields: dict, ts_recv: float, sym: str = SYM) -> None:
    on_the_bus(bus, OPT, {"key": sym, **fields}, ts_recv)


def _greeks(bus: MessageBus, sym: str = SYM) -> StreamedGreeks:
    return streamed_record(bus.current.get(held_key(OPT, sym))).greeks


def test_total_volume_is_captured_alongside_the_greeks():
    """TOTAL_VOLUME is held in the contract's same record, with its own receive time.

    So the exposure and per-strike overlay apply the same newer-than-REST precedence to it as to
    the Greeks.
    """
    bus = MessageBus()
    _sent(bus, {"TOTAL_VOLUME": 12345}, 500.0)
    g = _greeks(bus)
    assert g.total_volume.value == 12345.0
    assert g.total_volume.ts_recv == 500.0


def test_a_volume_only_tick_alone_is_captured_without_any_greek_present():
    bus = MessageBus()
    _sent(bus, {"TOTAL_VOLUME": 777}, time_et.now())
    g = _greeks(bus)
    assert g == StreamedGreeks(total_volume=Received(777.0, g.total_volume.ts_recv))


def test_a_genuine_zero_volume_is_captured_not_dropped():
    bus = MessageBus()
    _sent(bus, {"TOTAL_VOLUME": 0}, time_et.now())
    g = _greeks(bus)
    assert g.total_volume.value == 0.0


def test_a_negative_volume_is_rejected_not_stored_in_greeks_either():
    bus = MessageBus()
    _sent(bus, {"TOTAL_VOLUME": -1}, time_et.now())
    assert _greeks(bus) == NO_GREEKS


def test_a_gamma_only_tick_does_not_blank_a_previously_observed_volume():
    bus = MessageBus()
    _sent(bus, {"TOTAL_VOLUME": 500}, time_et.now())
    _sent(bus, {"GAMMA": 0.02}, time_et.now())
    g = _greeks(bus)
    assert g.total_volume.value == 500.0
    assert g.gamma.value == 0.02


def test_never_observed_symbol_returns_none_not_a_dict_of_nones():
    assert _greeks(MessageBus()) is NO_GREEKS


def test_a_bid_ask_only_tick_does_not_blank_a_previously_observed_gamma():
    """A quote tick that carries BID_PRICE/ASK_PRICE but not GAMMA must not erase a gamma.

    A gamma value learned on an earlier tick -- explicit per-field presence, not a group overwrite.
    """
    bus = MessageBus()
    _sent(bus, {"GAMMA": 0.0123, "DELTA": 0.45, "OPEN_INTEREST": 4200}, time_et.now())
    _sent(bus, {"BID_PRICE": 12.30, "ASK_PRICE": 12.35}, time_et.now())
    g = _greeks(bus)
    assert g.gamma.value == 0.0123, "gamma must survive a tick that does not mention it"
    assert g.delta.value == 0.45
    assert "open_interest" not in g.values(), "a contract's open interest is the chain's"


def test_each_field_is_independently_updatable():
    bus = MessageBus()
    _sent(bus, {"GAMMA": 0.01, "DELTA": 0.40, "OPEN_INTEREST": 100}, time_et.now())
    _sent(bus, {"GAMMA": 0.02}, time_et.now())
    g = _greeks(bus)
    assert g.gamma.value == 0.02, "gamma updates independently"
    assert g.delta.value == 0.40, "delta from the earlier tick is untouched"
    assert "open_interest" not in g.values(), "a contract's open interest is the chain's"


def test_a_negative_open_interest_is_rejected_not_stored():
    """schwab_count (AGENTS.md rule 2): a negative count is not a number and is not stored."""
    bus = MessageBus()
    _sent(bus, {"OPEN_INTEREST": -5}, time_et.now())
    assert _greeks(bus) == NO_GREEKS


def test_the_streams_open_interest_is_not_kept_the_chains_is_the_one_producer():
    """Schwab's stream does not send OPEN_INTEREST for every contract it streams.

    So the chain sends it for every contract and is its one producer; a streamed one is not kept
    beside it.
    """
    bus = MessageBus()
    _sent(bus, {"OPEN_INTEREST": 0}, time_et.now())
    _sent(bus, {"OPEN_INTEREST": 4200}, time_et.now())
    assert _greeks(bus) == NO_GREEKS


def test_a_non_finite_gamma_is_rejected_not_stored():
    bus = MessageBus()
    _sent(bus, {"GAMMA": 0.01}, 100.0)
    _sent(bus, {"GAMMA": float("nan")}, 105.0)
    assert _greeks(bus).gamma.value is None, (
        "a gamma sent as no number is no value, never the last one kept"
    )


def test_each_field_carries_its_own_receive_timestamp():
    bus = MessageBus()
    _sent(bus, {"GAMMA": 0.01}, 100.0)
    _sent(bus, {"DELTA": 0.40}, 105.0)
    g = _greeks(bus)
    assert g.gamma.ts_recv == 100.0, "an untouched field keeps its OWN last-update time"
    assert g.delta.ts_recv == 105.0


def test_greeks_are_symbol_scoped_not_cross_contaminated():
    bus = MessageBus()
    _sent(bus, {"GAMMA": 0.01}, time_et.now())
    _sent(bus, {"GAMMA": 0.02}, time_et.now(), sym="SPY   260116P00580000")
    assert _greeks(bus).gamma.value == 0.01
    assert _greeks(bus, "SPY   260116P00580000").gamma.value == 0.02
