"""Section 7 — Schwab dictionary derivation audit (V2 decision + A2 lifecycle)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SECTION7_V2_GLOB = "v2_decision/*.py"


def test_section7_inventory_covers_every_function_all_scopes():
    from governance.section7_derivation_inventory import (
        SECTION7_DERIVATION_INVENTORY,
        SECTION7_FILES,
    )
    from governance.section_inventory_gate import assert_inventory_covers_all_functions

    assert_inventory_covers_all_functions(
        ROOT, SECTION7_FILES, SECTION7_DERIVATION_INVENTORY
    )


def test_section7_inventory_counts_and_dispositions():
    from governance.section7_derivation_inventory import (
        SECTION7_DERIVATION_INVENTORY,
        SECTION7_FILES,
    )
    from governance.section_inventory_gate import all_functions_in_file

    assert len(SECTION7_DERIVATION_INVENTORY) >= 139
    for rel in SECTION7_FILES:
        required = len(all_functions_in_file(ROOT, rel))
        inventoried = len({r.derivation for r in SECTION7_DERIVATION_INVENTORY if r.file == rel})
        assert inventoried == required, f"{rel}: {inventoried} != {required}"

    keep = [r for r in SECTION7_DERIVATION_INVENTORY if r.disposition == "KEEP_DERIVED"]
    assert len(keep) >= 60
    assert any(
        r.file == "v2_decision/a2_price_precedence.py"
        and r.derivation == "resolve_a2_contract_mid"
        for r in keep
    )


def test_section7_inventory_registered_in_replacement_register():
    reg = (ROOT / "governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- SECTION7_DERIVATION_INVENTORY_START -->" in reg
    assert "139" in reg or "v2_decision" in reg


def test_section7_v2_no_direct_schwab_api():
    """V2 decision layer must not call Schwab client wrappers directly."""
    api_markers = (
        "safe_get_quote",
        "safe_get_chain",
        "safe_get_price_history",
        "get_price_history",
        "schwab_candles_to_bars",
    )
    for path in (ROOT / "v2_decision").glob("*.py"):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        hits = [m for m in api_markers if m in text]
        assert hits == [], f"{path.name} must not call Schwab API: {hits}"


def test_a2_contract_mid_mark_first_ladder():
    from v2_decision.a2_price_precedence import resolve_a2_contract_mid

    mid, src = resolve_a2_contract_mid(chain_row={"mark": 2.5, "bid": 2.4, "ask": 2.6})
    assert mid == 2.5
    assert src == "schwab_chain_mark"

    mid2, src2 = resolve_a2_contract_mid(
        chain_row={"bid": 2.4, "ask": 2.6, "last": None, "mark": None}
    )
    assert mid2 == pytest.approx(2.5)
    assert src2 == "derived_bid_ask_mid"
