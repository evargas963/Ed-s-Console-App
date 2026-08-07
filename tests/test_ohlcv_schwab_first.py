"""Day 1 / 1.5 / 1.6 — OHLCV adapters + silent-zero pattern family enforcement."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from market_data_adapter import normalize_bar, schwab_candles_to_bars
from math_exposure_core import bucket_metric, net_gex_dollars_at_strike
from snapshot_normalizer import resample_to_1m

ROOT = Path(__file__).resolve().parent.parent

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


@dataclass(frozen=True)
class _PatternSpec:
    name: str
    regex: re.Pattern[str]


# Silent-zero pattern family (variants and equivalent forms).
SILENT_ZERO_PATTERN_FAMILY: tuple[_PatternSpec, ...] = (
    _PatternSpec("get_default_or_zero", re.compile(r"\.get\([^)]+,\s*0\)\s*or\s*0")),
    _PatternSpec("get_no_default_or_zero", re.compile(r"\.get\([^,)]+\)\s+or\s+0(?:\.0)?")),
    _PatternSpec(
        "get_none_default_or_zero",
        re.compile(r"\.get\([^)]+,\s*None\)\s+or\s+0(?:\.0)?"),
    ),
    _PatternSpec(
        "cast_or_zero",
        re.compile(r"(?:int|float)\([^)]+\s+or\s+0(?:\.0)?\)"),
    ),
)

# Whole-file / prefix allowlist: path prefix → one-line justification.
ZERO_INJECTION_FILE_ALLOWLIST: tuple[tuple[str, str], ...] = (
    ("tests/", "fixtures and gate tests document forbidden patterns"),
    ("tools/", "profiling and scanner tooling not production data path"),
    ("calibration/", "audit SQL aggregates, null-rate denominators, phase cleanup counters"),
    ("verification/", "health-check counters and gap diagnostics"),
    ("arch_competition/", "offline eval harness metrics"),
    ("adaptive_shadow_v2_calibration.py", "shadow calibration ranking aggregates"),
    ("adaptive_similarity_engine.py", "similarity pool size / tier diagnostics"),
    ("replay_bundle_coverage.py", "bundle join row-count audit"),
    ("bar_rehydration_issue19_v1.py", "rehydration repair counters"),
    ("db_health_audit.py", "DB health audit counters"),
    ("similarity_audit.py", "similarity trace diagnostics"),
    ("similarity_feature_search.py", "shadow feature-search counters"),
    ("training_cache.py", "training manifest row_count fingerprint"),
    ("training_provenance.py", "training manifest rows_used counter"),
    ("ml_scheduler.py", "scheduler manifest skip/row counters"),
    ("patch_active_artifact_provenance.py", "artifact patch counters"),
    ("planes/", "L1/runtime plane timestamps and version counters"),
    ("bayesian_fusion.py", "signal_layer meta.n_bars gate counter"),
    ("features/signal_layer_v1.py", "derived signal layer counters (meta.n_bars)"),
    ("monte_carlo.py", "MC output dict serialization of derived sim metrics"),
    ("live_vs_replay_validation.py", "replay validation row counts"),
    ("lifecycle_rule_core.py", "session minutes-since-open derived input"),
    ("setup_readiness.py", "readiness probability coercion for display"),
    ("call_engine.py", "rules-engine display percent coercion"),
    ("ml_train.py", "training window max_ts_utc comparison guard"),
    ("realized_contract_eval.py", "contract eval PnL + SQL pool counts"),
    ("liquidity_value_engine.py", "bar sort key _ts (internal timestamp)"),
    ("order_flow_engine.py", "Schwab print time_millis sort/cutoff (native leaf present)"),
    ("snapshot_normalizer.py", "materialize row-count audit counters"),
    ("market_state.py", "wall-score audit diff (derived scores)"),
    ("db.py", "SQL COUNT aggregate int coercion"),
    ("server.py", "L1/SSE instrumentation timestamps, generations, volume deltas"),
)


def _line_counts_as_violation(line: str, pattern: _PatternSpec) -> bool:
    stripped = line.strip()
    if stripped.startswith("#"):
        return False
    if not pattern.regex.search(line):
        return False
    if '"""' in line or "'''" in line:
        if "silent default" in line or "without ``" in line or "pattern family" in line:
            return False
    return True


def _file_allowlisted(rel_posix: str) -> bool:
    for prefix, _reason in ZERO_INJECTION_FILE_ALLOWLIST:
        if rel_posix == prefix or rel_posix.startswith(prefix):
            return True
    return False


def _tracked_py_files() -> list[Path]:
    """RC-274: 'repo-wide' means what git tracks — nothing looser, nothing hand-maintained.

    `rglob` walked `scratchpad/`, which `.gitignore:202` excludes and which holds 0 tracked
    files, so ~25 of this gate's 38 hits were throwaway audit scripts. The temptation is an
    allowlist entry, but that is a list somebody has to keep true. The index already answers
    'is this repository code', it answers it for every future directory nobody thought of, and
    a staged file counts the moment it is staged.
    """
    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "git ls-files failed, so the scan scope is unknown: " + proc.stderr.strip())
    return [ROOT / p for p in proc.stdout.split("\0") if p]


def _iter_repo_py_files() -> list[Path]:
    out: list[Path] = []
    for path in _tracked_py_files():
        if set(path.parts) & SKIP_DIR_PARTS:
            continue
        if "tools" in set(path.parts) and path.name != "__init__.py":
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith("tools/"):
                continue
        out.append(path)
    return out


def _repo_wide_silent_zero_hits() -> list[str]:
    hits: list[str] = []
    for path in _iter_repo_py_files():
        rel = path.relative_to(ROOT).as_posix()
        if _file_allowlisted(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for spec in SILENT_ZERO_PATTERN_FAMILY:
                if _line_counts_as_violation(line, spec):
                    hits.append(f"{rel}:{lineno}:{spec.name}:{line.strip()}")
                    break
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
    """Pattern family gate — all variants must be fixed or explicitly allowlisted."""
    hits = _repo_wide_silent_zero_hits()
    assert not hits, "repo-wide silent-zero pattern family violations:\n" + "\n".join(hits[:80])


def test_market_data_adapter_no_zero_injection_pattern():
    text = (ROOT / "market_data_adapter.py").read_text(encoding="utf-8")
    assert not SILENT_ZERO_PATTERN_FAMILY[0].regex.search(text)


def test_snapshot_normalizer_no_open_zero_fallback():
    text = (ROOT / "snapshot_normalizer.py").read_text(encoding="utf-8")
    assert "o = 0.0" not in text


def test_math_levels_no_get_or_zero_on_exposure_buckets():
    text = (ROOT / "math_levels.py").read_text(encoding="utf-8")
    assert not SILENT_ZERO_PATTERN_FAMILY[1].regex.search(text)


def test_math_exposure_core_no_get_or_zero_on_buckets():
    text = (ROOT / "math_exposure_core.py").read_text(encoding="utf-8")
    assert not SILENT_ZERO_PATTERN_FAMILY[1].regex.search(text)
