"""Section 1 — Schwab dictionary derivation audit (not a CAPS-only gate)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SECTION1_FILES = frozenset(
    {
        "schwab_client.py",
        "reauth_schwab.py",
        "websocket_adapter.py",
        "polling_adapter.py",
        "sse_adapter.py",
        "market_data_adapter.py",
        "snapshot_normalizer.py",
        "snapshot_access.py",
    }
)


def test_section1_inventory_covers_all_eight_files():
    from governance.section1_derivation_inventory import SECTION1_DERIVATION_INVENTORY

    covered = {r.file for r in SECTION1_DERIVATION_INVENTORY}
    assert SECTION1_FILES <= covered


def test_section1_inventory_counts_and_dispositions():
    from governance.section1_derivation_inventory import SECTION1_DERIVATION_INVENTORY

    records = [r for r in SECTION1_DERIVATION_INVENTORY if r.disposition != "NONE"]
    assert len(SECTION1_DERIVATION_INVENTORY) >= 15
    replaced = [r for r in records if r.disposition == "REPLACED"]
    assert len(replaced) >= 3
    assert all(r.schwab_leaf.startswith("pricehistory") or "candles" in r.schwab_leaf for r in replaced)


def test_section1_inventory_registered_in_replacement_register():
    reg = (ROOT / "governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- SECTION1_DERIVATION_INVENTORY_START -->" in reg
    assert "schwab_client.py" in reg
    assert "KEEP_DERIVED" in reg


def test_market_data_adapter_requires_schwab_datetime():
    from market_data_adapter import normalize_bar, SCHWAB_CANDLE_LEAF_MAP

    assert "datetime" in SCHWAB_CANDLE_LEAF_MAP
    assert (
        normalize_bar(
            {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10},
            source="schwab_pricehistory",
        )
        is None
    )
    nb = normalize_bar(
        {
            "datetime": 1_710_000_000_000,
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 10,
        },
        source="schwab_pricehistory",
    )
    assert nb is not None


def test_schwab_candles_to_bars_uses_pricehistory_leaves_only():
    from market_data_adapter import schwab_candles_to_bars

    bars = schwab_candles_to_bars(
        [
            {
                "datetime": 1_710_000_000_000,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000,
            }
        ]
    )
    assert len(bars) == 1
    assert bars[0]["source"] == "schwab_pricehistory"
    assert bars[0]["missing_fields"] == []


def test_resample_synthetic_documents_proxies():
    from snapshot_normalizer import resample_to_1m

    base = 1_710_000_000.0
    out = resample_to_1m(
        [
            {
                "ts_utc": base + 30.0,
                "ticker": "SPY",
                "spot": 500.0,
                "candle_high": 501.0,
                "candle_low": 499.0,
                "candle_close": 500.5,
            },
            {
                "ts_utc": base + 50.0,
                "ticker": "SPY",
                "spot": 500.5,
                "candle_close": 500.8,
            },
        ],
        "SPY",
    )
    assert len(out) == 1
    assert out[0]["synthetic"] is True
    assert "candle_open_spot_proxy" in (out[0].get("missing_fields") or [])


def test_vwap_side_not_invented_without_inputs():
    from math_snapshot_derive import derive_vwap_side

    assert derive_vwap_side(None, 500.0) is None
    assert derive_vwap_side(500.0, None) is None


def test_liquidity_engine_schwab_bar_requires_datetime_leaf():
    from liquidity_value_engine import _bars_to_list

    missing_dt = [
        {
            "source": "schwab_pricehistory",
            "open": 500.0,
            "high": 501.0,
            "low": 499.0,
            "close": 500.5,
            "volume": 1000,
        }
    ]
    assert _bars_to_list(missing_dt) == []

    with_dt = [
        {
            "source": "schwab_pricehistory",
            "datetime": 1_710_000_000_000,
            "open": 500.0,
            "high": 501.0,
            "low": 499.0,
            "close": 500.5,
            "volume": 1000,
        }
    ]
    norm = _bars_to_list(with_dt)
    assert len(norm) == 1
    assert norm[0].get("_ts") is not None


def test_section1_no_timestamp_or_datetime_synthesis_repo_wide():
    """Repo-wide grep: no timestamp-or-datetime fallback synthesis in production .py."""
    pat = re.compile(
        r"""\.get\(["']timestamp["']\)\s+or\s+.*\.get\(["']datetime["']\)"""
    )
    skip_parts = {".claude", ".git", ".venv", "__pycache__", "backups", "tests", "tools"}
    hits: list[str] = []
    for path in ROOT.rglob("*.py"):
        if any(part in skip_parts for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), start=1):
            if pat.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{i}:{line.strip()}")
    assert hits == [], f"timestamp-or-datetime synthesis remains: {hits}"
