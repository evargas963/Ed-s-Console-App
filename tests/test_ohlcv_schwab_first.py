"""Day 1 / 1.5 — OHLCV bar adapters + repo-wide zero-injection enforcement."""

from __future__ import annotations

import re
from pathlib import Path

from market_data_adapter import normalize_bar, schwab_candles_to_bars
from math_exposure_core import bucket_metric, net_gex_dollars_at_strike
from snapshot_normalizer import resample_to_1m

ROOT = Path(__file__).resolve().parent.parent

ZERO_INJECTION_RE = re.compile(r"\.get\([^)]+,\s*0\)\s*or\s*0")

SKIP_DIR_PARTS = frozenset(
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
        "schwab_field_inventory",
    }
)


def _line_counts_as_violation(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("#"):
        return False
    if not ZERO_INJECTION_RE.search(line):
        return False
    # Docstring documenting the forbidden pattern (not executable code).
    if '"""' in line or "'''" in line:
        if "silent default" in line or "without ``" in line:
            return False
    return True

# (repo-relative path prefix, one-line justification)
ZERO_INJECTION_ALLOWLIST: tuple[tuple[str, str], ...] = (
    ("training_cache.py", "training manifest row_count default for cache fingerprint"),
    ("ml_scheduler.py", "scheduler manifest consecutive_scheduler_skips / n_rows counters"),
    (
        "calibration/run_production_accumulation_validation.py",
        "calibration audit counter fields skipped_ambiguous_duplicate_snapshots",
    ),
    ("server.py", "L1 SSE instrumentation counter l1_payload_identity_violation"),
    ("tests/", "test fixtures may document forbidden patterns intentionally"),
    ("tools/", "profiling / scanner tooling not production data path"),
)


def _iter_repo_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        parts = set(path.parts)
        if parts & SKIP_DIR_PARTS:
            continue
        if "tools" in parts and path.name != "__init__.py":
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith("tools/"):
                continue
        out.append(path)
    return out


def _allowlisted(rel_posix: str) -> bool:
    for prefix, _reason in ZERO_INJECTION_ALLOWLIST:
        if rel_posix == prefix or rel_posix.startswith(prefix):
            return True
    return False


def _repo_wide_zero_injection_hits() -> list[str]:
    hits: list[str] = []
    for path in _iter_repo_py_files():
        rel = path.relative_to(ROOT).as_posix()
        if _allowlisted(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if _line_counts_as_violation(line):
                hits.append(f"{rel}:{lineno}:{line.strip()}")
    return hits


def test_normalize_bar_rejects_missing_close():
    assert normalize_bar({"open": 1.0, "high": 2.0, "low": 0.5, "close": None}) is None


def test_normalize_bar_rejects_zero_close():
    assert (
        normalize_bar(
            {"open": 1.0, "high": 2.0, "low": 0.5, "close": 0, "volume": 100},
            source="schwab_pricehistory",
        )
        is None
    )


def test_normalize_bar_emits_source_and_missing_fields():
    nb = normalize_bar(
        {
            "datetime": 1_710_000_000_000,
            "open": 500.0,
            "high": 501.0,
            "low": 499.0,
            "close": 500.5,
            "volume": 1200,
        },
        source="schwab_pricehistory",
    )
    assert nb is not None
    d = nb.to_dict()
    assert d["source"] == "schwab_pricehistory"
    assert d["missing_fields"] == []


def test_schwab_candles_to_bars_rejects_zero_close():
    candles = [
        {
            "datetime": 1_710_000_000_000,
            "open": 500.0,
            "high": 501.0,
            "low": 499.0,
            "close": 0.0,
            "volume": 100,
        }
    ]
    assert schwab_candles_to_bars(candles) == []


def test_resample_synthetic_bars_are_tagged():
    rows = [
        {
            "ts_utc": 1_710_000_060.0,
            "ticker": "SPY",
            "candle_open": 500.0,
            "candle_high": 501.0,
            "candle_low": 499.0,
            "candle_close": 500.5,
            "candle_volume": 1000,
            "spot": 500.5,
        }
    ]
    out = resample_to_1m(rows, "SPY")
    assert len(out) == 1
    assert out[0]["synthetic"] is True
    assert out[0]["source"] == "snapshot_synthetic"


def test_resample_skips_bucket_with_no_open_or_spot():
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


def test_bucket_metric_missing_returns_none_not_zero():
    assert bucket_metric({}, "net_gex_1pct") is None
    assert net_gex_dollars_at_strike({}) is None
    assert bucket_metric({"net_gex_1pct": 0.0}, "net_gex_1pct") == 0.0


def test_no_schwab_leaf_zero_injection_repo_wide():
    hits = _repo_wide_zero_injection_hits()
    assert not hits, "repo-wide .get(*, 0) or 0 violations:\n" + "\n".join(hits[:80])


def test_market_data_adapter_no_zero_injection_pattern():
    text = (ROOT / "market_data_adapter.py").read_text(encoding="utf-8")
    assert not ZERO_INJECTION_RE.search(text)


def test_snapshot_normalizer_no_open_zero_fallback():
    text = (ROOT / "snapshot_normalizer.py").read_text(encoding="utf-8")
    assert "o = 0.0" not in text
