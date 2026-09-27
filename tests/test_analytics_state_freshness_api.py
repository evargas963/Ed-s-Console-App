"""S2A/S2B — Tier C /api/analytics/state card_freshness_v1 + operator mirror contract tests."""

from __future__ import annotations


# ── TIER_C_STAGE_TIMER_INSTRUMENTATION_V1 — stage timing + cache observability locks ──


def test_executor_sizing_unchanged_by_stage_timer_slice():
    """Hard constraint: analytics executor stays at 4 workers (no sizing change in this slice)."""
    import server as srv

    assert srv._get_analytics_executor()._max_workers == 4


# ── ANCHOR_QUOTE_LANE_REFRESHER_V1 ────────────────────────────────────────────


def test_no_rest_quote_refresher_feeds_the_live_plane():
    """The ANCHOR_QUOTE_LANE_REFRESHER re-quoted SPY/QQQ/IWM over REST every 20s into the
    live plane whenever their streamed quote aged past 20s -- a REST fallback for three named
    tickers. Deleted (operator rules 2026-09-23: no fallbacks, universality): a stale streamed
    quote now reads stale."""
    import inspect

    import server as srv
    src = inspect.getsource(srv)
    assert "_anchor_quote_lane" not in src and "rest_anchor_lane_refresher" not in src


# ── FIX_B_PUBLISH_BEFORE_LOG_REORDER_V1 ──────────────────────────────────────


def _fetch_state_source() -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")


# ── OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2 ───────────────────────────────


def test_step2_leaf_functions_have_no_nested_submit():
    """AST leaf lock: leaf functions, schwab_client, and the price_bars_1m readers
    contain no .submit() anywhere — the nested-submit deadlock class cannot form."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent

    def submit_sites(path, names=None):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if names and node.name not in names:
                    continue
                for sub in ast.walk(node):
                    if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                            and sub.func.attr == "submit"):
                        out.append((node.name, sub.lineno))
        return out

    assert submit_sites(root / "server.py",
                        # P2-1: the daemon fetches the chain; _gated_safe_get_chain is deleted
                        {"_safe_get_quote_with_retry",
                         "_read_bars_1m", "_bars_1m", "_bars_5m"}) == []
    assert submit_sites(root / "schwab_client.py") == []


# ── UI_05 residual — priority leaf lane + startup model prewarm sweep ────────


def test_ui05r_priority_leaf_teardown_present():
    src = _fetch_state_source()
    assert src.count("_priority_leaf_executor.shutdown(wait=True, cancel_futures=True)") == 1
