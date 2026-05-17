"""Section 6 — Schwab dictionary derivation audit (signals + decision)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_section6_inventory_covers_every_function_all_scopes():
    from governance.section6_derivation_inventory import (
        SECTION6_DERIVATION_INVENTORY,
        SECTION6_FILES,
    )
    from governance.section_inventory_gate import assert_inventory_covers_all_functions

    assert_inventory_covers_all_functions(
        ROOT, SECTION6_FILES, SECTION6_DERIVATION_INVENTORY
    )


def test_section6_inventory_counts_and_dispositions():
    from governance.section6_derivation_inventory import (
        SECTION6_DERIVATION_INVENTORY,
        SECTION6_FILES,
    )
    from governance.section_inventory_gate import all_functions_in_file

    assert len(SECTION6_DERIVATION_INVENTORY) >= 88
    for rel in SECTION6_FILES:
        required = len(all_functions_in_file(ROOT, rel))
        inventoried = len({r.derivation for r in SECTION6_DERIVATION_INVENTORY if r.file == rel})
        assert inventoried == required, f"{rel}: {inventoried} != {required}"

    keep = [r for r in SECTION6_DERIVATION_INVENTORY if r.disposition == "KEEP_DERIVED"]
    assert len(keep) >= 40
    assert any(r.file == "signals.py" and r.derivation == "compute_signals" for r in keep)
    assert any(r.file == "call_engine.py" and r.derivation == "compute_call" for r in keep)


def test_section6_inventory_registered_in_replacement_register():
    reg = (ROOT / "governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- SECTION6_DERIVATION_INVENTORY_START -->" in reg
    assert "88" in reg or "signals" in reg


def test_section6_no_direct_schwab_api_in_decision_layer():
    """Decision layer must not call Schwab client wrappers directly."""
    api_markers = (
        "safe_get_quote",
        "safe_get_chain",
        "safe_get_price_history",
        "get_price_history",
        "schwab_candles_to_bars",
    )
    for rel in (
        "signals.py",
        "prediction_engine.py",
        "call_engine.py",
        "multi_horizon_decision.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        hits = [m for m in api_markers if m in text]
        assert hits == [], f"{rel} must not call Schwab API: {hits}"


def test_signal_helpers_ordinal_none_disposition():
    from governance.section6_derivation_inventory import SECTION6_DERIVATION_INVENTORY

    row = next(
        r for r in SECTION6_DERIVATION_INVENTORY if r.derivation == "_ordinal"
    )
    assert row.disposition == "NONE"
