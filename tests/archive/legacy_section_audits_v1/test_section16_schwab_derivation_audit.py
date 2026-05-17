"""Section 16 — Schwab dictionary derivation audit (external signals)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SECTION16_FILES = (
    "news_sentiment.py",
    "api_pressure.py",
    "event_risk.py",
)

_DATETIME_DEFAULT_ZERO = re.compile(r"""\.get\(\s*["']datetime["']\s*,\s*0\s*\)""")


def _section16_paths() -> set[Path]:
    return {ROOT / name for name in _SECTION16_FILES}


def test_section16_inventory_covers_every_function_all_scopes():
    from governance.section16_derivation_inventory import (
        SECTION16_DERIVATION_INVENTORY,
        SECTION16_FILES,
    )
    from governance.section_inventory_gate import assert_inventory_covers_all_functions

    assert_inventory_covers_all_functions(
        ROOT, SECTION16_FILES, SECTION16_DERIVATION_INVENTORY
    )
    assert SECTION16_FILES == frozenset(_SECTION16_FILES)


def test_section16_inventory_counts_and_dispositions():
    from governance.section16_derivation_inventory import (
        SECTION16_DERIVATION_INVENTORY,
        SECTION16_FILES,
    )
    from governance.section_inventory_gate import all_functions_in_file

    assert len(SECTION16_DERIVATION_INVENTORY) >= 19
    assert len(SECTION16_FILES) == 3
    for rel in SECTION16_FILES:
        required = len(all_functions_in_file(ROOT, rel))
        inventoried = len(
            {r.derivation for r in SECTION16_DERIVATION_INVENTORY if r.file == rel}
        )
        assert inventoried == required, f"{rel}: {inventoried} != {required}"


def test_section16_inventory_registered_in_replacement_register():
    reg = (ROOT / "governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- SECTION16_DERIVATION_INVENTORY_START -->" in reg
    assert "19" in reg or "news_sentiment" in reg


def test_section16_no_direct_schwab_market_data_api():
    """External-signals layer must not call Schwab quote/chain/pricehistory wrappers."""
    api_markers = (
        "safe_get_quote",
        "safe_get_chain",
        "safe_get_price_history",
        "schwab_candles_to_bars",
    )
    for path in _section16_paths():
        text = path.read_text(encoding="utf-8")
        hits = [m for m in api_markers if m in text]
        assert hits == [], f"{path.name} must not call Schwab market-data API: {hits}"


def test_section16_no_datetime_default_zero():
    """Section 16 files must not use .get('datetime', 0) synthesis."""
    hits: list[str] = []
    for path in _section16_paths():
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if _DATETIME_DEFAULT_ZERO.search(line):
                hits.append(f"{path.name}:{i}:{line.strip()}")
    assert hits == [], f"datetime default-zero in section 16: {hits}"
