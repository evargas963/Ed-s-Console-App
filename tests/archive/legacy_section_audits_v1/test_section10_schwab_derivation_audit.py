"""Section 10 — Schwab dictionary derivation audit (ML training + predict)."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SECTION10_GLOBS = (
    "ml_*.py",
    "lstm_*.py",
    "xgboost_model.py",
    "transformer_*.py",
    "train_*.py",
    "training_*.py",
    "normalized_training_sync.py",
    "smoke_predict_active.py",
)

_DATETIME_DEFAULT_ZERO = re.compile(r"""\.get\(\s*["']datetime["']\s*,\s*0\s*\)""")


def _section10_paths() -> set[Path]:
    out: set[Path] = set()
    for pat in _SECTION10_GLOBS:
        out.update(ROOT.glob(pat))
    return {p for p in out if p.is_file() and p.name != "__init__.py"}


def test_section10_inventory_covers_every_function_all_scopes():
    from governance.section10_derivation_inventory import (
        SECTION10_DERIVATION_INVENTORY,
        SECTION10_FILES,
    )
    from governance.section_inventory_gate import assert_inventory_covers_all_functions

    assert_inventory_covers_all_functions(
        ROOT, SECTION10_FILES, SECTION10_DERIVATION_INVENTORY
    )
    assert SECTION10_FILES == frozenset(p.relative_to(ROOT).as_posix() for p in _section10_paths())


def test_section10_inventory_counts_and_dispositions():
    from governance.section10_derivation_inventory import (
        SECTION10_DERIVATION_INVENTORY,
        SECTION10_FILES,
    )
    from governance.section_inventory_gate import all_functions_in_file

    assert len(SECTION10_DERIVATION_INVENTORY) >= 247
    assert len(SECTION10_FILES) == 17
    for rel in SECTION10_FILES:
        required = len(all_functions_in_file(ROOT, rel))
        inventoried = len({r.derivation for r in SECTION10_DERIVATION_INVENTORY if r.file == rel})
        assert inventoried == required, f"{rel}: {inventoried} != {required}"


def test_section10_inventory_registered_in_replacement_register():
    reg = (ROOT / "schwab_field_inventory/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- SECTION10_DERIVATION_INVENTORY_START -->" in reg
    assert "247" in reg or "ml_predict" in reg


def test_section10_no_direct_schwab_api():
    """ML training/predict layer must not call Schwab client wrappers directly."""
    api_markers = (
        "safe_get_quote",
        "safe_get_chain",
        "safe_get_price_history",
        "schwab_candles_to_bars",
    )
    for path in _section10_paths():
        text = path.read_text(encoding="utf-8")
        hits = [m for m in api_markers if m in text]
        assert hits == [], f"{path.name} must not call Schwab API: {hits}"


def test_section10_no_datetime_default_zero():
    """Section 10 files must not use .get('datetime', 0) synthesis."""
    hits: list[str] = []
    for path in _section10_paths():
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if _DATETIME_DEFAULT_ZERO.search(line):
                hits.append(f"{path.name}:{i}:{line.strip()}")
    assert hits == [], f"datetime default-zero in section 10: {hits}"
