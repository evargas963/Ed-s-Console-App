"""The vendor-coercion lock's field set (tools/check_vendor_field_coercion.py VENDOR_FIELDS) covers
every numeric leaf of a real Schwab option contract: each is in VENDOR_FIELDS or listed in
EXCLUDED_NUMERIC_LEAVES with a reason. The truth comes from every real captured chain committed
under tests/fixtures (CDE, CRWD, SPY 0DTE, TSLA), so a hand list cannot drift."""
from __future__ import annotations

import json
from pathlib import Path

from tools.check_vendor_field_coercion import EXCLUDED_NUMERIC_LEAVES, VENDOR_FIELDS

_FIXTURES = Path(__file__).parent / "fixtures"
_CHAINS = {name: json.loads((_FIXTURES / name).read_text(encoding="utf-8"))["chain"] for name in (
    "real_cde_complete_chain_half_dollar.json", "real_crwd_complete_chain_quarter.json",
    "real_spy_0dte_chain.json", "real_tsla_complete_chain_strike_range_all.json")}


def test_vendor_fields_covers_every_numeric_contract_leaf():
    numeric = {k for chain in _CHAINS.values() for c in chain for k, v in c.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)}
    assert len(numeric) > 20, f"only {len(numeric)} numeric fields read -- the fixtures are not real chains"
    uncovered = sorted(numeric - set(VENDOR_FIELDS) - set(EXCLUDED_NUMERIC_LEAVES))
    assert not uncovered, (
        f"numeric Schwab contract fields in neither VENDOR_FIELDS nor EXCLUDED_NUMERIC_LEAVES: {uncovered}")
