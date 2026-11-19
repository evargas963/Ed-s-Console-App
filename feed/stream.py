"""Feed's side of Schwab's stream: schwab-py's StreamClient and the field names its services send.

The capture daemon holds the one connection (Schwab allows one per account); this module is the
schwab-py it is made of: each service's field names, a frame's fields named in place, the time
Schwab put on a frame, and the client that records when each frame was read.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from typing import Any, override

from schwab.client.base import BaseClient
from schwab.streaming import StreamClient

from numeric_contract import schwab_number

#: schwab-py's field names of each service's items, as its add_*_handler names them (NEWS_HEADLINE
#: has none: its items are taken as sent)
FIELD_NAMES = {
    "LEVELONE_EQUITIES": StreamClient.LevelOneEquityFields,
    "CHART_EQUITY": StreamClient.ChartEquityFields,
    "LEVELONE_OPTIONS": StreamClient.LevelOneOptionFields,
    "NYSE_BOOK": StreamClient.BookFields,
    "NASDAQ_BOOK": StreamClient.BookFields,
    "OPTIONS_BOOK": StreamClient.BookFields,
}
#: a book's sides: each price level's field names, and each venue's on it
BOOK_SIDES = (
    ("BIDS", StreamClient.BidFields, StreamClient.PerExchangeBidFields),
    ("ASKS", StreamClient.AskFields, StreamClient.PerExchangeAskFields),
)


def label(d: dict[str, Any]) -> dict[str, Any]:
    """Name a data entry's fields in place with schwab-py's field enums, a book's levels too.

    The names schwab-py's label_message gives, without the copy of the whole entry it makes first:
    the entry is the reader's own, just decoded, and nothing else holds it.
    """
    if d["service"] in FIELD_NAMES:
        for item in d["content"]:
            FIELD_NAMES[d["service"]].relabel_message(item, item)
            for side, level_fields, venue_fields in BOOK_SIDES:
                levels: list[dict[str, Any]] = item[side] if side in item else []
                for level in levels:
                    level_fields.relabel_message(level, level)
                    venues: list[dict[str, Any]] = level[side] if side in level else []
                    for venue in venues:
                        venue_fields.relabel_message(venue, venue)
    return d


def streaming_fields() -> dict[str, list[str]]:
    """Return schwab-py's field names for every streaming service."""
    return {
        n.removesuffix("Fields"): [f.name for f in getattr(StreamClient, n)]
        for n in dir(StreamClient)
        if n.endswith("Fields")
        and isinstance(getattr(StreamClient, n), type)
        and issubclass(getattr(StreamClient, n), enum.Enum)
    }


def schwab_time(msg: dict[str, Any]) -> float | None:
    """Return the time Schwab put on a frame, in seconds since the epoch.

    The newest of its answers' and data's `timestamp` and its heartbeat (Streamer API §1.3:
    milliseconds since the epoch, a heartbeat's sent as digits in text). None when it carries
    none that is a number (rule 2).
    """
    sent = [
        e["timestamp"] for k in ("response", "data") if k in msg for e in msg[k] if "timestamp" in e
    ]
    stamps = [v for v in map(schwab_number, sent) if v is not None]
    beats = (
        [str(n["heartbeat"]) for n in msg["notify"] if "heartbeat" in n] if "notify" in msg else []
    )
    stamps.extend(float(b) for b in beats if b.isdigit())
    return max(stamps) / 1000 if stamps else None


class TimedStream(StreamClient):
    """schwab-py's StreamClient, recording the time of every frame Schwab sends.

    Data, responses and Schwab's heartbeats alike are timed: when the reader took it
    (last_frame_ts, the liveness test) and the newest time Schwab put on one (schwab_ts, how far
    Schwab's stream has been read).
    """

    def __init__(self, client: BaseClient, clock: Callable[[], float]) -> None:
        super().__init__(client)
        self.clock = clock
        self.last_frame_ts = clock()
        self.schwab_ts: float | None = None

    async def close(self, *, logged_out: bool) -> None:
        """Close the websocket, which schwab-py's logout leaves open.

        Logged out, Schwab closes its end ("Streamer will close the connection", Streamer API
        §1), so the closing handshake ends at once. Not logged out (the logout failed or timed
        out: the connection is presumed dead), the connection is dropped without the handshake,
        whose wait (websockets' close_timeout) would hold up the reconnect.
        """
        if self._socket is None:
            return
        if logged_out:
            await self._socket.close()
        else:
            self._socket.transport.abort()

    async def receive(self) -> dict[str, Any]:
        """Return the next frame Schwab sends, timed as every frame is (_receive)."""
        return await self._receive()

    @override
    async def _receive(self) -> dict[str, Any]:
        msg = await super()._receive()
        self.last_frame_ts = self.clock()
        t = schwab_time(msg)
        if t is not None and (self.schwab_ts is None or t > self.schwab_ts):
            self.schwab_ts = t
        return msg
