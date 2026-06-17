"""Section 9 — Schwab dictionary derivation audit (features / ML inputs)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DATETIME_DEFAULT_ZERO = re.compile(r"""\.get\(\s*["']datetime["']\s*,\s*0\s*\)""")


def test_section9_inventory_covers_every_function_all_scopes():
    from governance.section9_derivation_inventory import (
        SECTION9_DERIVATION_INVENTORY,
        SECTION9_FILES,
    )
    from governance.section_inventory_gate import assert_inventory_covers_all_functions

    assert_inventory_covers_all_functions(
        ROOT, SECTION9_FILES, SECTION9_DERIVATION_INVENTORY
    )


def test_section9_inventory_counts_and_dispositions():
    from governance.section9_derivation_inventory import (
        SECTION9_DERIVATION_INVENTORY,
        SECTION9_FILES,
    )
    from governance.section_inventory_gate import all_functions_in_file

    assert len(SECTION9_DERIVATION_INVENTORY) >= 92
    assert len(SECTION9_FILES) >= 22
    for rel in SECTION9_FILES:
        required = len(all_functions_in_file(ROOT, rel))
        inventoried = len({r.derivation for r in SECTION9_DERIVATION_INVENTORY if r.file == rel})
        assert inventoried == required, f"{rel}: {inventoried} != {required}"


def test_section9_inventory_registered_in_replacement_register():
    reg = (ROOT / "governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- SECTION9_DERIVATION_INVENTORY_START -->" in reg
    assert "92" in reg or "features/" in reg


def test_section9_features_no_direct_schwab_api():
    """Feature layer must not call Schwab client wrappers directly."""
    api_markers = (
        "safe_get_quote",
        "safe_get_chain",
        "safe_get_price_history",
        "schwab_candles_to_bars",
    )
    features_dir = ROOT / "features"
    for path in features_dir.glob("*.py"):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        hits = [m for m in api_markers if m in text]
        assert hits == [], f"{path.name} must not call Schwab API: {hits}"


def test_section9_no_datetime_default_zero_in_features():
    """Features must not use .get('datetime', 0) synthesis."""
    hits: list[str] = []
    for path in (ROOT / "features").glob("*.py"):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if _DATETIME_DEFAULT_ZERO.search(line):
                hits.append(f"{path.name}:{i}:{line.strip()}")
    assert hits == [], f"datetime default-zero in features: {hits}"


def test_mvp_strict_float_rejects_bool():
    from features.mvp_source_coercion import MvpFeatureSourceError, strict_float_from_raw

    with pytest.raises(MvpFeatureSourceError):
        strict_float_from_raw(True, "test_field")
