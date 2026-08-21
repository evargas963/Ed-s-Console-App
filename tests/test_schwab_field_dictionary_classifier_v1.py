"""M3 regression lock (RC-439): the field-dictionary classifier must file BOOK-stream
fields as `streaming_book`, not the `streaming_quote` catch-all.

`BOOK_TIME` and the top-level book `SEQUENCE` carry no BID_/ASK_/QUOTE_ token, so before
RC-439 they fell through every specific rule to the `^streaming.` fallback and were
mislabeled `streaming_quote`. This test pins the corrected classification and proves the
genuine quote fields are unaffected.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import schwab_field_dictionary_builder as builder


def test_book_time_is_streaming_book():
    assert builder.categorize("streaming.content.*.BOOK_TIME") == "streaming_book"


def test_top_level_sequence_is_streaming_book():
    assert builder.categorize("streaming.content.*.SEQUENCE") == "streaming_book"


def test_nested_per_exchange_sequence_stays_streaming_book():
    assert builder.categorize("streaming.content.*.ASKS.*.ASKS.*.SEQUENCE") == "streaming_book"


def test_genuine_level_one_quote_fields_stay_streaming_quote():
    # The fix must not pull real quote fields into the book bucket.
    assert builder.categorize("streaming.content.*.BID_PRICE") == "streaming_quote"
    assert builder.categorize("streaming.content.*.TOTAL_VOLUME") == "streaming_quote"


def test_num_bids_stays_book_via_nested_path():
    assert builder.categorize("streaming.content.*.BIDS.*.NUM_BIDS") == "streaming_book"
