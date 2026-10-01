"""Transparent gzip compression for large JSON blob columns stored in SQLite.

RC-REHAB-3 (2026-09-23, operator-directed DB size reduction): `ed_console.db` measured
74.6 GB, of which 69.78 GB (93.5%) is JSON TEXT columns storing full option chains and
decision-record payloads, uncompressed, forever. A real sample compressed 13.8x with
plain gzip (396.2 KB -> 28.7 KB). This module is the ONE shared codec every writer/reader
of those columns uses, so there is exactly one compression format across every table.

SQLite is dynamically typed per VALUE, not per column: a column declared TEXT can hold
either a plain JSON string (a pre-migration row, or any row written before this codec
existed) or gzip-compressed bytes (a row written or backfilled after) with no schema
change and no ALTER TABLE. `decode_json_blob` tells the two apart using gzip's own
2-byte magic header (0x1f 0x8b) -- never a side-channel "is this compressed" column --
so old and new rows are both readable during and after a backfill, with no coordinated
cutover moment required. A table can be read successfully while a backfill against it is
still in progress, or never backfilled at all.
"""
from __future__ import annotations

import gzip
import json
from typing import Any

_GZIP_MAGIC = b"\x1f\x8b"

#: gzip level 6 is gzip's own default: a well-established balance of ratio vs CPU cost.
#: Not tuned further -- the measured 13.8x ratio on a real chain_json blob was already at
#: this level, and this codec runs on the write path of the live app, where compression
#: time is a cost every caller pays synchronously.
_COMPRESSLEVEL = 6


def encode_json_blob(obj: Any, *, default: Any = str) -> bytes:
    """Serialize `obj` to JSON, then gzip it, for storage in a TEXT/BLOB column.

    `default` is passed straight to json.dumps (default=str matches the existing
    call sites this codec replaces, which already tolerate non-JSON-native types by
    stringifying them)."""
    raw = json.dumps(obj, default=default).encode("utf-8")
    # mtime=0: gzip otherwise embeds a wall-clock timestamp, so identical content would
    # compress to different bytes on every call.
    return gzip.compress(raw, compresslevel=_COMPRESSLEVEL, mtime=0)


def decode_json_blob(value: "bytes | bytearray | str | None") -> Any:
    """Inverse of encode_json_blob. Also reads a pre-migration plain-JSON row (a str, or
    uncompressed bytes) unchanged.

    Returns None for a NULL column (never raises on the mere absence of a value); a
    malformed/undecodable payload still raises, matching every existing call site's own
    json.loads behavior on a corrupt row."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        if bytes(value[:2]) == _GZIP_MAGIC:
            return json.loads(gzip.decompress(bytes(value)).decode("utf-8"))
        return json.loads(bytes(value).decode("utf-8"))
    return json.loads(value)


