"""json_blob_codec: what encode_json_blob stores, decode_json_blob reads back.

And a row written before compression (plain JSON text) is read the same way.
"""

from __future__ import annotations

import datetime
import gzip
import json
import time

import pytest

from json_blob_codec import decode_json_blob, encode_json_blob


def test_round_trip_a_dict():
    obj = {"a": 1, "b": [1, 2, 3], "c": None}
    assert decode_json_blob(encode_json_blob(obj, default=str)) == obj


def test_round_trip_a_list_of_dicts_like_a_real_contract_list():
    contracts = [{"symbol": "SPY_123", "strike": 500.0}, {"symbol": "SPY_124", "strike": 505.0}]
    assert decode_json_blob(encode_json_blob(contracts, default=str)) == contracts


def test_encoded_value_is_gzip_bytes_with_the_magic_header():
    blob = encode_json_blob({"x": 1}, default=str)
    assert isinstance(blob, bytes)
    assert blob[:2] == b"\x1f\x8b"
    # Also a real, independently-decodable gzip stream -- not just header bytes.
    assert json.loads(gzip.decompress(blob)) == {"x": 1}


def test_decode_reads_a_pre_migration_plain_json_string_unchanged():
    """The exact shape sqlite3 hands back for a TEXT-affinity column never touched by this codec.

    A plain Python str, not bytes.
    """
    legacy_row_value = json.dumps({"legacy": True, "n": 42})
    assert decode_json_blob(legacy_row_value) == {"legacy": True, "n": 42}


def test_decode_reads_plain_json_encoded_as_raw_utf8_bytes():
    """A plain (uncompressed) JSON string stored as BLOB affinity bytes is not misread as gzip."""
    raw = json.dumps([1, 2, 3]).encode("utf-8")
    assert decode_json_blob(raw) == [1, 2, 3]


def test_decode_malformed_payload_raises():
    with pytest.raises(json.JSONDecodeError):
        decode_json_blob("{not valid json")


def test_default_str_matches_existing_call_sites_non_json_native_types():
    obj = {"ts": datetime.date(2026, 1, 1)}
    decoded = decode_json_blob(encode_json_blob(obj, default=str))
    assert decoded == {"ts": "2026-01-01"}


def test_encode_json_blob_is_deterministic_across_calls():
    """gzip.compress embeds a wall-clock timestamp by default.

    Without mtime=0, the same content would compress to different bytes on every call.
    """
    obj = {"a": 1, "b": [1, 2, 3]}
    first = encode_json_blob(obj, default=str)
    time.sleep(1.1)  # gzip's mtime field has 1-second resolution
    second = encode_json_blob(obj, default=str)
    assert first == second


def test_a_table_can_hold_both_pre_and_post_migration_rows_at_once():
    """The exact scenario a live backfill runs under: some rows already compressed, some not yet.

    Both must decode correctly with no per-row flag.
    """
    legacy = json.dumps({"row": "legacy"})
    migrated = encode_json_blob({"row": "migrated"}, default=str)
    assert decode_json_blob(legacy) == {"row": "legacy"}
    assert decode_json_blob(migrated) == {"row": "migrated"}
