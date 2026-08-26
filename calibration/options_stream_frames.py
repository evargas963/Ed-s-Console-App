"""OPTIONS FLOW FOUNDATION — durable RAW retention for the entitled options stream (2026-08-26).

WHY THIS EXISTS. Schwab entitles two options streaming services that this console has never
subscribed to, proven deliverable by a committed capture
(reports/of_capability_probe/options_20260820T1354Z/, response_code 0, 91 + 90 frames in 90s):

  * LEVELONE_OPTIONS — 58 native fields per contract, including a STREAMING greeks/IV surface
    (DELTA/GAMMA/THETA/VEGA/RHO, VOLATILITY, OPEN_INTEREST) and the temporal keys
    QUOTE_TIME_MILLIS / TRADE_TIME_MILLIS that the once-per-cycle REST chain cannot give.
  * OPTIONS_BOOK — market-maker depth. Field identities are the VENDOR's documented names, not our
    reading of the payload:
    # num-semantics-ok: Schwab Trader API Streamer Guide (first-party, login-gated; provenance
    # preserved in reports/of_capability_probe/schwab_streamer_guide_book_fields_citation.md and
    # adjudicated PROVEN at the vendor-contract level in
    # reports/schwab_field_semantic_normalization_ledger_20260820.md, M8) documents the shared
    # BookFields mapping as: book field 1 = Market Snapshot Time; price-level field 2 = Market Maker
    # Count; price-level field 3 = Array of Market Makers; nested 0 = Market Maker ID; nested 1 =
    # Size; nested 2 = Quote Time. Position identity is independently reproduced by three community
    # decoders and matches our captured frames exactly.
    BOOK_TIME (Market Snapshot Time), per price level TOTAL_VOLUME and NUM_BIDS/NUM_ASKS (Market
    Maker Count), and nested EXCHANGE (Market Maker ID), BID_VOLUME/ASK_VOLUME (Size), field 2
    (Quote Time).
    ONE HONEST CAVEAT KEPT WITH THE DATA: the vendor NAMES nested 0 "Market Maker ID", but the
    values our captures actually carry are venue codes (AMEX, BATS, BOSX, CBOE, EDGX, GMNI, ISEX,
    MEMX, ... 13 distinct in one frame). Vendor naming is authoritative for the field's identity;
    what the value domain turns out to mean for attribution is a separate question this module does
    not answer and must not pre-judge.

THE DESIGN IS RAW-FIRST, ON PURPOSE. The DECODED frame is stored whole, one row per frame, with no
projection at write time — so no field can be lost by an omission in today's parser, which is what
cost us the chain envelope. Typed projections are READERS over this store, so adding a consumer
later is a query change and never a re-collection: the history is already there. This is
deliberately NOT hundreds of columns.

PRECISELY WHAT IS PRESERVED (corrected 2026-08-26 after review — the first draft said "verbatim as
the vendor sent it", which overstates). This stores the DECODED frame object the streaming client
hands over, serialised to JSON. It is NOT byte-identical retention of the WebSocket wire message:
no wire bytes are captured at this layer, and the client library has already parsed the envelope.
Nothing lossy is applied to the decoded object, and a decoded frame round-trips through JSON
unchanged (tested). Literal wire fidelity would be a different, unproven claim and is not made.

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
#: CLOCK CONTRACT (corrected 2026-08-26 after review). Schwab frame timestamps are EPOCH
#: MILLISECONDS — measured on the committed capture: 1787234092900, which is ms, not seconds. Our
#: receive clock is time.time(), i.e. epoch SECONDS. The first version stored the vendor value in a
#: column beside the receive clock and promised "vendor-vs-local lag stays measurable", which was
#: false: subtracting seconds from milliseconds is meaningless and would have read as ~1.79e12 s of
#: lag. Both clocks are now stored in EXPLICIT MILLISECOND columns with the unit in the name, and the
#: lag is a stored, checkable quantity rather than a promise left to the reader.
#:
#: FRAME-vs-ROW GRAIN. A Schwab frame's `content` is a LIST and may carry MANY contracts at once
#: (our probe subscribed a single symbol, so every captured frame has exactly one entry — measured:
#: max content entries = 1 — but that is a property of the probe, not of the service). Indexing a
#: whole frame by content[0].key would make every contract after the first undiscoverable. The raw
#: frame is therefore stored ONCE, and a companion index row is written per contained contract.
TABLE_SQL = """
CREATE TABLE IF NOT EXISTS options_stream_frames (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    service           TEXT NOT NULL,     -- LEVELONE_OPTIONS | OPTIONS_BOOK
    frame_ts_ms       INTEGER NOT NULL,  -- VENDOR frame timestamp, epoch MILLISECONDS, as sent
    received_ts_ms    INTEGER NOT NULL,  -- OUR receive clock, epoch MILLISECONDS
    ingest_lag_ms     INTEGER,           -- received_ts_ms - frame_ts_ms, computed once, unit-correct
    n_contracts       INTEGER NOT NULL,  -- len(content); >1 means a multi-contract frame
    payload_json      TEXT NOT NULL,     -- the DECODED frame as received from the client library
    created_at        TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_osf_service_ts ON options_stream_frames(service, frame_ts_ms);

-- One row per CONTRACT contained in a frame, so a multi-contract frame stays discoverable for
-- every contract it carries rather than only its first.
CREATE TABLE IF NOT EXISTS options_stream_frame_symbols (
    frame_id     INTEGER NOT NULL REFERENCES options_stream_frames(id),
    symbol_key   TEXT NOT NULL,
    content_idx  INTEGER NOT NULL,       -- position within content[], so the entry is addressable
    PRIMARY KEY (frame_id, content_idx)
);
CREATE INDEX IF NOT EXISTS idx_osfs_symbol ON options_stream_frame_symbols(symbol_key);
"""

SERVICE_LEVELONE = "LEVELONE_OPTIONS"
SERVICE_BOOK = "OPTIONS_BOOK"
SUPPORTED_SERVICES = (SERVICE_LEVELONE, SERVICE_BOOK)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(TABLE_SQL)
    conn.commit()


#: Alias used by the batched ingestion writer. Same function, unambiguous at the import site.
ensure_options_stream_schema = ensure_schema


# ── ONE row shape, shared by both writers ─────────────────────────────────────────────────────
# There are two write paths into this table: persist_frame (one frame, its own connection) and
# calibration.options_stream_ingest (batched, on a dedicated writer thread). They MUST produce
# byte-identical rows. Two writers each building their own INSERT tuple is two sources of truth
# for one table, and they would drift the first time either is edited — so the row shaping lives
# here once and both call it.

def frame_row_values(service: str, frame: dict[str, Any],
                     received_ts_ms: int) -> tuple | None:
    """Build the options_stream_frames INSERT tuple, or None if the frame is unusable.

    Returning None rather than raising keeps the rejection decision identical on both paths: a
    malformed frame is skipped and counted, never allowed to abort a batch of good frames or to
    take the console down.
    """
    if service not in SUPPORTED_SERVICES or not isinstance(frame, dict):
        return None
    try:
        frame_ts_ms = int(frame.get("timestamp"))
        recv_ms = int(received_ts_ms)
    except (TypeError, ValueError):
        return None
    content = frame.get("content")
    return (
        service,
        frame_ts_ms,
        recv_ms,
        recv_ms - frame_ts_ms,
        len(content) if isinstance(content, list) else 0,
        json.dumps(frame, default=str, separators=(",", ":")),
    )


def frame_contract_entries(frame: dict[str, Any]) -> list[tuple[int, str]]:
    """(content_idx, symbol_key) for EVERY contract in the frame — not just the first.

    Entries without a key are skipped rather than given a fabricated one.
    """
    content = frame.get("content") if isinstance(frame, dict) else None
    if not isinstance(content, list):
        return []
    return [(i, c.get("key")) for i, c in enumerate(content)
            if isinstance(c, dict) and c.get("key")]


def frame_symbol_rows(frame_id: int, frame: dict[str, Any]) -> list[tuple[int, str, int]]:
    """options_stream_frame_symbols rows for one stored frame."""
    return [(frame_id, key, idx) for idx, key in frame_contract_entries(frame)]


def persist_frame(db_path: Path | str, *, service: str, frame: dict[str, Any],
                  received_ts_ms: int) -> dict[str, Any]:
    """Store ONE decoded vendor frame plus a per-contract index. Never raises on bad input.

    `received_ts_ms` is epoch MILLISECONDS — the same unit as the vendor's frame timestamp — so the
    stored ingest lag is a real quantity. Callers holding time.time() (seconds) must convert; the
    parameter name carries the unit precisely so the seconds/milliseconds mix that broke the first
    version cannot be reintroduced silently.

    WHAT "VERBATIM" MEANS HERE, stated exactly: this stores the DECODED frame object handed over by
    the streaming client, serialised to JSON. It is NOT byte-identical retention of the WebSocket
    wire message — no raw wire bytes are captured at this layer, key order is not preserved through
    the dict, and the client library has already parsed the envelope. Nothing lossy is done to the
    decoded object (no projection, no field selection), but a claim of literal wire fidelity would
    be false and is not made.

    Fails SOFT and says so: a collection path must not take the console down because one frame was
    malformed. A rejected frame is logged and reported, never silently swallowed.
    """
    if service not in SUPPORTED_SERVICES:
        return {"status": "rejected", "reason": f"unsupported service {service!r}"}
    if not isinstance(frame, dict):
        return {"status": "rejected", "reason": "frame is not a dict"}

    try:
        int(frame.get("timestamp"))
    except (TypeError, ValueError):
        return {"status": "rejected", "reason": "frame carries no usable vendor timestamp"}
    try:
        recv_ms = int(received_ts_ms)
    except (TypeError, ValueError):
        return {"status": "rejected", "reason": "received_ts_ms is not an integer millisecond clock"}

    # Shared row shaping — the batched writer calls exactly these, so both paths agree by
    # construction rather than by two developers remembering the same column order.
    values = frame_row_values(service, frame, recv_ms)
    if values is None:
        return {"status": "rejected", "reason": "frame could not be shaped into a row"}
    frame_ts_ms = values[1]
    entries = frame_contract_entries(frame)

    conn = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        ensure_schema(conn)
        cur = conn.execute(
            "INSERT INTO options_stream_frames"
            "(service, frame_ts_ms, received_ts_ms, ingest_lag_ms, n_contracts, payload_json)"
            " VALUES (?,?,?,?,?,?)",
            values,
        )
        frame_id = cur.lastrowid
        # every contained contract, not just the first
        conn.executemany(
            "INSERT OR REPLACE INTO options_stream_frame_symbols(frame_id, symbol_key, content_idx)"
            " VALUES (?,?,?)",
            frame_symbol_rows(frame_id, frame),
        )
        conn.commit()
    except sqlite3.Error as e:
        log.warning("options_stream_frames persist failed service=%s: %s", service, e)
        return {"status": "error", "reason": str(e)}
    finally:
        conn.close()
    return {"status": "written", "service": service, "frame_id": frame_id,
            "symbol_keys": [k for _, k in entries], "n_contracts": len(entries),
            "frame_ts_ms": frame_ts_ms, "ingest_lag_ms": recv_ms - frame_ts_ms}


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
