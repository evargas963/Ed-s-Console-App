"""Section 8 — Schwab dictionary derivation audit (MC + regime + volatility)."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_section8_inventory_covers_every_function_all_scopes():
    from governance.section8_derivation_inventory import (
        SECTION8_DERIVATION_INVENTORY,
        SECTION8_FILES,
    )
    from governance.section_inventory_gate import assert_inventory_covers_all_functions

    assert_inventory_covers_all_functions(
        ROOT, SECTION8_FILES, SECTION8_DERIVATION_INVENTORY
    )


def test_section8_inventory_counts_and_dispositions():
    from governance.section8_derivation_inventory import (
        SECTION8_DERIVATION_INVENTORY,
        SECTION8_FILES,
    )
    from governance.section_inventory_gate import all_functions_in_file

    assert len(SECTION8_DERIVATION_INVENTORY) >= 29
    for rel in SECTION8_FILES:
        required = len(all_functions_in_file(ROOT, rel))
        inventoried = len({r.derivation for r in SECTION8_DERIVATION_INVENTORY if r.file == rel})
        assert inventoried == required, f"{rel}: {inventoried} != {required}"

    keep = [r for r in SECTION8_DERIVATION_INVENTORY if r.disposition == "KEEP_DERIVED"]
    assert len(keep) >= 15
    assert any(r.file == "monte_carlo.py" and r.derivation == "simulate" for r in keep)


def test_section8_inventory_registered_in_replacement_register():
    reg = (ROOT / "schwab_field_inventory/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- SECTION8_DERIVATION_INVENTORY_START -->" in reg
    assert "29" in reg or "monte_carlo" in reg


def test_section8_no_direct_schwab_api():
    """MC/regime layer must not call Schwab client wrappers directly."""
    api_markers = (
        "safe_get_quote",
        "safe_get_chain",
        "safe_get_price_history",
        "schwab_candles_to_bars",
    )
    for rel in (
        "monte_carlo.py",
        "mc_fusion_adjustment.py",
        "volatility_regime.py",
        "regime_engine.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        hits = [m for m in api_markers if m in text]
        assert hits == [], f"{rel} must not call Schwab API: {hits}"


def test_mc_simulate_rejects_invalid_spot():
    from monte_carlo import simulate

    out = simulate(spot=0, iv=0.2, horizon_bars=5, n_paths=100)
    assert out.available is False or out.fallback_used
