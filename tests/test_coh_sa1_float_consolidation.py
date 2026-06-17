"""COH-SA-1: local float parsers delegate to numeric_contract (finite / positive)."""

from __future__ import annotations

import importlib
import importlib.util
import re
from pathlib import Path

import pytest

_SKIP_PY_TREE_DIRS = frozenset(
    {".claude", ".git", ".venv", "venv", "node_modules", "__pycache__"}
)

# COH-SA-1 redirect sites (v2_a1_execution_ev covers isotonic production via v2_a1_calibration).
_COH_SA1_FLOAT_OR_NONE: tuple[tuple[str, str], ...] = (
    ("lifecycle_rule_core", "_float_or_none"),
    ("live_decision_bundle", "_float_or_none"),
    ("v2_decision.a2_lifecycle_sidecar", "_float_or_none"),
    ("calibration.v2_a1_calibration", "_float_or_none"),
    ("calibration.v2_a1_conformal", "_float_or_none"),
    ("calibration.v2_a1_ev_bounds", "_float_or_none"),
    ("calibration.v2_a1_execution_ev", "_float_or_none"),
    ("v2_decision.a2_price_precedence", "_num"),
)

_COH_SA1_POSITIVE: tuple[tuple[str, str], ...] = (("lstm_data", "_positive_float_or_none"),)

_INLINE_FLOAT_TRY_EXCEPT = re.compile(
    r"def\s+_float_or_none\s*\([^)]*\)[^:]*:\s*\n\s+try:",
    re.MULTILINE,
)
_INLINE_F_TRY_EXCEPT = re.compile(
    r"def\s+_f\s*\([^)]*\)[^:]*:\s*\n\s+try:",
    re.MULTILINE,
)
_INLINE_NUM_TRY_EXCEPT = re.compile(
    r"def\s+_num\s*\([^)]*\)[^:]*:\s*\n\s+try:",
    re.MULTILINE,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _iter_repo_py_files(root: Path):
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] == "tests":
            continue
        if any(part in _SKIP_PY_TREE_DIRS for part in rel.parts):
            continue
        yield path, rel


@pytest.mark.parametrize("module_name,attr", _COH_SA1_FLOAT_OR_NONE)
def test_coh_sa1_wrappers_reject_nan_and_inf(module_name: str, attr: str):
    mod = importlib.import_module(module_name)
    fn = getattr(mod, attr)
    assert fn(float("nan")) is None
    assert fn(float("inf")) is None
    assert fn(float("-inf")) is None
    assert fn(1.25) == 1.25


@pytest.mark.parametrize("module_name,attr", _COH_SA1_POSITIVE)
def test_coh_sa1_positive_wrapper_rejects_non_positive(module_name: str, attr: str):
    mod = importlib.import_module(module_name)
    fn = getattr(mod, attr)
    assert fn(float("nan")) is None
    assert fn(0) is None
    assert fn(-1.0) is None
    assert fn(0.5) == 0.5


def test_training_cache_normalize_data_fp_rejects_nan_ts_utc():
    from training_cache import _normalize_data_fp

    out = _normalize_data_fp(
        {
            "table": "snapshots_1m_normalized",
            "timeframe": "1m",
            "ticker": "SPY",
            "min_ts_utc": float("nan"),
            "max_ts_utc": 100.0,
            "row_count": 10,
        }
    )
    assert out["min_ts_utc"] is None
    assert out["max_ts_utc"] == 100.0


def test_all_float_or_none_helpers_delegate_to_numeric_contract():
    root = _repo_root()
    offenders: list[str] = []
    for path, rel in _iter_repo_py_files(root):
        src = path.read_text(encoding="utf-8")
        if "def _float_or_none" not in src:
            continue
        if "float_finite_or_none" not in src:
            offenders.append(f"{rel}: missing float_finite_or_none delegation")
        elif _INLINE_FLOAT_TRY_EXCEPT.search(src):
            offenders.append(f"{rel}: inline try/except _float_or_none body")
    assert not offenders, offenders


def test_all_positive_float_helpers_delegate_to_numeric_contract():
    root = _repo_root()
    offenders: list[str] = []
    for path, rel in _iter_repo_py_files(root):
        src = path.read_text(encoding="utf-8")
        if "def _positive_float_or_none" not in src:
            continue
        if "float_positive_or_none" not in src:
            offenders.append(str(rel))
    assert not offenders, offenders


_COH_SA1_F_DELEGATE: tuple[tuple[str, str], ...] = (
    ("volatility_regime", "_f"),
    ("math_exposure_core", "_f"),
    ("features.signal_layer_v1", "_f"),
    ("realized_contract_eval", "_f"),
)


@pytest.mark.parametrize("module_name,attr", _COH_SA1_F_DELEGATE)
def test_coh_sa1_f_wrappers_reject_nan_and_inf(module_name: str, attr: str):
    mod = importlib.import_module(module_name)
    fn = getattr(mod, attr)
    assert fn(float("nan")) is None
    assert fn(float("inf")) is None
    assert fn(1.25) == 1.25


@pytest.mark.parametrize("module_name,attr", _COH_SA1_F_DELEGATE)
def test_coh_sa1_f_wrappers_delegate_to_numeric_contract(module_name: str, attr: str):
    mod = importlib.import_module(module_name)
    src = Path(importlib.util.find_spec(module_name).origin)  # type: ignore[union-attr]
    text = src.read_text(encoding="utf-8")
    assert "float_finite_or_none" in text
    assert f"def {attr}" in text


_MODULE_LEVEL_F = re.compile(r"^def _f\s*\(", re.MULTILINE)
_MODULE_LEVEL_NUM = re.compile(r"^def _num\s*\(", re.MULTILINE)


def test_all_module_level_f_helpers_delegate_to_numeric_contract():
    """Module-level ``def _f`` parsers (not nested locals in ml_train / adapters)."""
    root = _repo_root()
    offenders: list[str] = []
    for path, rel in _iter_repo_py_files(root):
        src = path.read_text(encoding="utf-8")
        if not _MODULE_LEVEL_F.search(src):
            continue
        if "float_finite_or_none" not in src:
            offenders.append(f"{rel}: missing float_finite_or_none delegation")
        elif _INLINE_F_TRY_EXCEPT.search(src):
            offenders.append(f"{rel}: inline try/except _f body")
    assert not offenders, offenders


def test_all_module_level_num_helpers_delegate_to_numeric_contract():
    root = _repo_root()
    offenders: list[str] = []
    for path, rel in _iter_repo_py_files(root):
        src = path.read_text(encoding="utf-8")
        if not _MODULE_LEVEL_NUM.search(src):
            continue
        if "float_finite_or_none" not in src:
            offenders.append(f"{rel}: missing float_finite_or_none delegation")
        elif _INLINE_NUM_TRY_EXCEPT.search(src):
            offenders.append(f"{rel}: inline try/except _num body")
    assert not offenders, offenders


def test_no_legacy_inline_float_or_none_try_body():
    """_float_or_none helpers must delegate; no inline try/return float bodies."""
    root = _repo_root()
    offenders: list[str] = []
    for path, rel in _iter_repo_py_files(root):
        src = path.read_text(encoding="utf-8")
        if "def _float_or_none" not in src:
            continue
        if "float_finite_or_none" not in src:
            offenders.append(f"{rel}: missing delegation")
        elif _INLINE_FLOAT_TRY_EXCEPT.search(src):
            offenders.append(f"{rel}: legacy inline try body")
    assert not offenders, offenders
