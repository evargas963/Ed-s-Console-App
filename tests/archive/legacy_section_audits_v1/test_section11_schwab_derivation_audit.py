"""Section 11 — Schwab dictionary derivation audit (calibration + fusion)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DATETIME_DEFAULT_ZERO = re.compile(r"""\.get\(\s*["']datetime["']\s*,\s*0\s*\)""")


def _section11_paths() -> set[Path]:
    out: set[Path] = set()
    for p in (ROOT / "calibration").rglob("*.py"):
        if p.name != "__init__.py":
            out.add(p)
    for p in (ROOT / "arch_competition").glob("*.py"):
        if p.name != "__init__.py":
            out.add(p)
    for name in ("governed_stack_contract.py", "bayesian_fusion.py"):
        out.add(ROOT / name)
    return out


def test_section11_inventory_covers_every_function_all_scopes():
    from governance.section11_derivation_inventory import (
        SECTION11_DERIVATION_INVENTORY,
        SECTION11_FILES,
    )
    from governance.section_inventory_gate import assert_inventory_covers_all_functions

    assert_inventory_covers_all_functions(
        ROOT, SECTION11_FILES, SECTION11_DERIVATION_INVENTORY
    )
    assert SECTION11_FILES == frozenset(
        p.relative_to(ROOT).as_posix() for p in _section11_paths()
    )


def test_section11_inventory_counts_and_dispositions():
    from governance.section11_derivation_inventory import (
        SECTION11_DERIVATION_INVENTORY,
        SECTION11_FILES,
    )
    from governance.section_inventory_gate import all_functions_in_file

    assert len(SECTION11_DERIVATION_INVENTORY) >= 466
    assert len(SECTION11_FILES) == 66
    for rel in SECTION11_FILES:
        required = len(all_functions_in_file(ROOT, rel))
        inventoried = len(
            {r.derivation for r in SECTION11_DERIVATION_INVENTORY if r.file == rel}
        )
        assert inventoried == required, f"{rel}: {inventoried} != {required}"


def test_section11_inventory_registered_in_replacement_register():
    reg = (ROOT / "schwab_field_inventory/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- SECTION11_DERIVATION_INVENTORY_START -->" in reg
    assert "466" in reg or "calibration/" in reg


def test_section11_no_direct_schwab_api():
    """Calibration/fusion layer must not call Schwab client wrappers directly."""
    api_markers = (
        "safe_get_quote",
        "safe_get_chain",
        "safe_get_price_history",
        "schwab_candles_to_bars",
    )
    for path in _section11_paths():
        text = path.read_text(encoding="utf-8")
        hits = [m for m in api_markers if m in text]
        assert hits == [], f"{path.as_posix()} must not call Schwab API: {hits}"


def test_section11_no_datetime_default_zero():
    """Section 11 files must not use .get('datetime', 0) synthesis."""
    hits: list[str] = []
    for path in _section11_paths():
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if _DATETIME_DEFAULT_ZERO.search(line):
                hits.append(f"{path.name}:{i}:{line.strip()}")
    assert hits == [], f"datetime default-zero in section 11: {hits}"
