"""Real LEVELONE_OPTIONS records as the daemon holds and pushes them: a contract's messages in the
2026-10-05 14:00 CT stream mix (tests/fixtures/real_stream_mix_2026_10_05_1400ct.json) merged on the
daemon's own bus. RECORD is SPY 261030C00910000's: it carries the six Greeks and IV; in those three
seconds the contract sent no bid, ask, last, mark or volume. Tests that price another contract with
it name it a STAND-IN."""
from __future__ import annotations

import json
from pathlib import Path

from app.market_data.schwab.streaming import capture
from stream_spine import MessageBus

_MIX = json.loads((Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json")
                  .read_text(encoding="utf-8"))["messages"]


def bus_records(symbol: str):
    """Each of `symbol`'s messages merged on the daemon's bus: (topic, its current record) after each."""
    bus = MessageBus()
    for m in _MIX:
        if m["item"]["key"] == symbol:
            kind, msg = capture._message(m["service"], symbol, m["item"], m["schwab_ts"])
            topic = f"{kind}.{symbol}"
            bus.publish(topic, {**msg, "ts_recv": m["ts_recv"]})
            yield topic, next(iter(bus.current.values()))[1]


RECORD = {k: v for k, v in list(bus_records("SPY   261030C00910000"))[-1][1]["content"].items() if k != "key"}


def stream_priced(ct: dict, content: dict = RECORD) -> dict:
    """`ct` as the one-source rule prices it from its stream record, written out field by field."""
    return {**ct, "bid": content.get("BID_PRICE"), "ask": content.get("ASK_PRICE"),
            "last": content.get("LAST_PRICE"), "mark": content.get("MARK"),
            "totalVolume": content.get("TOTAL_VOLUME"), "delta": content.get("DELTA"),
            "gamma": content.get("GAMMA"), "theta": content.get("THETA"), "vega": content.get("VEGA"),
            "rho": content.get("RHO"), "volatility": content.get("VOLATILITY")}
