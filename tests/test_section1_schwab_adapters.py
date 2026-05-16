"""Section 1 — Schwab client + adapters: provenance and fail-closed bar/snapshot paths."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SECTION1_FILES = (
    "schwab_client.py",
    "reauth_schwab.py",
    "websocket_adapter.py",
    "polling_adapter.py",
    "sse_adapter.py",
    "market_data_adapter.py",
    "snapshot_normalizer.py",
    "snapshot_access.py",
)


def test_section1_files_pass_caps_gate():
    from tools.anti_pattern_sweep import caps_hit_allowed, scan_file

    violations: list[str] = []
    for rel in SECTION1_FILES:
        for lineno, _rel, vid, expr in scan_file(ROOT / rel):
            if not caps_hit_allowed(rel, lineno, vid):
                violations.append(f"{rel}:{lineno}:{vid}:{expr}")
    assert not violations, "\n".join(violations)


def test_resample_tags_spot_proxies_in_missing_fields():
    from snapshot_normalizer import resample_to_1m

    base = 1_710_000_000.0
    rows = [
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
    ]
    out = resample_to_1m(rows, "SPY")
    assert len(out) == 1
    mf = set(out[0].get("missing_fields") or [])
    assert "candle_open_spot_proxy" in mf or "candle_open" in mf
    assert out[0].get("synthetic") is True
    assert out[0].get("source") == "snapshot_synthetic"


def test_resample_skips_bucket_without_open_or_spot():
    from snapshot_normalizer import resample_to_1m

    rows = [
        {
            "ts_utc": 1_710_000_060.0,
            "ticker": "SPY",
            "candle_high": 501.0,
            "candle_low": 499.0,
            "candle_close": 500.5,
        }
    ]
    assert resample_to_1m(rows, "SPY") == []


def test_market_data_adapter_rejects_zero_close():
    from market_data_adapter import normalize_bar

    assert (
        normalize_bar(
            {"open": 1.0, "high": 2.0, "low": 0.5, "close": 0, "volume": 10},
            source="schwab_pricehistory",
        )
        is None
    )
