"""UI-01 analytics key identity — server echo + client key-builder / adopt path."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "static" / "index.html"


def _html() -> str:
    return INDEX.read_text(encoding="utf-8", errors="replace")


def _fn_body(src: str, name: str) -> str:
    marker = f"function {name}("
    start = src.find(marker)
    assert start != -1, f"{name} missing from index.html"
    rest = src[start + len(marker) :]
    cuts = []
    for pat in ("\nfunction ", "\nasync function "):
        i = rest.find(pat)
        if i != -1:
            cuts.append(i)
    assert cuts, f"could not bound {name}"
    return src[start : start + len(marker) + min(cuts)]


def test_format_analytics_cache_key_shapes():
    from planes.context_light import format_analytics_cache_key

    assert format_analytics_cache_key("spy", "2026-08-15") == "SPY|2026-08-15"
    assert format_analytics_cache_key("SPY", "2026-08-15T00:00:00") == "SPY|2026-08-15"
    assert format_analytics_cache_key("SPY", None) == "SPY|"
    assert format_analytics_cache_key("SPY", "") == "SPY|"
    assert format_analytics_cache_key("SPY", "__auto__") == "SPY|"


def test_stamp_analytics_cache_identity_on_payload():
    from planes.context_light import stamp_analytics_cache_identity

    md = {"ticker": "QQQ", "selected_exp": "2026-12-18"}
    stamp_analytics_cache_identity(md)
    assert md["analytics_cache_key"] == "QQQ|2026-12-18"


def test_pending_shell_echoes_analytics_cache_key():
    import server as srv

    md = srv._minimal_analytics_pending_dict("SPY", "2026-08-21")
    assert md["analytics_cache_key"] == "SPY|2026-08-21"
    assert md["selected_exp"] == "2026-08-21"


def test_pending_shell_unresolved_expiry_echoes_open_key():
    import server as srv

    md = srv._minimal_analytics_pending_dict("SPY", None)
    assert md["analytics_cache_key"] == "SPY|"
    assert md["selected_exp"] is None


def test_build_l1_context_echoes_analytics_cache_key():
    import time

    from math_snapshot_derive import derive_vwap_side

    from planes.context_light import L1BuildContext, build_l1_context

    e = "2026-08-15"
    ctx = L1BuildContext(
        ticker="SPY",
        request_expiry=None,
        l0_row={"spot": 500.0, "bid": 499.0, "ask": 501.0},
        l2_cache_entry={
            "ts": 1.0,
            "generated_at": 1.0,
            "analytics_version": 1,
            "ms_dict": {"zone": "FROM_LATEST", "selected_exp": e},
        },
        now_ts=time.time(),
        l2_analytics_refresh_in_progress=False,
        l1_generation=1,
    )
    out = build_l1_context(ctx, derive_vwap_side_fn=derive_vwap_side)
    assert out.get("analytics_cache_key") == f"SPY|{e}"
    assert out.get("selected_exp") == e


def test_freshness_contract_stamps_cache_key():
    import server as srv

    md = {"ticker": "IWM", "selected_exp": "2026-09-18"}
    srv._attach_analytics_freshness_contract(
        md,
        data_cache_key=("IWM", "2026-09-18"),
        entry=None,
        now=1.0,
        sse_live=False,
        inflight_key=("IWM", "2026-09-18"),
    )
    assert md["analytics_cache_key"] == "IWM|2026-09-18"


def test_index_html_single_key_builder_used_by_sse_and_rest():
    html = _html()
    assert "function buildAnalyticsCacheKey(" in html
    assert "function buildAnalyticsRequestUrl(" in html
    assert "function adoptServerAnalyticsIdentity(" in html
    sse = _fn_body(html, "_buildSseStreamUrl")
    l1 = _fn_body(html, "_buildL1LightSseUrl")
    rest = _fn_body(html, "_fetchTierCRestAndApply")
    assert "buildAnalyticsRequestUrl('/api/stream'" in sse
    assert "buildAnalyticsRequestUrl('/api/analytics/light/stream'" in l1
    assert "buildAnalyticsRequestUrl('/api/analytics/state'" in rest
    assert "buildAnalyticsRequestUrl('/api/analytics/light'" in html
    assert "buildAnalyticsRequestUrl('/api/live/state'" in html


def test_index_html_sse_reject_uses_cache_key_not_silent_expiry():
    html = _html()
    onmsg = html[html.find("es.onmessage = (event) =>") : html.find("es.onmessage = (event) =>") + 4500]
    assert "adoptServerAnalyticsIdentity(data, sseGen)" in onmsg
    assert "reason=analytics_cache_key" in onmsg
    assert "reason=expiry" not in onmsg


def test_index_html_matching_cache_key_cannot_be_dropped_by_expiry_string():
    """Lock: echo match is an accept path; diverged date strings that share the key stay in."""
    html = _html()
    adopt = _fn_body(html, "adoptServerAnalyticsIdentity")
    assert "payloadKey === clientKey" in adopt
    assert "return true" in adopt
    assert "requestGeneration" in adopt


def test_index_html_render_tier_b_light_does_not_call_decision_rail():
    body = _fn_body(_html(), "renderTierBLight")
    assert "renderDecisionCommandRail" not in body


def test_python_accept_echo_match_and_explicit_mismatch():
    from tests.test_l1_cross_scope_isolation import l1_tier_b_payload_matches_active_scope

    echo = {
        "ticker": "SPY",
        "selected_exp": "2026-08-15",
        "analytics_cache_key": "SPY|2026-08-15",
    }
    assert l1_tier_b_payload_matches_active_scope(echo, "SPY", "2026-08-15") is True
    assert l1_tier_b_payload_matches_active_scope(echo, "SPY", None) is True
    assert (
        l1_tier_b_payload_matches_active_scope(echo, "SPY", "2026-12-19") is False
    )
    assert l1_tier_b_payload_matches_active_scope(echo, "QQQ", "2026-08-15") is False
