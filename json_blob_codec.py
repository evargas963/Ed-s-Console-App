"""gzip for the JSON and the answer bodies stored in SQLite.

`complete_chain_captures.chain_json`: gzip bytes, or, for a row written before compression, its
plain JSON text; the read tells the two apart by gzip's own magic bytes (0x1f 0x8b), so both
kinds are read. Schwab's REST answers (`rest_chains_raw`, `rest_quotes_raw` and each capture's
`chains_answer`): the body's text exactly as received, gzip-compressed (lossless).
"""

from __future__ import annotations

import gzip
import json
from typing import Any

_GZIP_MAGIC = b"\x1f\x8b"
#: gzip's own default level
_COMPRESSLEVEL = 6


def encode_json_blob(obj: Any, *, default: Any) -> bytes:
    """`obj` as gzip-compressed JSON (`default` as json.dumps takes it).

    `mtime=0`: the same object always gives the same bytes.
    """
    raw = json.dumps(obj, default=default).encode("utf-8")
    return gzip.compress(raw, compresslevel=_COMPRESSLEVEL, mtime=0)


def encode_text_blob(text: str) -> bytes:
    """`text` exactly as received (Schwab's answer body), gzip-compressed; `mtime=0` as above."""
    return gzip.compress(text.encode("utf-8"), compresslevel=_COMPRESSLEVEL, mtime=0)


def decode_text_blob(value: bytes) -> str:
    """Return the text encode_text_blob was given, character for character."""
    return gzip.decompress(value).decode("utf-8")


def decode_json_blob(value: bytes | str) -> Any:
    """Return the JSON a stored value holds: gzip bytes, or a pre-compression row's plain JSON."""
    if isinstance(value, bytes) and value[:2] == _GZIP_MAGIC:
        value = gzip.decompress(value)
    return json.loads(value)
