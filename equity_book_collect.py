"""Equity book-depth collection on the canonical Collect daemon — finding-#1 Section 1.

The daemon's ONE StreamClient adds NASDAQ_BOOK + NYSE_BOOK. Each book frame is PUBLISHED raw onto
the daemon's single bus (O(1), no SQLite on the receive loop); the daemon's ONE CaptureWriter
persists it through its OWN connection via a registered `equitybook` topic writer — never a second
connection to stream_capture.db. This is the exact seam options already use.

SECTION-1 GATE. Handlers + persister are registered UNCONDITIONALLY (inert without a subscription).
Only the vendor SUBSCRIBE is gated on ED_EQUITY_BOOK_CAPTURE, so merging/deploying this section
changes nothing on the running daemon until the operator sets that flag for a live proof. Retiring
the UI's own book socket is a LATER section — this one only lets the daemon OWN the capture.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

EQUITY_BOOK_TOPIC = "equitybook"
ED_EQUITY_BOOK_CAPTURE_ENV = "ED_EQUITY_BOOK_CAPTURE"
SERVICES = ("NASDAQ_BOOK", "NYSE_BOOK")
_HANDLER_ATTR = {"NASDAQ_BOOK": "add_nasdaq_book_handler", "NYSE_BOOK": "add_nyse_book_handler"}
_SUBS_ATTR = {"NASDAQ_BOOK": "nasdaq_book_subs", "NYSE_BOOK": "nyse_book_subs"}


def equity_book_capture_enabled() -> bool:
    return str(os.environ.get(ED_EQUITY_BOOK_CAPTURE_ENV, "")).strip().lower() in (
        "1", "true", "yes", "on")


def make_equity_book_frame_handler(
        bus: Any, service: str,
        on_beat: Callable[[str], None] | None = None) -> Callable[[dict], None]:
    """PUBLISH one raw book frame onto the daemon's bus and return. The frame does not touch storage
    here — it rides the same bus the equity handlers use, and the single CaptureWriter persists it on
    its own task. A publish problem must NEVER propagate into the shared loop that services equities.
    """
    def _handler(msg: dict) -> None:
        if bus is None:
            return
        try:
            if on_beat is not None:
                on_beat(service)
            key = ""
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list) and content and isinstance(content[0], dict):
                key = str(content[0].get("key") or "")
            bus.publish(f"{EQUITY_BOOK_TOPIC}.{key}",
                        {"service": service, "frame": msg,
                         "received_ts_ms": int(time.time() * 1000.0)})
        except Exception as e:  # noqa: BLE001
            log.debug("equity book frame publish (%s): %s", service, e)
    return _handler


def make_equity_book_topic_writer() -> Callable[[Any, str, dict], int]:
    """Build the persister the daemon registers on its CaptureWriter for the 'equitybook' kind.
    fn(conn, topic, msg) -> rows written, on the writer's OWN connection. Schema is ensured lazily on
    the first frame (the connection is the daemon's, created before any book frame arrives).
    """
    from calibration.equity_book_frames import (ensure_equity_book_schema, frame_row_values,
                                                 frame_symbol_rows)
    state = {"schema_ready": False}

    def _write(conn: Any, topic: str, msg: dict) -> int:
        if not isinstance(msg, dict):
            return 0
        if not state["schema_ready"]:
            ensure_equity_book_schema(conn)
            state["schema_ready"] = True
        vals = frame_row_values(msg.get("service"), msg.get("frame"), msg.get("received_ts_ms"))
        if vals is None:
            return 0
        cur = conn.execute(
            "INSERT INTO equity_book_frames (service, frame_ts_ms, received_ts_ms, ingest_lag_ms, "
            "n_symbols, payload_json) VALUES (?,?,?,?,?,?)", vals)
        rows = frame_symbol_rows(cur.lastrowid, msg.get("frame"))
        if rows:
            conn.executemany(
                "INSERT OR REPLACE INTO equity_book_frame_symbols (frame_id, symbol_key, "
                "content_idx) VALUES (?,?,?)", rows)
        return 1
    return _write


def register_equity_book_handlers(sc: Any, bus: Any,
                                  on_beat: Callable[[str], None] | None = None) -> None:
    """Attach NASDAQ_BOOK + NYSE_BOOK handlers to the daemon's EXISTING client. Inert until something
    subscribes — registration is separated from subscription so this is safe to run unconditionally
    and the enable decision stays in exactly one place (subscribe_equity_books)."""
    for service, attr in _HANDLER_ATTR.items():
        fn = getattr(sc, attr, None)
        if fn is None:
            log.warning("stream client has no %s — equity %s cannot be collected", attr, service)
            continue
        try:
            fn(make_equity_book_frame_handler(bus, service, on_beat))
        except Exception as e:  # noqa: BLE001
            log.warning("registering %s failed: %s", attr, e)


async def subscribe_equity_books(sc: Any, symbols: list[str]) -> list[str]:
    """SUBSCRIBE the two book services for `symbols` on the daemon's one StreamClient. Returns the
    services actually subscribed. The caller gates this on equity_book_capture_enabled()."""
    done: list[str] = []
    for service, attr in _SUBS_ATTR.items():
        fn = getattr(sc, attr, None)
        if fn is None:
            log.warning("stream client has no %s — cannot subscribe equity %s", attr, service)
            continue
        try:
            await fn(symbols)
            done.append(service)
        except Exception as e:  # noqa: BLE001
            log.warning("subscribing equity %s failed: %s", service, e)
    return done
