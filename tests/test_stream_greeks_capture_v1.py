"""A contract's streamed Greeks, volatility and volume, as its record on the bus holds them.

Schwab's LEVELONE_OPTIONS sends only the fields that changed (Change delivery), so the bus merges
each message into the contract's record field by field, each field with its own receive time
(stream_spine.MessageBus), and they are read on the first read after a message changes it and
held in that record (stream_spine.streamed_record, stream_spine.read_streamed). GAMMA, DELTA and
OPEN_INTEREST are in schwab-py's LEVELONE_OPTIONS field enum (LevelOneOptionFields: DELTA=28,
GAMMA=29, OPEN_INTEREST=9); open interest is the chain's, never the stream's.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import time_et
from option_contract import NO_GREEKS, Received, Streamed, StreamedGreeks, StreamedTop
from stream_spine import MessageBus, held_key, streamed_record
from tests.feed_live_helper import on_the_bus

SYM = "SPY   260116C00580000"
OPT = "LEVELONE_OPTIONS"
EQ = "LEVELONE_EQUITIES"
#: 3 s of the real stream in RTH, every message as Schwab sent it, in receive order
_MIX = json.loads(
    (Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json").read_text(
        encoding="utf-8"
    )
)["messages"]
#: Schwab's LEVELONE top-of-book fields (Streamer API §3.3, §3.6) by the record's names, and
#: whether each is a count (a size)
_TOP = {
    "BID_PRICE": ("bid", False),
    "ASK_PRICE": ("ask", False),
    "BID_SIZE": ("bid_size", True),
    "ASK_SIZE": ("ask_size", True),
    "MARK": ("mark", False),
    "QUOTE_TIME_MILLIS": ("quote_time_ms", False),
    "MONEY_INTRINSIC_VALUE": ("money_intrinsic", False),
}
_GREEKS = ("GAMMA", "DELTA", "THETA", "VEGA", "RHO", "VOLATILITY")


def _as_sent(v, count: bool = False) -> float | None:
    """A Schwab field as sent (AGENTS.md rule 2), worked out here, outside the code under test.

    Not a number: absent, -999, text, a bool, NaN or infinity; a count is also never negative.
    """
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    if v == -999 or not math.isfinite(v) or (count and v < 0):
        return None
    return float(v)


def _read_as_sent(topic: str, rec: dict) -> Streamed:
    """The record's merged fields as sent, each Greek and the volume at its own receive time."""
    content = rec["content" if topic.startswith("optquote.") else "native"]
    at = rec["field_ts"]
    top = {name: _as_sent(content[f], count) for f, (name, count) in _TOP.items() if f in content}
    greeks = {f.lower(): Received(_as_sent(content[f]), at[f][1]) for f in _GREEKS if f in content}
    volume = _as_sent(content.get("TOTAL_VOLUME"), count=True)
    if volume is not None:
        greeks["total_volume"] = Received(volume, at["TOTAL_VOLUME"][1])
    return Streamed(StreamedTop(**top), StreamedGreeks(**greeks))


def test_each_record_holds_its_fields_read_once_as_every_real_message_changes_it():
    """Each LEVELONE message of 3 s of the real stream, put on the bus in receive order.

    After each, the record's reading is its merged fields as sent, every Greek and the volume at
    its own receive time: the 7,420 option and 152 equity messages carry only the fields that
    changed, a few of them Greeks or volume over a held record, and the rest stand. A message
    reads nothing: it makes a new version of the record, read on its first read and held, so a
    second read with no message between is the same reading, and the version before stands as it
    was read.
    """
    bus = MessageBus()
    over_held = greeks_over_held = 0
    for m in _MIX:
        if m["service"] not in (OPT, EQ):
            continue
        before = bus.current.get(held_key(m["service"], m["item"]["key"].upper()))
        was_held = before is not None
        held_before = streamed_record(before)
        topic, rec = on_the_bus(bus, m["service"], m["item"], m["ts_recv"], m["schwab_ts"])
        assert rec["streamed"] is None  # nothing read on the message
        first = streamed_record((topic, rec))
        assert first == _read_as_sent(topic, rec), m
        assert streamed_record((topic, rec)) is first  # read once per version
        if before is not None:
            assert before[1] is not rec and before[1]["streamed"] is held_before
        over_held += was_held
        greeks_over_held += was_held and any(f in m["item"] for f in (*_GREEKS, "TOTAL_VOLUME"))
    assert over_held == 4777  # each merged into a record it changes only in part
    assert greeks_over_held == 110  # of them, those that change a held record's Greeks or volume


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
