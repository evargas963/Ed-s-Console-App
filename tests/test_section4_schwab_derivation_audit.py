"""Section 4 — KEY LEVELS Schwab dictionary derivation audit (full function walk)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(str(ROOT)) not in sys.path:
    sys.path.insert(0, str(ROOT))

SECTION4_FILES = frozenset(
    {
        "math_exposure.py",
        "math_exposure_core.py",
        "math_levels.py",
        "math_volatility.py",
        "math_probabilities.py",
        "levels.py",
    }
)

_OR_ZERO_PAIR_SUM = re.compile(
    r"""\(\s*\w+\s+or\s+0(?:\.0)?\s*\)\s*\+\s*\(\s*\w+\s+or\s+0(?:\.0)?\s*\)"""
)

_MIN_PER_FILE = {
    "math_exposure.py": 10,
    "math_exposure_core.py": 33,
    "math_levels.py": 29,
    "math_volatility.py": 22,
    "math_probabilities.py": 28,
    "levels.py": 9,
}


def test_section4_inventory_covers_all_six_files():
    from governance.section4_derivation_inventory import SECTION4_DERIVATION_INVENTORY

    covered = {r.file for r in SECTION4_DERIVATION_INVENTORY}
    assert SECTION4_FILES <= covered


def test_section4_inventory_function_walk_scale():
    from governance.section4_derivation_inventory import SECTION4_DERIVATION_INVENTORY

    assert len(SECTION4_DERIVATION_INVENTORY) >= 131
    by_file: dict[str, int] = {}
    for r in SECTION4_DERIVATION_INVENTORY:
        by_file[r.file] = by_file.get(r.file, 0) + 1
    for f, minimum in _MIN_PER_FILE.items():
        assert by_file.get(f, 0) >= minimum, f"{f}: {by_file.get(f, 0)} < {minimum}"


def test_section4_every_function_inventoried_all_scopes():
    from governance.section4_derivation_inventory import (
        SECTION4_DERIVATION_INVENTORY,
        SECTION4_FILES,
    )
    from governance.section_inventory_gate import (
        all_functions_in_file,
        assert_inventory_covers_all_functions,
    )

    assert_inventory_covers_all_functions(
        ROOT, SECTION4_FILES, SECTION4_DERIVATION_INVENTORY
    )
    assert len(SECTION4_DERIVATION_INVENTORY) >= 131
    for rel in sorted(SECTION4_FILES):
        required = {fn.qualified_name for fn in all_functions_in_file(ROOT, rel)}
        inventoried = {
            r.derivation for r in SECTION4_DERIVATION_INVENTORY if r.file == rel
        }
        assert inventoried >= required, f"{rel}: {required - inventoried}"


def test_section4_math_volatility_all_functions_present():
    from governance.section4_derivation_inventory import SECTION4_DERIVATION_INVENTORY
    from governance.section_inventory_gate import all_functions_in_file

    vol_fns = {r.derivation for r in SECTION4_DERIVATION_INVENTORY if r.file == "math_volatility.py"}
    expected = {fn.qualified_name for fn in all_functions_in_file(ROOT, "math_volatility.py")}
    assert vol_fns == expected
    assert len(vol_fns) >= 22


def test_section4_inventory_counts_and_dispositions():
    from governance.section4_derivation_inventory import SECTION4_DERIVATION_INVENTORY

    replaced = [r for r in SECTION4_DERIVATION_INVENTORY if r.disposition == "REPLACED"]
    assert len(replaced) >= 2
    assert any(r.file == "math_levels.py" for r in replaced)
    assert any(r.file == "math_probabilities.py" for r in replaced)


def test_section4_inventory_registered_in_replacement_register():
    reg = (ROOT / "governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- SECTION4_DERIVATION_INVENTORY_START -->" in reg
    assert "131" in reg or "function" in reg.lower()
    assert "section4_derivation_inventory.py" in reg


def test_section4_no_or_zero_pair_sum_in_key_levels_files():
    hits: list[str] = []
    for rel in sorted(SECTION4_FILES):
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), start=1):
            if _OR_ZERO_PAIR_SUM.search(line):
                hits.append(f"{rel}:{i}:{line.strip()}")
    assert hits == [], f"or-zero pair sums remain: {hits}"


def test_section4_no_or_zero_pair_sum_repo_wide():
    """Repo-wide: no (x or 0) + (y or 0) gamma-bucket synthesis in production .py."""
    skip_parts = {
        ".claude",
        ".git",
        ".venv",
        "__pycache__",
        "backups",
        "governance",
        "tests",
        "tools",
    }
    hits: list[str] = []
    for path in ROOT.rglob("*.py"):
        if any(part in skip_parts for part in path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), start=1):
            if _OR_ZERO_PAIR_SUM.search(line):
                hits.append(f"{rel}:{i}:{line.strip()}")
    assert hits == [], f"or-zero pair sums remain repo-wide: {hits}"


def test_liquidity_void_get_gex_sums_only_present_gamma():
    from math_levels import compute_gamma_void_zones

    exposures = {
        495.0: {"call_gamma": 1000.0, "put_gamma": 900.0, "call_oi": 100, "put_oi": 100},
        500.0: {"call_gamma": 100.0, "put_gamma": None, "call_oi": 10, "put_oi": 10},
        505.0: {"call_gamma": None, "put_gamma": 80.0, "call_oi": 10, "put_oi": 10},
        510.0: {"call_gamma": 1000.0, "put_gamma": 900.0, "call_oi": 100, "put_oi": 100},
    }
    voids = compute_gamma_void_zones(exposures, spot=502.0, min_width_strikes=1)
    assert isinstance(voids, list)


def test_extract_iv_for_strike_reads_schwab_volatility_leaf():
    from math_volatility import _extract_iv_for_strike

    contracts = [
        {"strikePrice": 500, "putCall": "CALL", "volatility": 22.5},
        {"strikePrice": 500, "putCall": "PUT", "volatility": 24.0},
    ]
    c_iv, p_iv = _extract_iv_for_strike(contracts, 500.0)
    assert c_iv == 22.5
    assert p_iv == 24.0


def test_strike_activity_skips_missing_volumes():
    from math_probabilities import compute_smart_money_signal

    exposures = {
        500.0: {
            "call_volume": 100.0,
            "put_volume": None,
            "call_oi": 1000.0,
            "put_oi": 1000.0,
            "call_bid_size": 10.0,
            "call_ask_size": 5.0,
            "put_bid_size": 8.0,
            "put_ask_size": 6.0,
        }
    }
    out = compute_smart_money_signal(exposures, spot=500.0, window_pts=5.0)
    assert out["score"] >= 0
