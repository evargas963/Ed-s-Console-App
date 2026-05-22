"""STACK-VERIFY-CAND-LOAD-TICKERS-RETURN-TYPE: typed return contract guard.

`load_user_scheduler_tickers` now returns `Optional[list[str]]` — None on DB
failure, distinct from empty list ("DB OK but nobody enrolled"). Legacy callers
that want the pre-fix `list[str]` semantic call `load_user_scheduler_tickers_or_empty()`.

This file pins:
- The typed function's None branch on DB failure.
- The convenience wrapper returns [] on DB failure.
- Every existing production caller uses the `_or_empty` wrapper (no caller
  accidentally feeds None into list-comprehension or filter_valid_tickers).
"""

from __future__ import annotations

import inspect

import pytest


def test_load_user_scheduler_tickers_returns_none_on_db_failure(monkeypatch):
    import scheduler_user_tickers as sut

    class _BoomDB:
        def logging_universe_migrate_scheduler_companion_json(self, **_kw):
            raise RuntimeError("db down")

        def logging_universe_authoritative_tickers(self):
            raise RuntimeError("db down")

    import db as _db_mod

    monkeypatch.setattr(_db_mod, "get_db", lambda: _BoomDB())
    out = sut.load_user_scheduler_tickers()
    assert out is None, "DB failure must return None (not empty list)"


def test_or_empty_wrapper_returns_list_on_db_failure(monkeypatch):
    import scheduler_user_tickers as sut

    class _BoomDB:
        def logging_universe_migrate_scheduler_companion_json(self, **_kw):
            raise RuntimeError("db down")

        def logging_universe_authoritative_tickers(self):
            raise RuntimeError("db down")

    import db as _db_mod

    monkeypatch.setattr(_db_mod, "get_db", lambda: _BoomDB())
    out = sut.load_user_scheduler_tickers_or_empty()
    assert out == [], "_or_empty wrapper must return [] when typed version returns None"
    assert isinstance(out, list)


def test_typed_signature_is_optional_list_str():
    """Return annotation must be Optional[list[str]] (or equivalent)."""
    import scheduler_user_tickers as sut

    sig = inspect.signature(sut.load_user_scheduler_tickers)
    # The return annotation should explicitly include Optional / None.
    ret = str(sig.return_annotation)
    assert "Optional" in ret or "None" in ret or "| None" in ret, (
        f"return annotation must signal Optional / None branch; got {ret!r}"
    )


def test_no_production_caller_uses_typed_version_directly():
    """Production callers that don't handle the None branch must use the
    `_or_empty()` wrapper. Catches regressions where someone re-introduces a bare
    `load_user_scheduler_tickers()` call without explicit None handling.
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    callers = [
        "lstm_data.py",
        "ml_scheduler.py",
        "train_all.py",
        "transformer_train.py",
        "verify_active_models.py",
    ]
    for rel in callers:
        src = (repo / rel).read_text(encoding="utf-8")
        # The typed name without `_or_empty` should only appear in import-and-handled patterns.
        # Easiest guard: assert the convenience wrapper IS imported, and the bare name does NOT
        # appear as a function call.
        assert "load_user_scheduler_tickers_or_empty" in src, (
            f"{rel} must import load_user_scheduler_tickers_or_empty (or explicitly "
            f"handle the None branch; current impl uses the convenience wrapper)"
        )
        # Allow the typed name in import lines but ban bare function calls.
        for line in src.splitlines():
            if "load_user_scheduler_tickers(" in line and "load_user_scheduler_tickers_or_empty(" not in line:
                pytest.fail(
                    f"{rel}: bare load_user_scheduler_tickers() call without None handling: {line.strip()!r}"
                )
