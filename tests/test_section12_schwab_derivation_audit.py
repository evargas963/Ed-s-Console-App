"""Section 12 — Schwab dictionary derivation audit (liquidity playbook)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SECTION12_FILES = (
    "liquidity_models.py",
    "liquidity_value_engine.py",
    "print_liquidity_value_snapshot.py",
    "run_liquidity_sample.py",
)

_DATETIME_DEFAULT_ZERO = re.compile(r"""\.get\(\s*["']datetime["']\s*,\s*0\s*\)""")


def _section12_paths() -> set[Path]:
    return {ROOT / name for name in _SECTION12_FILES}


def test_section12_inventory_covers_every_function_all_scopes():
    from governance.section12_derivation_inventory import (
        SECTION12_DERIVATION_INVENTORY,
        SECTION12_FILES,
    )
    from governance.section_inventory_gate import assert_inventory_covers_all_functions

    assert_inventory_covers_all_functions(
        ROOT, SECTION12_FILES, SECTION12_DERIVATION_INVENTORY
    )
    assert SECTION12_FILES == frozenset(_SECTION12_FILES)


def test_section12_inventory_counts_and_dispositions():
    from governance.section12_derivation_inventory import (
        SECTION12_DERIVATION_INVENTORY,
        SECTION12_FILES,
    )
    from governance.section_inventory_gate import all_functions_in_file

    assert len(SECTION12_DERIVATION_INVENTORY) >= 37
    assert len(SECTION12_FILES) == 4
    for rel in SECTION12_FILES:
        required = len(all_functions_in_file(ROOT, rel))
        inventoried = len(
            {r.derivation for r in SECTION12_DERIVATION_INVENTORY if r.file == rel}
        )
        assert inventoried == required, f"{rel}: {inventoried} != {required}"


def test_section12_inventory_registered_in_replacement_register():
    reg = (ROOT / "governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- SECTION12_DERIVATION_INVENTORY_START -->" in reg
    assert "37" in reg or "liquidity_value_engine" in reg


def test_section12_engine_no_direct_schwab_api():
    """Core engine must not call Schwab client wrappers (CLI may fetch via adapter)."""
    api_markers = (
        "safe_get_quote",
        "safe_get_chain",
        "safe_get_price_history",
        "schwab_candles_to_bars",
        "build_client_from_token",
        "fetch_bars_via_schwab",
    )
    engine = ROOT / "liquidity_value_engine.py"
    text = engine.read_text(encoding="utf-8")
    hits = [m for m in api_markers if m in text]
    assert hits == [], f"liquidity_value_engine must not call Schwab API: {hits}"


def test_section12_no_datetime_default_zero():
    """Section 12 files must not use .get('datetime', 0) synthesis."""
    hits: list[str] = []
    for path in _section12_paths():
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if _DATETIME_DEFAULT_ZERO.search(line):
                hits.append(f"{path.name}:{i}:{line.strip()}")
    assert hits == [], f"datetime default-zero in section 12: {hits}"


def test_section12_resolve_bar_timestamp_replaced():
    from governance.section12_derivation_inventory import SECTION12_DERIVATION_INVENTORY

    rows = {
        r.derivation: r
        for r in SECTION12_DERIVATION_INVENTORY
        if r.file == "liquidity_value_engine.py"
    }
    assert rows["_resolve_bar_timestamp"].disposition == "REPLACED"
    assert rows["_resolve_bar_timestamp"].schwab_leaf == "pricehistory.candles.datetime"


def test_section12_resolve_bar_timestamp_repo_wide_regression_via_section1_and_3():
    """
    §12 REPLACED formalizes Day 1.5 bar-datetime enforcement (d40b537); repo-wide
    nets live in §1 and §3 — re-run those tests here so readers find the chain.
    """
    from tests.test_section1_schwab_derivation_audit import (
        test_section1_no_timestamp_or_datetime_synthesis_repo_wide,
    )
    from tests.test_section3_schwab_derivation_audit import (
        test_section3_no_datetime_default_zero_repo_wide,
    )

    test_section1_no_timestamp_or_datetime_synthesis_repo_wide()
    test_section3_no_datetime_default_zero_repo_wide()
