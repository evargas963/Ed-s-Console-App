"""Section 14 — Schwab dictionary derivation audit (DB + backfill + repair)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DATETIME_DEFAULT_ZERO = re.compile(r"""\.get\(\s*["']datetime["']\s*,\s*0\s*\)""")


def _section14_paths() -> set[Path]:
    out: set[Path] = set()
    out.update(p for p in ROOT.glob("db*.py") if p.is_file())
    out.update(p for p in ROOT.glob("backfill_*.py") if p.is_file())
    out.update(p for p in ROOT.glob("bar_rehydration_*.py") if p.is_file())
    for name in (
        "clean_db.py",
        "eval_metrics_store.py",
        "pin_neutral_outcome_repair_v1.py",
        "distance_option_a_backfill_v1.py",
        "patch_active_artifact_provenance.py",
        "replay_bundle_coverage.py",
        "realized_contract_eval.py",
    ):
        p = ROOT / name
        if p.is_file():
            out.add(p)
    return out


def test_section14_inventory_covers_every_function_all_scopes():
    from governance.section14_derivation_inventory import (
        SECTION14_DERIVATION_INVENTORY,
        SECTION14_FILES,
    )
    from governance.section_inventory_gate import assert_inventory_covers_all_functions

    assert_inventory_covers_all_functions(
        ROOT, SECTION14_FILES, SECTION14_DERIVATION_INVENTORY
    )
    assert SECTION14_FILES == frozenset(
        p.relative_to(ROOT).as_posix() for p in _section14_paths()
    )


def test_section14_inventory_counts_and_dispositions():
    from governance.section14_derivation_inventory import (
        SECTION14_DERIVATION_INVENTORY,
        SECTION14_FILES,
    )
    from governance.section_inventory_gate import all_functions_in_file

    assert len(SECTION14_DERIVATION_INVENTORY) >= 229
    assert len(SECTION14_FILES) == 14
    for rel in SECTION14_FILES:
        required = len(all_functions_in_file(ROOT, rel))
        inventoried = len(
            {r.derivation for r in SECTION14_DERIVATION_INVENTORY if r.file == rel}
        )
        assert inventoried == required, f"{rel}: {inventoried} != {required}"


def test_section14_inventory_registered_in_replacement_register():
    reg = (ROOT / "schwab_field_inventory/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- SECTION14_DERIVATION_INVENTORY_START -->" in reg
    assert "229" in reg or "db.py" in reg


_REHYDRATION_BAR_ADAPTER = "bar_rehydration_issue19_v1.py"


def test_section14_no_direct_schwab_api():
    """DB/backfill layer must not call Schwab client wrappers directly."""
    api_markers = (
        "safe_get_quote",
        "safe_get_chain",
        "safe_get_price_history",
        "schwab_candles_to_bars",
    )
    for path in _section14_paths():
        text = path.read_text(encoding="utf-8")
        hits = [m for m in api_markers if m in text]
        if path.name == _REHYDRATION_BAR_ADAPTER:
            # Controlled rehydration: adapter PASS_THROUGH only (no safe_get_*).
            hits = [m for m in hits if m != "schwab_candles_to_bars"]
        assert hits == [], f"{path.name} must not call Schwab API: {hits}"


def test_section14_no_datetime_default_zero():
    """Section 14 files must not use .get('datetime', 0) synthesis."""
    hits: list[str] = []
    for path in _section14_paths():
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if _DATETIME_DEFAULT_ZERO.search(line):
                hits.append(f"{path.name}:{i}:{line.strip()}")
    assert hits == [], f"datetime default-zero in section 14: {hits}"
