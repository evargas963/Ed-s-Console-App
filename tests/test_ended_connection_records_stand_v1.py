"""When Schwab's connection ends, the records it held stand with their last values, not live, and
the next connection's first message replaces each whole (operator 2026-10-13: "On disconnect keep
the last values, marked not live; reconnect's opening replaces them"). Before, the daemon forgot
them: a console that connected meanwhile had no last value to show.

Real data: SPY's first two LEVELONE_EQUITIES messages received 2026-10-05 14:00 CT
(tests/fixtures/real_stream_mix_2026_10_05_1400ct.json), each through the daemon's real Schwab
handler (capture._publisher) onto its bus. The second stands for the next connection's first
message (STAND-IN, named: no reconnect was captured; it carries a different set of fields, so a
merge and a replacement differ)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.market_data.schwab.streaming import capture
from stream_spine import HealthRegistry, MessageBus

_SPY = [m for m in json.loads((Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json")
                              .read_text(encoding="utf-8"))["messages"]
        if m["service"] == "LEVELONE_EQUITIES" and m["item"]["key"] == "SPY"][:2]
_KEY = capture._current_key("LEVELONE_EQUITIES", "SPY")


def _sent(handler, m: dict) -> None:
    handler({"service": "LEVELONE_EQUITIES", "timestamp": m["schwab_ts"], "content": [m["item"]]})


def test_an_ended_connections_records_stand_not_live_and_the_next_ones_first_message_replaces_them():
    first, opening = _SPY
    assert set(first["item"]) - set(opening["item"]) == {"LAST_SIZE", "REGULAR_MARKET_LAST_SIZE"}
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])
    handler = capture._publisher("LEVELONE_EQUITIES", daemon.bus, daemon.health)
    daemon.held["LEVELONE_EQUITIES"] = frozenset({"SPY"})
    _sent(handler, first)
    asyncio.run(daemon.disconnect())
    # the last values stand; nothing is held, which the heartbeat reports: not live
    assert daemon.bus.current[_KEY][1]["native"] == first["item"]
    assert daemon.status()["held"]["LEVELONE_EQUITIES"] == []
    # a reader that starts now (the console reconnecting) is handed them
    reader = daemon.bus.subscribe("quote.")
    assert _KEY in reader.changed
    # the next connection's first message is the whole record: no field of the ended one stays
    daemon.held["LEVELONE_EQUITIES"] = frozenset({"SPY"})
    _sent(handler, opening)
    assert daemon.bus.current[_KEY][1]["native"] == opening["item"]
    assert set(daemon.bus.current[_KEY][1]["field_ts"]) == set(opening["item"])
