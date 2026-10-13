"""A real LEVELONE_OPTIONS record as the daemon holds and pushes it: SPY 261030C00910000's messages in
the 2026-10-05 14:00 CT stream mix (tests/fixtures/real_stream_mix_2026_10_05_1400ct.json), merged on
the daemon's own bus. It carries the six Greeks and IV; in those three seconds the contract sent no
bid, ask, last, mark or volume. Tests that price another contract with it name it a STAND-IN."""
from __future__ import annotations

import json
from pathlib import Path

from app.market_data.schwab.streaming import capture
from math_exposure_core import STREAMED_CHAIN_FIELDS
from stream_spine import MessageBus

SYMBOL = "SPY   261030C00910000"


def _record() -> dict:
    bus = MessageBus()
    for m in json.loads((Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json")
                        .read_text(encoding="utf-8"))["messages"]:
        if m["item"]["key"] == SYMBOL:
            kind, msg = capture._message(m["service"], SYMBOL, m["item"], m["schwab_ts"])
            bus.publish(f"{kind}.{SYMBOL}", {**msg, "ts_recv": m["ts_recv"]})
    return {k: v for k, v in next(iter(bus.current.values()))[1]["content"].items() if k != "key"}


RECORD = _record()


def stream_priced(ct: dict, content: dict = RECORD) -> dict:
    """`ct` priced from its stream alone: every STREAMED_CHAIN_FIELDS value from `content`."""
    return {**ct, **{key: read(content.get(field)) for key, field, read in STREAMED_CHAIN_FIELDS}}
