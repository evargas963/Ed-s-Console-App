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


def test_verify_active_tickers_excludes_panel_auto(monkeypatch, tmp_path):
    """Section 11 / verify_active_models must not flag confluence-only panel_auto tickers."""
    import sqlite3

    import verify_active_models as vam

    db_file = tmp_path / "verify_scope.db"
    con = sqlite3.connect(str(db_file))
    con.execute("CREATE TABLE snapshots_1m_normalized (ticker TEXT, ts_et TEXT)")
    for t in ("SPY", "PSCI", "ASTS"):
        con.execute(
            "INSERT INTO snapshots_1m_normalized (ticker, ts_et) VALUES (?, '2026-01-01 10:00:00')",
            (t,),
        )
    con.commit()
    con.close()

    class _Row:
        def __init__(self, ticker: str, category: str):
            self._d = {"ticker": ticker, "category": category}

        def get(self, key, default=None):
            return self._d.get(key, default)

    class _GetDB:
        db_path = db_file

        def logging_universe_list_rows(self):
            return [
                _Row("SPY", "core"),
                _Row("PSCI", "panel_auto"),
                _Row("ASTS", "panel_auto"),
            ]

    import db as _db_mod

    class _EdDB:
        def __init__(self, _path):
            pass

        def logging_universe_list_rows(self):
            return _GetDB().logging_universe_list_rows()

    monkeypatch.setattr(_db_mod, "get_db", lambda: _GetDB())
    monkeypatch.setattr(_db_mod, "EdDB", _EdDB)
    monkeypatch.setattr(
        "scheduler_user_tickers.load_user_scheduler_tickers_or_empty",
        lambda: ["SPY", "PSCI", "ASTS"],
    )

    tickers = vam._get_active_tickers()
    assert tickers == ["SPY"]


def test_filter_tickers_for_background_logging_is_universal():
    """UNIVERSAL COLLECTION (operator requirement, restated 2026-08-25): panel_auto
    enrollment no longer excludes a ticker from the full-snapshot roster — the filter
    passes the roster through unchanged (RC-482)."""
    from scheduler_user_tickers import filter_tickers_for_background_logging

    out = filter_tickers_for_background_logging(["SPY", "PSCI", "QQQ"], ":memory:")
    assert out == ["SPY", "PSCI", "QQQ"]


def test_retired_confluence_code_is_deleted_not_stubbed():
    """Audit of #272 (2026-09-24): the retirement left None-returning stubs and their callers.
    Stubs are dead code carrying a retired contract -- they are deleted."""
    import backfill_snapshot_derived
    import market_context
    import math_probabilities
    import server
    for mod, name in ((market_context, "missing_confluence_weighted_pushes"),
                      (market_context, "weighted_pushes_from_snapshot_row"),
                      (market_context, "iwm_blended_participation_push"),
                      (market_context, "stamp_confluence_display_fields"),
                      (market_context, "resolve_chg_pct"),
                      (market_context, "ConfluenceRead"),
                      (math_probabilities, "compute_iwm_confluence"),
                      (math_probabilities, "compute_sector_strength"),
                      (backfill_snapshot_derived, "backfill_weighted_pushes"),
                      (server, "_ensure_mkt_ctx_confluence_complete")):
        assert not hasattr(mod, name), f"{mod.__name__}.{name}"
    ctx = market_context.MarketContext()
    for field in ("spy_chg_pct", "constituents", "confluence", "iwm_sectors", "iwm_holdings"):
        assert not hasattr(ctx, field), field


def test_filter_tickers_for_ml_training_excludes_panel_auto():

    class _Row:
        def __init__(self, ticker: str, category: str):
            self._d = {"ticker": ticker, "category": category}

        def get(self, key, default=None):
            return self._d.get(key, default)

    class _DB:
        def logging_universe_list_rows(self):
            return [
                _Row("SPY", "core"),
                _Row("PSCI", "panel_auto"),
                _Row("QQQ", "core"),
            ]

    import db as _db_mod

    import scheduler_user_tickers as sut

    orig = _db_mod.EdDB

    class _EdDB:
        def __init__(self, _path):
            pass

        def logging_universe_list_rows(self):
            return _DB().logging_universe_list_rows()

    _db_mod.EdDB = _EdDB
    try:
        out = sut.filter_tickers_for_ml_training(["SPY", "PSCI", "QQQ"], ":memory:")
    finally:
        _db_mod.EdDB = orig
    assert out == ["SPY", "QQQ"]


def test_evaluate_training_readiness_empty_db(tmp_path):
    """pre_train_gate helper fail-closed when DB missing."""
    from audit_model_readiness import evaluate_training_readiness

    missing = tmp_path / "nope.db"
    r = evaluate_training_readiness(missing)
    assert r["training_ok"] is False
    assert r["reasons"]


def test_confluence_quote_ticks_upsert_and_inventory(tmp_path):
    """Thin panel quote table: write path + read inventory consumer."""
    from db import EdDB

    dbp = tmp_path / "cq.db"
    db = EdDB(dbp, allow_noncanonical=True)
    n = db.upsert_confluence_quote_ticks(
        [
            {
                "ticker": "PSCI",
                "ts_utc": 1_777_000_000.0,
                "ts_et": "2026-01-02 10:00:00",
                "last_price": 42.5,
                "chg_pct": 0.12,
            }
        ]
    )
    assert n == 1
    inv = db.confluence_quote_tick_inventory()
    assert inv["total_rows"] == 1
    assert inv["distinct_tickers"] == 1


def test_retired_chg_map_cannot_alias_goog_onto_googl():
    """The GOOG/GOOGL alias lived in the retired weighted-push map. Absence is the pin."""
    import market_context as mc

    assert not hasattr(mc, "SYMBOL_TO_SNAPSHOT_CHG_COL")
    assert not hasattr(mc, "snapshot_row_chg_map")


def test_fetch_confluence_quote_chg_as_of(tmp_path):
    from db import EdDB

    dbp = tmp_path / "cq_asof.db"
    db = EdDB(dbp, allow_noncanonical=True)
    db.upsert_confluence_quote_ticks(
        [
            {
                "ticker": "WMT",
                "ts_utc": 100.0,
                "ts_et": "2026-01-01 09:00:00",
                "last_price": 50.0,
                "chg_pct": 0.11,
            },
            {
                "ticker": "WMT",
                "ts_utc": 200.0,
                "ts_et": "2026-01-01 10:00:00",
                "last_price": 50.5,
                "chg_pct": 0.22,
            },
        ]
    )
    got = db.fetch_confluence_quote_chg_as_of(150.0, ["WMT"])
    assert got["WMT"] == 0.11
    got2 = db.fetch_confluence_quote_chg_as_of(250.0, ["WMT"])
    assert got2["WMT"] == 0.22


def test_no_stored_percent_change_patches_a_live_confluence_value():
    """Audit P0 (2026-09-23): a missing live confluence value was patched from the latest
    stored %-change with no age limit. That path is gone -- missing stays missing."""
    import inspect

    import db as db_mod
    import market_context
    import server
    assert not hasattr(market_context, "patch_context_confluence_from_quote_ticks")
    assert not hasattr(db_mod.EdDB, "fetch_latest_confluence_quote_chg")
    assert "fetch_latest_confluence_quote_chg" not in inspect.getsource(server)


def _logging_universe_rows(rows: list[tuple[str, str]]):
    class _Row:
        def __init__(self, ticker: str, category: str):
            self._d = {"ticker": ticker, "category": category}

        def get(self, key, default=None):
            return self._d.get(key, default)

    return [_Row(t, c) for t, c in rows]


def test_resolve_ml_training_roster_defaults_to_three_anchors(monkeypatch):
    import scheduler_user_tickers as sut

    class _EdDB:
        def __init__(self, _path):
            pass

        def logging_universe_list_rows(self):
            return _logging_universe_rows(
                [
                    ("SPY", "core"),
                    ("QQQ", "core"),
                    ("IWM", "core"),
                    ("NVDA", "core"),
                    ("PLTR", "pinned"),
                    ("PSCI", "panel_auto"),
                ]
            )

    import db as _db_mod

    monkeypatch.setattr(_db_mod, "EdDB", _EdDB)
    monkeypatch.delenv("ED_ML_SCHEDULER_TRAINING_EXPAND", raising=False)
    monkeypatch.delenv("ED_ML_SCHEDULER_TICKERS", raising=False)

    enrolled = ["SPY", "QQQ", "IWM", "NVDA", "PLTR", "PSCI"]
    out = sut.resolve_ml_training_roster(enrolled, ":memory:")
    assert out == ["SPY", "QQQ", "IWM"]


def test_resolve_ml_training_roster_expansion_includes_pinned_guests(monkeypatch):
    import scheduler_user_tickers as sut

    class _EdDB:
        def __init__(self, _path):
            pass

        def logging_universe_list_rows(self):
            return _logging_universe_rows(
                [
                    ("SPY", "core"),
                    ("QQQ", "core"),
                    ("IWM", "core"),
                    ("NVDA", "core"),
                    ("PLTR", "pinned"),
                    ("PSCI", "panel_auto"),
                ]
            )

    import db as _db_mod

    monkeypatch.setattr(_db_mod, "EdDB", _EdDB)
    monkeypatch.setenv("ED_ML_SCHEDULER_TRAINING_EXPAND", "1")
    monkeypatch.delenv("ED_ML_SCHEDULER_TICKERS", raising=False)

    enrolled = ["SPY", "QQQ", "IWM", "NVDA", "PLTR", "PSCI"]
    out = sut.resolve_ml_training_roster(enrolled, ":memory:")
    assert set(out) == {"SPY", "QQQ", "IWM", "NVDA", "PLTR"}
    assert "PSCI" not in out


def test_require_ml_training_ticker_allowed_rejects_guest_mega_cap(monkeypatch):
    import scheduler_user_tickers as sut

    monkeypatch.delenv("ED_ML_SCHEDULER_TRAINING_EXPAND", raising=False)
    with pytest.raises(ValueError, match="NVDA is not a training anchor"):
        sut.require_ml_training_ticker_allowed("NVDA")
    assert sut.require_ml_training_ticker_allowed("SPY") == "SPY"


def test_live_diag_default_tickers_are_all_three_anchors():
    from tools.live_diag_compare import DEFAULT_DIAG_TICKERS
    from scheduler_user_tickers import TRAINING_ANCHOR_TICKERS

    assert DEFAULT_DIAG_TICKERS == TRAINING_ANCHOR_TICKERS
    assert DEFAULT_DIAG_TICKERS == ("SPY", "QQQ", "IWM")


def test_live_diag_stack_meta_ok_when_bases_and_fusion_up():
    from tools.live_diag_compare import _summarize_full_stack_layers, stack_layer_failures

    d = {
        "xgb_available": True,
        "lstm_available": True,
        "transformer_available": True,
        "fusion_available": True,
        "mc_available": True,
        "regime_label": "trend",
    }
    stack = _summarize_full_stack_layers(d)
    assert stack["meta"] == "ok"
    assert stack["fusion"] == "ok"
    assert stack_layer_failures("SPY", d) == []


def test_live_diag_anchor_stack_fail_when_fusion_missing():
    from tools.live_diag_compare import stack_layer_failures

    d = {
        "xgb_available": True,
        "lstm_available": True,
        "transformer_available": True,
        "fusion_available": False,
        "mc_available": True,
        "regime_label": "trend",
    }
    missing = stack_layer_failures("IWM", d)
    assert "fusion" in missing
    assert "meta" in missing
