"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, eighteenth extracted phase.

_additive_context_for_state (server.py) is the Additive Context phase (liquidity
behavior + news/sentiment, both non-authoritative), extracted verbatim from
_fetch_state's body. It mutates `ms` in place (ms.liquidity_behavior,
ms.news_context) and has no separate return value, matching the original inline
code's own side-effect-only shape.

Two fully independent try/except blocks, each failing closed to None on its own
exception without affecting the other -- a liquidity-behavior failure must never take
down news_context, and vice versa.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import server as srv


def _fixture_ms():
    return SimpleNamespace(net_gamma=1000.0, liquidity_behavior=None, news_context=None)


def test_both_fields_set_from_real_computation_when_available():
    ms = _fixture_ms()
    fake_lb = {"label": "absorption", "score": 0.7}
    fake_news = {"headline": "test", "sentiment": 0.1}

    with mock.patch("institutional_behavior.compute_liquidity_behavior_row", return_value=fake_lb), \
         mock.patch("news_sentiment.refresh_and_context_for_ui", return_value=fake_news):
        result = srv._additive_context_for_state(
            ms, "ZZZ_ADDCTX_MATCH", object(), 100.0, 99.0, 101.0, 98.5, 100.5, 5000.0,
            0.3, 2.0, 2.5, 1.5,
        )
    assert result is None, "the phase mutates ms in place and returns nothing"
    assert ms.liquidity_behavior == fake_lb
    assert ms.news_context == fake_news


def test_liquidity_behavior_failure_does_not_affect_news_context():
    ms = _fixture_ms()
    fake_news = {"headline": "test", "sentiment": 0.1}
    with mock.patch("institutional_behavior.compute_liquidity_behavior_row", side_effect=RuntimeError("boom")), \
         mock.patch("news_sentiment.refresh_and_context_for_ui", return_value=fake_news):
        srv._additive_context_for_state(
            ms, "ZZZ_ADDCTX_LBFAIL", object(), 100.0, 99.0, 101.0, 98.5, 100.5, 5000.0,
            0.3, 2.0, 2.5, 1.5,
        )
    assert ms.liquidity_behavior is None
    assert ms.news_context == fake_news


def test_news_context_failure_does_not_affect_liquidity_behavior():
    ms = _fixture_ms()
    fake_lb = {"label": "absorption", "score": 0.7}
    with mock.patch("institutional_behavior.compute_liquidity_behavior_row", return_value=fake_lb), \
         mock.patch("news_sentiment.refresh_and_context_for_ui", side_effect=RuntimeError("boom")):
        srv._additive_context_for_state(
            ms, "ZZZ_ADDCTX_NEWSFAIL", object(), 100.0, 99.0, 101.0, 98.5, 100.5, 5000.0,
            0.3, 2.0, 2.5, 1.5,
        )
    assert ms.liquidity_behavior == fake_lb
    assert ms.news_context is None


def test_both_failing_leaves_both_fields_none_without_raising():
    ms = _fixture_ms()
    with mock.patch("institutional_behavior.compute_liquidity_behavior_row", side_effect=RuntimeError("boom")), \
         mock.patch("news_sentiment.refresh_and_context_for_ui", side_effect=RuntimeError("boom")):
        srv._additive_context_for_state(
            ms, "ZZZ_ADDCTX_BOTHFAIL", object(), 100.0, 99.0, 101.0, 98.5, 100.5, 5000.0,
            0.3, 2.0, 2.5, 1.5,
        )
    assert ms.liquidity_behavior is None
    assert ms.news_context is None


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _additive_context_for_state exactly once."""
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
    assert calls_in_fetch_state.count("_additive_context_for_state") == 1
