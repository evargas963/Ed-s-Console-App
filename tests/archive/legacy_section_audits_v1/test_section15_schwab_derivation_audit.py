"""Section 15 — Schwab dictionary derivation audit (audit + verify + config + contracts)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DATETIME_DEFAULT_ZERO = re.compile(r"""\.get\(\s*["']datetime["']\s*,\s*0\s*\)""")


def _section15_paths() -> set[Path]:
    out: set[Path] = set()
    out.update(p for p in ROOT.glob("audit_*.py") if p.is_file())
    out.update(p for p in ROOT.glob("verify_*.py") if p.is_file())
    out.update(p for p in ROOT.glob("ticker_*.py") if p.is_file())
    out.update(p for p in ROOT.glob("feature_contract_*.py") if p.is_file())
    for name in (
        "inspect_trading_data.py",
        "config.py",
        "setup_readiness.py",
        "scheduler_user_tickers.py",
        "production_universe.py",
        "instrument_identity.py",
        "timeframe_config.py",
        "model_contract.py",
        "horizon_outcomes.py",
        "movement_target_threshold.py",
        "institutional_behavior.py",
        "canonical_distances.py",
        "tier3_design.py",
    ):
        p = ROOT / name
        if p.is_file():
            out.add(p)
    return out


def test_section15_inventory_covers_every_function_all_scopes():
    from governance.section15_derivation_inventory import (
        SECTION15_DERIVATION_INVENTORY,
        SECTION15_FILES,
    )
    from governance.section_inventory_gate import assert_inventory_covers_all_functions

    assert_inventory_covers_all_functions(
        ROOT, SECTION15_FILES, SECTION15_DERIVATION_INVENTORY
    )
    assert SECTION15_FILES == frozenset(
        p.relative_to(ROOT).as_posix() for p in _section15_paths()
    )


def test_section15_inventory_counts_and_dispositions():
    from governance.section15_derivation_inventory import (
        SECTION15_DERIVATION_INVENTORY,
        SECTION15_FILES,
    )
    from governance.section_inventory_gate import all_functions_in_file

    assert len(SECTION15_DERIVATION_INVENTORY) >= 89
    assert len(SECTION15_FILES) == 27
    for rel in SECTION15_FILES:
        required = len(all_functions_in_file(ROOT, rel))
        inventoried = len(
            {r.derivation for r in SECTION15_DERIVATION_INVENTORY if r.file == rel}
        )
        assert inventoried == required, f"{rel}: {inventoried} != {required}"


def test_section15_inventory_registered_in_replacement_register():
    reg = (ROOT / "governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- SECTION15_DERIVATION_INVENTORY_START -->" in reg
    assert "89" in reg or "verify_snapshot_pipeline" in reg


def test_section15_no_direct_schwab_api():
    """Audit/verify/config layer must not call Schwab client wrappers directly."""
    api_markers = (
        "safe_get_quote",
        "safe_get_chain",
        "safe_get_price_history",
        "schwab_candles_to_bars",
    )
    for path in _section15_paths():
        text = path.read_text(encoding="utf-8")
        hits = [m for m in api_markers if m in text]
        assert hits == [], f"{path.name} must not call Schwab API: {hits}"


def test_section15_no_datetime_default_zero():
    """Section 15 files must not use .get('datetime', 0) synthesis."""
    hits: list[str] = []
    for path in _section15_paths():
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if _DATETIME_DEFAULT_ZERO.search(line):
                hits.append(f"{path.name}:{i}:{line.strip()}")
    assert hits == [], f"datetime default-zero in section 15: {hits}"
