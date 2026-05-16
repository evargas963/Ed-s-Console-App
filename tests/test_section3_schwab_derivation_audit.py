"""Section 3 — Schwab dictionary derivation audit (market data + state)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SECTION3_FILES = frozenset(
    {
        "market_context.py",
        "market_state.py",
        "math_snapshot_derive.py",
    }
)

_DATETIME_DEFAULT_ZERO = re.compile(r"""\.get\(\s*["']datetime["']\s*,\s*0\s*\)""")


def test_section3_inventory_covers_all_three_files():
    from governance.section3_derivation_inventory import SECTION3_DERIVATION_INVENTORY

    covered = {r.file for r in SECTION3_DERIVATION_INVENTORY}
    assert SECTION3_FILES <= covered


def test_section3_inventory_counts_and_dispositions():
    from governance.section3_derivation_inventory import SECTION3_DERIVATION_INVENTORY

    assert len(SECTION3_DERIVATION_INVENTORY) >= 11
    replaced = [r for r in SECTION3_DERIVATION_INVENTORY if r.disposition == "REPLACED"]
    assert len(replaced) >= 3
    assert any(r.file == "market_context.py" for r in replaced)


def test_section3_inventory_registered_in_replacement_register():
    reg = (ROOT / "governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- SECTION3_DERIVATION_INVENTORY_START -->" in reg
    assert "market_context.py" in reg


def test_section3_no_datetime_default_zero_repo_wide():
    skip_parts = {".claude", ".git", ".venv", "__pycache__", "backups", "tests", "tools"}
    hits: list[str] = []
    for path in ROOT.rglob("*.py"):
        if any(part in skip_parts for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), start=1):
            if _DATETIME_DEFAULT_ZERO.search(line):
                hits.append(f"{path.relative_to(ROOT).as_posix()}:{i}:{line.strip()}")
    assert hits == [], f"datetime default-zero synthesis remains: {hits}"


def test_market_context_price_history_requires_datetime_leaf():
    src = (ROOT / "market_context.py").read_text(encoding="utf-8")
    assert '.get("datetime", 0)' not in src
    assert "if dt_ms is None:" in src


def test_returns_from_candles_skips_missing_datetime():
    from math_exposure_core import returns_from_candles

    out = returns_from_candles(
        [
            {"close": 100.0},
            {
                "datetime": 1_704_067_800_000,
                "close": 101.0,
            },
            {
                "datetime": 1_704_154_200_000,
                "close": 102.0,
            },
        ]
    )
    assert len(out) == 1


def test_derive_vwap_side_fail_closed():
    from math_snapshot_derive import derive_vwap_side

    assert derive_vwap_side(None, 100.0) is None
    assert derive_vwap_side(100.0, None) is None
    assert derive_vwap_side(101.0, 100.0) == "above"
    assert derive_vwap_side(100.0, 100.0) == "below"
