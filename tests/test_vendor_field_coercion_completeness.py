"""The vendor-coercion lock's field set (tools/check_vendor_field_coercion.py VENDOR_FIELDS) covers
every numeric leaf of a real Schwab option contract: each is in VENDOR_FIELDS or listed in
EXCLUDED_NUMERIC_LEAVES with a reason. The truth comes from a real captured chain
(tests/fixtures/real_tsla_complete_chain_strike_range_all.json), so a hand list cannot drift."""
from __future__ import annotations

import json
from pathlib import Path

from tools.check_vendor_field_coercion import EXCLUDED_NUMERIC_LEAVES, VENDOR_FIELDS

_CHAIN = json.loads((Path(__file__).parent / "fixtures" / "real_tsla_complete_chain_strike_range_all.json")
                    .read_text(encoding="utf-8"))["chain"]


def test_vendor_fields_covers_every_numeric_contract_leaf():
    numeric = {k for c in _CHAIN for k, v in c.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)}
    uncovered = sorted(numeric - set(VENDOR_FIELDS) - set(EXCLUDED_NUMERIC_LEAVES))
    assert not uncovered, (
        f"numeric Schwab contract fields in neither VENDOR_FIELDS nor EXCLUDED_NUMERIC_LEAVES: {uncovered}")
