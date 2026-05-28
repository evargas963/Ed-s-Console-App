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


def test_filter_tickers_for_background_logging_excludes_panel_auto():
    import db as _db_mod

    class _Row:
        def __init__(self, ticker: str, category: str):
            self._d = {"ticker": ticker, "category": category}

        def get(self, key, default=None):
            return self._d.get(key, default)

    class _EdDB:
        def __init__(self, _path):
            pass

        def logging_universe_list_rows(self):
            return [
                _Row("SPY", "core"),
                _Row("PSCI", "panel_auto"),
                _Row("QQQ", "core"),
            ]

    orig = _db_mod.EdDB
    _db_mod.EdDB = _EdDB
    try:
        from scheduler_user_tickers import filter_tickers_for_background_logging

        out = filter_tickers_for_background_logging(["SPY", "PSCI", "QQQ"], ":memory:")
    finally:
        _db_mod.EdDB = orig
    assert out == ["SPY", "QQQ"]


def test_missing_confluence_weighted_pushes_detects_qqq_gap():
    from market_context import MarketContext, ConfluenceRead, missing_confluence_weighted_pushes

    ctx = MarketContext()
    ctx.confluence = ConfluenceRead(weighted_push=0.1)
    ctx.qqq_confluence = ConfluenceRead(weighted_push=None)
    ctx.iwm_confluence = ConfluenceRead(weighted_push=0.05)
    ctx.iwm_holdings_confluence = ConfluenceRead(weighted_push=0.04)
    assert missing_confluence_weighted_pushes(ctx) == ["qqq_weighted_push"]


def test_filter_tickers_for_ml_training_excludes_panel_auto():
    from scheduler_user_tickers import filter_tickers_for_ml_training

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


def test_weighted_push_from_constituents_matches_build_confluence():
    from market_context import (
        QQQ_TOP,
        QQQ_TOP_WEIGHT_SUM,
        SPY_TOP,
        SPY_TOP_WEIGHT_SUM,
        IWM_SECTORS,
        IWM_SECTOR_WEIGHT_SUM,
        IWM_TOP_HOLDINGS,
        IWM_HOLDINGS_WEIGHT_SUM,
        _build_confluence,
        _build_iwm_confluence,
        ConstituentQuote,
        SectorQuote,
        MarketContext,
        ConfluenceRead,
        blend_iwm_weighted_push,
        iwm_blended_participation_push,
        weighted_push_from_constituents,
        weighted_pushes_from_snapshot_row,
    )

    chg = {"NVDA": 1.2, "AAPL": 0.5, "MSFT": -0.3}
    push = weighted_push_from_constituents(chg, QQQ_TOP, QQQ_TOP_WEIGHT_SUM)
    assert push is not None
    cqs = [
        ConstituentQuote(sym, name, w, chg_pct=chg.get(sym))
        for sym, name, w in QQQ_TOP
        if sym in chg
    ]
    live = _build_confluence(cqs, QQQ_TOP_WEIGHT_SUM)
    assert live.weighted_push == push

    row = {
        "nvda_chg_pct": 1.2,
        "aapl_chg_pct": 0.5,
        "msft_chg_pct": -0.3,
        "qqq_weighted_push": None,
    }
    out = weighted_pushes_from_snapshot_row(row)
    assert out["qqq_weighted_push"] == push


def test_qqq_weighted_push_full_top_matches_build_confluence():
    """QQQ backfill must use the full QQQ_TOP roster (incl. WMT), not a 3-name subset."""
    from market_context import (
        QQQ_TOP,
        QQQ_TOP_WEIGHT_SUM,
        _build_confluence,
        ConstituentQuote,
        weighted_pushes_from_snapshot_row,
    )

    chg = {
        "NVDA": 1.0,
        "AAPL": 0.8,
        "MSFT": -0.2,
        "AMZN": 0.4,
        "TSLA": -0.5,
        "META": 0.3,
        "GOOGL": 0.1,
        "WMT": 0.25,
        "GOOG": 0.15,
        "AVGO": 0.6,
    }
    cqs = [
        ConstituentQuote(sym, name, w, chg_pct=chg[sym])
        for sym, name, w in QQQ_TOP
    ]
    live = _build_confluence(cqs, QQQ_TOP_WEIGHT_SUM).weighted_push
    row = {
        "nvda_chg_pct": 1.0,
        "aapl_chg_pct": 0.8,
        "msft_chg_pct": -0.2,
        "amzn_chg_pct": 0.4,
        "tsla_chg_pct": -0.5,
        "meta_chg_pct": 0.3,
        "googl_chg_pct": 0.1,
        "avgo_chg_pct": 0.6,
        "qqq_weighted_push": None,
    }
    backfill = weighted_pushes_from_snapshot_row(
        row, extra_chg={"WMT": 0.25, "GOOG": 0.15}
    )
    assert backfill["qqq_weighted_push"] == live


def test_iwm_weighted_push_matches_blended_participation():
    from market_context import (
        IWM_HOLDINGS_WEIGHT_SUM,
        IWM_SECTOR_WEIGHT_SUM,
        IWM_SECTORS,
        IWM_TOP_HOLDINGS,
        MarketContext,
        ConfluenceRead,
        blend_iwm_weighted_push,
        iwm_blended_participation_push,
        weighted_push_from_constituents,
        weighted_pushes_from_snapshot_row,
    )

    chg = {
        "BE": 0.4,
        "FN": -0.1,
        "KRE": 0.2,
        "XBI": -0.15,
        "PSCI": 0.05,
        "XRT": 0.1,
    }
    h = weighted_push_from_constituents(chg, IWM_TOP_HOLDINGS, IWM_HOLDINGS_WEIGHT_SUM)
    s = weighted_push_from_constituents(
        chg, [(x, y, z) for x, y, z in IWM_SECTORS], IWM_SECTOR_WEIGHT_SUM
    )
    blended = blend_iwm_weighted_push(h, s)
    ctx = MarketContext(
        iwm_holdings_confluence=ConfluenceRead(weighted_push=h),
        iwm_confluence=ConfluenceRead(weighted_push=s),
    )
    assert iwm_blended_participation_push(ctx) == blended

    row = {
        "kre_chg_pct": 0.2,
        "xbi_chg_pct": -0.15,
        "psci_chg_pct": 0.05,
        "xrt_chg_pct": 0.1,
        "iwm_weighted_push": None,
    }
    out = weighted_pushes_from_snapshot_row(
        row, extra_chg={"BE": 0.4, "FN": -0.1}
    )
    assert out["iwm_weighted_push"] == blended
    assert out["iwm_weighted_push"] != s


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


def test_backfill_weighted_pushes_uses_quote_ticks(tmp_path):
    import sqlite3

    from backfill_snapshot_derived import backfill_weighted_pushes
    from db import EdDB

    dbp = tmp_path / "bf_wp.db"
    db = EdDB(dbp, allow_noncanonical=True)
    db.upsert_confluence_quote_ticks(
        [
            {
                "ticker": "WMT",
                "ts_utc": 1000.0,
                "ts_et": "2026-01-02 10:00:00",
                "last_price": 100.0,
                "chg_pct": 0.5,
            }
        ]
    )
    con = sqlite3.connect(str(dbp))
    con.execute(
        """
        INSERT INTO snapshots (
            ticker, timeframe, ts_utc, ts_et, spot, qqq_weighted_push,
            nvda_chg_pct, aapl_chg_pct, msft_chg_pct, amzn_chg_pct,
            googl_chg_pct, avgo_chg_pct, meta_chg_pct, tsla_chg_pct
        ) VALUES ('SPY', '1m', 1000.0, '2026-01-02 10:00:00', 500.0, NULL,
                  1.0, 0.5, -0.2, 0.3, 0.1, 0.4, 0.2, -0.1)
        """
    )
    con.commit()
    con.close()

    stats = backfill_weighted_pushes(dbp)
    assert stats["qqq_filled"] == 1
    con = sqlite3.connect(str(dbp))
    row = con.execute(
        "SELECT qqq_weighted_push FROM snapshots WHERE ticker='SPY'"
    ).fetchone()
    con.close()
    assert row[0] is not None


def test_fetch_latest_confluence_quote_chg(tmp_path):
    from db import EdDB

    dbp = tmp_path / "cq2.db"
    db = EdDB(dbp, allow_noncanonical=True)
    db.upsert_confluence_quote_ticks(
        [
            {
                "ticker": "NVDA",
                "ts_utc": 1_777_000_100.0,
                "ts_et": "2026-01-02 10:01:00",
                "last_price": 900.0,
                "chg_pct": 0.42,
            },
            {
                "ticker": "NVDA",
                "ts_utc": 1_777_000_200.0,
                "ts_et": "2026-01-02 10:02:00",
                "last_price": 901.0,
                "chg_pct": 0.55,
            },
        ]
    )
    got = db.fetch_latest_confluence_quote_chg(["NVDA", "WMT"])
    assert got["NVDA"] == 0.55
    assert got["WMT"] is None
