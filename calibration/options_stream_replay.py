"""OPTIONS FLOW — reconstruct what was KNOWABLE at an instant. Causally, with no lookahead.

THE MEASURED FACT THIS IS BUILT ON. The two options services do NOT have the same message
semantics, and treating them alike silently corrupts history. Measured on the committed capture
(reports/of_capability_probe/options_20260820T1354Z, 6 frames per service, one contract):

  LEVELONE_OPTIONS is a DELTA / SPARSE service.
      Fields per content entry across the six frames: 55, 23, 17, 17, 17, 11.
      Only TEN field names appear in every entry (ASK_PRICE, ASK_SIZE, BID_PRICE, BID_SIZE,
      MARK, MARK_CHANGE, MARK_CHANGE_PERCENT, QUOTE_TIME_MILLIS, TOTAL_VOLUME,
      TRADE_TIME_MILLIS); the union across all frames is 55.
      The first frame after subscription carries the full picture and later frames carry only
      what CHANGED. Reading any single later frame as a snapshot would show GAMMA, DELTA and
      OPEN_INTEREST as ABSENT when they were merely unchanged — the exact opposite of the truth.

  OPTIONS_BOOK is a FULL REPLACEMENT service.
      Every frame carried exactly the same three fields (BOOK_TIME, BIDS, ASKS). The book is
      re-sent whole, so the latest frame at-or-before an instant IS the state; folding book
      frames together would splice price levels that never coexisted.

SAMPLE HONESTY: six frames per service, one symbol, ninety seconds. That is enough to establish
that L1 is sparse (a 55-field frame followed by an 11-field frame cannot be a snapshot stream)
but it is NOT enough to characterise every field's update cadence. Where the evidence is thin
this module reports observation AGE rather than pretending freshness.

NO LOOKAHEAD, structurally. Every query filters frame_ts_ms <= as_of_ms in SQL. A reconstruction
cannot see a frame that had not arrived, because such rows are never fetched — not because a
later step remembers to discard them.

WHAT THIS IS NOT. Reconstructed native fields are NATIVE OBSERVATIONS, nothing more. This module
derives no greeks, infers no dealer ownership, inventory sign, aggressor side, or opening and
closing intent, and produces nothing that may enter Decide.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SERVICE_LEVELONE = "LEVELONE_OPTIONS"
SERVICE_BOOK = "OPTIONS_BOOK"

#: Vendor service metadata that identifies the frame rather than describing the instrument.
#: Folded through like any other field, but flagged so a reader does not mistake them for
#: market observations.
SERVICE_METADATA_FIELDS = frozenset({"key", "delayed", "assetMainType", "cusip"})


def _connect(db_path: Path | str | None) -> sqlite3.Connection:
    from calibration.options_stream_coverage import coverage_db_path
    return sqlite3.connect(f"file:{coverage_db_path(db_path)}?mode=ro", uri=True, timeout=30.0)


def level_one_state_as_of(db_path: Path | str | None, symbol: str, as_of_ms: int, *,
                          since_ms: int | None = None,
                          check_coverage: bool = True) -> dict[str, Any]:
    """Fold LEVELONE_OPTIONS deltas up to `as_of_ms` into the state known at that instant.

    Returns each field with the value last observed at-or-before the instant AND the timestamp
    at which it was observed, because on a delta stream those are different questions. A caller
    that only wants values gets them; a caller that needs to know a GAMMA is forty minutes old
    can see that instead of being quietly misled.

    `since_ms` bounds how far back the fold reaches. Default is the start of the coverage epoch
    containing `as_of_ms` — folding across a subscription gap would carry a value forward over a
    window in which we were not watching and could not have seen it change.
    """
    out: dict[str, Any] = {
        "symbol": symbol, "as_of_ms": int(as_of_ms), "service": SERVICE_LEVELONE,
        "fields": {}, "frames_folded": 0, "coverage": None, "notes": [],
    }

    if check_coverage:
        from calibration.options_stream_coverage import was_subscribed
        if not was_subscribed(db_path, symbol, as_of_ms, service=SERVICE_LEVELONE):
            out["coverage"] = "NOT_SUBSCRIBED"
            out["notes"].append(
                "no coverage epoch contains this instant — an empty state here is OUR gap, "
                "not an observation that the contract was quiet")
            return out
        out["coverage"] = "SUBSCRIBED"

    if since_ms is None:
        since_ms = _epoch_start_for(db_path, symbol, as_of_ms, SERVICE_LEVELONE)
        if since_ms is None:
            since_ms = 0
        else:
            out["notes"].append(
                f"folded from the start of the containing coverage epoch ({since_ms}); values "
                f"are not carried across a subscription gap")

    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT f.frame_ts_ms, f.payload_json, s.content_idx "
            "FROM options_stream_frame_symbols s "
            "JOIN options_stream_frames f ON f.id = s.frame_id "
            "WHERE s.symbol_key = ? AND f.service = ? "
            "  AND f.frame_ts_ms <= ? AND f.frame_ts_ms >= ? "
            "ORDER BY f.frame_ts_ms ASC, f.id ASC",
            (symbol, SERVICE_LEVELONE, int(as_of_ms), int(since_ms))).fetchall()
    except sqlite3.Error as e:
        out["notes"].append(f"query failed: {e}")
        return out
    finally:
        conn.close()

    fields: dict[str, dict[str, Any]] = {}
    for frame_ts, payload, idx in rows:
        entry = _content_entry(payload, idx)
        if not isinstance(entry, dict):
            continue
        out["frames_folded"] += 1
        for k, v in entry.items():
            # LAST WRITE WINS, in vendor frame-time order. Absence in a later frame means
            # UNCHANGED on this service, so a missing key must never clear a held value.
            fields[k] = {"value": v, "observed_ts_ms": int(frame_ts),
                         "age_ms": int(as_of_ms) - int(frame_ts),
                         "is_service_metadata": k in SERVICE_METADATA_FIELDS}
    out["fields"] = fields
    out["field_count"] = len(fields)
    if rows:
        out["first_frame_ts_ms"] = int(rows[0][0])
        out["last_frame_ts_ms"] = int(rows[-1][0])
        ages = [f["age_ms"] for f in fields.values()]
        out["max_field_age_ms"] = max(ages) if ages else None
        out["min_field_age_ms"] = min(ages) if ages else None
    else:
        out["notes"].append(
            "covered, but no frames at or before this instant — nothing was knowable yet")
    return out


def book_state_as_of(db_path: Path | str | None, symbol: str, as_of_ms: int, *,
                     check_coverage: bool = True) -> dict[str, Any]:
    """Latest OPTIONS_BOOK frame at-or-before `as_of_ms`. NOT folded, deliberately.

    The book is re-sent whole on every frame (measured: all six captured frames carried exactly
    BOOK_TIME/BIDS/ASKS). Folding would splice price levels from different instants into a book
    that never existed, which is worse than no answer.
    """
    out: dict[str, Any] = {
        "symbol": symbol, "as_of_ms": int(as_of_ms), "service": SERVICE_BOOK,
        "book": None, "coverage": None, "notes": [],
        "semantics": "FULL_REPLACEMENT — latest frame wins; frames are never merged",
    }
    if check_coverage:
        from calibration.options_stream_coverage import was_subscribed
        if not was_subscribed(db_path, symbol, as_of_ms, service=SERVICE_BOOK):
            out["coverage"] = "NOT_SUBSCRIBED"
            out["notes"].append("no coverage epoch contains this instant — our gap, not a quiet book")
            return out
        out["coverage"] = "SUBSCRIBED"

    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT f.frame_ts_ms, f.payload_json, s.content_idx "
            "FROM options_stream_frame_symbols s "
            "JOIN options_stream_frames f ON f.id = s.frame_id "
            "WHERE s.symbol_key = ? AND f.service = ? AND f.frame_ts_ms <= ? "
            "ORDER BY f.frame_ts_ms DESC, f.id DESC LIMIT 1",
            (symbol, SERVICE_BOOK, int(as_of_ms))).fetchone()
    except sqlite3.Error as e:
        out["notes"].append(f"query failed: {e}")
        return out
    finally:
        conn.close()

    if not row:
        out["notes"].append("covered, but no book frame at or before this instant")
        return out
    frame_ts, payload, idx = row
    out["book"] = _content_entry(payload, idx)
    out["observed_ts_ms"] = int(frame_ts)
    out["age_ms"] = int(as_of_ms) - int(frame_ts)
    return out


def _content_entry(payload_json: str, content_idx: int) -> Any:
    """The addressed contract entry inside a retained frame."""
    try:
        frame = json.loads(payload_json)
    except (TypeError, ValueError):
        return None
    content = frame.get("content") if isinstance(frame, dict) else None
    if not isinstance(content, list) or not (0 <= int(content_idx) < len(content)):
        return None
    return content[int(content_idx)]


def _epoch_start_for(db_path: Path | str | None, symbol: str, at_ms: int,
                     service: str) -> int | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT started_ms FROM options_stream_coverage_epochs "
            "WHERE symbol = ? AND service = ? AND started_ms <= ? "
            "  AND (ended_ms IS NULL OR ended_ms >= ?) "
            "ORDER BY started_ms DESC LIMIT 1",
            (symbol, service, int(at_ms), int(at_ms))).fetchone()
        return int(row[0]) if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def replay_window(db_path: Path | str | None, symbol: str, start_ms: int, end_ms: int,
                  step_ms: int = 60_000) -> list[dict[str, Any]]:
    """Step through a window, reconstructing state at each instant WITHOUT lookahead.

    Each step is an independent causal reconstruction rather than a running mutation, so a bug
    in one step cannot contaminate later ones — and each carries its own field ages, which is
    what makes a delta stream honest to read.
    """
    out = []
    t = int(start_ms)
    while t <= int(end_ms):
        st = level_one_state_as_of(db_path, symbol, t)
        out.append({
            "as_of_ms": t,
            "coverage": st.get("coverage"),
            "field_count": st.get("field_count", 0),
            "frames_folded": st.get("frames_folded", 0),
            "max_field_age_ms": st.get("max_field_age_ms"),
        })
        t += int(step_ms)
    return out
