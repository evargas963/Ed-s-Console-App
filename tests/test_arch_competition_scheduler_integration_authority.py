"""COH-SA: arch_competition.scheduler_integration delegates ml_horizon normalization to authority.

Prior to this refactor scheduler_integration carried a local `_normalize_ml_horizon_slug` that was
strictly weaker than `ml_horizon.normalize_ml_horizon_slug` — it did `str(s).strip().lower()` with
no validation, no default, and would silently accept invalid slugs like "foo" or "999c" and build
path-like values from them. This locks the refactor: the module must use the canonical authority
(which validates against ML_HORIZON_SLUGS and raises ValueError on unknown slugs), and the legacy
arch_state.json branch must key off DEFAULT_ML_HORIZON_SLUG rather than a hardcoded "1c" literal.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from arch_competition import scheduler_integration as si


def test_no_local_shadow_normalize_function():
    """Module must NOT redefine a local _normalize_ml_horizon_slug shadowing the authority."""
    assert not hasattr(si, "_normalize_ml_horizon_slug"), (
        "scheduler_integration must not carry a local _normalize_ml_horizon_slug; "
        "delegate to ml_horizon.normalize_ml_horizon_slug"
    )


def test_path_builders_reject_invalid_horizon():
    """ml_horizon.normalize_ml_horizon_slug raises ValueError on unknown slugs — path builders inherit that."""
    md = Path("/tmp/_test_md_not_real")
    with pytest.raises(ValueError):
        si.arch_competition_ticker_dir(md, "not-a-horizon", "SPY")
    with pytest.raises(ValueError):
        si.evaluation_manifest_path(md, "999c", "SPY")
    with pytest.raises(ValueError):
        si.promotion_decision_path(md, "garbage", "SPY")
    with pytest.raises(ValueError):
        si.arch_competition_summary_path(md, "totally-invalid")


def test_path_builders_normalize_via_authority():
    """Whitespace/case normalization happens via the authority, not a local copy."""
    md = Path("/tmp/_test_md_not_real")
    p_upper = si.arch_competition_ticker_dir(md, "  5C  ", "SPY")
    p_lower = si.arch_competition_ticker_dir(md, "5c", "SPY")
    assert p_upper == p_lower
    assert p_upper.parts[-2] == "5c"


def test_legacy_arch_state_filename_uses_default_horizon_constant():
    """Legacy `arch_state.json` branch must key off DEFAULT_ML_HORIZON_SLUG, not a hardcoded '1c'."""
    src = inspect.getsource(si.load_architecture_competition_visibility)
    # Use the named constant, not a literal compare
    assert "DEFAULT_ML_HORIZON_SLUG" in src
    assert 'hz == "1c"' not in src


def test_module_imports_authority_directly():
    """Module-level import must reference the canonical authority."""
    src = inspect.getsource(si)
    assert "from ml_horizon import" in src
    assert "normalize_ml_horizon_slug" in src
    # Authority comparison constant must be imported too (DEFAULT_ML_HORIZON_SLUG)
    assert "DEFAULT_ML_HORIZON_SLUG" in src


def test_no_inline_str_strip_lower_substitute():
    """Defensive: the deleted local impl was `str(s).strip().lower()`. Ensure no inline equivalent crept back."""
    src = inspect.getsource(si)
    # Allow `.strip().lower()` only when it's not chained on a horizon-slug variable.
    # Tightest check: the exact one-line shape of the deleted helper must not return.
    assert "str(ml_horizon_slug).strip().lower()" not in src
