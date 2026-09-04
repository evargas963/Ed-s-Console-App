"""Fail-closed: production code must not use .get('datetime', 0) silent synthesis."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from unittest.mock import MagicMock

_DATETIME_DEFAULT_ZERO = re.compile(r"""\.get\(\s*["']datetime["']\s*,\s*0\s*\)""")

_SKIP_DIR_PARTS = frozenset(
    {
        ".git",
        ".claude",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".pytest_cache",
        "backups",
        "governance",
        "tests",
        "tools",
        "calibration",
        "verification",
        "arch_competition",
    }
)

# Explicit allowlist only if a documented exception is required (empty by default).
_DATETIME_DEFAULT_ZERO_ALLOWLIST: frozenset[str] = frozenset()


def test_no_datetime_default_zero_in_production_py(repo_index):
    """TEST_SYSTEM_REHAB_V2: was an independent ROOT.rglob("*.py") + per-file
    read_text -- now sources from the shared `repo_index` corpus. Filter semantics
    unchanged (same _SKIP_DIR_PARTS, incl. the deliberate calibration/verification/
    arch_competition exclusions)."""
    hits: list[str] = []
    for rel, text, _tree in repo_index.items():
        if any(part in _SKIP_DIR_PARTS for part in rel.parts):
            continue
        rel_posix = rel.as_posix()
        if rel_posix in _DATETIME_DEFAULT_ZERO_ALLOWLIST:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if _DATETIME_DEFAULT_ZERO.search(line):
                hits.append(f"{rel_posix}:{i}:{line.strip()}")
    assert hits == [], f".get('datetime', 0) remains in production code: {hits}"


def test_fetch_price_levels_skips_candle_missing_datetime():
    """RC-371 re-anchor: Phase 2A deleted the carrier's own candle fetch, so a
    datetime-poisoned candle CANNOT reach PDH through fetch_price_levels at all —
    the missing-datetime rejection lives at the ONE ingestion point (normalize_bar,
    locked below and in market_data_adapter's own suite). This test now holds the
    carrier candle-free and the ingestion rejection in place."""
    import inspect

    from market_context import fetch_price_levels
    from market_data_adapter import normalize_bar

    src = inspect.getsource(fetch_price_levels)
    assert "get_price_history" not in src, (
        "fetch_price_levels fetches candles again — a datetime-poisoned candle can "
        "reach the levels once more; the Phase 2A carrier must stay candle-free"
    )
    assert "candles" not in src, "candle parsing is back in the carrier"
    assert normalize_bar(
        {"open": 1.0, "high": 888.0, "low": 1.0, "close": 2.0, "volume": 50},
        source="schwab_pricehistory",
    ) is None, "the ONE vendor ingestion point accepted a candle with no datetime"


def _retired_fetch_price_levels_candle_test():
    from market_context import fetch_price_levels

    from app.domain.time_et import ET as et  # noqa: F401
    yday = (datetime.now(et) - timedelta(days=1)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    dt_ms = int(yday.timestamp() * 1000)

    valid = {
        "datetime": dt_ms,
        "open": 40.0,
        "high": 50.0,
        "low": 39.0,
        "close": 45.0,
        "volume": 1000,
    }
    poison = {
        "open": 1.0,
        "high": 888.0,
        "low": 1.0,
        "close": 2.0,
        "volume": 50,
    }

    client = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"candles": [valid, poison]}
    client.get_price_history.return_value = resp

    pl = fetch_price_levels(client, "SPY")
    assert pl.pdh == 50.0


def test_candle_accumulator_seed_skips_missing_datetime():
    from server import _CandleAccumulator

    acc = _CandleAccumulator(bar_seconds=60, max_bars=25)
    bars = [
        {
            "datetime": 1_710_000_000_000,
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 100.0,
        },
        {
            "open": 9.0,
            "high": 9.0,
            "low": 9.0,
            "close": 9.0,
            "volume": 9.0,
        },
    ]
    acc.seed("SPY", bars)
    seeded = acc.get_bars("SPY")
    assert len(seeded) == 1
    assert seeded[0].high == 2.0


def test_returns_from_candles_skips_missing_datetime():
    from math_exposure_core import returns_from_candles

    out = returns_from_candles(
        [
            {"close": 100.0},
            {"datetime": 1_704_067_800_000, "close": 101.0},
            {"datetime": 1_704_154_200_000, "close": 102.0},
        ]
    )
    assert len(out) == 1
