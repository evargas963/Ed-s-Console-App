"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, second extracted phase.

_pcr_val_for_state (server.py) is the PCR (put/call ratio) phase, moved out of
_fetch_state's body into a standalone function with an explicit input/output contract.
See tests/test_fetch_state_garch_phase_v1.py for the first phase (GARCH) and the extraction
pattern this follows.
"""
from __future__ import annotations

from types import SimpleNamespace

import server as srv


def test_reads_pcr_oi_off_the_first_totals_row():
    row = SimpleNamespace(pcr_oi=1.34)
    assert srv._pcr_val_for_state([row]) == 1.34


def test_only_the_first_row_is_read_never_averaged_or_summed():
    """Matches the original inline `totals[0]` — a second/third row's pcr_oi must never
    influence the result, proving this is a read-through, not a silent aggregation."""
    row0 = SimpleNamespace(pcr_oi=2.5)
    row1 = SimpleNamespace(pcr_oi=99.0)
    assert srv._pcr_val_for_state([row0, row1]) == 2.5


def test_empty_or_none_totals_returns_none():
    assert srv._pcr_val_for_state([]) is None
    assert srv._pcr_val_for_state(None) is None


def test_missing_pcr_oi_attribute_returns_none():
    assert srv._pcr_val_for_state([SimpleNamespace()]) is None


def test_pcr_oi_none_returns_none():
    assert srv._pcr_val_for_state([SimpleNamespace(pcr_oi=None)]) is None


def test_pcr_oi_zero_is_a_real_value_not_treated_as_absent():
    """The original inline check is `if v is not None`, not `if v` — a genuine 0.0 PCR
    (all puts, zero calls, or vice versa) must survive, not be silently dropped to None
    by a falsy-zero bug."""
    result = srv._pcr_val_for_state([SimpleNamespace(pcr_oi=0.0)])
    assert result == 0.0
    assert result is not None


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _pcr_val_for_state exactly once and must not
    contain a second, independent `totals[0].pcr_oi`-style read."""
    import ast
    from pathlib import Path

    src = Path(srv.__file__).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    fetch_state_fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state"
    )
    calls_in_fetch_state = [
        n.func.id for n in ast.walk(fetch_state_fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert calls_in_fetch_state.count("_pcr_val_for_state") == 1, (
        f"expected exactly one call to _pcr_val_for_state inside _fetch_state, "
        f"found {calls_in_fetch_state.count('_pcr_val_for_state')}"
    )
    # A surviving second read site would look like `getattr(totals[0], "pcr_oi", ...)`
    # directly inside _fetch_state -- catch it as a stray `getattr` call whose second
    # argument is the string "pcr_oi".
    stray_pcr_getattr = [
        n for n in ast.walk(fetch_state_fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "getattr"
        and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant) and n.args[1].value == "pcr_oi"
    ]
    assert not stray_pcr_getattr, (
        "_fetch_state still contains a direct getattr(..., 'pcr_oi', ...) read -- the PCR "
        "phase was not fully extracted, a second inline read site survived"
    )
