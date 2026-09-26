"""json_blob_codec's own contract: encode/decode round-trips, and -- the property every
call site's safety depends on -- decode_json_blob transparently reads a pre-migration
plain-JSON string exactly like a legacy call site's own json.loads(row[N]) always did,
with no schema change and no coordinated cutover."""
from __future__ import annotations

import gzip
import json

import pytest

from json_blob_codec import (
    decode_json_blob,
    decode_text_blob,
    encode_json_blob,
    encode_text_blob,
)


def test_round_trip_a_dict():
    obj = {"a": 1, "b": [1, 2, 3], "c": None}
    assert decode_json_blob(encode_json_blob(obj)) == obj


def test_round_trip_a_list_of_dicts_like_a_real_contract_list():
    contracts = [{"symbol": "SPY_123", "strike": 500.0}, {"symbol": "SPY_124", "strike": 505.0}]
    assert decode_json_blob(encode_json_blob(contracts)) == contracts


def test_encoded_value_is_gzip_bytes_with_the_magic_header():
    blob = encode_json_blob({"x": 1})
    assert isinstance(blob, bytes)
    assert blob[:2] == b"\x1f\x8b"
    # Also a real, independently-decodable gzip stream -- not just header bytes.
    assert json.loads(gzip.decompress(blob)) == {"x": 1}


def test_decode_reads_a_pre_migration_plain_json_string_unchanged():
    """The exact shape sqlite3 hands back for a TEXT-affinity column that has never
    been touched by this codec: a plain Python str, not bytes."""
    legacy_row_value = json.dumps({"legacy": True, "n": 42})
    assert decode_json_blob(legacy_row_value) == {"legacy": True, "n": 42}


def test_decode_reads_plain_json_encoded_as_raw_utf8_bytes():
    """Defensive: a plain (uncompressed) JSON string stored as BLOB affinity bytes,
    not just str -- still must not be misread as gzip."""
    raw = json.dumps([1, 2, 3]).encode("utf-8")
    assert decode_json_blob(raw) == [1, 2, 3]


def test_decode_none_returns_none():
    assert decode_json_blob(None) is None


def test_decode_malformed_payload_raises():
    with pytest.raises(json.JSONDecodeError):
        decode_json_blob("{not valid json")


def test_default_str_matches_existing_call_sites_non_json_native_types():
    import datetime
    obj = {"ts": datetime.date(2026, 1, 1)}
    decoded = decode_json_blob(encode_json_blob(obj, default=str))
    assert decoded == {"ts": "2026-01-01"}




def test_encode_json_blob_is_deterministic_across_calls():
    """gzip.compress embeds a wall-clock timestamp by default -- without mtime=0, the
    same logical content would compress to DIFFERENT bytes on every call, silently
    breaking any code that compares stored blobs for byte-identity (e.g.
    execution_identity.py's dedup-collision check)."""
    import time
    obj = {"a": 1, "b": [1, 2, 3]}
    first = encode_json_blob(obj)
    time.sleep(1.1)   # gzip's mtime field has 1-second resolution
    second = encode_json_blob(obj)
    assert first == second


def test_encode_text_blob_compresses_already_serialized_text_exactly():
    """A caller that built its own canonical JSON text (sort_keys, specific separators)
    for hashing purposes must get that EXACT text back, not a re-serialized copy that
    merely happens to be semantically equal."""
    text = json.dumps({"z": 1, "a": 2}, sort_keys=True, separators=(",", ":"))
    blob = encode_text_blob(text)
    assert blob[:2] == b"\x1f\x8b"
    decompressed = gzip.decompress(blob).decode("utf-8")
    assert decompressed == text   # byte-exact, not just JSON-equal


def test_encode_text_blob_is_also_deterministic():
    import time
    text = json.dumps({"a": 1})
    first = encode_text_blob(text)
    time.sleep(1.1)
    second = encode_text_blob(text)
    assert first == second


def test_decode_text_blob_round_trips_byte_exact_through_compression():
    """The property execution_identity.py's content-address hash check depends on:
    decode_text_blob(encode_text_blob(text)) must equal `text` exactly, not just
    parse to an equal JSON value."""
    text = json.dumps({"z": 1, "a": [3, 2, 1]}, sort_keys=True, separators=(",", ":"))
    assert decode_text_blob(encode_text_blob(text)) == text


def test_decode_text_blob_reads_a_legacy_plain_string_unchanged():
    text = json.dumps({"legacy": True})
    assert decode_text_blob(text) == text


def test_decode_text_blob_none_returns_none():
    assert decode_text_blob(None) is None


def test_a_table_can_hold_both_pre_and_post_migration_rows_at_once():
    """The exact scenario a live backfill runs under: some rows already compressed,
    some not yet -- both must decode correctly with no per-row flag."""
    legacy = json.dumps({"row": "legacy"})
    migrated = encode_json_blob({"row": "migrated"})
    assert decode_json_blob(legacy) == {"row": "legacy"}
    assert decode_json_blob(migrated) == {"row": "migrated"}
