"""OPTIONS FLOW FOUNDATION — durable RAW retention for the entitled options stream (2026-08-26).

WHY THIS EXISTS. Schwab entitles two options streaming services that this console has never
subscribed to, proven deliverable by a committed capture
(reports/of_capability_probe/options_20260820T1354Z/, response_code 0, 91 + 90 frames in 90s):

  * LEVELONE_OPTIONS — 58 native fields per contract, including a STREAMING greeks/IV surface
    (DELTA/GAMMA/THETA/VEGA/RHO, VOLATILITY, OPEN_INTEREST) and the temporal keys
    QUOTE_TIME_MILLIS / TRADE_TIME_MILLIS that the once-per-cycle REST chain cannot give.
  * OPTIONS_BOOK — market-maker depth: BOOK_TIME (market snapshot time), per price level
    TOTAL_VOLUME and NUM_BIDS/NUM_ASKS (market-maker COUNT), and nested per-market-maker
    EXCHANGE (MM id), BID_VOLUME/ASK_VOLUME (per-MM size) and field 2 (per-MM quote time).

THE DESIGN IS RAW-FIRST, ON PURPOSE. A frame is stored VERBATIM as the vendor sent it, one row per
frame. No projection happens at write time, so no field can be lost by an omission in today's
parser — the thing that cost us the chain envelope. Typed projections are built as READERS over
this store, so adding a consumer later is a query change and never a re-collection: the history is
already there. This is deliberately NOT hundreds of columns.

WHAT THIS MODULE DOES NOT DO. It does not subscribe. Wiring a new subscription changes what the
live production streamer does, which is the operator's call, not a side effect of adding storage.
The writer is inert until something calls it.

SEMANTICS NOTE (kept with the data, because a decoder label is not vendor truth): the per-market-maker
field 2 is labelled SEQUENCE by the probe's decoder, but the repo's own first-party citation
(reports/of_capability_probe/schwab_streamer_guide_book_fields_citation.md) names it a Quote Time,
and the captured values behave like a time — measured across all 6 captured frames, all 157 nested
values lag BOOK_TIME by 0-604 ms (median 263 ms) rather than counting. Raw retention means this
question stays ANSWERABLE from stored bytes instead of being frozen by a naming guess.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: One row per frame, payload verbatim. `service` and `symbol_key` are indexed read keys lifted from
#: the frame so a reader can find frames without parsing every blob; they are COPIES, never a
#: replacement for the payload.
TABLE_SQL = """
CREATE TABLE IF NOT EXISTS options_stream_frames (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    service      TEXT NOT NULL,          -- LEVELONE_OPTIONS | OPTIONS_BOOK
    symbol_key   TEXT,                   -- the frame's own `key` (the option symbol), when present
    frame_ts_utc REAL NOT NULL,          -- vendor frame timestamp (NOT our clock)
    received_ts_utc REAL NOT NULL,       -- our receive clock, so vendor-vs-local lag stays measurable
    payload_json TEXT NOT NULL,          -- the frame VERBATIM, no projection
    created_at   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_osf_service_ts ON options_stream_frames(service, frame_ts_utc);
CREATE INDEX IF NOT EXISTS idx_osf_symbol_ts  ON options_stream_frames(symbol_key, frame_ts_utc);
"""

SERVICE_LEVELONE = "LEVELONE_OPTIONS"
SERVICE_BOOK = "OPTIONS_BOOK"
SUPPORTED_SERVICES = (SERVICE_LEVELONE, SERVICE_BOOK)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(TABLE_SQL)
    conn.commit()


def persist_frame(db_path: Path | str, *, service: str, frame: dict[str, Any],
                  received_ts_utc: float) -> dict[str, Any]:
    """Store ONE vendor frame verbatim. Returns a small receipt; never raises on bad input.

    Fails SOFT and says so: a collection path must not take the console down because one frame was
    malformed. A rejected frame is logged and reported, not silently swallowed.
    """
    if service not in SUPPORTED_SERVICES:
        return {"status": "rejected", "reason": f"unsupported service {service!r}"}
    if not isinstance(frame, dict):
        return {"status": "rejected", "reason": "frame is not a dict"}

    content = frame.get("content")
    symbol_key = None
    if isinstance(content, list) and content and isinstance(content[0], dict):
        symbol_key = content[0].get("key")
    frame_ts = frame.get("timestamp")
    try:
        frame_ts = float(frame_ts)
    except (TypeError, ValueError):
        return {"status": "rejected", "reason": "frame carries no usable vendor timestamp"}

    conn = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO options_stream_frames"
            "(service, symbol_key, frame_ts_utc, received_ts_utc, payload_json) VALUES (?,?,?,?,?)",
            (service, symbol_key, frame_ts, float(received_ts_utc),
             json.dumps(frame, default=str, separators=(",", ":"))),
        )
        conn.commit()
    except sqlite3.Error as e:
        log.warning("options_stream_frames persist failed service=%s: %s", service, e)
        return {"status": "error", "reason": str(e)}
    finally:
        conn.close()
    return {"status": "written", "service": service, "symbol_key": symbol_key,
            "frame_ts_utc": frame_ts}


# ── canonical typed PROJECTIONS over the raw store ────────────────────────────────────────────
# Readers, not writers. Each one names exactly which native fields it reads, so the field matrix can
# cite a projection by name and a future consumer is a new reader here rather than a re-collection.

def project_book_market_makers(frame: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten ONE OPTIONS_BOOK frame to per-market-maker rows.

    NATIVE fields read, and nothing else: BOOK_TIME; per level BID_PRICE/ASK_PRICE, TOTAL_VOLUME,
    NUM_BIDS/NUM_ASKS; per market maker EXCHANGE, BID_VOLUME/ASK_VOLUME, and field 2 (carried
    through under its raw decoder name, unresolved on purpose — see the module docstring).
    Every value is passed through unchanged; `side` is the only added key and it is structural,
    not a market claim. NOTHING here infers dealer ownership or direction.
    """
    out: list[dict[str, Any]] = []
    content = frame.get("content")
    if not isinstance(content, list):
        return out
    for entry in content:
        if not isinstance(entry, dict):
            continue
        book_time = entry.get("BOOK_TIME")
        key = entry.get("key")
        for side, price_field, count_field, size_field in (
                ("BID", "BID_PRICE", "NUM_BIDS", "BID_VOLUME"),
                ("ASK", "ASK_PRICE", "NUM_ASKS", "ASK_VOLUME")):
            levels = entry.get("BIDS" if side == "BID" else "ASKS")
            if not isinstance(levels, list):
                continue
            for level in levels:
                if not isinstance(level, dict):
                    continue
                makers = level.get("BIDS" if side == "BID" else "ASKS")
                if not isinstance(makers, list):
                    continue
                for mm in makers:
                    if not isinstance(mm, dict):
                        continue
                    out.append({
                        "symbol_key": key,
                        "book_time": book_time,
                        "side": side,
                        "price": level.get(price_field),
                        "level_total_volume": level.get("TOTAL_VOLUME"),
                        "market_maker_count": level.get(count_field),
                        "market_maker_id": mm.get("EXCHANGE"),
                        "market_maker_size": mm.get(size_field),
                        "market_maker_time_raw": mm.get("SEQUENCE"),
                    })
    return out
