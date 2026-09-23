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
    return encode_text_blob(raw)


def encode_text_blob(text: "str | bytes") -> bytes:
    """gzip an ALREADY-serialized JSON string/bytes directly, with no re-serialization.

    Some call sites (execution_identity.py's canonical_envelope_json, for one) build
    their own exact JSON text for other reasons (hashing it, or a specific
    sort_keys/separators contract) before this codec ever sees it -- compressing that
    exact text, rather than parsing and re-dumping it, guarantees the compressed blob
    decodes back to byte-identical text, not just semantically-equal JSON.

    `mtime=0` is REQUIRED, not cosmetic: gzip.compress embeds a wall-clock timestamp in
    its header by default, so identical input produces DIFFERENT output bytes on every
    call. Any code that compares stored blobs for byte-identity (execution_identity.py's
    own dedup-collision check is exactly this) would break silently without it."""
    raw = text.encode("utf-8") if isinstance(text, str) else text
    return gzip.compress(raw, compresslevel=_COMPRESSLEVEL, mtime=0)


def decode_text_blob(value: "bytes | bytearray | str | None") -> "str | None":
    """Inverse of encode_text_blob: returns the raw JSON TEXT, not parsed.

    Required (not just decode_json_blob's parsed form) by any caller that re-verifies a
    content-address hash against the exact stored bytes, or does a raw substring search
    over the envelope text (execution_identity.py does both) -- parsing and re-serializing
    would not reliably reproduce the original byte sequence a hash was computed over.

    Also transparently reads a pre-migration plain-JSON row (sqlite3 returns
    TEXT-affinity values already holding a Python str, never bytes) unchanged -- safe to
    deploy on the read path immediately, with no coordinated backfill cutover."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        if bytes(value[:2]) == _GZIP_MAGIC:
            return gzip.decompress(bytes(value)).decode("utf-8")
        return bytes(value).decode("utf-8")
    return value


def decode_json_blob(value: "bytes | bytearray | str | None") -> Any:
    """Inverse of encode_json_blob: decode_text_blob, then json.loads the result.

    Returns None for a NULL column (never raises on the mere absence of a value); a
    malformed/undecodable payload still raises, matching every existing call site's own
    json.loads behavior on a corrupt row."""
    text = decode_text_blob(value)
    if text is None:
        return None
    return json.loads(text)


def is_compressed_blob(value: "bytes | bytearray | str | None") -> bool:
    """True only for a value this codec would actually gzip-decompress -- used by
    backfill tools to report real progress (how many rows are still plain-text) without
    re-implementing the magic-header check."""
    if not isinstance(value, (bytes, bytearray)):
        return False
    return bytes(value[:2]) == _GZIP_MAGIC
